import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

from .case_service import (
    PREMIUM_CASE_LIMIT,
    STANDARD_CASE_LIMIT,
    computeNextCheckAt,
    nextProfileSortOrder,
    upsertSmtpConfig,
)
from .database import getConnection, utcNowIso
from .mailer import sendCaseEmail
from .schemas import KoreaCaseInput, KoreaCasePatch
from .secrets import decryptIfNeeded, encryptSecret, isEncryptedSecret


KOREA_VISA_STATUS_URL = "https://www.visa.go.kr/openPage.do?MENU_ID=10301"
KOREA_QUERY_TRIGGER_PREFIX = "korea_"
KOREA_QUERY_TIMEOUT_ERROR_MESSAGE = "韩国签证查询运行超过系统设定时间仍未完成，已标记为失败；请稍后重试。"
KOREA_NO_DATA_STATUS = "暂无查询资料"
SENSITIVE_KOREA_COLUMNS = {"passport_number", "english_name", "birth_date", "receive_email"}
REQUEST_TIMEOUT = (10, 45)


def normalizeText(value: str) -> str:
    return " ".join(value.split())


def readDivText(soup: BeautifulSoup, elementId: str) -> str:
    node = soup.find(id=elementId)
    return normalizeText(node.get_text(" ", strip=True)) if node else ""


def hasNoDataResult(html: str, soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True)
    return (
        "没有您要查询的资料" in text
        or "조회된 데이터가 없습니다" in text
        or re.search(r'if\s*\(\s*["\']0["\']\s*==\s*0\s*\)', html) is not None
    )


def buildSnapshotHash(snapshot: dict[str, Any]) -> str:
    normalized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(normalized.encode()).hexdigest()


def parseKoreaVisaStatusHtml(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    applicationNo = readDivText(soup, "ONLINE_APPL_NO") or readDivText(soup, "INVITEE_SEQ")
    applicationDate = readDivText(soup, "APPL_DTM") or readDivText(soup, "APPL_YMD")
    entryPurpose = readDivText(soup, "ENTRY_PURPOSE")
    status = readDivText(soup, "PROC_STS_CDNM_1") or readDivText(soup, "PROC_STS_CDNM")

    if applicationNo or applicationDate or entryPurpose or status:
        return {
            "success": True,
            "application_no": applicationNo,
            "application_date": applicationDate,
            "entry_purpose": entryPurpose,
            "status": status or "未知状态",
            "description": "",
            "no_data": False,
        }
    if hasNoDataResult(html, soup):
        return {
            "success": True,
            "application_no": "",
            "application_date": "",
            "entry_purpose": "",
            "status": KOREA_NO_DATA_STATUS,
            "description": "韩国签证门户返回：没有您要查询的资料。",
            "no_data": True,
        }
    raise RuntimeError("韩国签证门户未返回可识别的查询结果，可能是页面结构变化或服务临时异常。")


def queryKoreaVisaStatus(passportNumber: str, englishName: str, birthDate: str) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ko;q=0.7",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.visa.go.kr",
        "Referer": KOREA_VISA_STATUS_URL,
    }
    data = {
        "CMM_TEST_VAL": "test",
        "sBUSI_GB": "PASS_NO",
        "sBUSI_GBNO": passportNumber,
        "ssBUSI_GBNO": passportNumber,
        "pRADIOSEARCH": "gb03",
        "sEK_NM": englishName,
        "sFROMDATE": birthDate,
        "sMainPopUpGB": "main",
        "TRAN_TYPE": "ComSubmit",
        "SE_FLAG_YN": "",
        "LANG_TYPE": "CH",
    }
    try:
        response = requests.post(KOREA_VISA_STATUS_URL, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"韩国签证门户请求失败：{exc}") from exc
    result = parseKoreaVisaStatusHtml(response.text)
    result.update(
        {
            "success": True,
            "time": str(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())),
            "query_type": "驻外使领馆",
            "identifier_type": "护照号码",
        },
    )
    return result


def decryptKoreaCaseRow(row: dict[str, Any]) -> dict[str, Any]:
    decrypted = dict(row)
    for column in SENSITIVE_KOREA_COLUMNS:
        decrypted[column] = decryptIfNeeded(decrypted.get(column)) or ""
    return decrypted


def normalizeKoreaCaseRow(row: dict[str, Any]) -> dict[str, Any]:
    row = decryptKoreaCaseRow(row)
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "displayName": row["display_name"],
        "passportNumber": row["passport_number"],
        "englishName": row["english_name"],
        "birthDate": row["birth_date"],
        "receiveEmail": row["receive_email"],
        "senderMode": row["sender_mode"],
        "isEnabled": bool(row["is_enabled"]),
        "emailNotificationsEnabled": bool(row["email_notifications_enabled"]),
        "sortOrder": int(row.get("sort_order") or 0),
        "nextCheckAt": row["next_check_at"],
        "lastCheckedAt": row["last_checked_at"],
        "lastTriggerType": row.get("last_trigger_type"),
        "lastSnapshotHash": row.get("last_snapshot_hash") or "",
        "lastApplicationNo": row.get("last_application_no") or "",
        "lastApplicationDate": row.get("last_application_date") or "",
        "lastEntryPurpose": row.get("last_entry_purpose") or "",
        "lastStatus": row.get("last_status") or "",
        "lastErrorMessage": row.get("last_error_message") or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def listKoreaCases(userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if userId is not None:
        where = "WHERE user_id = ?"
        params = (userId,)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM korea_cases
            {where}
            ORDER BY sort_order ASC, updated_at DESC, id DESC
            """,
            params,
        ).fetchall()
    return [normalizeKoreaCaseRow(row) for row in rows]


def getKoreaCase(caseId: int, userId: int | None = None) -> dict[str, Any] | None:
    params: tuple[Any, ...] = (caseId,)
    extraWhere = ""
    if userId is not None:
        extraWhere = "AND user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"SELECT * FROM korea_cases WHERE id = ? {extraWhere}",
            params,
        ).fetchone()
    return normalizeKoreaCaseRow(row) if row else None


def countAllUserProfiles(connection: Any, userId: int) -> int:
    total = 0
    for tableName in ("ceac_cases", "ircc_cases", "korea_cases"):
        row = connection.execute(f"SELECT COUNT(*) AS case_count FROM {tableName} WHERE user_id = ?", (userId,)).fetchone()
        total += int(row["case_count"] if row else 0)
    return total


def createKoreaCase(userId: int, payload: KoreaCaseInput) -> dict[str, Any]:
    now = utcNowIso()
    if payload.emailNotificationsEnabled and not payload.receiveEmail:
        raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
    with getConnection() as connection:
        user = connection.execute("SELECT role, account_tier FROM users WHERE id = ?", (userId,)).fetchone()
        if not user:
            raise ValueError("用户不存在")
        if user.get("role") != "admin":
            profileLimit = PREMIUM_CASE_LIMIT if user.get("account_tier") == "premium" else STANDARD_CASE_LIMIT
            if countAllUserProfiles(connection, userId) >= profileLimit:
                raise ValueError(f"当前账号最多可添加 {profileLimit} 个档案，请联系管理员升级账号。")
        upsertSmtpConfig(connection, userId, payload.smtpConfig)
        cursor = connection.execute(
            """
            INSERT INTO korea_cases (
                user_id, display_name, passport_number, english_name, birth_date,
                receive_email, sender_mode, is_enabled, email_notifications_enabled,
                sort_order, next_check_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                userId,
                payload.displayName,
                encryptSecret(payload.passportNumber),
                encryptSecret(payload.englishName),
                encryptSecret(payload.birthDate),
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
    case = getKoreaCase(int(cursor.lastrowid), userId)
    if case is None:
        raise RuntimeError("创建韩国签证档案失败")
    return case


def patchKoreaCase(caseId: int, userId: int, payload: KoreaCasePatch) -> dict[str, Any] | None:
    current = getKoreaCase(caseId, userId)
    if not current:
        return None
    data = payload.model_dump(exclude_unset=True)
    nextEmailNotificationsEnabled = data.get("emailNotificationsEnabled", current.get("emailNotificationsEnabled"))
    nextReceiveEmail = data.get("receiveEmail", current.get("receiveEmail"))
    if nextEmailNotificationsEnabled and not nextReceiveEmail:
        raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
    columnMap = {
        "displayName": "display_name",
        "passportNumber": "passport_number",
        "englishName": "english_name",
        "birthDate": "birth_date",
        "receiveEmail": "receive_email",
        "senderMode": "sender_mode",
        "isEnabled": "is_enabled",
        "emailNotificationsEnabled": "email_notifications_enabled",
    }
    encryptedKeys = {"passportNumber", "englishName", "birthDate", "receiveEmail"}
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
            if key == "emailNotificationsEnabled":
                value = int(value)
            assignments.append(f"{column} = ?")
            values.append(value)
        if not assignments:
            return getKoreaCase(caseId, userId)
        assignments.append("updated_at = ?")
        values.extend([now, caseId, userId])
        connection.execute(f"UPDATE korea_cases SET {', '.join(assignments)} WHERE id = ? AND user_id = ?", tuple(values))
    return getKoreaCase(caseId, userId)


def deleteKoreaCase(caseId: int, userId: int) -> bool:
    with getConnection() as connection:
        cursor = connection.execute("DELETE FROM korea_cases WHERE id = ? AND user_id = ?", (caseId, userId))
        return cursor.rowcount > 0


def sendKoreaNotification(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    result: dict[str, Any],
    connection: Any | None = None,
    *,
    isTest: bool = False,
) -> None:
    subject = f"[Korea Visa] {case['passport_number']} 状态更新：{result['status']}"
    if isTest:
        subject = f"[Korea Visa] {case['passport_number']} 测试邮件：当前状态 {result['status']}"
    lines = [
        f"档案：{case['display_name']}",
        f"护照号码：{case['passport_number']}",
        f"英文姓名：{case['english_name']}",
        f"状态：{result.get('status', '')}",
        f"申请编号：{result.get('application_no', '') or '-'}",
        f"申请日期：{result.get('application_date', '') or '-'}",
        f"入境目的：{result.get('entry_purpose', '') or '-'}",
        "",
        str(result.get("description", "")),
    ]
    caseForEmail = {**case, "id": None}
    sendCaseEmail(caseForEmail, smtpConfig, subject, "\n".join(lines), emailType="korea_status", connection=connection)


def runKoreaCaseQuery(caseId: int, triggerType: str = "korea_automatic") -> dict[str, Any]:
    started = datetime.now(UTC)
    startedIso = started.replace(microsecond=0).isoformat()
    success = False
    changed = False
    notificationSent = False
    errorMessage = ""
    result: dict[str, Any] = {"success": False}
    with getConnection() as connection:
        row = connection.execute("SELECT * FROM korea_cases WHERE id = ?", (caseId,)).fetchone()
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone() if row else None
        previous = connection.execute(
            """
            SELECT snapshot_hash
            FROM korea_status_history
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
    if not row:
        raise RuntimeError("韩国签证档案不存在")
    case = decryptKoreaCaseRow(row)
    try:
        result = queryKoreaVisaStatus(case["passport_number"], case["english_name"], case["birth_date"])
        snapshotHash = buildSnapshotHash(
            {
                "application_no": result.get("application_no", ""),
                "application_date": result.get("application_date", ""),
                "entry_purpose": result.get("entry_purpose", ""),
                "status": result.get("status", ""),
                "no_data": bool(result.get("no_data")),
            },
        )
        changed = previous is None or previous["snapshot_hash"] != snapshotHash
        success = True
    except Exception as exc:
        errorMessage = str(exc)

    finished = datetime.now(UTC)
    finishedIso = finished.replace(microsecond=0).isoformat()
    durationMs = int((finished - started).total_seconds() * 1000)
    with getConnection() as connection:
        if success:
            if changed:
                shouldNotify = previous is not None and bool(row["email_notifications_enabled"])
                if shouldNotify:
                    try:
                        sendKoreaNotification(case, smtpConfig, result, connection)
                        notificationSent = True
                    except Exception as exc:
                        errorMessage = f"Notification failed: {exc}"
                connection.execute(
                    """
                    INSERT INTO korea_status_history (
                        case_id, snapshot_hash, application_no, application_date,
                        entry_purpose, status, fetched_at, raw_payload, notification_sent
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        caseId,
                        snapshotHash,
                        str(result.get("application_no", "")),
                        str(result.get("application_date", "")),
                        str(result.get("entry_purpose", "")),
                        str(result.get("status", "")),
                        finishedIso,
                        encryptSecret(json.dumps(result, ensure_ascii=False, default=str)),
                        int(notificationSent),
                    ),
                )
            connection.execute(
                """
                UPDATE korea_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_trigger_type = ?,
                    last_snapshot_hash = ?,
                    last_application_no = ?,
                    last_application_date = ?,
                    last_entry_purpose = ?,
                    last_status = ?,
                    last_error_message = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    finishedIso,
                    computeNextCheckAt(finished) if bool(row["is_enabled"]) else None,
                    triggerType,
                    snapshotHash,
                    str(result.get("application_no", "")),
                    str(result.get("application_date", "")),
                    str(result.get("entry_purpose", "")),
                    str(result.get("status", "")),
                    finishedIso,
                    caseId,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE korea_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_trigger_type = ?,
                    last_error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (finishedIso, computeNextCheckAt(finished), triggerType, errorMessage, finishedIso, caseId),
            )
        connection.execute(
            """
            INSERT INTO korea_query_runs (case_id, started_at, finished_at, success, error_message, duration_ms, trigger_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (caseId, startedIso, finishedIso, int(success), errorMessage, durationMs, triggerType),
        )
    return {"success": success, "changed": success and changed, "notified": notificationSent, "error": errorMessage, "result": result}


def listKoreaHistory(caseId: int, userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT h.*
            FROM korea_status_history h
            JOIN korea_cases c ON c.id = h.case_id
            WHERE h.case_id = ? {userFilter}
            ORDER BY h.id DESC
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "caseId": row["case_id"],
            "snapshotHash": row["snapshot_hash"],
            "applicationNo": row["application_no"],
            "applicationDate": row["application_date"],
            "entryPurpose": row["entry_purpose"],
            "status": row["status"],
            "fetchedAt": row["fetched_at"],
            "rawPayload": json.loads(decryptIfNeeded(row["raw_payload"]) or "{}"),
            "notificationSent": bool(row["notification_sent"]),
        }
        for row in rows
    ]


def normalizeKoreaQueryJob(row: dict[str, Any]) -> dict[str, Any]:
    resultJson = decryptIfNeeded(row.get("result_json") or "") or ""
    return {
        "id": row["id"],
        "caseId": row["case_id"],
        "triggerType": row["trigger_type"],
        "status": row["status"],
        "attempts": row["attempts"],
        "errorMessage": row["error_message"],
        "result": json.loads(resultJson) if resultJson else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
    }


def enqueueKoreaCaseQuery(caseId: int, triggerType: str, userId: int | None = None) -> dict[str, Any] | None:
    now = utcNowIso()
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        case = connection.execute(f"SELECT id FROM korea_cases WHERE id = ? {userFilter}", params).fetchone()
        if not case:
            return None
        existing = connection.execute(
            """
            SELECT *
            FROM korea_query_jobs
            WHERE case_id = ? AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
        if existing:
            return normalizeKoreaQueryJob(existing)
        cursor = connection.execute(
            """
            INSERT INTO korea_query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?)
            """,
            (caseId, triggerType, now, now),
        )
        row = connection.execute("SELECT * FROM korea_query_jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return normalizeKoreaQueryJob(row)


def enqueueDueKoreaCases(limit: int = 20) -> list[dict[str, Any]]:
    nowIso = datetime.now(UTC).replace(microsecond=0).isoformat()
    queued: list[dict[str, Any]] = []
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM korea_cases c
            WHERE c.is_enabled = 1
              AND c.next_check_at IS NOT NULL
              AND c.next_check_at <= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM korea_query_jobs j
                  WHERE j.case_id = c.id AND j.status IN ('queued', 'running')
              )
            ORDER BY c.next_check_at ASC
            LIMIT ?
            """,
            (nowIso, limit),
        ).fetchall()
    for row in rows:
        job = enqueueKoreaCaseQuery(int(row["id"]), "korea_automatic")
        if job:
            queued.append(job)
    return queued


def claimNextKoreaQueryJob(workerId: str | None = None) -> dict[str, Any] | None:
    workerId = workerId or f"korea-worker-{uuid.uuid4()}"
    nowIso = utcNowIso()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT j.*
            FROM korea_query_jobs j
            JOIN korea_cases c ON c.id = j.case_id
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
            UPDATE korea_query_jobs
            SET status = 'running', attempts = attempts + 1, locked_at = ?, locked_by = ?,
                started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (nowIso, workerId, nowIso, nowIso, row["id"]),
        )
        claimed = connection.execute("SELECT * FROM korea_query_jobs WHERE id = ?", (row["id"],)).fetchone()
    return normalizeKoreaQueryJob(claimed)


def failTimedOutKoreaQueryJobs(now: datetime | None = None, timeoutSeconds: int = 360) -> int:
    now = now or datetime.now(UTC)
    timeoutAt = (now - timedelta(seconds=timeoutSeconds)).replace(microsecond=0).isoformat()
    nowIso = now.replace(microsecond=0).isoformat()
    result = {"success": False, "changed": False, "error": KOREA_QUERY_TIMEOUT_ERROR_MESSAGE, "timeout": True}
    with getConnection() as connection:
        cursor = connection.execute(
            """
            UPDATE korea_query_jobs
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
                KOREA_QUERY_TIMEOUT_ERROR_MESSAGE,
                encryptSecret(json.dumps(result, ensure_ascii=False)),
                nowIso,
                nowIso,
                timeoutAt,
            ),
        )
    return int(cursor.rowcount)


def runKoreaQueryJob(job: dict[str, Any]) -> dict[str, Any]:
    try:
        result = runKoreaCaseQuery(int(job["caseId"]), triggerType=str(job["triggerType"]))
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
            UPDATE korea_query_jobs
            SET status = ?, error_message = ?, result_json = ?, finished_at = ?, updated_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (
                status,
                errorMessage,
                encryptSecret(json.dumps(result, ensure_ascii=False, default=str)),
                finishedIso,
                finishedIso,
                job["id"],
            ),
        )
        row = connection.execute("SELECT * FROM korea_query_jobs WHERE id = ?", (job["id"],)).fetchone()
    return normalizeKoreaQueryJob(row)


def getKoreaQueryJob(jobId: int, userId: int | None = None) -> dict[str, Any] | None:
    params: tuple[Any, ...] = (jobId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (jobId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT j.*
            FROM korea_query_jobs j
            JOIN korea_cases c ON c.id = j.case_id
            WHERE j.id = ? {userFilter}
            """,
            params,
        ).fetchone()
    return normalizeKoreaQueryJob(row) if row else None


def sendCurrentKoreaEmail(caseId: int, userId: int | None = None) -> dict[str, Any]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(f"SELECT * FROM korea_cases WHERE id = ? {userFilter}", params).fetchone()
        if not row:
            return {"success": False, "error": "韩国签证档案不存在"}
        case = decryptKoreaCaseRow(row)
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone()
        latest = connection.execute(
            """
            SELECT *
            FROM korea_status_history
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
    if not latest:
        return {"success": False, "error": "暂无韩国签证状态快照，请先立即查询一次"}
    result = {
        "success": True,
        "application_no": latest["application_no"],
        "application_date": latest["application_date"],
        "entry_purpose": latest["entry_purpose"],
        "status": latest["status"],
        "description": "",
    }
    try:
        sendKoreaNotification(case, smtpConfig, result, isTest=True)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "error": ""}


def migrateKoreaEncryptedFields() -> None:
    with getConnection() as connection:
        for row in connection.execute("SELECT * FROM korea_cases").fetchall():
            assignments: list[str] = []
            values: list[Any] = []
            for column in SENSITIVE_KOREA_COLUMNS:
                value = row[column]
                if value and not isEncryptedSecret(value):
                    assignments.append(f"{column} = ?")
                    values.append(encryptSecret(str(value)))
            if assignments:
                values.append(row["id"])
                connection.execute(f"UPDATE korea_cases SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        for row in connection.execute("SELECT id, raw_payload FROM korea_status_history").fetchall():
            value = row["raw_payload"]
            if value and not isEncryptedSecret(value):
                connection.execute(
                    "UPDATE korea_status_history SET raw_payload = ? WHERE id = ?",
                    (encryptSecret(str(value)), row["id"]),
                )
