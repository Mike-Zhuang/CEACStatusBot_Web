import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from fastapi import HTTPException, Request, Response, status

from .account_controls import publicAccountFields
from .config import getSettings
from .database import getConnection, utcNowIso
from .security_guard import enforceAuthenticatedApiLimit, logSecurityEvent, requestActorHashes


SESSION_COOKIE_NAME = "ceac_session"
PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hashLegacyPassword(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 210_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(digest).decode()}"


def hashPassword(password: str) -> str:
    return f"argon2id${PASSWORD_HASHER.hash(password)}"


def verifyPassword(password: str, storedHash: str) -> bool:
    if storedHash.startswith("argon2id$"):
        try:
            return PASSWORD_HASHER.verify(storedHash.removeprefix("argon2id$"), password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False
    try:
        algorithm, salt, digest = storedHash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashLegacyPassword(password, salt).split("$", 2)[2]
    return hmac.compare_digest(candidate, digest)


def needsPasswordRehash(storedHash: str) -> bool:
    if not storedHash.startswith("argon2id$"):
        return True
    try:
        return PASSWORD_HASHER.check_needs_rehash(storedHash.removeprefix("argon2id$"))
    except (InvalidHashError, VerificationError):
        return True


def hashCode(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def createSessionToken() -> str:
    return secrets.token_urlsafe(48)


def hashSessionToken(token: str) -> str:
    return hmac.new(getSettings().secretKey.encode(), token.encode(), hashlib.sha256).hexdigest()


def setSessionCookie(response: Response, user: dict[str, Any], request: Request | None = None) -> None:
    settings = getSettings()
    token = createSessionToken()
    now = datetime.now(UTC).replace(microsecond=0)
    expiresAt = now + timedelta(days=settings.sessionAbsoluteTimeoutDays)
    hashes = requestActorHashes(request) if request is not None else {"device_hash": "", "ip_hash": ""}
    userAgent = request.headers.get("user-agent", "")[:240] if request is not None else ""
    with getConnection() as connection:
        connection.execute(
            """
            INSERT INTO user_sessions (
                user_id, token_hash, device_hash, ip_hash, user_agent, created_at, last_seen_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user["id"]),
                hashSessionToken(token),
                hashes["device_hash"],
                hashes["ip_hash"],
                userAgent,
                now.isoformat(),
                now.isoformat(),
                expiresAt.isoformat(),
            ),
        )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookieSecure,
        max_age=settings.sessionAbsoluteTimeoutDays * 24 * 60 * 60,
    )


def clearSessionCookie(response: Response, request: Request | None = None) -> None:
    if request is not None:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token:
            with getConnection() as connection:
                connection.execute(
                    "UPDATE user_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                    (utcNowIso(), hashSessionToken(token)),
                )
    response.delete_cookie(SESSION_COOKIE_NAME)


def getCurrentUser(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    now = datetime.now(UTC).replace(microsecond=0)
    settings = getSettings()
    expiredUserId: int | None = None
    with getConnection() as connection:
        session = connection.execute(
            """
            SELECT s.*, u.id, u.email, u.role, u.account_tier, u.is_email_verified, u.timezone,
                   u.account_status, u.created_at
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (hashSessionToken(token),),
        ).fetchone()
        if not session or session["revoked_at"]:
            logSecurityEvent(eventType="session_invalid", request=request, severity="warning")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
        expiresAt = datetime.fromisoformat(session["expires_at"])
        lastSeenAt = datetime.fromisoformat(session["last_seen_at"])
        if expiresAt < now or now - lastSeenAt > timedelta(minutes=settings.sessionIdleTimeoutMinutes):
            connection.execute(
                "UPDATE user_sessions SET revoked_at = ? WHERE id = ?",
                (now.isoformat(), session["id"]),
            )
            expiredUserId = int(session["user_id"])
        else:
            connection.execute(
                "UPDATE user_sessions SET last_seen_at = ? WHERE id = ?",
                (now.isoformat(), session["id"]),
            )
    if expiredUserId is not None:
        logSecurityEvent(eventType="session_expired", request=request, severity="info", userId=expiredUserId)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已超时，请重新登录")
    user = {
        "id": session["user_id"],
        "email": session["email"],
        "role": session["role"],
        "account_tier": session["account_tier"],
        "is_email_verified": session["is_email_verified"],
        "timezone": session["timezone"],
        "created_at": session["created_at"],
    }
    user.update(publicAccountFields(session))
    enforceAuthenticatedApiLimit(request, user)
    return user


def requireAdmin(request: Request) -> dict[str, Any]:
    user = getCurrentUser(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def seedDefaultUsers() -> None:
    now = utcNowIso()
    settings = getSettings()
    defaults = []
    if settings.defaultAdminEmail and settings.defaultAdminPassword:
        defaults.append((settings.defaultAdminEmail, settings.defaultAdminPassword, "admin"))
    if settings.defaultUserEmail and settings.defaultUserPassword:
        defaults.append((settings.defaultUserEmail, settings.defaultUserPassword, "user"))
    with getConnection() as connection:
        for email, password, role in defaults:
            exists = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists:
                continue
            connection.execute(
                """
                INSERT INTO users (email, password_hash, role, account_tier, is_email_verified, created_at, updated_at)
                VALUES (?, ?, ?, 'standard', 1, ?, ?)
                """,
                (email, hashPassword(password), role, now, now),
            )
