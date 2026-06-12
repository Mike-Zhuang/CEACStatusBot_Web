from datetime import UTC, datetime, timedelta
import secrets
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .case_service import (
    createCase,
    deleteCase,
    enqueueCaseQuery,
    enqueueDueCases,
    getCase,
    getQueryJob,
    listCases,
    listHistory,
    migrateEncryptedFields,
    patchCase,
    reorderProfiles,
    restoreCaseAutomaticQuery,
    sendCurrentStatusEmail,
    updateUserAccountTier,
    updateUserWorkerPriority,
)
from .config import getSettings
from .database import getConnection, initializeDatabase, utcNowIso
from .ircc_portal_service import (
    createIrccCase,
    deleteIrccCase,
    discoverIrccApplications,
    enqueueDueIrccCases,
    enqueueIrccCaseQuery,
    getIrccCase,
    getIrccQueryJob,
    listIrccCases,
    listIrccHistory,
    patchIrccCase,
    sendCurrentIrccEmail,
)
from .korea_visa_service import (
    createKoreaCase,
    deleteKoreaCase,
    enqueueDueKoreaCases,
    enqueueKoreaCaseQuery,
    getKoreaCase,
    getKoreaQueryJob,
    listKoreaCases,
    listKoreaHistory,
    migrateKoreaEncryptedFields,
    patchKoreaCase,
    sendCurrentKoreaEmail,
)
from .mailer import getSystemSmtpConfigPublic, saveSystemSmtpConfig, sendSystemEmail
from .passport_slot_service import (
    enqueueDuePassportSlotMonitors,
    enqueuePassportSlotQuery,
    getPassportSlotMonitor,
    listPassportSlotHistory,
    patchPassportSlotMonitor,
    sendCurrentPassportSlotEmail,
    upsertPassportSlotMonitor,
)
from .schemas import (
    AccountTierPatch,
    CeacCaseInput,
    CeacCasePatch,
    IrccCaseInput,
    IrccCasePatch,
    IrccDiscoverRequest,
    KoreaCaseInput,
    KoreaCasePatch,
    LoginRequest,
    PasswordResetCodeRequest,
    PasswordResetRequest,
    PassportSlotMonitorInput,
    PassportSlotMonitorPatch,
    ProfileOrderPatch,
    ProfileUpdateRequest,
    RegisterRequest,
    SendCodeRequest,
    SystemSmtpConfigInput,
    TimezoneUpdateRequest,
    WorkerPriorityPatch,
)
from .security import (
    clearSessionCookie,
    getCurrentUser,
    hashCode,
    hashPassword,
    needsPasswordRehash,
    requireAdmin,
    seedDefaultUsers,
    setSessionCookie,
    verifyPassword,
)
from .security_guard import (
    attachDeviceCookie,
    clearLoginFailures,
    enforceAuthCodeLimits,
    enforceLoginAttemptLimit,
    enforceRateLimit,
    getOrCreateDeviceId,
    listSecurityEvents,
    logSecurityEvent,
    recordLoginFailure,
    requestActorHashes,
)
from .secrets import decryptIfNeeded, getCredentialMasterKey

TERMS_VERSION = "2026-05-15"
INACTIVITY_NOTICE_DAYS = 15
INACTIVITY_DELETE_DAYS = 30


app = FastAPI(title="CEACStatusBot Web", version="1.0.0")
settings = getSettings()
scheduler = BackgroundScheduler(timezone="UTC")

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowedHosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.corsOrigins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validationExceptionHandler(request: Request, exc: RequestValidationError):
    logSecurityEvent(
        eventType="validation_rejected",
        request=request,
        severity="warning",
        detail={"errorCount": len(exc.errors())},
    )
    return JSONResponse({"detail": "请求参数格式不正确"}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


@app.middleware("http")
async def securityResponseHeaders(request: Request, callNext):
    response = await callNext(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if settings.cookieSecure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.middleware("http")
async def requestGuard(request: Request, callNext):
    if request.url.path.startswith("/api/"):
        getOrCreateDeviceId(request)
        contentLength = request.headers.get("content-length")
        if contentLength and contentLength.isdigit() and int(contentLength) > settings.apiMaxBodyBytes:
            logSecurityEvent(eventType="request_body_too_large", request=request, severity="warning")
            return JSONResponse({"detail": "请求体过大"}, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    response = await callNext(request)
    if request.url.path.startswith("/api/"):
        attachDeviceCookie(request, response)
    return response


def requestOrigin(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if not referer:
        return ""
    parsed = urlparse(referer)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


@app.middleware("http")
async def csrfOriginGuard(request: Request, callNext):
    unsafeMethods = {"POST", "PATCH", "PUT", "DELETE"}
    if request.method in unsafeMethods and request.url.path.startswith("/api/"):
        origin = requestOrigin(request)
        if origin not in settings.csrfTrustedOrigins:
            logSecurityEvent(
                eventType="csrf_rejected",
                request=request,
                severity="warning",
                detail={"origin": origin or "missing"},
            )
            return JSONResponse({"detail": "Forbidden origin"}, status_code=status.HTTP_403_FORBIDDEN)
    return await callNext(request)


def currentUserDependency(request: Request) -> dict:
    return getCurrentUser(request)


def adminDependency(request: Request) -> dict:
    return requireAdmin(request)


def listCasesForQueryRuns(rows: list[dict]) -> list[dict]:
    runs: list[dict] = []
    for row in rows:
        item = dict(row)
        item["application_num"] = decryptIfNeeded(item.get("application_num")) or ""
        item["profile_type"] = item.get("profile_type") or "ceac"
        runs.append(item)
    return runs


def listQueryJobsForAdmin(rows: list[dict]) -> list[dict]:
    now = datetime.now(UTC)
    jobs: list[dict] = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item["queue_position"] = index
        item["application_num"] = decryptIfNeeded(item.get("application_num")) or ""
        item["profile_type"] = item.get("profile_type") or "ceac"
        baseTime = item.get("started_at") if item.get("status") == "running" else item.get("created_at")
        try:
            started = datetime.fromisoformat(str(baseTime)) if baseTime else now
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            item["wait_seconds"] = max(0, int((now - started.astimezone(UTC)).total_seconds()))
        except ValueError:
            item["wait_seconds"] = 0
        jobs.append(item)
    return jobs


def listScheduledQueryJobsForAdmin(rows: list[dict]) -> list[dict]:
    now = datetime.now(UTC)
    jobs: list[dict] = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item["schedule_position"] = index
        item["application_num"] = decryptIfNeeded(item.get("application_num")) or ""
        item["profile_type"] = item.get("profile_type") or "ceac"
        try:
            nextCheckAt = datetime.fromisoformat(str(item.get("next_check_at") or ""))
            if nextCheckAt.tzinfo is None:
                nextCheckAt = nextCheckAt.replace(tzinfo=UTC)
            item["seconds_until_queue"] = max(0, int((nextCheckAt.astimezone(UTC) - now).total_seconds()))
        except ValueError:
            item["seconds_until_queue"] = 0
        jobs.append(item)
    return jobs


def listFinishedQueryJobsForAdmin(rows: list[dict]) -> list[dict]:
    jobs: list[dict] = []
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item["finished_position"] = index
        item["application_num"] = decryptIfNeeded(item.get("application_num")) or ""
        item["profile_type"] = item.get("profile_type") or "ceac"
        startedAt = parseOptionalIso(item.get("started_at"))
        finishedAt = parseOptionalIso(item.get("finished_at"))
        item["duration_seconds"] = max(0, int((finishedAt - startedAt).total_seconds())) if startedAt and finishedAt else 0
        jobs.append(item)
    return jobs


def enforceDailyManualQueryLimit(user: dict) -> None:
    if user.get("role") == "admin":
        return
    queryLimit = settings.premiumDailyManualQueryLimit if user.get("account_tier") == "premium" else settings.standardDailyManualQueryLimit
    now = datetime.now(UTC)
    todayStart = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrowStart = todayStart + timedelta(days=1)
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS query_count
            FROM query_jobs j
            JOIN ceac_cases c ON c.id = j.case_id
            WHERE c.user_id = ?
              AND j.trigger_type IN ('manual', 'passport_slot_manual')
              AND j.created_at >= ?
              AND j.created_at < ?
            """,
            (
                int(user["id"]),
                todayStart.isoformat(),
                tomorrowStart.isoformat(),
            ),
        ).fetchone()
        irccRow = connection.execute(
            """
            SELECT COUNT(*) AS query_count
            FROM ircc_query_jobs j
            JOIN ircc_cases c ON c.id = j.case_id
            WHERE c.user_id = ?
              AND j.trigger_type = 'ircc_manual'
              AND j.created_at >= ?
              AND j.created_at < ?
            """,
            (
                int(user["id"]),
                todayStart.isoformat(),
                tomorrowStart.isoformat(),
            ),
        ).fetchone()
        koreaRow = connection.execute(
            """
            SELECT COUNT(*) AS query_count
            FROM korea_query_jobs j
            JOIN korea_cases c ON c.id = j.case_id
            WHERE c.user_id = ?
              AND j.trigger_type = 'korea_manual'
              AND j.created_at >= ?
              AND j.created_at < ?
            """,
            (
                int(user["id"]),
                todayStart.isoformat(),
                tomorrowStart.isoformat(),
            ),
        ).fetchone()
    queryCount = (
        int(row["query_count"] if row else 0)
        + int(irccRow["query_count"] if irccRow else 0)
        + int(koreaRow["query_count"] if koreaRow else 0)
    )
    if queryCount >= queryLimit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日立即查询次数已达上限（{queryLimit} 次），请明天再试。",
        )


def runDueCases() -> None:
    try:
        queued = enqueueDueCases()
        if queued:
            print(f"[scheduler] queued {len(queued)} CEAC query job(s)")
    except Exception as exc:
        print(f"[scheduler] enqueue failed: {exc}")


def runDuePassportSlotMonitors() -> None:
    try:
        queued = enqueueDuePassportSlotMonitors()
        if queued:
            print(f"[scheduler] queued {len(queued)} GTS slot query job(s)")
    except Exception as exc:
        print(f"[scheduler] enqueue GTS failed: {exc}")


def runDueIrccCases() -> None:
    try:
        queued = enqueueDueIrccCases()
        if queued:
            print(f"[scheduler] queued {len(queued)} IRCC query job(s)")
    except Exception as exc:
        print(f"[scheduler] enqueue IRCC failed: {exc}")


def runDueKoreaCases() -> None:
    try:
        queued = enqueueDueKoreaCases()
        if queued:
            print(f"[scheduler] queued {len(queued)} Korea visa query job(s)")
    except Exception as exc:
        print(f"[scheduler] enqueue Korea visa failed: {exc}")


def parseOptionalIso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def hasUserApplicationProfiles(user: dict) -> bool:
    if int(user.get("has_application_profile_history") or 0) > 0:
        return True
    return any(int(user.get(key) or 0) > 0 for key in ("ceac_case_count", "ircc_case_count", "korea_case_count"))


def processInactiveAccounts() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    noticeBefore = now - timedelta(days=INACTIVITY_NOTICE_DAYS)
    deleteBefore = now - timedelta(days=INACTIVITY_DELETE_DAYS)
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE users
            SET inactivity_notice_sent_at = NULL,
                updated_at = ?
            WHERE lower(trim(coalesce(role, ''))) = 'admin'
              AND inactivity_notice_sent_at IS NOT NULL
            """,
            (now.isoformat(),),
        )
        rows = connection.execute(
            """
            SELECT
                u.id,
                u.email,
                u.role,
                u.created_at,
                u.inactivity_notice_sent_at,
                u.has_application_profile_history,
                (
                    SELECT COUNT(*)
                    FROM ceac_cases c
                    WHERE c.user_id = u.id
                ) AS ceac_case_count,
                (
                    SELECT COUNT(*)
                    FROM ircc_cases ic
                    WHERE ic.user_id = u.id
                ) AS ircc_case_count,
                (
                    SELECT COUNT(*)
                    FROM korea_cases kc
                    WHERE kc.user_id = u.id
                ) AS korea_case_count
            FROM users u
            WHERE lower(trim(coalesce(u.role, ''))) != 'admin'
            """,
        ).fetchall()
        for row in rows:
            if str(row.get("role") or "").strip().lower() == "admin":
                continue
            noticeSentAt = parseOptionalIso(row.get("inactivity_notice_sent_at"))
            if hasUserApplicationProfiles(row):
                if noticeSentAt:
                    connection.execute(
                        "UPDATE users SET inactivity_notice_sent_at = NULL, updated_at = ? WHERE id = ?",
                        (now.isoformat(), row["id"]),
                    )
                continue
            createdAt = parseOptionalIso(row.get("created_at")) or now
            if createdAt > noticeBefore:
                continue
            if createdAt <= deleteBefore and noticeSentAt:
                try:
                    sendSystemEmail(
                        row["email"],
                        "CEACStatusBot 空账号已自动删除",
                        "\n".join(
                            [
                                "你的 CEACStatusBot 账号已因注册后长期未添加任何签证申请档案被自动删除。",
                                "规则：普通账号注册约 15 天后仍未添加 CEAC、IRCC 或韩国签证申请档案会先发送提醒；注册约 30 天后仍未添加任何申请档案，会删除账号。",
                                "只要账号添加过申请档案，就不适用这条自动删除规则。",
                                "管理员账号不适用这条自动删除规则。",
                                "",
                                "如仍需使用，可重新注册账号。",
                            ],
                        ),
                    )
                except Exception as exc:
                    print(f"[cleanup] inactivity deletion email failed for user {row['id']}: {exc}")
                connection.execute("DELETE FROM users WHERE id = ?", (row["id"],))
                continue
            if not noticeSentAt:
                try:
                    sendSystemEmail(
                        row["email"],
                        "CEACStatusBot 空账号删除提醒",
                        "\n".join(
                            [
                                "你的 CEACStatusBot 账号注册后已经约 15 天未添加任何签证申请档案。",
                                "如果注册约 30 天后仍未添加 CEAC、IRCC 或韩国签证申请档案，系统会自动删除该账号。",
                                "只要账号添加过申请档案，就不适用这条自动删除规则。",
                                "管理员账号不适用这条自动删除规则。",
                                "",
                                f"登录入口：{settings.appBaseUrl}",
                            ],
                        ),
                    )
                    connection.execute(
                        "UPDATE users SET inactivity_notice_sent_at = ?, updated_at = ? WHERE id = ?",
                        (now.isoformat(), now.isoformat(), row["id"]),
                    )
                except Exception as exc:
                    print(f"[cleanup] inactivity notice email failed for user {row['id']}: {exc}")


def runInactiveAccountCleanup() -> None:
    try:
        processInactiveAccounts()
    except Exception as exc:
        print(f"[cleanup] inactive account cleanup failed: {exc}")


@app.on_event("startup")
def onStartup() -> None:
    getCredentialMasterKey()
    initializeDatabase()
    migrateEncryptedFields()
    migrateKoreaEncryptedFields()
    if settings.seedDefaultUsers:
        seedDefaultUsers()
    if not scheduler.running:
        scheduler.add_job(runDueCases, "interval", minutes=1, id="run-due-cases", replace_existing=True)
        scheduler.add_job(runDuePassportSlotMonitors, "interval", seconds=1, id="run-due-passport-slot-monitors", replace_existing=True)
        scheduler.add_job(runDueIrccCases, "interval", minutes=1, id="run-due-ircc-cases", replace_existing=True)
        scheduler.add_job(runDueKoreaCases, "interval", minutes=1, id="run-due-korea-cases", replace_existing=True)
        scheduler.add_job(runInactiveAccountCleanup, "interval", hours=6, id="run-inactive-account-cleanup", replace_existing=True)
        scheduler.start()


@app.on_event("shutdown")
def onShutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/auth/send-code")
def sendCode(payload: SendCodeRequest, request: Request) -> dict:
    email = str(payload.email).lower()
    enforceAuthCodeLimits(request, email, "register")
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(UTC)
    with getConnection() as connection:
        existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")
        connection.execute(
            """
            INSERT INTO email_verification_codes (email, code_hash, purpose, expires_at, created_at)
            VALUES (?, ?, 'register', ?, ?)
            """,
            (
                email,
                hashCode(code),
                (now + timedelta(minutes=10)).replace(microsecond=0).isoformat(),
                now.replace(microsecond=0).isoformat(),
            ),
        )
    sendSystemEmail(email, "CEACStatusBot 注册验证码", f"你的注册验证码是：{code}\n\n验证码 10 分钟内有效。")
    logSecurityEvent(eventType="register_code_sent", request=request, email=email)
    return {"ok": True}


@app.post("/api/auth/send-password-reset-code")
def sendPasswordResetCode(payload: PasswordResetCodeRequest, request: Request) -> dict:
    email = str(payload.email).lower()
    enforceAuthCodeLimits(request, email, "password_reset")
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(UTC)
    with getConnection() as connection:
        existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not existing:
            return {"ok": True}
        connection.execute(
            """
            INSERT INTO email_verification_codes (email, code_hash, purpose, expires_at, created_at)
            VALUES (?, ?, 'password_reset', ?, ?)
            """,
            (
                email,
                hashCode(code),
                (now + timedelta(minutes=10)).replace(microsecond=0).isoformat(),
                now.replace(microsecond=0).isoformat(),
            ),
        )
    sendSystemEmail(email, "CEACStatusBot 重置密码验证码", f"你的重置密码验证码是：{code}\n\n验证码 10 分钟内有效。")
    logSecurityEvent(eventType="password_reset_code_sent", request=request, email=email)
    return {"ok": True}


@app.post("/api/auth/reset-password")
def resetPassword(payload: PasswordResetRequest, request: Request) -> dict:
    email = str(payload.email).lower()
    hashes = requestActorHashes(request, email)
    enforceRateLimit(
        request=request,
        scope="password_reset_submit_ip_device",
        subject=f"{hashes['ip_hash']}:{hashes['device_hash']}",
        limit=10,
        windowSeconds=900,
        eventType="password_reset_rate_limited",
    )
    nowIso = utcNowIso()
    with getConnection() as connection:
        user = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
        codeRow = connection.execute(
            """
            SELECT id, code_hash, expires_at
            FROM email_verification_codes
            WHERE email = ? AND purpose = 'password_reset' AND used_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,),
        ).fetchone()
        if not codeRow or codeRow["code_hash"] != hashCode(payload.code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
        if datetime.fromisoformat(codeRow["expires_at"]) < datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
        connection.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hashPassword(payload.password), nowIso, user["id"]),
        )
        connection.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (nowIso, codeRow["id"]))
        connection.execute(
            "UPDATE user_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (nowIso, user["id"]),
        )
    logSecurityEvent(eventType="password_reset_completed", request=request, userId=int(user["id"]), email=email)
    return {"ok": True}


@app.post("/api/auth/register")
def register(payload: RegisterRequest, request: Request, response: Response) -> dict:
    email = str(payload.email).lower()
    hashes = requestActorHashes(request, email)
    enforceRateLimit(
        request=request,
        scope="register_submit_ip_device",
        subject=f"{hashes['ip_hash']}:{hashes['device_hash']}",
        limit=10,
        windowSeconds=900,
        eventType="register_rate_limited",
    )
    nowIso = utcNowIso()
    with getConnection() as connection:
        existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已注册")
        codeRow = connection.execute(
            """
            SELECT id, code_hash, expires_at
            FROM email_verification_codes
            WHERE email = ? AND purpose = 'register' AND used_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,),
        ).fetchone()
        if not codeRow or codeRow["code_hash"] != hashCode(payload.code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")
        if datetime.fromisoformat(codeRow["expires_at"]) < datetime.now(UTC):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期")
        cursor = connection.execute(
            """
            INSERT INTO users (
                email, password_hash, role, account_tier, is_email_verified,
                terms_version, terms_accepted_at, terms_acceptance_ip_hash, terms_acceptance_device_hash,
                created_at, updated_at
            )
            VALUES (?, ?, 'user', 'standard', 1, ?, ?, ?, ?, ?, ?)
            """,
            (
                email,
                hashPassword(payload.password),
                TERMS_VERSION,
                nowIso,
                hashes["ip_hash"],
                hashes["device_hash"],
                nowIso,
                nowIso,
            ),
        )
        connection.execute("UPDATE email_verification_codes SET used_at = ? WHERE id = ?", (nowIso, codeRow["id"]))
        user = connection.execute(
            "SELECT id, email, role, account_tier, is_email_verified, timezone, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    setSessionCookie(response, user, request)
    logSecurityEvent(eventType="register_completed", request=request, userId=int(user["id"]), email=email)
    return {"user": user}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    email = str(payload.email).lower()
    enforceLoginAttemptLimit(request, email)
    with getConnection() as connection:
        user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not verifyPassword(payload.password, user["password_hash"]):
        recordLoginFailure(request, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    clearLoginFailures(email)
    if needsPasswordRehash(user["password_hash"]):
        with getConnection() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hashPassword(payload.password), utcNowIso(), user["id"]),
            )
    publicUser = {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "account_tier": user["account_tier"],
        "is_email_verified": user["is_email_verified"],
        "timezone": user["timezone"],
        "created_at": user["created_at"],
    }
    setSessionCookie(response, publicUser, request)
    logSecurityEvent(eventType="login_success", request=request, userId=int(user["id"]), email=email)
    return {"user": publicUser}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict:
    userId = None
    try:
        userId = int(getCurrentUser(request)["id"])
    except HTTPException:
        userId = None
    clearSessionCookie(response, request)
    logSecurityEvent(eventType="logout", request=request, userId=userId)
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(currentUserDependency)) -> dict:
    return {"user": user}


@app.patch("/api/me")
def updateMe(payload: ProfileUpdateRequest, request: Request, response: Response, user: dict = Depends(currentUserDependency)) -> dict:
    nowIso = utcNowIso()
    with getConnection() as connection:
        privateUser = connection.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not privateUser or not verifyPassword(payload.currentPassword, privateUser["password_hash"]):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误")
        nextEmail = str(payload.email).lower() if payload.email else privateUser["email"]
        if nextEmail != privateUser["email"]:
            exists = connection.execute("SELECT id FROM users WHERE email = ? AND id != ?", (nextEmail, user["id"])).fetchone()
            if exists:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已被使用")
        nextPasswordHash = (
            hashPassword(payload.newPassword)
            if payload.newPassword
            else hashPassword(payload.currentPassword) if needsPasswordRehash(privateUser["password_hash"]) else privateUser["password_hash"]
        )
        connection.execute(
            """
            UPDATE users
            SET email = ?, password_hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (nextEmail, nextPasswordHash, nowIso, user["id"]),
        )
        publicUser = connection.execute(
            "SELECT id, email, role, account_tier, is_email_verified, timezone, created_at FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
    clearSessionCookie(response, request)
    setSessionCookie(response, publicUser, request)
    logSecurityEvent(
        eventType="profile_updated",
        request=request,
        userId=int(user["id"]),
        email=nextEmail,
        detail={"emailChanged": nextEmail != privateUser["email"], "passwordChanged": bool(payload.newPassword)},
    )
    return {"user": publicUser}


@app.patch("/api/me/timezone")
def updateMyTimezone(payload: TimezoneUpdateRequest, user: dict = Depends(currentUserDependency)) -> dict:
    nowIso = utcNowIso()
    with getConnection() as connection:
        connection.execute(
            "UPDATE users SET timezone = ?, updated_at = ? WHERE id = ?",
            (payload.timezone, nowIso, user["id"]),
        )
        publicUser = connection.execute(
            "SELECT id, email, role, account_tier, is_email_verified, timezone, created_at FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
    return {"user": publicUser}


@app.post("/api/me/terms-acceptance")
def acceptCurrentTerms(request: Request, user: dict = Depends(currentUserDependency)) -> dict:
    nowIso = utcNowIso()
    hashes = requestActorHashes(request, str(user.get("email") or ""))
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE users
            SET terms_version = ?,
                terms_accepted_at = ?,
                terms_acceptance_ip_hash = ?,
                terms_acceptance_device_hash = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                TERMS_VERSION,
                nowIso,
                hashes["ip_hash"],
                hashes["device_hash"],
                nowIso,
                user["id"],
            ),
        )
    logSecurityEvent(
        eventType="terms_accepted",
        request=request,
        userId=int(user["id"]),
        email=str(user.get("email") or ""),
        detail={"termsVersion": TERMS_VERSION, "source": "view_terms"},
    )
    return {"ok": True, "termsVersion": TERMS_VERSION, "acceptedAt": nowIso}


@app.get("/api/cases")
def apiListCases(user: dict = Depends(currentUserDependency)) -> dict:
    return {"cases": listCases(int(user["id"]))}


@app.post("/api/cases")
def apiCreateCase(payload: CeacCaseInput, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        case = createCase(int(user["id"]), payload)
        initialQueryJob = None
        if payload.isEnabled:
            job = enqueueCaseQuery(int(case["id"]), "automatic", int(user["id"]))
            if job:
                initialQueryJob = {"jobId": job["id"], "status": job["status"]}
        return {"case": case, "initialQueryJob": initialQueryJob}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.patch("/api/cases/{caseId}")
def apiPatchCase(caseId: int, payload: CeacCasePatch, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        case = patchCase(caseId, int(user["id"]), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {"case": case}


@app.delete("/api/cases/{caseId}")
def apiDeleteCase(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not deleteCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {"ok": True}


@app.patch("/api/profiles/order")
def apiReorderProfiles(payload: ProfileOrderPatch, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        reorderProfiles(int(user["id"]), payload.profiles)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/cases/{caseId}/history")
def apiHistory(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not getCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {"history": listHistory(caseId, int(user["id"]))}


@app.post("/api/cases/{caseId}/test-query")
def apiTestQuery(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    enforceDailyManualQueryLimit(user)
    job = enqueueCaseQuery(caseId, "manual", int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {"jobId": job["id"], "status": job["status"]}


@app.get("/api/query-jobs/{jobId}")
def apiQueryJob(jobId: int, user: dict = Depends(currentUserDependency)) -> dict:
    job = getQueryJob(jobId, int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="查询任务不存在")
    return {"job": job}


@app.post("/api/cases/{caseId}/test-email")
def apiTestEmail(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not getCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    payload = sendCurrentStatusEmail(caseId, int(user["id"]))
    if not payload["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=payload["error"])
    return payload


@app.get("/api/cases/{caseId}/passport-slot-monitor")
def apiPassportSlotMonitor(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not getCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {
        "monitor": getPassportSlotMonitor(caseId, int(user["id"])),
        "history": listPassportSlotHistory(caseId, int(user["id"])),
    }


@app.put("/api/cases/{caseId}/passport-slot-monitor")
def apiSavePassportSlotMonitor(caseId: int, payload: PassportSlotMonitorInput, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        monitor = upsertPassportSlotMonitor(
            caseId,
            int(user["id"]),
            payload.identifier,
            payload.isEnabled,
            payload.emailNotificationsEnabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not monitor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {"monitor": monitor}


@app.patch("/api/cases/{caseId}/passport-slot-monitor")
def apiPatchPassportSlotMonitor(caseId: int, payload: PassportSlotMonitorPatch, user: dict = Depends(currentUserDependency)) -> dict:
    monitor = patchPassportSlotMonitor(
        caseId,
        int(user["id"]),
        isEnabled=payload.isEnabled,
        emailNotificationsEnabled=payload.emailNotificationsEnabled,
    )
    if not monitor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="护照预约监控不存在")
    return {"monitor": monitor}


@app.post("/api/cases/{caseId}/passport-slot-monitor/test-query")
def apiTestPassportSlotMonitor(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    enforceDailyManualQueryLimit(user)
    job = enqueuePassportSlotQuery(caseId, "passport_slot_manual", int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="护照预约监控不存在")
    return {"jobId": job["id"], "status": job["status"]}


@app.post("/api/cases/{caseId}/passport-slot-monitor/test-email")
def apiTestPassportSlotMonitorEmail(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    payload = sendCurrentPassportSlotEmail(caseId, int(user["id"]))
    if not payload["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=payload["error"])
    return payload


@app.post("/api/ircc/applications/discover")
def apiDiscoverIrccApplications(payload: IrccDiscoverRequest, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        return discoverIrccApplications(int(user["id"]), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/ircc/cases")
def apiListIrccCases(user: dict = Depends(currentUserDependency)) -> dict:
    return {"cases": listIrccCases(int(user["id"]))}


@app.post("/api/ircc/cases")
def apiCreateIrccCase(payload: IrccCaseInput, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        case = createIrccCase(int(user["id"]), payload)
        initialQueryJob = None
        if payload.isEnabled:
            job = enqueueIrccCaseQuery(int(case["id"]), "ircc_automatic", int(user["id"]))
            if job:
                initialQueryJob = {"jobId": job["id"], "status": job["status"]}
        return {"case": case, "initialQueryJob": initialQueryJob}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.patch("/api/ircc/cases/{caseId}")
def apiPatchIrccCase(caseId: int, payload: IrccCasePatch, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        case = patchIrccCase(caseId, int(user["id"]), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IRCC 档案不存在")
    return {"case": case}


@app.delete("/api/ircc/cases/{caseId}")
def apiDeleteIrccCase(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not deleteIrccCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IRCC 档案不存在")
    return {"ok": True}


@app.get("/api/ircc/cases/{caseId}/history")
def apiIrccHistory(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not getIrccCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IRCC 档案不存在")
    return {"history": listIrccHistory(caseId, int(user["id"]))}


@app.post("/api/ircc/cases/{caseId}/test-query")
def apiTestIrccQuery(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    enforceDailyManualQueryLimit(user)
    job = enqueueIrccCaseQuery(caseId, "ircc_manual", int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IRCC 档案不存在")
    return {"jobId": job["id"], "status": job["status"]}


@app.post("/api/ircc/cases/{caseId}/test-email")
def apiTestIrccEmail(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    payload = sendCurrentIrccEmail(caseId, int(user["id"]))
    if not payload["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=payload["error"])
    return payload


@app.get("/api/ircc/query-jobs/{jobId}")
def apiIrccQueryJob(jobId: int, user: dict = Depends(currentUserDependency)) -> dict:
    job = getIrccQueryJob(jobId, int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IRCC 查询任务不存在")
    return {"job": job}


@app.get("/api/korea/cases")
def apiListKoreaCases(user: dict = Depends(currentUserDependency)) -> dict:
    return {"cases": listKoreaCases(int(user["id"]))}


@app.post("/api/korea/cases")
def apiCreateKoreaCase(payload: KoreaCaseInput, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        case = createKoreaCase(int(user["id"]), payload)
        initialQueryJob = None
        if payload.isEnabled:
            job = enqueueKoreaCaseQuery(int(case["id"]), "korea_automatic", int(user["id"]))
            if job:
                initialQueryJob = {"jobId": job["id"], "status": job["status"]}
        return {"case": case, "initialQueryJob": initialQueryJob}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.patch("/api/korea/cases/{caseId}")
def apiPatchKoreaCase(caseId: int, payload: KoreaCasePatch, user: dict = Depends(currentUserDependency)) -> dict:
    try:
        case = patchKoreaCase(caseId, int(user["id"]), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="韩国签证档案不存在")
    return {"case": case}


@app.delete("/api/korea/cases/{caseId}")
def apiDeleteKoreaCase(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not deleteKoreaCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="韩国签证档案不存在")
    return {"ok": True}


@app.get("/api/korea/cases/{caseId}/history")
def apiKoreaHistory(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    if not getKoreaCase(caseId, int(user["id"])):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="韩国签证档案不存在")
    return {"history": listKoreaHistory(caseId, int(user["id"]))}


@app.post("/api/korea/cases/{caseId}/test-query")
def apiTestKoreaQuery(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    enforceDailyManualQueryLimit(user)
    job = enqueueKoreaCaseQuery(caseId, "korea_manual", int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="韩国签证档案不存在")
    return {"jobId": job["id"], "status": job["status"]}


@app.post("/api/korea/cases/{caseId}/test-email")
def apiTestKoreaEmail(caseId: int, user: dict = Depends(currentUserDependency)) -> dict:
    payload = sendCurrentKoreaEmail(caseId, int(user["id"]))
    if not payload["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=payload["error"])
    return payload


@app.get("/api/korea/query-jobs/{jobId}")
def apiKoreaQueryJob(jobId: int, user: dict = Depends(currentUserDependency)) -> dict:
    job = getKoreaQueryJob(jobId, int(user["id"]))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="韩国签证查询任务不存在")
    return {"job": job}


@app.get("/api/admin/users")
def adminUsers(_: dict = Depends(adminDependency)) -> dict:
    with getConnection() as connection:
        users = connection.execute(
            """
            SELECT
                u.id,
                u.email,
                u.role,
                u.account_tier,
                u.worker_priority,
                u.is_email_verified,
                u.created_at,
                u.updated_at,
                (
                    SELECT COUNT(*)
                    FROM ceac_cases c
                    WHERE c.user_id = u.id
                ) + (
                    SELECT COUNT(*)
                    FROM ircc_cases ic
                    WHERE ic.user_id = u.id
                ) + (
                    SELECT COUNT(*)
                    FROM korea_cases kc
                    WHERE kc.user_id = u.id
                ) AS case_count,
                NULLIF(MAX(
                    COALESCE((
                        SELECT MAX(c.last_checked_at)
                        FROM ceac_cases c
                        WHERE c.user_id = u.id
                    ), ''),
                    COALESCE((
                        SELECT MAX(ic.last_checked_at)
                        FROM ircc_cases ic
                        WHERE ic.user_id = u.id
                    ), ''),
                    COALESCE((
                        SELECT MAX(kc.last_checked_at)
                        FROM korea_cases kc
                        WHERE kc.user_id = u.id
                    ), '')
                ), '') AS last_checked_at
            FROM users u
            ORDER BY u.id ASC
            """,
        ).fetchall()
    return {"users": users}


@app.patch("/api/admin/users/{userId}/worker-priority")
def adminPatchUserWorkerPriority(userId: int, payload: WorkerPriorityPatch, request: Request, admin: dict = Depends(adminDependency)) -> dict:
    user = updateUserWorkerPriority(userId, payload.workerPriority)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    logSecurityEvent(
        eventType="admin_worker_priority_updated",
        request=request,
        userId=int(admin["id"]),
        detail={"targetUserId": userId, "workerPriority": payload.workerPriority},
    )
    return {"user": user}


@app.patch("/api/admin/users/{userId}/account-tier")
def adminPatchUserAccountTier(userId: int, payload: AccountTierPatch, request: Request, admin: dict = Depends(adminDependency)) -> dict:
    user = updateUserAccountTier(userId, payload.accountTier)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    logSecurityEvent(
        eventType="admin_account_tier_updated",
        request=request,
        userId=int(admin["id"]),
        detail={"targetUserId": userId, "accountTier": payload.accountTier},
    )
    return {"user": user}


@app.get("/api/admin/cases")
def adminCases(_: dict = Depends(adminDependency)) -> dict:
    ceacCases = [
        {
            **case,
            "profileType": "ceac",
            "adminCaseKey": f"ceac-{case['id']}",
        }
        for case in listCases()
    ]
    irccCases = [
        {
            "id": case["id"],
            "userId": case["userId"],
            "displayName": case["displayName"],
            "location": "Canada",
            "applicationNum": case["applicationNumber"] or case["appId"],
            "passportNumber": "",
            "surname": "",
            "receiveEmail": case["receiveEmail"],
            "senderMode": case["senderMode"],
            "isEnabled": case["isEnabled"],
            "ceacAutoLockedByPassportSlot": False,
            "ceacConsecutiveErrorCount": 0,
            "emailNotificationsEnabled": case["emailNotificationsEnabled"],
            "nextCheckAt": case["nextCheckAt"],
            "lastCheckedAt": case["lastCheckedAt"],
            "lastTriggerType": case["lastTriggerType"],
            "lastStatus": case["lastSummary"] or None,
            "lastDescription": case["lastErrorMessage"],
            "lastCeacError": case["lastErrorMessage"],
            "passportSlotMonitor": None,
            "createdAt": case["createdAt"],
            "updatedAt": case["updatedAt"],
            "profileType": "ircc",
            "adminCaseKey": f"ircc-{case['id']}",
            "appId": case["appId"],
            "applicationNumber": case["applicationNumber"],
            "principalApplicant": case["principalApplicant"],
            "statusOverview": case["statusOverview"],
        }
        for case in listIrccCases()
    ]
    koreaCases = [
        {
            "id": case["id"],
            "userId": case["userId"],
            "displayName": case["displayName"],
            "location": "Korea Visa Portal",
            "applicationNum": case["lastApplicationNo"] or case["passportNumber"],
            "passportNumber": case["passportNumber"],
            "surname": "",
            "receiveEmail": case["receiveEmail"],
            "senderMode": case["senderMode"],
            "isEnabled": case["isEnabled"],
            "ceacAutoLockedByPassportSlot": False,
            "ceacConsecutiveErrorCount": 0,
            "emailNotificationsEnabled": case["emailNotificationsEnabled"],
            "nextCheckAt": case["nextCheckAt"],
            "lastCheckedAt": case["lastCheckedAt"],
            "lastTriggerType": case["lastTriggerType"],
            "lastStatus": case["lastStatus"] or None,
            "lastDescription": case["lastErrorMessage"],
            "lastCeacError": case["lastErrorMessage"],
            "passportSlotMonitor": None,
            "createdAt": case["createdAt"],
            "updatedAt": case["updatedAt"],
            "profileType": "korea",
            "adminCaseKey": f"korea-{case['id']}",
            "applicationNo": case["lastApplicationNo"],
            "applicationDate": case["lastApplicationDate"],
            "entryPurpose": case["lastEntryPurpose"],
        }
        for case in listKoreaCases()
    ]
    return {"cases": ceacCases + irccCases + koreaCases}


@app.post("/api/admin/cases/{caseId}/restore-ceac-auto-query")
def adminRestoreCaseAutomaticQuery(caseId: int, _: dict = Depends(adminDependency)) -> dict:
    case = restoreCaseAutomaticQuery(caseId)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="签证档案不存在")
    return {"case": case}


@app.get("/api/admin/cases/{caseId}/history")
def adminCaseHistory(caseId: int, _: dict = Depends(adminDependency)) -> dict:
    return {"history": listHistory(caseId)}


@app.get("/api/admin/query-runs")
def adminQueryRuns(_: dict = Depends(adminDependency)) -> dict:
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    r.id,
                    r.case_id,
                    c.display_name,
                    c.application_num,
                    u.email AS user_email,
                    r.started_at,
                    r.finished_at,
                    r.trigger_type,
                    r.success,
                    CASE
                        WHEN r.trigger_type LIKE 'passport_slot_%' THEN (
                            SELECT
                                CASE
                                    WHEN h.slot_fingerprint LIKE 'state:has_slot:%'
                                        THEN CASE
                                            WHEN EXISTS (
                                                SELECT 1
                                                FROM passport_slot_history previous_h
                                                WHERE previous_h.case_id = h.case_id
                                                  AND previous_h.id < h.id
                                                  AND previous_h.slot_fingerprint LIKE 'state:has_slot:%'
                                            )
                                                THEN 'slot 结果变化：可预约时间有变化（' || h.slot_count || ' 个日期）'
                                            ELSE 'slot 结果变化：发现可预约时间（' || h.slot_count || ' 个日期）'
                                        END
                                    WHEN h.slot_fingerprint = 'state:not_eligible'
                                        THEN CASE
                                            WHEN h.notification_sent = 1
                                                THEN 'slot 结果变化：预约资格可能已结束，已自动停止监控'
                                            ELSE 'slot 结果变化：暂不具备护照预约资格'
                                        END
                                    WHEN h.slot_fingerprint = 'state:no_slot' OR h.slot_fingerprint = 'empty'
                                        THEN 'slot 结果变化：当前暂无 slot'
                                    ELSE 'slot 结果变化：' || h.slot_fingerprint
                                END
                            FROM passport_slot_history h
                            WHERE h.case_id = c.id
                              AND h.fetched_at >= r.started_at
                              AND h.fetched_at <= r.finished_at
                            ORDER BY h.id DESC
                            LIMIT 1
                        )
                        ELSE s.status
                    END AS status,
                    r.error_message,
                    r.duration_ms,
                    CASE
                        WHEN r.trigger_type LIKE 'passport_slot_%' THEN 'passport_slot'
                        ELSE 'ceac'
                    END AS profile_type
                FROM query_runs r
                JOIN ceac_cases c ON c.id = r.case_id
                JOIN users u ON u.id = c.user_id
                LEFT JOIN status_catalog s ON s.id = r.status_id
                UNION ALL
                SELECT
                    1000000000 + r.id AS id,
                    r.case_id,
                    c.display_name,
                    COALESCE(NULLIF(c.application_number, ''), c.app_id) AS application_num,
                    u.email AS user_email,
                    r.started_at,
                    r.finished_at,
                    r.trigger_type,
                    r.success,
                    (
                        SELECT h.change_summary
                        FROM ircc_status_history h
                        WHERE h.case_id = c.id
                          AND h.fetched_at >= r.started_at
                          AND h.fetched_at <= r.finished_at
                        ORDER BY h.id DESC
                        LIMIT 1
                    ) AS status,
                    r.error_message,
                    r.duration_ms,
                    'ircc' AS profile_type
                FROM ircc_query_runs r
                JOIN ircc_cases c ON c.id = r.case_id
                JOIN users u ON u.id = c.user_id
                UNION ALL
                SELECT
                    2000000000 + r.id AS id,
                    r.case_id,
                    c.display_name,
                    COALESCE(NULLIF(c.last_application_no, ''), c.passport_number) AS application_num,
                    u.email AS user_email,
                    r.started_at,
                    r.finished_at,
                    r.trigger_type,
                    r.success,
                    (
                        SELECT h.status
                        FROM korea_status_history h
                        WHERE h.case_id = c.id
                          AND h.fetched_at >= r.started_at
                          AND h.fetched_at <= r.finished_at
                        ORDER BY h.id DESC
                        LIMIT 1
                    ) AS status,
                    r.error_message,
                    r.duration_ms,
                    'korea' AS profile_type
                FROM korea_query_runs r
                JOIN korea_cases c ON c.id = r.case_id
                JOIN users u ON u.id = c.user_id
            )
            ORDER BY finished_at DESC, id DESC
            LIMIT 200
            """,
        ).fetchall()
    return {"runs": listCasesForQueryRuns(rows)}


@app.get("/api/admin/query-jobs")
def adminQueryJobs(_: dict = Depends(adminDependency)) -> dict:
    nowIso = datetime.now(UTC).replace(microsecond=0).isoformat()
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    j.id,
                    j.case_id,
                    j.trigger_type,
                    j.status,
                    j.attempts,
                    j.locked_at,
                    j.locked_by,
                    j.started_at,
                    j.finished_at,
                    j.error_message,
                    j.created_at,
                    j.updated_at,
                    c.display_name,
                    c.application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ceac' AS profile_type
                FROM query_jobs j
                JOIN ceac_cases c ON c.id = j.case_id
                JOIN users u ON u.id = c.user_id
                WHERE j.status IN ('queued', 'running')
                UNION ALL
                SELECT
                    1000000000 + j.id AS id,
                    j.case_id,
                    j.trigger_type,
                    j.status,
                    j.attempts,
                    j.locked_at,
                    j.locked_by,
                    j.started_at,
                    j.finished_at,
                    j.error_message,
                    j.created_at,
                    j.updated_at,
                    c.display_name,
                    COALESCE(NULLIF(c.application_number, ''), c.app_id) AS application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ircc' AS profile_type
                FROM ircc_query_jobs j
                JOIN ircc_cases c ON c.id = j.case_id
                JOIN users u ON u.id = c.user_id
                WHERE j.status IN ('queued', 'running')
                UNION ALL
                SELECT
                    2000000000 + j.id AS id,
                    j.case_id,
                    j.trigger_type,
                    j.status,
                    j.attempts,
                    j.locked_at,
                    j.locked_by,
                    j.started_at,
                    j.finished_at,
                    j.error_message,
                    j.created_at,
                    j.updated_at,
                    c.display_name,
                    COALESCE(NULLIF(c.last_application_no, ''), c.passport_number) AS application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'korea' AS profile_type
                FROM korea_query_jobs j
                JOIN korea_cases c ON c.id = j.case_id
                JOIN users u ON u.id = c.user_id
                WHERE j.status IN ('queued', 'running')
            )
            ORDER BY
                CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                worker_priority ASC,
                id ASC
            LIMIT 200
            """,
        ).fetchall()
        scheduledRows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    'ceac-' || c.id AS scheduled_id,
                    c.id AS case_id,
                    'automatic' AS trigger_type,
                    c.next_check_at,
                    c.display_name,
                    c.application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ceac' AS profile_type
                FROM ceac_cases c
                JOIN users u ON u.id = c.user_id
                WHERE c.is_enabled = 1
                  AND c.next_check_at IS NOT NULL
                  AND c.next_check_at > ?
                  AND NOT EXISTS (
                      SELECT 1 FROM query_jobs j
                      WHERE j.case_id = c.id
                        AND j.status IN ('queued', 'running')
                        AND j.trigger_type NOT LIKE 'passport_slot_%'
                  )
                UNION ALL
                SELECT
                    'gts-' || m.case_id AS scheduled_id,
                    m.case_id AS case_id,
                    'passport_slot_automatic' AS trigger_type,
                    m.next_check_at,
                    c.display_name,
                    c.application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ceac' AS profile_type
                FROM passport_slot_monitors m
                JOIN ceac_cases c ON c.id = m.case_id
                JOIN users u ON u.id = c.user_id
                WHERE m.is_enabled = 1
                  AND m.next_check_at IS NOT NULL
                  AND m.next_check_at > ?
                  AND NOT EXISTS (
                      SELECT 1 FROM query_jobs j
                      WHERE j.case_id = m.case_id
                        AND j.status IN ('queued', 'running')
                        AND j.trigger_type LIKE 'passport_slot_%'
                  )
                UNION ALL
                SELECT
                    'ircc-' || c.id AS scheduled_id,
                    c.id AS case_id,
                    'ircc_automatic' AS trigger_type,
                    c.next_check_at,
                    c.display_name,
                    COALESCE(NULLIF(c.application_number, ''), c.app_id) AS application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ircc' AS profile_type
                FROM ircc_cases c
                JOIN users u ON u.id = c.user_id
                WHERE c.is_enabled = 1
                  AND c.next_check_at IS NOT NULL
                  AND c.next_check_at > ?
                  AND NOT EXISTS (
                      SELECT 1 FROM ircc_query_jobs j
                      WHERE j.case_id = c.id
                        AND j.status IN ('queued', 'running')
                  )
                UNION ALL
                SELECT
                    'korea-' || c.id AS scheduled_id,
                    c.id AS case_id,
                    'korea_automatic' AS trigger_type,
                    c.next_check_at,
                    c.display_name,
                    COALESCE(NULLIF(c.last_application_no, ''), c.passport_number) AS application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'korea' AS profile_type
                FROM korea_cases c
                JOIN users u ON u.id = c.user_id
                WHERE c.is_enabled = 1
                  AND c.next_check_at IS NOT NULL
                  AND c.next_check_at > ?
                  AND NOT EXISTS (
                      SELECT 1 FROM korea_query_jobs j
                      WHERE j.case_id = c.id
                        AND j.status IN ('queued', 'running')
                  )
            )
            ORDER BY next_check_at ASC, worker_priority ASC, case_id ASC
            LIMIT 50
            """,
            (nowIso, nowIso, nowIso, nowIso),
        ).fetchall()
        finishedRows = connection.execute(
            """
            SELECT *
            FROM (
                SELECT
                    j.id,
                    j.case_id,
                    j.trigger_type,
                    j.status,
                    j.attempts,
                    j.locked_at,
                    j.locked_by,
                    j.started_at,
                    j.finished_at,
                    j.error_message,
                    j.created_at,
                    j.updated_at,
                    c.display_name,
                    c.application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ceac' AS profile_type
                FROM query_jobs j
                JOIN ceac_cases c ON c.id = j.case_id
                JOIN users u ON u.id = c.user_id
                WHERE j.status IN ('succeeded', 'failed')
                  AND j.finished_at IS NOT NULL
                UNION ALL
                SELECT
                    1000000000 + j.id AS id,
                    j.case_id,
                    j.trigger_type,
                    j.status,
                    j.attempts,
                    j.locked_at,
                    j.locked_by,
                    j.started_at,
                    j.finished_at,
                    j.error_message,
                    j.created_at,
                    j.updated_at,
                    c.display_name,
                    COALESCE(NULLIF(c.application_number, ''), c.app_id) AS application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'ircc' AS profile_type
                FROM ircc_query_jobs j
                JOIN ircc_cases c ON c.id = j.case_id
                JOIN users u ON u.id = c.user_id
                WHERE j.status IN ('succeeded', 'failed')
                  AND j.finished_at IS NOT NULL
                UNION ALL
                SELECT
                    2000000000 + j.id AS id,
                    j.case_id,
                    j.trigger_type,
                    j.status,
                    j.attempts,
                    j.locked_at,
                    j.locked_by,
                    j.started_at,
                    j.finished_at,
                    j.error_message,
                    j.created_at,
                    j.updated_at,
                    c.display_name,
                    COALESCE(NULLIF(c.last_application_no, ''), c.passport_number) AS application_num,
                    u.email AS user_email,
                    u.worker_priority,
                    'korea' AS profile_type
                FROM korea_query_jobs j
                JOIN korea_cases c ON c.id = j.case_id
                JOIN users u ON u.id = c.user_id
                WHERE j.status IN ('succeeded', 'failed')
                  AND j.finished_at IS NOT NULL
            )
            ORDER BY finished_at DESC, id DESC
            LIMIT 50
            """,
        ).fetchall()
    return {
        "jobs": listQueryJobsForAdmin(rows),
        "scheduledJobs": listScheduledQueryJobsForAdmin(scheduledRows),
        "finishedJobs": listFinishedQueryJobsForAdmin(finishedRows),
    }


@app.get("/api/admin/security-events")
def adminSecurityEvents(limit: int = 200, _: dict = Depends(adminDependency)) -> dict:
    return {"events": listSecurityEvents(limit)}


@app.get("/api/admin/system-email")
def adminSystemEmail(_: dict = Depends(adminDependency)) -> dict:
    return {"config": getSystemSmtpConfigPublic()}


@app.get("/api/admin/email-deliveries")
def adminEmailDeliveries(limit: int = 200, _: dict = Depends(adminDependency)) -> dict:
    safeLimit = min(max(limit, 1), 500)
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT
                l.id,
                l.user_id,
                u.email AS user_email,
                l.case_id,
                COALESCE(c.display_name, '') AS display_name,
                l.email_type,
                l.recipient,
                l.subject,
                l.body_encrypted,
                l.created_at
            FROM email_delivery_logs l
            JOIN users u ON u.id = l.user_id
            LEFT JOIN ceac_cases c ON c.id = l.case_id
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT ?
            """,
            (safeLimit,),
        ).fetchall()
    deliveries = []
    for row in rows:
        item = dict(row)
        item["body"] = decryptIfNeeded(item.pop("body_encrypted") or "") or ""
        deliveries.append(item)
    return {"deliveries": deliveries}


@app.put("/api/admin/system-email")
def adminSaveSystemEmail(payload: SystemSmtpConfigInput, _: dict = Depends(adminDependency)) -> dict:
    try:
        config = saveSystemSmtpConfig(
            fromEmail=str(payload.fromEmail),
            host=payload.host,
            port=payload.port,
            useSsl=payload.useSsl,
            password=payload.password,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"config": config}
