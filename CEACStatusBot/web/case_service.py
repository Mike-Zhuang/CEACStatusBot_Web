import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from CEACStatusBot.request import query_status
from CEACStatusBot.request.query import CEAC_PROVIDER_BLOCKED_ERROR_CODE

from .account_controls import (
    RISK_GROUP_STATE_REVIEW,
    createRiskGroup,
    enforceProfileActivationLimit,
    enforceProfileCreationLimit,
    isUserAccountActive,
    placeUserAccountUnderReview,
)
from .config import getSettings
from .database import getConnection, utcNowIso
from .mailer import (
    sendCaseNotification,
    sendCeacConsecutiveFailureNotification,
    sendCeacProviderIncidentNotification,
    sendIssuedAutoStopNotification,
)
from .passport_slot_service import (
    isPassportSlotTrigger,
    runPassportSlotQuery,
)
from .schemas import CeacCaseInput, CeacCasePatch, ProfileOrderItem
from .secrets import (
    decryptIfNeeded,
    encryptSecret,
    hashSensitiveLookup,
    isEncryptedSecret,
    isSensitiveLookupHash,
)


SENSITIVE_CASE_COLUMNS = {"application_num", "passport_number", "surname", "receive_email"}
STANDARD_CASE_LIMIT = 1
PREMIUM_CASE_LIMIT = 5
STANDARD_WORKER_PRIORITY = 100
PREMIUM_WORKER_PRIORITY = 50
CEAC_FAILURE_NOTICE_THRESHOLD = 5
CEAC_FAILURE_STOP_THRESHOLD = 10
CEAC_FAILURE_SLOW_STOP_DAYS = 7
CEAC_PROVIDER_PROBE_MINUTES = 120
CEAC_PROVIDER_PROBE_MAX_MINUTES = 240
RESTRICTED_APPLICATION_REUSE_REASON = "reused_restricted_ceac_application"
QUERY_TIMEOUT_ERROR_MESSAGE = (
    "查询运行超过系统设定时间仍未完成，已标记为失败。可能是信息填写有误、CEAC/GTS 服务暂时异常或服务器繁忙；"
    "请核对信息输入是否正确后重试，仍有问题请联系管理员。"
)


class RestrictedApplicationReuseError(ValueError):
    def __init__(self, restrictedAt: str) -> None:
        super().__init__("该签证申请与已受限账号重复，当前账号已进入人工审核。")
        self.restrictedAt = restrictedAt
        self.reasonCode = RESTRICTED_APPLICATION_REUSE_REASON


class CeacProviderUnavailableError(ValueError):
    pass


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


def computeCeacProviderProbeAt(base: datetime | None = None) -> str:
    base = base or datetime.now(UTC)
    return (base + timedelta(minutes=random.randint(CEAC_PROVIDER_PROBE_MINUTES, CEAC_PROVIDER_PROBE_MAX_MINUTES))).replace(
        microsecond=0,
    ).isoformat()


def getCeacProviderIncident(connection: Any) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM ceac_provider_incident WHERE id = 1").fetchone()
    return dict(row) if row else None


def isCeacProviderIncidentActive(connection: Any) -> bool:
    incident = getCeacProviderIncident(connection)
    return bool(incident and incident["is_active"])


def ensureCeacProviderManualQueryAvailable() -> None:
    with getConnection() as connection:
        if isCeacProviderIncidentActive(connection):
            raise CeacProviderUnavailableError(
                "CEAC 自动查询通道当前被官网安全防护拦截，请暂时前往 CEAC 官网手动查询。",
            )


def markCeacProviderBlocked(connection: Any, detectedAt: datetime) -> dict[str, Any]:
    detectedIso = detectedAt.replace(microsecond=0).isoformat()
    nextProbeAt = computeCeacProviderProbeAt(detectedAt)
    current = getCeacProviderIncident(connection)
    isNewIncident = not current or not bool(current["is_active"])
    if isNewIncident:
        connection.execute(
            """
            INSERT INTO ceac_provider_incident (
                id, is_active, started_at, last_seen_at, next_probe_at,
                alert_sent_at, recovered_at, recovery_alert_sent_at, updated_at
            )
            VALUES (1, 1, ?, ?, ?, NULL, NULL, NULL, ?)
            ON CONFLICT(id) DO UPDATE SET
                is_active = 1,
                started_at = excluded.started_at,
                last_seen_at = excluded.last_seen_at,
                next_probe_at = excluded.next_probe_at,
                alert_sent_at = NULL,
                recovered_at = NULL,
                recovery_alert_sent_at = NULL,
                updated_at = excluded.updated_at
            """,
            (detectedIso, detectedIso, nextProbeAt, detectedIso),
        )
        notifyAdministrator = True
    else:
        connection.execute(
            """
            UPDATE ceac_provider_incident
            SET last_seen_at = ?, next_probe_at = ?, updated_at = ?
            WHERE id = 1
            """,
            (detectedIso, nextProbeAt, detectedIso),
        )
        notifyAdministrator = not bool(current.get("alert_sent_at"))
    stoppedMessage = "CEAC 查询通道当前被官网安全防护拦截，排队任务已暂停。"
    connection.execute(
        """
        UPDATE query_jobs
        SET status = 'failed',
            error_message = ?,
            result_json = ?,
            finished_at = ?,
            updated_at = ?
        WHERE status = 'queued'
          AND trigger_type NOT LIKE 'passport_slot_%'
        """,
        (
            stoppedMessage,
            encryptSecret(json.dumps({"success": False, "changed": False, "error": stoppedMessage}, ensure_ascii=False)),
            detectedIso,
            detectedIso,
        ),
    )
    return {
        "isNewIncident": isNewIncident,
        "notifyAdministrator": notifyAdministrator,
        "detectedAt": detectedIso,
        "nextProbeAt": nextProbeAt,
    }


def resolveCeacProviderIncident(connection: Any, recoveredAt: datetime) -> dict[str, Any] | None:
    current = getCeacProviderIncident(connection)
    if not current or not bool(current["is_active"]):
        return None
    recoveredIso = recoveredAt.replace(microsecond=0).isoformat()
    connection.execute(
        """
        UPDATE ceac_provider_incident
        SET is_active = 0, next_probe_at = NULL, recovered_at = ?, updated_at = ?
        WHERE id = 1
        """,
        (recoveredIso, recoveredIso),
    )
    return {
        "notifyAdministrator": bool(current.get("alert_sent_at")) and not bool(current.get("recovery_alert_sent_at")),
        "recoveredAt": recoveredIso,
    }


def markCeacProviderIncidentNoticeSent(*, recovered: bool, sentAt: str) -> None:
    column = "recovery_alert_sent_at" if recovered else "alert_sent_at"
    with getConnection() as connection:
        connection.execute(
            f"UPDATE ceac_provider_incident SET {column} = ?, updated_at = ? WHERE id = 1",
            (sentAt, sentAt),
        )


def notifyCeacProviderIncident(*, recovered: bool, occurredAt: str, nextProbeAt: str | None = None) -> None:
    try:
        notification = sendCeacProviderIncidentNotification(
            recovered=recovered,
            occurredAt=occurredAt,
            nextProbeAt=nextProbeAt,
        )
        if notification["delivered"]:
            markCeacProviderIncidentNoticeSent(recovered=recovered, sentAt=utcNowIso())
    except Exception as exc:
        print(f"[ceac] Provider incident notification failed: {type(exc).__name__}")


def countRecentCeacFailureRuns(connection: Any, caseId: int) -> int:
    rows = connection.execute(
        """
        SELECT success, error_code
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
        if row.get("error_code") == CEAC_PROVIDER_BLOCKED_ERROR_CODE:
            continue
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
            encryptSecret(str(smtpConfig.fromEmail)),
            smtpConfig.host,
            smtpConfig.port,
            int(smtpConfig.useSsl),
            encryptSecret(smtpConfig.password),
            now,
            now,
        ),
    )


def restrictedApplicationOwnerIds(connection: Any, userId: int, applicationNum: str) -> tuple[int, ...]:
    applicationHash = hashSensitiveLookup(applicationNum)
    rows = connection.execute(
        """
        SELECT DISTINCT c.user_id, c.application_num, c.application_num_hash
        FROM ceac_cases c
        JOIN users u ON u.id = c.user_id
        WHERE c.user_id != ?
          AND u.role != 'admin'
          AND (
              COALESCE(u.account_status, 'active') = 'suspended'
              OR EXISTS (
                  SELECT 1
                  FROM account_risk_group_members m
                  JOIN account_risk_groups g ON g.id = m.group_id
                  WHERE m.user_id = c.user_id
                    AND g.enforcement_state = 'enforced'
              )
          )
          AND (c.application_num_hash = ? OR c.application_num_hash = '')
        """,
        (userId, applicationHash),
    ).fetchall()
    ownerIds = set()
    for row in rows:
        storedHash = str(row["application_num_hash"] or "")
        if storedHash == applicationHash:
            ownerIds.add(int(row["user_id"]))
            continue
        storedApplication = decryptIfNeeded(row["application_num"]) or ""
        if storedApplication and hashSensitiveLookup(storedApplication) == applicationHash:
            ownerIds.add(int(row["user_id"]))
    return tuple(sorted(ownerIds))


def hasApprovedRestrictedApplicationAppeal(connection: Any, userId: int, applicationHash: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM account_risk_groups g
        JOIN account_risk_group_members m
          ON m.group_id = g.id
         AND m.user_id = ?
         AND m.evidence_reference_hash = ?
        JOIN account_appeals a
          ON a.user_id = m.user_id
         AND a.status = 'approved'
         AND a.reviewed_at IS NOT NULL
         AND a.reviewed_at >= g.created_at
        WHERE g.reason_code = ?
        LIMIT 1
        """,
        (userId, applicationHash, RESTRICTED_APPLICATION_REUSE_REASON),
    ).fetchone()
    return row is not None


def reviewRestrictedApplicationReuse(connection: Any, userId: int, applicationNum: str) -> str | None:
    user = connection.execute("SELECT role, account_status FROM users WHERE id = ?", (userId,)).fetchone()
    if not user or user["role"] == "admin":
        return None
    applicationHash = hashSensitiveLookup(applicationNum)
    if hasApprovedRestrictedApplicationAppeal(connection, userId, applicationHash):
        return None
    ownerIds = restrictedApplicationOwnerIds(connection, userId, applicationNum)
    if not ownerIds:
        return None

    now = utcNowIso()
    placeUserAccountUnderReview(
        connection,
        userId=userId,
        reasonCode=RESTRICTED_APPLICATION_REUSE_REASON,
        adminNote="自动规则：提交的 CEAC 申请号曾属于已限制账号，等待人工审核。",
    )
    createRiskGroup(
        connection,
        userIds=(*ownerIds, userId),
        label="受限 CEAC 申请复用审核组",
        reasonCode=RESTRICTED_APPLICATION_REUSE_REASON,
        adminNote="新账号复用了已限制账号的 CEAC 申请号；仅限制新账号，既有成员状态不变。",
        createdByUserId=None,
        enforcementState=RISK_GROUP_STATE_REVIEW,
        suspendMembers=False,
        evidenceType="reused_ceac_application",
        evidenceReferenceHash=applicationHash,
    )
    return now


def createCase(userId: int, payload: CeacCaseInput) -> dict[str, Any]:
    now = utcNowIso()
    caseId: int | None = None
    restrictedAt: str | None = None
    with getConnection() as connection:
        user = connection.execute("SELECT id, role FROM users WHERE id = ?", (userId,)).fetchone()
        if not user:
            raise ValueError("用户不存在")
        if payload.emailNotificationsEnabled and not payload.receiveEmail:
            raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
        restrictedAt = reviewRestrictedApplicationReuse(connection, userId, payload.applicationNum)
        if restrictedAt is None:
            enforceProfileCreationLimit(connection, userId)
            upsertSmtpConfig(connection, userId, payload.smtpConfig)
            cursor = connection.execute(
                """
                INSERT INTO ceac_cases (
                    user_id, display_name, location,
                    application_num, application_num_hash,
                    passport_number, passport_number_hash,
                    surname, surname_hash,
                    receive_email, sender_mode, is_enabled, email_notifications_enabled,
                    sort_order, next_check_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    userId,
                    payload.displayName,
                    payload.location,
                    encryptSecret(payload.applicationNum),
                    hashSensitiveLookup(payload.applicationNum),
                    encryptSecret(payload.passportNumber),
                    hashSensitiveLookup(payload.passportNumber),
                    encryptSecret(payload.surname),
                    hashSensitiveLookup(payload.surname),
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
            caseId = int(cursor.lastrowid)
            connection.execute("UPDATE users SET has_application_profile_history = 1, updated_at = ? WHERE id = ?", (now, userId))
    if restrictedAt is not None:
        raise RestrictedApplicationReuseError(restrictedAt)
    if caseId is None:
        raise RuntimeError("创建档案失败")
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
    restrictedAt: str | None = None
    with getConnection() as connection:
        if "applicationNum" in data:
            restrictedAt = reviewRestrictedApplicationReuse(connection, userId, str(data["applicationNum"]))
        if restrictedAt is None:
            if data.get("isEnabled") is True and not current.get("isEnabled"):
                enforceProfileActivationLimit(connection, userId, tableName="ceac_cases", profileId=caseId)
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
                if key == "applicationNum" and data[key] is not None:
                    assignments.append("application_num_hash = ?")
                    values.append(hashSensitiveLookup(str(data[key])))
                if key == "passportNumber" and data[key] is not None:
                    assignments.append("passport_number_hash = ?")
                    values.append(hashSensitiveLookup(str(data[key])))
                if key == "surname" and data[key] is not None:
                    assignments.append("surname_hash = ?")
                    values.append(hashSensitiveLookup(str(data[key])))
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
    if restrictedAt is not None:
        raise RestrictedApplicationReuseError(restrictedAt)
    return getCase(caseId, userId)


def restoreCaseAutomaticQuery(caseId: int) -> dict[str, Any] | None:
    now = utcNowIso()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT c.user_id, s.status AS last_status, u.account_status, u.role
            FROM ceac_cases c
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            JOIN users u ON u.id = c.user_id
            WHERE c.id = ?
            """,
            (caseId,),
        ).fetchone()
        if not row:
            return None
        if row["role"] != "admin" and str(row.get("account_status") or "active") != "active":
            return getCase(caseId, int(row["user_id"]))
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
    failureCode = ""
    result: dict[str, Any] = {"success": False}
    incidentNotice: dict[str, Any] | None = None
    recoveryNotice: dict[str, Any] | None = None
    with getConnection() as connection:
        case = connection.execute(
            """
            SELECT c.*, u.account_status, u.role
            FROM ceac_cases c
            JOIN users u ON u.id = c.user_id
            WHERE c.id = ?
            """,
            (caseId,),
        ).fetchone()
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (case["user_id"],)).fetchone() if case else None
    if not case:
        raise RuntimeError("签证档案不存在")
    if case["role"] != "admin" and str(case.get("account_status") or "active") != "active":
        return {"success": False, "changed": False, "error": "账号当前不可用，查询已停止。"}
    case = decryptCaseRow(case)

    try:
        result = query_status(case["location"], case["application_num"], case["passport_number"], case["surname"])
        failureCode = str(result.get("error_code") or "")
        if not result.get("success"):
            raise RuntimeError(str(result.get("error") or "CEAC 查询失败"))
        success = True
    except Exception as exc:
        errorMessage = str(exc)

    finished = datetime.now(UTC)
    durationMs = int((finished - started).total_seconds() * 1000)
    finishedIso = finished.replace(microsecond=0).isoformat()
    providerAvailable = success or bool(result.get("provider_available"))

    with getConnection() as connection:
        # 外部 CEAC 请求可能跨越管理员限制操作；落库前必须再次确认，不能让在途任务恢复监控。
        if not isUserAccountActive(int(case["user_id"]), connection):
            return {"success": False, "changed": False, "error": "账号当前不可用，查询结果已丢弃。"}
        hasChanged = False
        if providerAvailable:
            recoveryNotice = resolveCeacProviderIncident(connection, finished)
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
        elif failureCode == CEAC_PROVIDER_BLOCKED_ERROR_CODE:
            incidentNotice = markCeacProviderBlocked(connection, finished)
            connection.execute(
                """
                UPDATE ceac_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_trigger_type = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    finishedIso,
                    incidentNotice["nextProbeAt"],
                    triggerType,
                    finishedIso,
                    caseId,
                ),
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
            INSERT INTO query_runs (
                case_id, started_at, finished_at, success, status_id,
                error_message, error_code, duration_ms, trigger_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (caseId, startedIso, finishedIso, int(success), statusId, errorMessage, failureCode, durationMs, triggerType),
        )
    if incidentNotice and incidentNotice["notifyAdministrator"]:
        notifyCeacProviderIncident(
            recovered=False,
            occurredAt=incidentNotice["detectedAt"],
            nextProbeAt=incidentNotice["nextProbeAt"],
        )
    if recoveryNotice and recoveryNotice["notifyAdministrator"]:
        notifyCeacProviderIncident(
            recovered=True,
            occurredAt=recoveryNotice["recoveredAt"],
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
            for sourceColumn, hashColumn in (
                ("application_num", "application_num_hash"),
                ("passport_number", "passport_number_hash"),
                ("surname", "surname_hash"),
            ):
                value = decryptIfNeeded(row[sourceColumn]) or ""
                expectedHash = hashSensitiveLookup(value) if value else ""
                if str(row.get(hashColumn) or "") != expectedHash:
                    assignments.append(f"{hashColumn} = ?")
                    values.append(expectedHash)
            if assignments:
                values.append(row["id"])
                connection.execute(f"UPDATE ceac_cases SET {', '.join(assignments)} WHERE id = ?", tuple(values))

        for tableName in ("smtp_configs", "system_smtp_config"):
            for row in connection.execute(f"SELECT id, from_email, password_encrypted FROM {tableName}").fetchall():
                fromEmail = row["from_email"]
                if fromEmail and not isEncryptedSecret(fromEmail):
                    connection.execute(
                        f"UPDATE {tableName} SET from_email = ? WHERE id = ?",
                        (encryptSecret(str(fromEmail)), row["id"]),
                    )
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

        for row in connection.execute("SELECT id, recipient, subject, body_encrypted FROM email_delivery_logs").fetchall():
            assignments = []
            values = []
            for column in ("recipient", "subject", "body_encrypted"):
                value = row[column]
                if value and not isEncryptedSecret(value):
                    assignments.append(f"{column} = ?")
                    values.append(encryptSecret(str(value)))
            if assignments:
                values.append(row["id"])
                connection.execute(
                    f"UPDATE email_delivery_logs SET {', '.join(assignments)} WHERE id = ?",
                    tuple(values),
                )

        for row in connection.execute("SELECT id, email FROM email_verification_codes").fetchall():
            value = row["email"]
            if value and not isSensitiveLookupHash(value):
                connection.execute(
                    "UPDATE email_verification_codes SET email = ? WHERE id = ?",
                    (hashSensitiveLookup(str(value)), row["id"]),
                )

        for row in connection.execute("SELECT * FROM ircc_cases").fetchall():
            assignments = []
            values = []
            for column in ("app_id", "application_number", "principal_applicant", "receive_email", "last_summary"):
                value = row[column]
                if value and not isEncryptedSecret(value):
                    assignments.append(f"{column} = ?")
                    values.append(encryptSecret(str(value)))
            if assignments:
                values.append(row["id"])
                connection.execute(
                    f"UPDATE ircc_cases SET {', '.join(assignments)} WHERE id = ?",
                    tuple(values),
                )

        for row in connection.execute("SELECT id, change_summary FROM ircc_status_history").fetchall():
            value = row["change_summary"]
            if value and not isEncryptedSecret(value):
                connection.execute(
                    "UPDATE ircc_status_history SET change_summary = ? WHERE id = ?",
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


def enqueueCaseQuery(
    caseId: int,
    triggerType: str,
    userId: int | None = None,
    *,
    allowProviderProbe: bool = False,
) -> dict[str, Any] | None:
    now = utcNowIso()
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        case = connection.execute(
            f"""
            SELECT c.id
            FROM ceac_cases c
            JOIN users u ON u.id = c.user_id
            WHERE c.id = ? {userFilter}
              AND (u.role = 'admin' OR COALESCE(u.account_status, 'active') = 'active')
            """,
            params,
        ).fetchone()
        if not case:
            return None
        if isCeacProviderIncidentActive(connection) and not allowProviderProbe:
            if triggerType == "manual":
                raise CeacProviderUnavailableError(
                    "CEAC 自动查询通道当前被官网安全防护拦截，请暂时前往 CEAC 官网手动查询。",
                )
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
    providerProbe = False
    with getConnection() as connection:
        incident = getCeacProviderIncident(connection)
        if incident and bool(incident["is_active"]):
            nextProbeAt = str(incident.get("next_probe_at") or "")
            if nextProbeAt and parseIso(nextProbeAt) > now:
                return []
            providerProbe = True
            limit = 1
        rows = connection.execute(
            """
            SELECT c.*, s.status AS last_status
            FROM ceac_cases c
            JOIN users u ON u.id = c.user_id
            LEFT JOIN status_catalog s ON s.id = c.last_status_id
            WHERE c.is_enabled = 1
              AND (u.role = 'admin' OR COALESCE(u.account_status, 'active') = 'active')
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
        job = enqueueCaseQuery(
            int(row["id"]),
            "automatic",
            allowProviderProbe=providerProbe,
        )
        if job:
            queued.append(job)
            if providerProbe:
                probeLeaseAt = computeCeacProviderProbeAt(now)
                with getConnection() as connection:
                    connection.execute(
                        """
                        UPDATE ceac_provider_incident
                        SET next_probe_at = ?, updated_at = ?
                        WHERE id = 1 AND is_active = 1
                        """,
                        (probeLeaseAt, nowIso),
                    )
                break
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
              AND (u.role = 'admin' OR COALESCE(u.account_status, 'active') = 'active')
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
