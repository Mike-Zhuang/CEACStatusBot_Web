import hashlib
import json
import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .database import getConnection, utcNowIso
from .mailer import (
    sendPassportSlotLongNoSlotNoticeEmail,
    sendPassportSlotLongNoSlotStoppedEmail,
    sendPassportSlotNotification,
    sendPassportSlotStatusEmail,
)
from .secrets import decryptIfNeeded, encryptSecret


GTS_API_BASE_URL = "https://scheduling-api.gtspremium.com"
GTS_SITE_URL = "https://schedule.gtspremium.com/"
PASSPORT_SLOT_TRIGGER_PREFIX = "passport_slot_"
PASSPORT_SLOT_STATUS_NOT_ELIGIBLE = "not_eligible"
PASSPORT_SLOT_STATUS_NO_SLOT = "no_slot"
PASSPORT_SLOT_STATUS_HAS_SLOT = "has_slot"
PASSPORT_SLOT_STATUS_UNKNOWN = "unknown"
PASSPORT_SLOT_STATE_PREFIX = "state:"
PASSPORT_SLOT_EMPTY_FINGERPRINT = f"{PASSPORT_SLOT_STATE_PREFIX}{PASSPORT_SLOT_STATUS_NO_SLOT}"
CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
LONG_NO_SLOT_NOTICE_DAYS = 15
LONG_NO_SLOT_GRACE_DAYS = 7


def normalizeIdentifier(identifier: str) -> str:
    value = re.sub(r"\s+", "", identifier or "").upper()
    if not value:
        raise ValueError("UID/HAL 不能为空")
    if value.startswith("HAL"):
        if not re.fullmatch(r"HAL\d{10}", value):
            raise ValueError("HAL 必须以 HAL 开头并包含 10 位数字")
        return value
    digits = re.sub(r"\D", "", value)
    if not re.fullmatch(r"\d{8,9}", digits):
        raise ValueError("UID 必须是 8 或 9 位数字")
    return digits


def maskIdentifier(identifier: str) -> str:
    value = normalizeIdentifier(identifier)
    if value.startswith("HAL"):
        return f"HAL******{value[-4:]}"
    return f"{value[:2]}***{value[-3:]}"


def computeNextPassportSlotCheckAt(
    base: datetime | None = None,
    *,
    isRateLimited: bool = False,
    hadError: bool = False,
    slotStatus: str | None = None,
    previousSlotStatus: str | None = None,
    changed: bool = False,
    hasSlotStableCount: int = 0,
    longNoSlotMode: bool = False,
) -> str:
    base = base or datetime.now(UTC)
    if isRateLimited:
        minutes = random.randint(30, 60)
        return (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
    elif hadError:
        minutes = random.randint(10, 20)
        return (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
    if slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT:
        minutes = random.randint(50, 70)
        return (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
    if slotStatus == PASSPORT_SLOT_STATUS_NO_SLOT:
        if longNoSlotMode:
            minutes = random.randint(50, 70)
            return (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
        return computeNextNoSlotCheckAt(base).isoformat()
    minutes = random.randint(1, 30)
    return (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def computeNextNoSlotCheckAt(base: datetime) -> datetime:
    local = base.astimezone(CHINA_TIMEZONE)
    currentSeconds = local.hour * 3600 + local.minute * 60 + local.second
    broadStart = 23 * 3600 + 59 * 60
    broadEndAfterMidnight = 2 * 60 + 59
    inBroadWindow = currentSeconds >= broadStart or currentSeconds <= broadEndAfterMidnight
    if inBroadWindow:
        targetMidnightDate = local.date()
        if currentSeconds >= broadStart:
            targetMidnightDate = (local + timedelta(days=1)).date()
        targetMidnight = datetime.combine(targetMidnightDate, datetime.min.time(), tzinfo=CHINA_TIMEZONE)
        coreOffsets = [-15, -10, -5, 0, 2, 5, 10, 15, 20, 25, 30]
        for target in (targetMidnight + timedelta(seconds=offset) for offset in coreOffsets):
            if local < target:
                return target.astimezone(UTC).replace(microsecond=0)
        return (base + timedelta(seconds=15)).replace(microsecond=0)
    nextWindowStart = local.replace(hour=23, minute=59, second=0, microsecond=0)
    if local >= nextWindowStart:
        nextWindowStart += timedelta(days=1)
    if nextWindowStart - local <= timedelta(minutes=10):
        return nextWindowStart.astimezone(UTC).replace(microsecond=0)
    minutes = random.randint(1, 30)
    return (base + timedelta(minutes=minutes)).replace(microsecond=0)


def parseIsoDatetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def getLongNoSlotStartedAt(monitorRow: dict[str, Any], firstRunAt: str | None) -> datetime | None:
    candidates = [
        parsed
        for parsed in (
            parseIsoDatetime(monitorRow["created_at"]),
            parseIsoDatetime(firstRunAt),
        )
        if parsed is not None
    ]
    return min(candidates) if candidates else None


def getPassportSlotLongNoSlotStats(connection: Any, monitorRow: dict[str, Any]) -> dict[str, Any]:
    positiveHistory = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM passport_slot_history
        WHERE monitor_id = ?
          AND slot_count > 0
        """,
        (monitorRow["id"],),
    ).fetchone()
    firstRun = connection.execute(
        """
        SELECT MIN(started_at) AS first_run_at
        FROM query_runs
        WHERE case_id = ?
          AND success = 1
          AND trigger_type LIKE 'passport_slot_%'
        """,
        (monitorRow["case_id"],),
    ).fetchone()
    firstRunAt = firstRun["first_run_at"] if firstRun else None
    return {
        "positiveHistoryCount": int(positiveHistory["count"] if positiveHistory else 0),
        "firstRunAt": firstRunAt,
        "startedAt": getLongNoSlotStartedAt(monitorRow, firstRunAt),
    }


def hasLongNoSlotNotice(monitorRow: dict[str, Any]) -> bool:
    return bool(monitorRow["long_no_slot_notice_sent_at"] and monitorRow["long_no_slot_stop_at"])


def isLongNoSlotGraceActive(monitorRow: dict[str, Any], now: datetime) -> bool:
    stopAt = parseIsoDatetime(monitorRow["long_no_slot_stop_at"])
    return hasLongNoSlotNotice(monitorRow) and not monitorRow["long_no_slot_stopped_at"] and stopAt is not None and now < stopAt


def shouldSendLongNoSlotNotice(
    monitorRow: dict[str, Any],
    *,
    slotStatus: str,
    success: bool,
    positiveHistoryCount: int,
    startedAt: datetime | None,
    now: datetime,
) -> bool:
    if not success or slotStatus != PASSPORT_SLOT_STATUS_NO_SLOT:
        return False
    if not bool(monitorRow["is_enabled"]) or hasLongNoSlotNotice(monitorRow):
        return False
    if positiveHistoryCount > 0 or startedAt is None:
        return False
    return now - startedAt >= timedelta(days=LONG_NO_SLOT_NOTICE_DAYS)


def shouldAutoStopLongNoSlotMonitor(
    monitorRow: dict[str, Any],
    *,
    positiveHistoryCount: int,
    now: datetime,
) -> bool:
    if not bool(monitorRow["is_enabled"]) or positiveHistoryCount > 0:
        return False
    if not hasLongNoSlotNotice(monitorRow) or monitorRow["long_no_slot_stopped_at"]:
        return False
    stopAt = parseIsoDatetime(monitorRow["long_no_slot_stop_at"])
    if stopAt is None or now < stopAt:
        return False
    resultJson = decryptIfNeeded(monitorRow["last_result_json"] or "") or ""
    result = json.loads(resultJson) if resultJson else {}
    currentStatus = passportSlotStatusFromResult(result if isinstance(result, dict) else {}, monitorRow["last_slot_fingerprint"])
    return currentStatus == PASSPORT_SLOT_STATUS_NO_SLOT and int(monitorRow["last_slot_count"] or 0) == 0


def passportSlotStatusFromFingerprint(fingerprint: str | None) -> str:
    value = str(fingerprint or "")
    if value.startswith(f"{PASSPORT_SLOT_STATE_PREFIX}{PASSPORT_SLOT_STATUS_HAS_SLOT}:"):
        return PASSPORT_SLOT_STATUS_HAS_SLOT
    if value == f"{PASSPORT_SLOT_STATE_PREFIX}{PASSPORT_SLOT_STATUS_NOT_ELIGIBLE}":
        return PASSPORT_SLOT_STATUS_NOT_ELIGIBLE
    if value in {PASSPORT_SLOT_EMPTY_FINGERPRINT, "empty"}:
        return PASSPORT_SLOT_STATUS_NO_SLOT
    if value:
        return PASSPORT_SLOT_STATUS_HAS_SLOT
    return PASSPORT_SLOT_STATUS_UNKNOWN


def passportSlotStatusFromResult(result: dict[str, Any] | None, fallbackFingerprint: str | None = None) -> str:
    if isinstance(result, dict):
        slotStatus = str(result.get("slotStatus") or "")
        if slotStatus in {PASSPORT_SLOT_STATUS_NOT_ELIGIBLE, PASSPORT_SLOT_STATUS_NO_SLOT, PASSPORT_SLOT_STATUS_HAS_SLOT}:
            return slotStatus
    return passportSlotStatusFromFingerprint(fallbackFingerprint)


def computePassportSlotFingerprint(slotStatus: str, slots: list[Any]) -> str:
    if slotStatus == PASSPORT_SLOT_STATUS_NOT_ELIGIBLE:
        return f"{PASSPORT_SLOT_STATE_PREFIX}{PASSPORT_SLOT_STATUS_NOT_ELIGIBLE}"
    if slotStatus == PASSPORT_SLOT_STATUS_NO_SLOT:
        return PASSPORT_SLOT_EMPTY_FINGERPRINT
    normalized = [stableSlotValue(slot) for slot in slots]
    normalized.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    return f"{PASSPORT_SLOT_STATE_PREFIX}{PASSPORT_SLOT_STATUS_HAS_SLOT}:{hashlib.sha256(payload.encode()).hexdigest()}"


def extractGtsMessage(data: Any) -> str:
    messages: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            messages.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return " ".join(message.strip() for message in messages if message.strip())


def classifyAuthFailure(data: dict[str, Any]) -> tuple[str, str]:
    message = extractGtsMessage(data)
    normalizedMessage = message.lower()
    if "invalid_uid" in normalizedMessage or "invalid uid" in normalizedMessage or "无效" in message:
        return PASSPORT_SLOT_STATUS_UNKNOWN, message or "GTS UID/HAL 无效"
    if data.get("token") is None:
        return PASSPORT_SLOT_STATUS_NOT_ELIGIBLE, message or "您没有资格预约。"
    return PASSPORT_SLOT_STATUS_UNKNOWN, message or "GTS UID/HAL 鉴权失败"


def detectNoSlotMessage(data: dict[str, Any]) -> str:
    message = extractGtsMessage(data)
    if "目前没有可用的预约" in message:
        return message
    normalizedMessage = message.lower()
    if "no available" in normalizedMessage or "no appointment" in normalizedMessage:
        return message
    return ""


def formatSlotStatus(slotStatus: str, language: str = "zh") -> str:
    if language == "en":
        if slotStatus == PASSPORT_SLOT_STATUS_NOT_ELIGIBLE:
            return "Not eligible for passport appointment yet"
        if slotStatus == PASSPORT_SLOT_STATUS_NO_SLOT:
            return "Eligible, but no available slot"
        if slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT:
            return "Available slots found"
        return "Unknown"
    if slotStatus == PASSPORT_SLOT_STATUS_NOT_ELIGIBLE:
        return "暂不具备预约资格"
    if slotStatus == PASSPORT_SLOT_STATUS_NO_SLOT:
        return "已可预约但暂无 slot"
    if slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT:
        return "发现可预约时间"
    return "未知状态"


def buildPassportSlotEmailCase(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["case_id"],
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "application_num": decryptIfNeeded(row["application_num"]) or row["application_num"],
        "receive_email": decryptIfNeeded(row["receive_email"]) or row["receive_email"],
        "sender_mode": row["sender_mode"],
    }


def normalizePassportSlotMonitor(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    resultJson = decryptIfNeeded(row.get("last_result_json") or "") or ""
    result = json.loads(resultJson) if resultJson else None
    identifier = decryptIfNeeded(row.get("identifier_encrypted")) or ""
    return {
        "id": row["id"],
        "caseId": row["case_id"],
        "identifier": identifier,
        "identifierMasked": maskIdentifier(identifier) if identifier else "",
        "isEnabled": bool(row["is_enabled"]),
        "emailNotificationsEnabled": bool(row["email_notifications_enabled"]),
        "nextCheckAt": row["next_check_at"],
        "lastCheckedAt": row["last_checked_at"],
        "lastSlotFingerprint": row["last_slot_fingerprint"],
        "lastSlotCount": row["last_slot_count"],
        "lastResult": result,
        "lastErrorMessage": row["last_error_message"],
        "longNoSlotNoticeSentAt": row["long_no_slot_notice_sent_at"],
        "longNoSlotStopAt": row["long_no_slot_stop_at"],
        "longNoSlotStoppedAt": row["long_no_slot_stopped_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def getPassportSlotMonitor(caseId: int, userId: int | None = None) -> dict[str, Any] | None:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT m.*
            FROM passport_slot_monitors m
            JOIN ceac_cases c ON c.id = m.case_id
            WHERE m.case_id = ? {userFilter}
            """,
            params,
        ).fetchone()
    return normalizePassportSlotMonitor(row)


def upsertPassportSlotMonitor(
    caseId: int,
    userId: int,
    identifier: str,
    isEnabled: bool,
    emailNotificationsEnabled: bool,
) -> dict[str, Any] | None:
    normalizedIdentifier = normalizeIdentifier(identifier)
    now = datetime.now(UTC).replace(microsecond=0)
    nowIso = now.isoformat()
    nextCheckAt = computeNextPassportSlotCheckAt(now) if isEnabled else None
    with getConnection() as connection:
        case = connection.execute("SELECT id FROM ceac_cases WHERE id = ? AND user_id = ?", (caseId, userId)).fetchone()
        if not case:
            return None
        current = connection.execute("SELECT id FROM passport_slot_monitors WHERE case_id = ?", (caseId,)).fetchone()
        if current:
            connection.execute(
                """
                UPDATE passport_slot_monitors
                SET identifier_encrypted = ?, is_enabled = ?, email_notifications_enabled = ?,
                    next_check_at = ?, last_error_message = '',
                    long_no_slot_notice_sent_at = ?,
                    long_no_slot_stop_at = ?,
                    long_no_slot_stopped_at = ?,
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    encryptSecret(normalizedIdentifier),
                    int(isEnabled),
                    int(emailNotificationsEnabled),
                    nextCheckAt,
                    None,
                    None,
                    None,
                    nowIso,
                    caseId,
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO passport_slot_monitors (
                    case_id, identifier_encrypted, is_enabled, email_notifications_enabled, next_check_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (caseId, encryptSecret(normalizedIdentifier), int(isEnabled), int(emailNotificationsEnabled), nextCheckAt, nowIso, nowIso),
            )
    return getPassportSlotMonitor(caseId, userId)


def patchPassportSlotMonitor(
    caseId: int,
    userId: int,
    *,
    isEnabled: bool | None = None,
    emailNotificationsEnabled: bool | None = None,
) -> dict[str, Any] | None:
    now = datetime.now(UTC).replace(microsecond=0)
    nowIso = now.isoformat()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT m.id
            FROM passport_slot_monitors m
            JOIN ceac_cases c ON c.id = m.case_id
            WHERE m.case_id = ? AND c.user_id = ?
            """,
            (caseId, userId),
        ).fetchone()
        if not row:
            return None
        assignments: list[str] = []
        values: list[Any] = []
        if isEnabled is not None:
            assignments.extend(["is_enabled = ?", "next_check_at = ?"])
            values.extend([int(isEnabled), computeNextPassportSlotCheckAt(now) if isEnabled else None])
            if isEnabled:
                assignments.extend(
                    [
                        "long_no_slot_notice_sent_at = NULL",
                        "long_no_slot_stop_at = NULL",
                        "long_no_slot_stopped_at = NULL",
                    ],
                )
        if emailNotificationsEnabled is not None:
            assignments.append("email_notifications_enabled = ?")
            values.append(int(emailNotificationsEnabled))
        if not assignments:
            return getPassportSlotMonitor(caseId, userId)
        assignments.append("updated_at = ?")
        values.extend([nowIso, caseId])
        connection.execute(
            f"UPDATE passport_slot_monitors SET {', '.join(assignments)} WHERE case_id = ?",
            tuple(values),
        )
    return getPassportSlotMonitor(caseId, userId)


def normalizeSlots(data: dict[str, Any]) -> list[Any]:
    availableDates = data.get("availableDates")
    if isinstance(availableDates, list):
        return availableDates
    for key in ("slots", "availableSlots", "dates"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def stableSlotValue(slot: Any) -> Any:
    if isinstance(slot, dict):
        if "date" in slot and isinstance(slot.get("times"), list):
            times: list[Any] = []
            for item in slot["times"]:
                if isinstance(item, dict):
                    value = item.get("time") or item.get("startTime") or item.get("dateTime") or item.get("datetime")
                    if value not in (None, ""):
                        times.append(str(value))
                elif item not in (None, ""):
                    times.append(str(item))
            return {
                "date": slot.get("date"),
                "city": slot.get("city") or slot.get("cityName") or slot.get("location") or slot.get("center"),
                "times": sorted(times),
            }
        preferredKeys = [
            "date",
            "time",
            "datetime",
            "dateTime",
            "startTime",
            "endTime",
            "city",
            "location",
            "center",
            "available",
        ]
        compact = {key: slot[key] for key in preferredKeys if key in slot}
        return compact or {key: slot[key] for key in sorted(slot)}
    return slot


def computeSlotFingerprint(slots: list[Any]) -> str:
    return computePassportSlotFingerprint(PASSPORT_SLOT_STATUS_HAS_SLOT if slots else PASSPORT_SLOT_STATUS_NO_SLOT, slots)


def formatSlotLines(slots: list[Any]) -> list[str]:
    lines: list[str] = []
    for index, slot in enumerate(slots[:20], start=1):
        if isinstance(slot, dict):
            if "date" in slot and isinstance(slot.get("times"), list):
                times: list[str] = []
                for item in slot["times"]:
                    if isinstance(item, dict):
                        value = item.get("time") or item.get("startTime") or item.get("dateTime") or item.get("datetime")
                        if value not in (None, ""):
                            times.append(str(value))
                    elif item not in (None, ""):
                        times.append(str(item))
                timeText = "、".join(times) if times else "接口未返回具体时间"
                location = slot.get("city") or slot.get("cityName") or slot.get("location") or slot.get("center")
                locationText = f"（{location}）" if location else ""
                lines.append(f"{index}. {slot.get('date')}{locationText}：{timeText}")
                continue
            parts = []
            for key in ("date", "time", "datetime", "dateTime", "startTime", "endTime", "city", "location", "center"):
                value = slot.get(key)
                if value not in (None, ""):
                    parts.append(f"{key}: {value}")
            lines.append(f"{index}. {'; '.join(parts) if parts else json.dumps(slot, ensure_ascii=False, default=str)}")
        else:
            lines.append(f"{index}. {slot}")
    if len(slots) > 20:
        lines.append(f"... 还有 {len(slots) - 20} 条结果未在邮件中展开。")
    return lines


def summarizePayload(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)[:2000]


def buildGtsHeaders() -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": GTS_SITE_URL.rstrip("/"),
        "Referer": GTS_SITE_URL,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    }


def isRateLimitedResponse(data: dict[str, Any], statusCode: int) -> bool:
    return statusCode == 429 or data.get("rateLimited") is True or data.get("reason") == "rate_limited"


def errorFromAuthResponse(data: dict[str, Any]) -> str:
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("reason") or "GTS UID/HAL 鉴权失败")
    if data.get("token") is None:
        return "GTS 未返回 token，UID/HAL 可能不具备预约资格"
    return "GTS UID/HAL 鉴权失败"


def fetchPassportSlotAvailability(identifier: str) -> dict[str, Any]:
    normalizedIdentifier = normalizeIdentifier(identifier)
    headers = buildGtsHeaders()
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        authResponse = client.post(
            f"{GTS_API_BASE_URL}/authenticate",
            headers=headers,
            json={"uid": normalizedIdentifier},
        )
        try:
            authData = authResponse.json()
        except ValueError as exc:
            raise RuntimeError(f"GTS 鉴权返回非 JSON：HTTP {authResponse.status_code}") from exc
        if isRateLimitedResponse(authData, authResponse.status_code):
            return {"success": False, "rateLimited": True, "error": "GTS 请求被限流", "raw": authData}
        token = authData.get("token") if isinstance(authData, dict) else None
        if not token:
            slotStatus, authError = classifyAuthFailure(authData)
            if slotStatus == PASSPORT_SLOT_STATUS_NOT_ELIGIBLE:
                return {
                    "success": True,
                    "rateLimited": False,
                    "slotStatus": PASSPORT_SLOT_STATUS_NOT_ELIGIBLE,
                    "statusMessage": authError or "您没有资格预约。",
                    "availableSlots": [],
                    "availableDates": [],
                    "raw": authData,
                }
            return {"success": False, "rateLimited": False, "error": authError or errorFromAuthResponse(authData), "raw": authData}
        availabilityResponse = client.get(
            f"{GTS_API_BASE_URL}/availability7days/",
            headers={**headers, "Authorization": str(token)},
        )
        try:
            availabilityData = availabilityResponse.json()
        except ValueError as exc:
            raise RuntimeError(f"GTS slot 返回非 JSON：HTTP {availabilityResponse.status_code}") from exc
        if isRateLimitedResponse(availabilityData, availabilityResponse.status_code):
            return {"success": False, "rateLimited": True, "error": "GTS slot 查询被限流", "raw": availabilityData}
        slots = normalizeSlots(availabilityData)
        slotStatus = PASSPORT_SLOT_STATUS_HAS_SLOT if slots else PASSPORT_SLOT_STATUS_NO_SLOT
        statusMessage = detectNoSlotMessage(availabilityData)
        return {
            "success": True,
            "rateLimited": False,
            "slotStatus": slotStatus,
            "statusMessage": statusMessage or ("发现可预约时间。" if slots else "目前没有可用的预约，请稍后再试。"),
            "availableSlots": slots,
            "availableDates": availabilityData.get("availableDates", slots),
            "raw": availabilityData,
        }


def runPassportSlotQuery(caseId: int, triggerType: str = "passport_slot_automatic") -> dict[str, Any]:
    started = datetime.now(UTC)
    startedIso = started.replace(microsecond=0).isoformat()
    success = False
    errorMessage = ""
    result: dict[str, Any] = {"success": False}
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT m.*, c.user_id, c.display_name, c.application_num, c.receive_email, c.sender_mode
            FROM passport_slot_monitors m
            JOIN ceac_cases c ON c.id = m.case_id
            WHERE m.case_id = ?
            """,
            (caseId,),
        ).fetchone()
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone() if row else None
    if not row:
        raise RuntimeError("护照预约监控不存在")
    identifier = decryptIfNeeded(row["identifier_encrypted"]) or ""
    previousResultJson = decryptIfNeeded(row.get("last_result_json") or "") or ""
    previousResult = json.loads(previousResultJson) if previousResultJson else {}
    previousFingerprint = row["last_slot_fingerprint"] or ""
    previousSlotStatus = passportSlotStatusFromResult(previousResult if isinstance(previousResult, dict) else {}, previousFingerprint)
    slots: list[Any] = []
    slotStatus = previousSlotStatus
    statusMessage = ""
    fingerprint = previousFingerprint
    notificationSent = False

    try:
        result = fetchPassportSlotAvailability(identifier)
        success = bool(result.get("success"))
        if not success:
            errorMessage = str(result.get("error") or "GTS slot 查询失败")
        else:
            slots = normalizeSlots(result)
            slotStatus = passportSlotStatusFromResult(result, computeSlotFingerprint(slots))
            statusMessage = str(result.get("statusMessage") or formatSlotStatus(slotStatus))
            fingerprint = computePassportSlotFingerprint(slotStatus, slots)
    except Exception as exc:
        errorMessage = str(exc)
        result = {"success": False, "error": errorMessage, "rateLimited": False}

    finished = datetime.now(UTC)
    finishedIso = finished.replace(microsecond=0).isoformat()
    durationMs = int((finished - started).total_seconds() * 1000)
    changed = success and fingerprint != previousFingerprint
    previousStableCount = int(previousResult.get("hasSlotStableCount") or 0) if isinstance(previousResult, dict) else 0
    hasSlotStableCount = previousStableCount + 1 if success and slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT and previousSlotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT and not changed else 0
    longNoSlotStats: dict[str, Any] = {"positiveHistoryCount": 0, "firstRunAt": None, "startedAt": None}
    if success:
        with getConnection() as connection:
            longNoSlotStats = getPassportSlotLongNoSlotStats(connection, row)
    shouldAutoStopMonitor = (
        success
        and changed
        and slotStatus == PASSPORT_SLOT_STATUS_NOT_ELIGIBLE
        and previousSlotStatus in {PASSPORT_SLOT_STATUS_NO_SLOT, PASSPORT_SLOT_STATUS_HAS_SLOT}
    )
    if shouldAutoStopMonitor:
        statusMessage = "GTS 已不再返回可预约资格，系统判断预约资格可能已结束，并已自动停止护照预约监控。"
    slotListChanged = (
        success
        and changed
        and slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT
        and previousSlotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT
    )
    if slotListChanged:
        statusMessage = "可预约时间列表发生变化。"
    if success:
        result["slotStatus"] = slotStatus
        result["statusMessage"] = statusMessage or formatSlotStatus(slotStatus)
        result["slotFingerprint"] = fingerprint
        result["hasSlotStableCount"] = hasSlotStableCount
        result["autoStopped"] = shouldAutoStopMonitor
        result["slotListChanged"] = slotListChanged
    longNoSlotNoticeShouldSend = shouldSendLongNoSlotNotice(
        row,
        slotStatus=slotStatus,
        success=success,
        positiveHistoryCount=int(longNoSlotStats["positiveHistoryCount"]),
        startedAt=longNoSlotStats["startedAt"],
        now=finished,
    )
    longNoSlotGraceActive = isLongNoSlotGraceActive(row, finished) or longNoSlotNoticeShouldSend
    shouldNotify = (
        success
        and bool(row["email_notifications_enabled"])
        and not longNoSlotNoticeShouldSend
        and (
            (slotStatus == PASSPORT_SLOT_STATUS_NO_SLOT and previousSlotStatus == PASSPORT_SLOT_STATUS_NOT_ELIGIBLE and changed)
            or (slotStatus == PASSPORT_SLOT_STATUS_NO_SLOT and previousSlotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT and changed)
            or shouldAutoStopMonitor
            or (slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT and (previousSlotStatus in {PASSPORT_SLOT_STATUS_UNKNOWN, PASSPORT_SLOT_STATUS_NO_SLOT} or changed))
        )
    )

    with getConnection() as connection:
        longNoSlotStopAt: str | None = None
        if shouldNotify:
            try:
                sendPassportSlotNotification(
                    buildPassportSlotEmailCase(row),
                    smtpConfig,
                    identifierFull=identifier,
                    identifierMasked=maskIdentifier(identifier),
                    fetchedAt=finishedIso,
                    slotStatus=slotStatus,
                    statusMessage=statusMessage or formatSlotStatus(slotStatus),
                    slotLines=formatSlotLines(slots),
                    rawSummary="",
                    autoStopped=shouldAutoStopMonitor,
                    slotListChanged=slotListChanged,
                    connection=connection,
                )
                notificationSent = True
            except Exception as exc:
                errorMessage = f"Notification failed: {exc}"
        if longNoSlotNoticeShouldSend:
            longNoSlotStopAt = (finished + timedelta(days=LONG_NO_SLOT_GRACE_DAYS)).replace(microsecond=0).isoformat()
            try:
                sendPassportSlotLongNoSlotNoticeEmail(
                    buildPassportSlotEmailCase(row),
                    smtpConfig,
                    identifierFull=identifier,
                    identifierMasked=maskIdentifier(identifier),
                    noticeAt=finishedIso,
                    stopAt=longNoSlotStopAt,
                    monitorStartedAt=longNoSlotStats["startedAt"].replace(microsecond=0).isoformat()
                    if longNoSlotStats["startedAt"]
                    else row["created_at"],
                    connection=connection,
                )
                notificationSent = True
                result["longNoSlotNoticeSent"] = True
                result["longNoSlotStopAt"] = longNoSlotStopAt
            except Exception as exc:
                errorMessage = f"Long no-slot notification failed: {exc}"
        if success and slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT and hasLongNoSlotNotice(row):
            result["longNoSlotCleared"] = True
        if success and changed:
            connection.execute(
                """
                INSERT INTO passport_slot_history (
                    monitor_id, case_id, slot_fingerprint, slot_count, raw_payload, fetched_at, notification_sent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    caseId,
                    fingerprint,
                    len(slots),
                    encryptSecret(json.dumps(result, ensure_ascii=False, default=str)),
                    finishedIso,
                    int(notificationSent),
                ),
            )
        nextCheckAt = (
            computeNextPassportSlotCheckAt(
                finished,
                isRateLimited=bool(result.get("rateLimited")),
                hadError=not success,
                slotStatus=slotStatus,
                previousSlotStatus=previousSlotStatus,
                changed=changed,
                hasSlotStableCount=hasSlotStableCount,
                longNoSlotMode=longNoSlotGraceActive,
            )
            if bool(row["is_enabled"]) and not shouldAutoStopMonitor
            else None
        )
        if success and slotStatus in {PASSPORT_SLOT_STATUS_NO_SLOT, PASSPORT_SLOT_STATUS_HAS_SLOT}:
            connection.execute(
                """
                UPDATE ceac_cases
                SET is_enabled = 0,
                    ceac_auto_locked_by_passport_slot = 1,
                    next_check_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (finishedIso, caseId),
            )
        connection.execute(
            """
            UPDATE passport_slot_monitors
            SET last_checked_at = ?, is_enabled = ?, next_check_at = ?, last_slot_fingerprint = ?,
                last_slot_count = ?, last_result_json = ?, last_error_message = ?, updated_at = ?
                {long_no_slot_setters}
            WHERE id = ?
            """.format(
                long_no_slot_setters=(
                    ", long_no_slot_notice_sent_at = ?, long_no_slot_stop_at = ?, long_no_slot_stopped_at = NULL"
                    if longNoSlotNoticeShouldSend and longNoSlotStopAt
                    else ", long_no_slot_notice_sent_at = NULL, long_no_slot_stop_at = NULL, long_no_slot_stopped_at = NULL"
                    if success and slotStatus == PASSPORT_SLOT_STATUS_HAS_SLOT and hasLongNoSlotNotice(row)
                    else ""
                ),
            ),
            (
                finishedIso,
                0 if shouldAutoStopMonitor else int(row["is_enabled"]),
                nextCheckAt,
                fingerprint if success else previousFingerprint,
                len(slots) if success else int(row["last_slot_count"]),
                encryptSecret(json.dumps(result, ensure_ascii=False, default=str)),
                errorMessage,
                finishedIso,
                *(
                    (finishedIso, longNoSlotStopAt)
                    if longNoSlotNoticeShouldSend and longNoSlotStopAt
                    else ()
                ),
                row["id"],
            ),
        )
        connection.execute(
            """
            INSERT INTO query_runs (case_id, started_at, finished_at, success, status_id, error_message, duration_ms, trigger_type)
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (caseId, startedIso, finishedIso, int(success), errorMessage, durationMs, triggerType),
        )
    return {
        "success": success,
        "changed": changed,
        "notified": notificationSent,
        "slotCount": len(slots),
        "slotStatus": slotStatus,
        "error": errorMessage,
        "result": result,
    }


def sendCurrentPassportSlotEmail(caseId: int, userId: int | None = None) -> dict[str, Any]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT m.*, c.user_id, c.display_name, c.application_num, c.receive_email, c.sender_mode
            FROM passport_slot_monitors m
            JOIN ceac_cases c ON c.id = m.case_id
            WHERE m.case_id = ? {userFilter}
            """,
            params,
        ).fetchone()
        if not row:
            return {"success": False, "error": "护照预约监控不存在，请先保存 UID/HAL"}
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone()
    identifier = decryptIfNeeded(row["identifier_encrypted"]) or ""
    resultJson = decryptIfNeeded(row.get("last_result_json") or "") or ""
    result = json.loads(resultJson) if resultJson else {}
    slots = normalizeSlots(result) if isinstance(result, dict) else []
    slotStatus = passportSlotStatusFromResult(result if isinstance(result, dict) else {}, row["last_slot_fingerprint"])
    statusMessage = str(result.get("statusMessage") or formatSlotStatus(slotStatus)) if isinstance(result, dict) else formatSlotStatus(slotStatus)
    case = {
        "id": row["case_id"],
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "application_num": decryptIfNeeded(row["application_num"]) or row["application_num"],
        "receive_email": decryptIfNeeded(row["receive_email"]) or row["receive_email"],
        "sender_mode": row["sender_mode"],
    }
    try:
        sendPassportSlotStatusEmail(
            case,
            smtpConfig,
            identifierFull=identifier,
            identifierMasked=maskIdentifier(identifier),
            fetchedAt=row["last_checked_at"] or utcNowIso(),
            slotStatus=slotStatus,
            statusMessage=statusMessage,
            slotLines=formatSlotLines(slots),
            rawSummary="",
            hasSlots=bool(slots),
            isTest=True,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "error": ""}


def enqueuePassportSlotQuery(caseId: int, triggerType: str, userId: int | None = None) -> dict[str, Any] | None:
    now = utcNowIso()
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        monitor = connection.execute(
            f"""
            SELECT m.id
            FROM passport_slot_monitors m
            JOIN ceac_cases c ON c.id = m.case_id
            WHERE m.case_id = ? {userFilter}
            """,
            params,
        ).fetchone()
        if not monitor:
            return None
        existing = connection.execute(
            """
            SELECT * FROM query_jobs
            WHERE case_id = ?
              AND trigger_type LIKE 'passport_slot_%'
              AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
        if existing:
            from .case_service import normalizeQueryJob

            return normalizeQueryJob(existing)
        cursor = connection.execute(
            """
            INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?)
            """,
            (caseId, triggerType, now, now),
        )
        row = connection.execute("SELECT * FROM query_jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    from .case_service import normalizeQueryJob

    return normalizeQueryJob(row)


def stopPassportSlotLongNoSlotMonitorIfDue(caseId: int, now: datetime) -> bool:
    nowIso = now.replace(microsecond=0).isoformat()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT m.*, c.user_id, c.display_name, c.application_num, c.receive_email, c.sender_mode
            FROM passport_slot_monitors m
            JOIN ceac_cases c ON c.id = m.case_id
            WHERE m.case_id = ?
            """,
            (caseId,),
        ).fetchone()
        if not row:
            return False
        stats = getPassportSlotLongNoSlotStats(connection, row)
        if not shouldAutoStopLongNoSlotMonitor(row, positiveHistoryCount=int(stats["positiveHistoryCount"]), now=now):
            return False
        identifier = decryptIfNeeded(row["identifier_encrypted"]) or ""
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone()
        connection.execute(
            """
            UPDATE passport_slot_monitors
            SET is_enabled = 0,
                next_check_at = NULL,
                long_no_slot_stopped_at = ?,
                last_error_message = '',
                updated_at = ?
            WHERE id = ?
            """,
            (nowIso, nowIso, row["id"]),
        )
        try:
            sendPassportSlotLongNoSlotStoppedEmail(
                buildPassportSlotEmailCase(row),
                smtpConfig,
                identifierFull=identifier,
                identifierMasked=maskIdentifier(identifier),
                stoppedAt=nowIso,
                noticeAt=row["long_no_slot_notice_sent_at"],
                connection=connection,
            )
        except Exception as exc:
            connection.execute(
                """
                UPDATE passport_slot_monitors
                SET last_error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (f"Long no-slot stop notification failed: {exc}", nowIso, row["id"]),
            )
        return True


def enqueueDuePassportSlotMonitors(limit: int = 20) -> list[dict[str, Any]]:
    now = datetime.now(UTC).replace(microsecond=0)
    nowIso = now.isoformat()
    queued: list[dict[str, Any]] = []
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT m.case_id
            FROM passport_slot_monitors m
            WHERE m.is_enabled = 1
              AND m.next_check_at IS NOT NULL
              AND m.next_check_at <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM query_jobs j
                  WHERE j.case_id = m.case_id
                    AND j.trigger_type LIKE 'passport_slot_%'
                    AND j.status IN ('queued', 'running')
              )
            ORDER BY m.next_check_at ASC
            LIMIT ?
            """,
            (nowIso, limit),
        ).fetchall()
    for row in rows:
        if stopPassportSlotLongNoSlotMonitorIfDue(int(row["case_id"]), now):
            continue
        job = enqueuePassportSlotQuery(int(row["case_id"]), "passport_slot_automatic")
        if job:
            queued.append(job)
    return queued


def listPassportSlotHistory(caseId: int, userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT h.*
            FROM passport_slot_history h
            JOIN ceac_cases c ON c.id = h.case_id
            WHERE h.case_id = ? {userFilter}
            ORDER BY h.id DESC
            LIMIT 50
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "caseId": row["case_id"],
            "slotFingerprint": row["slot_fingerprint"],
            "slotCount": row["slot_count"],
            "rawPayload": json.loads(decryptIfNeeded(row["raw_payload"]) or "{}"),
            "fetchedAt": row["fetched_at"],
            "notificationSent": bool(row["notification_sent"]),
        }
        for row in rows
    ]


def isPassportSlotTrigger(triggerType: str | None) -> bool:
    return str(triggerType or "").startswith(PASSPORT_SLOT_TRIGGER_PREFIX)


def passportWorkerId() -> str:
    return f"passport-slot-{uuid.uuid4()}"
