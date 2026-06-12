import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from CEACStatusBot.request import query_status

from .config import getSettings
from .database import getConnection, utcNowIso
from .mailer import sendCaseNotification, sendCeacConsecutiveFailureNotification, sendIssuedAutoStopNotification
from .passport_slot_service import (
    isPassportSlotTrigger,
    runPassportSlotQuery,
)
from .schemas import CeacCaseInput, CeacCasePatch, ProfileOrderItem
from .secrets import decryptIfNeeded, encryptSecret, isEncryptedSecret


SENSITIVE_CASE_COLUMNS = {"application_num", "passport_number", "surname", "receive_email"}
STANDARD_CASE_LIMIT = 1
PREMIUM_CASE_LIMIT = 5
STANDARD_WORKER_PRIORITY = 100
PREMIUM_WORKER_PRIORITY = 50
CEAC_FAILURE_NOTICE_THRESHOLD = 5
CEAC_FAILURE_STOP_THRESHOLD = 10
CEAC_FAILURE_SLOW_STOP_DAYS = 7
QUERY_TIMEOUT_ERROR_MESSAGE = (
    "查询运行超过系统设定时间仍未完成，已标记为失败。可能是信息填写有误、CEAC/GTS 服务暂时异常或服务器繁忙；"
    "请核对信息输入是否正确后重试，仍有问题请联系管理员。"
)


def isIssuedStatus(status: str | None) -> bool:
    return (status or "").strip().lower() == "issued"


def computeNextCheckAt(base: datetime | None = None, status: str | None = None) -> str:
    base = base or datetime.now(UTC)
    if isIssuedStatus(status):
        return computeNextDailyCheckAt(base)
    nextHour = (base + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (nextHour + timedelta(minutes=random.randint(0, 59))).isoformat()


def computeNextDailyCheckAt(base: datetime | None = None) -> str:
    base = base or datetime.now(UTC)
    nextDay = (base + timedelta(days=1)).replace(second=0, microsecond=0)
    return nextDay.replace(hour=random.randint(0, 23), minute=random.randint(0, 59)).isoformat()


def countRecentCeacFailureRuns(connection: Any, caseId: int) -> int:
    rows = connection.execute(
        """
        SELECT success
        FROM query_runs
        WHERE case_id = ?
          AND trigger_type IN ('manual', 'automatic')
        ORDER BY id DESC
        LIMIT ?
        """,
        (caseId, CEAC_FAILURE_STOP_THRESHOLD),
    ).fetchall()
    count = 0
    for row in rows:
        if int(row["success"]):
            break
        count += 1
    return count


def parseIso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def decryptCaseRow(row: dict[str, Any]) -> dict[str, Any]:
    decrypted = dict(row)
    for column in SENSITIVE_CASE_COLUMNS:
        decrypted[column] = decryptIfNeeded(decrypted.get(column)) or ""
    return decrypted


def normalizeCaseRow(row: dict[str, Any]) -> dict[str, Any]:
    row = decryptCaseRow(row)
    passportSlotLastResult = None
    passportSlotLastResultJson = decryptIfNeeded(row.get("passport_slot_last_result_json") or "") or ""
    if passportSlotLastResultJson:
        try:
            passportSlotLastResult = json.loads(passportSlotLastResultJson)
        except json.JSONDecodeError:
            passportSlotLastResult = None
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "displayName": row["display_name"],
        "location": row["location"],
        "applicationNum": row["application_num"],
        "passportNumber": row["passport_number"],
        "surname": row["surname"],
        "receiveEmail": row["receive_email"],
        "senderMode": row["sender_mode"],
        "isEnabled": bool(row["is_enabled"]),
        "ceacAutoLockedByPassportSlot": bool(row.get("ceac_auto_locked_by_passport_slot", 0)),
        "ceacConsecutiveErrorCount": int(row.get("ceac_consecutive_error_count") or 0),
        "emailNotificationsEnabled": bool(row["email_notifications_enabled"]),
        "sortOrder": int(row.get("sort_order") or 0),
        "nextCheckAt": row["next_check_at"],
        "lastCheckedAt": row["last_checked_at"],
        "lastTriggerType": row.get("last_trigger_type"),
        "lastStatus": row.get("last_status"),
        "lastDescription": row.get("last_description"),
        "lastCeacError": row.get("last_ceac_error") or "",
        "passportSlotMonitor": {
            "isEnabled": bool(row.get("passport_slot_is_enabled")),
            "emailNotificationsEnabled": bool(row.get("passport_slot_email_notifications_enabled")),
            "nextCheckAt": row.get("passport_slot_next_check_at"),
            "lastCheckedAt": row.get("passport_slot_last_checked_at"),
            "lastSlotCount": int(row.get("passport_slot_last_slot_count") or 0),
            "lastResult": passportSlotLastResult,
            "lastErrorMessage": row.get("passport_slot_last_error_message") or "",
        } if row.get("passport_slot_monitor_id") is not None else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def listCases(userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if userId is not None:
        where = "WHERE c.user_id = ?"
        params = (userId,)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT c.*,
                   s.status AS last_status,
                   s.description AS last_description,
                   m.id AS passport_slot_monitor_id,
                   m.is_enabled AS passport_slot_is_enabled,
                   m.email_notifications_enabled AS passport_slot_email_notifications_enabled,
                   m.next_check_at AS passport_slot_next_check_at,
                   m.last_checked_at AS passport_slot_last_checked_at,
                   m.last_slot_count AS passport_slot_last_slot_count,
                   m.last_result_json AS passport_slot_last_result_json,
                   m.last_error_message AS passport_slot_last_error_message,
                   (
                       SELECT r.error_message
                       FROM query_runs r
                       WHERE r.case_id = c.id
                         AND r.trigger_type IN ('manual', 'automatic')
                       ORDER BY r.id DESC
                       LIMIT 1
                   ) AS last_ceac_error
            FROM ceac_cases c
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            LEFT JOIN passport_slot_monitors m ON m.case_id = c.id
            {where}
            ORDER BY c.sort_order ASC, c.updated_at DESC, c.id DESC
            """,
            params,
        ).fetchall()
    return [normalizeCaseRow(row) for row in rows]


def nextProfileSortOrder(connection: Any, userId: int) -> int:
    rows = connection.execute(
        """
        SELECT MIN(sort_order) AS min_sort_order FROM ceac_cases WHERE user_id = ?
        UNION ALL
        SELECT MIN(sort_order) AS min_sort_order FROM ircc_cases WHERE user_id = ?
        UNION ALL
        SELECT MIN(sort_order) AS min_sort_order FROM korea_cases WHERE user_id = ?
        """,
        (userId, userId, userId),
    ).fetchall()
    values = [int(row["min_sort_order"]) for row in rows if row["min_sort_order"] is not None]
    return (min(values) if values else 0) - 100


def reorderProfiles(userId: int, profiles: list[ProfileOrderItem]) -> None:
    with getConnection() as connection:
        ceacRows = connection.execute("SELECT id FROM ceac_cases WHERE user_id = ?", (userId,)).fetchall()
        irccRows = connection.execute("SELECT id FROM ircc_cases WHERE user_id = ?", (userId,)).fetchall()
        koreaRows = connection.execute("SELECT id FROM korea_cases WHERE user_id = ?", (userId,)).fetchall()
        ownedKeys = {("ceac", int(row["id"])) for row in ceacRows}
        ownedKeys.update({("ircc", int(row["id"])) for row in irccRows})
        ownedKeys.update({("korea", int(row["id"])) for row in koreaRows})
        requestedKeys = [(profile.profileType, int(profile.id)) for profile in profiles]
        if set(requestedKeys) != ownedKeys:
            raise ValueError("档案排序列表已过期，请刷新后重试。")
        for index, (profileType, profileId) in enumerate(requestedKeys):
            table = {"ceac": "ceac_cases", "ircc": "ircc_cases", "korea": "korea_cases"}[profileType]
            connection.execute(
                f"UPDATE {table} SET sort_order = ? WHERE id = ? AND user_id = ?",
                (index * 100, profileId, userId),
            )


def getCase(caseId: int, userId: int | None = None) -> dict[str, Any] | None:
    params: tuple[Any, ...] = (caseId,)
    extraWhere = ""
    if userId is not None:
        extraWhere = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT c.*,
                   s.status AS last_status,
                   s.description AS last_description,
                   m.id AS passport_slot_monitor_id,
                   m.is_enabled AS passport_slot_is_enabled,
                   m.email_notifications_enabled AS passport_slot_email_notifications_enabled,
                   m.next_check_at AS passport_slot_next_check_at,
                   m.last_checked_at AS passport_slot_last_checked_at,
                   m.last_slot_count AS passport_slot_last_slot_count,
                   m.last_result_json AS passport_slot_last_result_json,
                   m.last_error_message AS passport_slot_last_error_message,
                   (
                       SELECT r.error_message
                       FROM query_runs r
                       WHERE r.case_id = c.id
                         AND r.trigger_type IN ('manual', 'automatic')
                       ORDER BY r.id DESC
                       LIMIT 1
                   ) AS last_ceac_error
            FROM ceac_cases c
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            LEFT JOIN passport_slot_monitors m ON m.case_id = c.id
            WHERE c.id = ? {extraWhere}
            """,
            params,
        ).fetchone()
    return normalizeCaseRow(row) if row else None


def upsertSmtpConfig(connection: Any, userId: int, smtpConfig: Any) -> None:
    if not smtpConfig:
        return
    now = utcNowIso()
    connection.execute(
        """
        INSERT INTO smtp_configs (user_id, from_email, host, port, use_ssl, password_encrypted, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            from_email = excluded.from_email,
            host = excluded.host,
            port = excluded.port,
            use_ssl = excluded.use_ssl,
            password_encrypted = excluded.password_encrypted,
            updated_at = excluded.updated_at
        """,
        (
            userId,
            str(smtpConfig.fromEmail),
            smtpConfig.host,
            smtpConfig.port,
            int(smtpConfig.useSsl),
            encryptSecret(smtpConfig.password),
            now,
            now,
        ),
    )


def createCase(userId: int, payload: CeacCaseInput) -> dict[str, Any]:
    now = utcNowIso()
    with getConnection() as connection:
        user = connection.execute("SELECT role, account_tier FROM users WHERE id = ?", (userId,)).fetchone()
        if not user:
            raise ValueError("用户不存在")
        if payload.emailNotificationsEnabled and not payload.receiveEmail:
            raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
        if user.get("role") != "admin":
            caseCountRow = connection.execute("SELECT COUNT(*) AS case_count FROM ceac_cases WHERE user_id = ?", (userId,)).fetchone()
            irccCaseCountRow = connection.execute("SELECT COUNT(*) AS case_count FROM ircc_cases WHERE user_id = ?", (userId,)).fetchone()
            koreaCaseCountRow = connection.execute("SELECT COUNT(*) AS case_count FROM korea_cases WHERE user_id = ?", (userId,)).fetchone()
            caseCount = (
                int(caseCountRow["case_count"] if caseCountRow else 0)
                + int(irccCaseCountRow["case_count"] if irccCaseCountRow else 0)
                + int(koreaCaseCountRow["case_count"] if koreaCaseCountRow else 0)
            )
            caseLimit = PREMIUM_CASE_LIMIT if user.get("account_tier") == "premium" else STANDARD_CASE_LIMIT
            if caseCount >= caseLimit:
                raise ValueError(f"当前账号最多可添加 {caseLimit} 个档案，请联系管理员升级账号。")
        upsertSmtpConfig(connection, userId, payload.smtpConfig)
        cursor = connection.execute(
            """
            INSERT INTO ceac_cases (
                user_id, display_name, location, application_num, passport_number, surname,
                receive_email, sender_mode, is_enabled, email_notifications_enabled,
                sort_order, next_check_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                userId,
                payload.displayName,
                payload.location,
                encryptSecret(payload.applicationNum),
                encryptSecret(payload.passportNumber),
                encryptSecret(payload.surname),
                encryptSecret(str(payload.receiveEmail or "")),
                payload.senderMode,
                int(payload.isEnabled),
                int(payload.emailNotificationsEnabled),
                nextProfileSortOrder(connection, userId),
                computeNextCheckAt() if payload.isEnabled else None,
                now,
                now,
            ),
        )
        caseId = cursor.lastrowid
        connection.execute("UPDATE users SET has_application_profile_history = 1, updated_at = ? WHERE id = ?", (now, userId))
    case = getCase(int(caseId), userId)
    if case is None:
        raise RuntimeError("创建档案失败")
    return case


def patchCase(caseId: int, userId: int, payload: CeacCasePatch, *, allowLockedEnable: bool = False) -> dict[str, Any] | None:
    current = getCase(caseId, userId)
    if not current:
        return None
    data = payload.model_dump(exclude_unset=True)
    if data.get("isEnabled") is True and current.get("ceacAutoLockedByPassportSlot") and not allowLockedEnable:
        raise ValueError("GTS 监控已接管该档案，普通用户不能恢复 CEAC 自动查询；请联系管理员恢复。")
    nextEmailNotificationsEnabled = data.get("emailNotificationsEnabled", current.get("emailNotificationsEnabled"))
    nextReceiveEmail = data.get("receiveEmail", current.get("receiveEmail"))
    if nextEmailNotificationsEnabled and not nextReceiveEmail:
        raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
    columnMap = {
        "displayName": "display_name",
        "location": "location",
        "applicationNum": "application_num",
        "passportNumber": "passport_number",
        "surname": "surname",
        "receiveEmail": "receive_email",
        "senderMode": "sender_mode",
        "isEnabled": "is_enabled",
        "emailNotificationsEnabled": "email_notifications_enabled",
    }
    encryptedKeys = {"applicationNum", "passportNumber", "surname", "receiveEmail"}
    now = utcNowIso()
    with getConnection() as connection:
        if payload.smtpConfig:
            upsertSmtpConfig(connection, userId, payload.smtpConfig)
        assignments: list[str] = []
        values: list[Any] = []
        for key, column in columnMap.items():
            if key not in data:
                continue
            value = data[key]
            if key in encryptedKeys and value is not None:
                value = encryptSecret(str(value))
            if key == "isEnabled":
                value = int(value)
                assignments.append("next_check_at = ?")
                values.append(computeNextCheckAt() if value else None)
                if value and allowLockedEnable:
                    assignments.append("ceac_auto_locked_by_passport_slot = ?")
                    values.append(0)
            if key == "emailNotificationsEnabled":
                value = int(value)
            assignments.append(f"{column} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(now)
        values.extend([caseId, userId])
        connection.execute(
            f"UPDATE ceac_cases SET {', '.join(assignments)} WHERE id = ? AND user_id = ?",
            tuple(values),
        )
    return getCase(caseId, userId)


def restoreCaseAutomaticQuery(caseId: int) -> dict[str, Any] | None:
    now = utcNowIso()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT c.user_id, s.status AS last_status
            FROM ceac_cases c
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            WHERE c.id = ?
            """,
            (caseId,),
        ).fetchone()
        if not row:
            return None
        connection.execute(
            """
            UPDATE ceac_cases
            SET is_enabled = 1,
                ceac_auto_locked_by_passport_slot = 0,
                next_check_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (computeNextCheckAt(status=row.get("last_status")), now, caseId),
        )
    return getCase(caseId, int(row["user_id"]))


def updateUserWorkerPriority(userId: int, workerPriority: int) -> dict[str, Any] | None:
    now = utcNowIso()
    with getConnection() as connection:
        cursor = connection.execute(
            "UPDATE users SET worker_priority = ?, updated_at = ? WHERE id = ?",
            (workerPriority, now, userId),
        )
        if cursor.rowcount == 0:
            return None
        return connection.execute(
            "SELECT id, email, role, account_tier, worker_priority, is_email_verified, created_at, updated_at FROM users WHERE id = ?",
            (userId,),
        ).fetchone()


def updateUserAccountTier(userId: int, accountTier: str) -> dict[str, Any] | None:
    now = utcNowIso()
    workerPriority = PREMIUM_WORKER_PRIORITY if accountTier == "premium" else STANDARD_WORKER_PRIORITY
    with getConnection() as connection:
        cursor = connection.execute(
            "UPDATE users SET account_tier = ?, worker_priority = ?, updated_at = ? WHERE id = ?",
            (accountTier, workerPriority, now, userId),
        )
        if cursor.rowcount == 0:
            return None
        return connection.execute(
            "SELECT id, email, role, account_tier, worker_priority, is_email_verified, created_at, updated_at FROM users WHERE id = ?",
            (userId,),
        ).fetchone()


def deleteCase(caseId: int, userId: int) -> bool:
    with getConnection() as connection:
        cursor = connection.execute("DELETE FROM ceac_cases WHERE id = ? AND user_id = ?", (caseId, userId))
        return cursor.rowcount > 0


def getOrCreateStatus(connection: Any, status: str, description: str) -> int:
    now = utcNowIso()
    existing = connection.execute(
        "SELECT id FROM status_catalog WHERE status = ? AND description = ?",
        (status, description),
    ).fetchone()
    if existing:
        return int(existing["id"])
    cursor = connection.execute(
        "INSERT INTO status_catalog (status, description, created_at) VALUES (?, ?, ?)",
        (status, description, now),
    )
    return int(cursor.lastrowid)


def runCaseQuery(caseId: int, triggerType: str = "automatic") -> dict[str, Any]:
    started = datetime.now(UTC)
    startedIso = started.replace(microsecond=0).isoformat()
    errorMessage = ""
    statusId: int | None = None
    success = False
    result: dict[str, Any] = {"success": False}
    with getConnection() as connection:
        case = connection.execute("SELECT * FROM ceac_cases WHERE id = ?", (caseId,)).fetchone()
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (case["user_id"],)).fetchone() if case else None
    if not case:
        raise RuntimeError("签证档案不存在")
    case = decryptCaseRow(case)

    try:
        result = query_status(case["location"], case["application_num"], case["passport_number"], case["surname"])
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "CEAC 查询失败"))
        success = True
    except Exception as exc:
        errorMessage = str(exc)

    finished = datetime.now(UTC)
    durationMs = int((finished - started).total_seconds() * 1000)
    finishedIso = finished.replace(microsecond=0).isoformat()

    with getConnection() as connection:
        hasChanged = False
        if success:
            statusId = getOrCreateStatus(connection, str(result["status"]), str(result.get("description", "")))
            lastHistory = connection.execute(
                """
                SELECT h.ceac_last_updated, s.status
                FROM case_status_history h
                JOIN status_catalog s ON s.id = h.status_id
                WHERE h.case_id = ?
                ORDER BY h.id DESC
                LIMIT 1
                """,
                (caseId,),
            ).fetchone()
            ceacLastUpdated = str(result.get("case_last_updated", ""))
            hasChanged = (
                lastHistory is None
                or lastHistory["status"] != result["status"]
                or lastHistory["ceac_last_updated"] != ceacLastUpdated
            )
            if hasChanged:
                connection.execute(
                    """
                    INSERT INTO case_status_history (
                        case_id, status_id, ceac_last_updated, visa_type, case_created, fetched_at, raw_payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        caseId,
                        statusId,
                        ceacLastUpdated,
                        str(result.get("visa_type", "")),
                        str(result.get("case_created", "")),
                        finishedIso,
                        encryptSecret(json.dumps(result, ensure_ascii=False)),
                    ),
                )
                if bool(case["email_notifications_enabled"]):
                    try:
                        sendCaseNotification(case, smtpConfig, result, connection)
                    except Exception as exc:
                        errorMessage = f"Notification failed: {exc}"
            connection.execute(
                """
                UPDATE ceac_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_status_id = ?,
                    last_trigger_type = ?,
                    ceac_consecutive_error_count = 0,
                    ceac_error_notice_sent_at = NULL,
                    ceac_failure_slow_started_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (finishedIso, computeNextCheckAt(finished, str(result.get("status", ""))), statusId, triggerType, finishedIso, caseId),
            )
        else:
            previousErrorCount = int(case.get("ceac_consecutive_error_count") or 0)
            recentFailureRunCount = countRecentCeacFailureRuns(connection, caseId)
            previousConsecutiveFailures = max(previousErrorCount, recentFailureRunCount)
            errorCount = previousConsecutiveFailures + 1
            slowStartedValue = str(case.get("ceac_failure_slow_started_at") or "")
            slowStartedAt = parseIso(slowStartedValue) if slowStartedValue else None
            shouldEnterSlowMode = errorCount >= CEAC_FAILURE_STOP_THRESHOLD and slowStartedAt is None
            effectiveSlowStartedAt = finished if shouldEnterSlowMode else slowStartedAt
            shouldStopAuto = (
                errorCount >= CEAC_FAILURE_STOP_THRESHOLD
                and effectiveSlowStartedAt is not None
                and not shouldEnterSlowMode
                and finished - effectiveSlowStartedAt >= timedelta(days=CEAC_FAILURE_SLOW_STOP_DAYS)
            )
            shouldSendFailureNotice = (
                errorCount >= CEAC_FAILURE_NOTICE_THRESHOLD
                and not bool(case.get("ceac_error_notice_sent_at"))
                and not shouldEnterSlowMode
                and not shouldStopAuto
            )
            shouldSendSlowNotice = shouldEnterSlowMode
            shouldSendStopNotice = shouldStopAuto
            nextCheckAt = None if shouldStopAuto else computeNextDailyCheckAt(finished) if errorCount >= CEAC_FAILURE_STOP_THRESHOLD else computeNextCheckAt(finished)
            slowStartedValue = finishedIso if shouldEnterSlowMode else slowStartedValue
            connection.execute(
                """
                UPDATE ceac_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_trigger_type = ?,
                    is_enabled = CASE WHEN ? THEN 0 ELSE is_enabled END,
                    ceac_consecutive_error_count = ?,
                    ceac_failure_slow_started_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    finishedIso,
                    nextCheckAt,
                    triggerType,
                    int(shouldStopAuto),
                    errorCount,
                    slowStartedValue or None,
                    finishedIso,
                    caseId,
                ),
            )
            if bool(case["email_notifications_enabled"]) and (shouldSendFailureNotice or shouldSendSlowNotice or shouldSendStopNotice):
                try:
                    sendCeacConsecutiveFailureNotification(
                        case,
                        smtpConfig,
                        errorCount=errorCount,
                        errorMessage=errorMessage,
                        stopped=shouldStopAuto,
                        slowed=shouldSendSlowNotice,
                        connection=connection,
                    )
                    connection.execute(
                        "UPDATE ceac_cases SET ceac_error_notice_sent_at = ?, updated_at = ? WHERE id = ?",
                        (finishedIso, finishedIso, caseId),
                    )
                except Exception as exc:
                    errorMessage = f"{errorMessage}; Notification failed: {exc}" if errorMessage else f"Notification failed: {exc}"
        connection.execute(
            """
            INSERT INTO query_runs (case_id, started_at, finished_at, success, status_id, error_message, duration_ms, trigger_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (caseId, startedIso, finishedIso, int(success), statusId, errorMessage, durationMs, triggerType),
        )
    return {"success": success, "changed": success and hasChanged, "error": errorMessage, "result": result}


def sendCurrentStatusEmail(caseId: int, userId: int | None = None) -> dict[str, Any]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        case = connection.execute(f"SELECT * FROM ceac_cases WHERE id = ? {userFilter}", params).fetchone()
        if not case:
            return {"success": False, "error": "签证档案不存在"}
        case = decryptCaseRow(case)
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (case["user_id"],)).fetchone()
        latest = connection.execute(
            """
            SELECT h.*, s.status, s.description
            FROM case_status_history h
            JOIN status_catalog s ON s.id = h.status_id
            WHERE h.case_id = ?
            ORDER BY h.id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
    if not latest:
        return {"success": False, "error": "暂无现有状态，请先立即查询一次"}
    result = {
        "success": True,
        "visa_type": latest["visa_type"],
        "status": latest["status"],
        "case_created": latest["case_created"],
        "case_last_updated": latest["ceac_last_updated"],
        "description": latest["description"],
        "application_num": case["application_num"],
        "application_num_origin": case["application_num"],
    }
    try:
        sendCaseNotification(case, smtpConfig, result, isTest=True)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "error": ""}


def listHistory(caseId: int, userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT h.*, s.status, s.description
            FROM case_status_history h
            JOIN ceac_cases c ON c.id = h.case_id
            JOIN status_catalog s ON s.id = h.status_id
            WHERE h.case_id = ? {userFilter}
            ORDER BY h.id DESC
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "caseId": row["case_id"],
            "status": row["status"],
            "description": row["description"],
            "ceacLastUpdated": row["ceac_last_updated"],
            "visaType": row["visa_type"],
            "caseCreated": row["case_created"],
            "fetchedAt": row["fetched_at"],
            "rawPayload": json.loads(decryptIfNeeded(row["raw_payload"]) or "{}"),
        }
        for row in rows
    ]


def migrateEncryptedFields() -> None:
    with getConnection() as connection:
        for row in connection.execute("SELECT * FROM ceac_cases").fetchall():
            assignments: list[str] = []
            values: list[Any] = []
            for column in SENSITIVE_CASE_COLUMNS:
                value = row[column]
                if value and not isEncryptedSecret(value):
                    assignments.append(f"{column} = ?")
                    values.append(encryptSecret(str(value)))
            if assignments:
                values.append(row["id"])
                connection.execute(f"UPDATE ceac_cases SET {', '.join(assignments)} WHERE id = ?", tuple(values))

        for tableName in ("smtp_configs", "system_smtp_config"):
            for row in connection.execute(f"SELECT id, password_encrypted FROM {tableName}").fetchall():
                value = row["password_encrypted"]
                if value and not value.startswith("v2:"):
                    connection.execute(
                        f"UPDATE {tableName} SET password_encrypted = ? WHERE id = ?",
                        (encryptSecret(decryptIfNeeded(value) or value), row["id"]),
                    )

        for row in connection.execute("SELECT id, raw_payload FROM case_status_history").fetchall():
            value = row["raw_payload"]
            if value and not isEncryptedSecret(value):
                connection.execute(
                    "UPDATE case_status_history SET raw_payload = ? WHERE id = ?",
                    (encryptSecret(str(value)), row["id"]),
                )

        for row in connection.execute("SELECT id, identifier_encrypted, last_result_json FROM passport_slot_monitors").fetchall():
            if row["identifier_encrypted"] and not isEncryptedSecret(row["identifier_encrypted"]):
                connection.execute(
                    "UPDATE passport_slot_monitors SET identifier_encrypted = ? WHERE id = ?",
                    (encryptSecret(str(row["identifier_encrypted"])), row["id"]),
                )
            if row["last_result_json"] and not isEncryptedSecret(row["last_result_json"]):
                connection.execute(
                    "UPDATE passport_slot_monitors SET last_result_json = ? WHERE id = ?",
                    (encryptSecret(str(row["last_result_json"])), row["id"]),
                )

        for row in connection.execute("SELECT id, raw_payload FROM passport_slot_history").fetchall():
            value = row["raw_payload"]
            if value and not isEncryptedSecret(value):
                connection.execute(
                    "UPDATE passport_slot_history SET raw_payload = ? WHERE id = ?",
                    (encryptSecret(str(value)), row["id"]),
                )


def normalizeQueryJob(row: dict[str, Any]) -> dict[str, Any]:
    resultJson = decryptIfNeeded(row.get("result_json") or "") or ""
    result = json.loads(resultJson) if resultJson else None
    return {
        "id": row["id"],
        "caseId": row["case_id"],
        "triggerType": row["trigger_type"],
        "status": row["status"],
        "attempts": row["attempts"],
        "errorMessage": row["error_message"],
        "result": result,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
    }


def enqueueCaseQuery(caseId: int, triggerType: str, userId: int | None = None) -> dict[str, Any] | None:
    now = utcNowIso()
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        case = connection.execute(f"SELECT id FROM ceac_cases WHERE id = ? {userFilter}", params).fetchone()
        if not case:
            return None
        existing = connection.execute(
            """
            SELECT * FROM query_jobs
            WHERE case_id = ?
              AND trigger_type NOT LIKE 'passport_slot_%'
              AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
        if existing:
            return normalizeQueryJob(existing)
        cursor = connection.execute(
            """
            INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?)
            """,
            (caseId, triggerType, now, now),
        )
        row = connection.execute("SELECT * FROM query_jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return normalizeQueryJob(row)


def enqueueDueCases(limit: int = 20) -> list[dict[str, Any]]:
    now = datetime.now(UTC).replace(microsecond=0)
    nowIso = now.isoformat()
    queued: list[dict[str, Any]] = []
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT c.*, s.status AS last_status
            FROM ceac_cases c
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            WHERE c.is_enabled = 1
              AND c.next_check_at IS NOT NULL
              AND c.next_check_at <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM query_jobs j
                  WHERE j.case_id = c.id
                    AND j.trigger_type NOT LIKE 'passport_slot_%'
                    AND j.status IN ('queued', 'running')
              )
            ORDER BY c.next_check_at ASC
            LIMIT ?
            """,
            (nowIso, limit),
        ).fetchall()
    for row in rows:
        if isIssuedStatus(row.get("last_status")) and handleIssuedDueCase(int(row["id"]), now):
            continue
        job = enqueueCaseQuery(int(row["id"]), "automatic")
        if job:
            queued.append(job)
    return queued


def handleIssuedDueCase(caseId: int, now: datetime) -> bool:
    issuedAt = getFirstIssuedAt(caseId)
    if not issuedAt:
        return False
    if now - issuedAt >= timedelta(days=7):
        return stopIssuedCaseIfExpired(caseId, now, issuedAt)
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE ceac_cases
            SET next_check_at = ?, updated_at = ?
            WHERE id = ? AND is_enabled = 1
            """,
            (computeNextCheckAt(now, "Issued"), now.isoformat(), caseId),
        )
    return True


def getFirstIssuedAt(caseId: int) -> datetime | None:
    with getConnection() as connection:
        firstIssued = connection.execute(
            """
            SELECT h.fetched_at
            FROM case_status_history h
            JOIN status_catalog s ON s.id = h.status_id
            WHERE h.case_id = ? AND lower(trim(s.status)) = 'issued'
            ORDER BY h.fetched_at ASC, h.id ASC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
    if not firstIssued:
        return None
    return parseIso(str(firstIssued["fetched_at"]))


def stopIssuedCaseIfExpired(caseId: int, now: datetime, issuedAt: datetime | None = None) -> bool:
    with getConnection() as connection:
        case = connection.execute(
            """
            SELECT c.*, s.status AS last_status
            FROM ceac_cases c
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            WHERE c.id = ? AND c.is_enabled = 1
            """,
            (caseId,),
        ).fetchone()
        if not case or not isIssuedStatus(case.get("last_status")):
            return False
        issuedAt = issuedAt or getFirstIssuedAt(caseId)
        if not issuedAt:
            return False
        if now - issuedAt < timedelta(days=7):
            return False
        connection.execute(
            """
            UPDATE ceac_cases
            SET is_enabled = 0, next_check_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now.isoformat(), caseId),
        )
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (case["user_id"],)).fetchone()

    try:
        sendIssuedAutoStopNotification(decryptCaseRow(case), smtpConfig, issuedAt.isoformat())
    except Exception as exc:
        print(f"[scheduler] issued auto-stop notification failed for case {caseId}: {exc}")
    return True


def getQueryJob(jobId: int, userId: int | None = None) -> dict[str, Any] | None:
    failTimedOutQueryJobs()
    params: tuple[Any, ...] = (jobId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (jobId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT j.*
            FROM query_jobs j
            JOIN ceac_cases c ON c.id = j.case_id
            WHERE j.id = ? {userFilter}
            """,
            params,
        ).fetchone()
    return normalizeQueryJob(row) if row else None


def failTimedOutQueryJobs(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    timeoutAt = (now - timedelta(seconds=getSettings().queryJobTimeoutSeconds)).replace(microsecond=0).isoformat()
    nowIso = now.replace(microsecond=0).isoformat()
    result = {"success": False, "changed": False, "error": QUERY_TIMEOUT_ERROR_MESSAGE, "timeout": True}
    with getConnection() as connection:
        cursor = connection.execute(
            """
            UPDATE query_jobs
            SET status = 'failed',
                error_message = ?,
                result_json = ?,
                finished_at = ?,
                updated_at = ?
            WHERE status = 'running'
              AND started_at IS NOT NULL
              AND started_at <= ?
            """,
            (
                QUERY_TIMEOUT_ERROR_MESSAGE,
                encryptSecret(json.dumps(result, ensure_ascii=False)),
                nowIso,
                nowIso,
                timeoutAt,
            ),
        )
    return int(cursor.rowcount)


def claimNextQueryJob(workerId: str | None = None) -> dict[str, Any] | None:
    failTimedOutQueryJobs()
    workerId = workerId or f"worker-{uuid.uuid4()}"
    nowIso = utcNowIso()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT j.*
            FROM query_jobs j
            JOIN ceac_cases c ON c.id = j.case_id
            JOIN users u ON u.id = c.user_id
            WHERE j.status = 'queued'
            ORDER BY u.worker_priority ASC, j.id ASC
            LIMIT 1
            """,
        ).fetchone()
        if not row:
            return None
        connection.execute(
            """
            UPDATE query_jobs
            SET status = 'running', attempts = attempts + 1, locked_at = ?, locked_by = ?,
                started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (nowIso, workerId, nowIso, nowIso, row["id"]),
        )
        claimed = connection.execute("SELECT * FROM query_jobs WHERE id = ?", (row["id"],)).fetchone()
    return normalizeQueryJob(claimed)


def runQueryJob(job: dict[str, Any]) -> dict[str, Any]:
    try:
        if isPassportSlotTrigger(str(job["triggerType"])):
            result = runPassportSlotQuery(int(job["caseId"]), triggerType=str(job["triggerType"]))
        else:
            result = runCaseQuery(int(job["caseId"]), triggerType=str(job["triggerType"]))
        status = "succeeded" if result.get("success") else "failed"
        errorMessage = str(result.get("error") or "")
    except Exception as exc:
        result = {"success": False, "changed": False, "error": str(exc)}
        status = "failed"
        errorMessage = str(exc)
    finishedIso = utcNowIso()
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE query_jobs
            SET status = ?, error_message = ?, result_json = ?, finished_at = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (
                status,
                errorMessage,
                encryptSecret(json.dumps(result, ensure_ascii=False)),
                finishedIso,
                finishedIso,
                job["id"],
            ),
        )
        row = connection.execute("SELECT * FROM query_jobs WHERE id = ?", (job["id"],)).fetchone()
    return normalizeQueryJob(row)
