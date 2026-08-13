import hashlib
import ipaddress
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request, Response, status

from .config import getSettings
from .database import getConnection, utcNowIso


DEVICE_COOKIE_NAME = "ceac_device_id"


def hashSecurityValue(value: str) -> str:
    normalized = value.strip().lower()
    return hashlib.sha256(f"{getSettings().secretKey}:{normalized}".encode()).hexdigest()


def requestIp(request: Request) -> str:
    clientHost = request.client.host if request.client else ""
    if clientHost in getSettings().trustedProxyIps:
        # Nginx 覆盖 X-Real-IP 为实际对端地址；不能信任客户端可自行附加的 XFF 首段。
        realIp = request.headers.get("x-real-ip", "").strip()
        if realIp:
            try:
                ipaddress.ip_address(realIp)
                return realIp
            except ValueError:
                pass
        forwardedFor = request.headers.get("x-forwarded-for", "")
        forwardedCandidates = [item.strip() for item in forwardedFor.split(",") if item.strip()]
        # 未配置 X-Real-IP 的受信代理回退到最后一个有效 XFF；Nginx 会将真实对端追加在末尾。
        for forwardedIp in reversed(forwardedCandidates):
            try:
                ipaddress.ip_address(forwardedIp)
                return forwardedIp
            except ValueError:
                continue
    return clientHost


def getOrCreateDeviceId(request: Request) -> str:
    deviceId = request.cookies.get(DEVICE_COOKIE_NAME, "")
    if len(deviceId) >= 32:
        return deviceId
    stateDeviceId = getattr(request.state, "device_id", "")
    if stateDeviceId:
        return str(stateDeviceId)
    deviceId = secrets.token_urlsafe(32)
    request.state.device_id = deviceId
    request.state.device_cookie_needed = True
    return deviceId


def attachDeviceCookie(request: Request, response: Response) -> None:
    if not getattr(request.state, "device_cookie_needed", False):
        return
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        str(request.state.device_id),
        httponly=True,
        samesite="lax",
        secure=getSettings().cookieSecure,
        max_age=365 * 24 * 60 * 60,
    )


def requestActorHashes(request: Request, email: str = "") -> dict[str, str]:
    deviceId = getOrCreateDeviceId(request)
    ip = requestIp(request)
    return {
        "ip_hash": hashSecurityValue(ip) if ip else "",
        "device_hash": hashSecurityValue(deviceId),
        "email_hash": hashSecurityValue(email) if email else "",
        "actor_summary": f"ip:{ip or 'unknown'} device:{deviceId[:8]}",
    }


def logSecurityEvent(
    *,
    eventType: str,
    request: Request | None = None,
    severity: str = "info",
    userId: int | None = None,
    email: str = "",
    detail: str | dict[str, Any] = "",
) -> None:
    hashes = {"ip_hash": "", "device_hash": "", "email_hash": "", "actor_summary": ""}
    path = ""
    if request is not None:
        hashes = requestActorHashes(request, email)
        path = request.url.path
    if email and not hashes["email_hash"]:
        hashes["email_hash"] = hashSecurityValue(email)
    detailText = json.dumps(detail, ensure_ascii=False, default=str) if isinstance(detail, dict) else str(detail)
    with getConnection() as connection:
        connection.execute(
            """
            INSERT INTO security_events (
                event_type, severity, user_id, email_hash, ip_hash, device_hash, actor_summary, path, detail, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eventType,
                severity,
                userId,
                hashes["email_hash"],
                hashes["ip_hash"],
                hashes["device_hash"],
                hashes["actor_summary"],
                path,
                detailText[:1200],
                utcNowIso(),
            ),
        )


def _windowStart(now: datetime, windowSeconds: int) -> datetime:
    timestamp = int(now.timestamp())
    return datetime.fromtimestamp(timestamp - (timestamp % windowSeconds), UTC).replace(microsecond=0)


def enforceRateLimit(
    *,
    request: Request,
    scope: str,
    subject: str,
    limit: int,
    windowSeconds: int,
    eventType: str = "rate_limited",
    userId: int | None = None,
) -> None:
    now = datetime.now(UTC)
    windowStart = _windowStart(now, windowSeconds)
    expiresAt = windowStart + timedelta(seconds=windowSeconds * 2)
    subjectHash = hashSecurityValue(subject)
    with getConnection() as connection:
        # 认证与接口请求可能同时落到同一账号/设备窗口。单条 UPSERT 避免先查后插
        # 在并发请求下触发唯一索引冲突，且每次请求都会准确累加。
        connection.execute(
            """
            INSERT INTO rate_limit_counters (
                scope, subject_hash, window_start, expires_at, count, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(scope, subject_hash, window_start) DO UPDATE SET
                count = rate_limit_counters.count + 1,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (scope, subjectHash, windowStart.isoformat(), expiresAt.isoformat(), now.isoformat()),
        ).fetchone()
        row = connection.execute(
            """
            SELECT count
            FROM rate_limit_counters
            WHERE scope = ? AND subject_hash = ? AND window_start = ?
            """,
            (scope, subjectHash, windowStart.isoformat()),
        ).fetchone()
        count = int(row["count"] if row else 1)
    if count > limit:
        logSecurityEvent(
            eventType=eventType,
            request=request,
            severity="warning",
            userId=userId,
            detail={"scope": scope, "limit": limit, "windowSeconds": windowSeconds},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试。",
        )


def checkLoginCooldown(request: Request, email: str) -> None:
    now = datetime.now(UTC)
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT locked_until
            FROM rate_limit_counters
            WHERE scope = 'login_failure_email' AND subject_hash = ?
            ORDER BY locked_until DESC
            LIMIT 1
            """,
            (hashSecurityValue(email),),
        ).fetchone()
    if row and row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now:
        logSecurityEvent(eventType="login_cooldown_blocked", request=request, severity="warning", email=email)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="登录失败次数过多，请稍后再试。")


def recordLoginFailure(request: Request, email: str) -> None:
    settings = getSettings()
    now = datetime.now(UTC)
    windowSeconds = 15 * 60
    windowStart = _windowStart(now, windowSeconds)
    subjectHash = hashSecurityValue(email)
    lockUntil: str | None = None
    with getConnection() as connection:
        # 和通用限流器一样，登录失败计数也必须是原子累加，避免并发猜密码时
        # 因唯一键竞争而漏记或抛出 500。
        connection.execute(
            """
            INSERT INTO rate_limit_counters (
                scope, subject_hash, window_start, expires_at, count, locked_until, updated_at
            )
            VALUES ('login_failure_email', ?, ?, ?, 1, NULL, ?)
            ON CONFLICT(scope, subject_hash, window_start) DO UPDATE SET
                count = rate_limit_counters.count + 1,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (subjectHash, windowStart.isoformat(), (windowStart + timedelta(hours=2)).isoformat(), now.isoformat()),
        ).fetchone()
        row = connection.execute(
            """
            SELECT count
            FROM rate_limit_counters
            WHERE scope = 'login_failure_email' AND subject_hash = ? AND window_start = ?
            """,
            (subjectHash, windowStart.isoformat()),
        ).fetchone()
        count = int(row["count"] if row else 1)
        if count >= settings.authLoginEmailFailureLimitPer15Minutes:
            minutes = 60 if count >= settings.authLoginEmailFailureLimitPer15Minutes * 2 else 15
            lockUntil = (now + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
        if lockUntil:
            connection.execute(
                """
                UPDATE rate_limit_counters
                SET locked_until = ?, updated_at = ?
                WHERE scope = 'login_failure_email' AND subject_hash = ? AND window_start = ?
                """,
                (
                    lockUntil,
                    now.isoformat(),
                    subjectHash,
                    windowStart.isoformat(),
                ),
            )
    logSecurityEvent(
        eventType="login_failed",
        request=request,
        severity="warning",
        email=email,
        detail={"failureCount": count, "lockedUntil": lockUntil},
    )


def clearLoginFailures(email: str) -> None:
    with getConnection() as connection:
        connection.execute(
            "DELETE FROM rate_limit_counters WHERE scope = 'login_failure_email' AND subject_hash = ?",
            (hashSecurityValue(email),),
        )


def enforceAuthCodeLimits(request: Request, email: str, purpose: str) -> None:
    settings = getSettings()
    hashes = requestActorHashes(request, email)
    enforceRateLimit(
        request=request,
        scope=f"{purpose}_code_email",
        subject=email,
        limit=settings.authCodeEmailLimitPerHour,
        windowSeconds=3600,
        eventType="auth_code_rate_limited",
    )
    enforceRateLimit(
        request=request,
        scope=f"{purpose}_code_ip_device",
        subject=f"{hashes['ip_hash']}:{hashes['device_hash']}",
        limit=settings.authCodeIpDeviceLimitPer10Minutes,
        windowSeconds=600,
        eventType="auth_code_rate_limited",
    )


def enforceLoginAttemptLimit(request: Request, email: str) -> None:
    settings = getSettings()
    hashes = requestActorHashes(request, email)
    enforceRateLimit(
        request=request,
        scope="login_ip_device",
        subject=f"{hashes['ip_hash']}:{hashes['device_hash']}",
        limit=settings.authLoginIpDeviceLimitPerMinute,
        windowSeconds=60,
        eventType="login_rate_limited",
    )
    checkLoginCooldown(request, email)


def enforceAuthenticatedApiLimit(request: Request, user: dict[str, Any]) -> None:
    settings = getSettings()
    if user["role"] == "admin":
        limit = settings.adminApiLimitPerMinute
    elif user["account_tier"] == "premium":
        limit = settings.premiumApiLimitPerMinute
    else:
        limit = settings.standardApiLimitPerMinute
    deviceId = getOrCreateDeviceId(request)
    enforceRateLimit(
        request=request,
        scope="authenticated_api",
        subject=f"{user['id']}:{hashSecurityValue(deviceId)}",
        limit=limit,
        windowSeconds=60,
        eventType="authenticated_api_rate_limited",
        userId=int(user["id"]),
    )


def listSecurityEvents(limit: int = 200) -> list[dict[str, Any]]:
    boundedLimit = min(max(limit, 1), 500)
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT e.*, u.email AS user_email
            FROM security_events e
            LEFT JOIN users u ON u.id = e.user_id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (boundedLimit,),
        ).fetchall()
    return [dict(row) for row in rows]
