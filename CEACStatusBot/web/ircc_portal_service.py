import hashlib
import hmac
import json
import random
import re
import secrets as stdlibSecrets
import uuid
from base64 import b64decode, b64encode
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from .case_service import PREMIUM_CASE_LIMIT, STANDARD_CASE_LIMIT, computeNextDailyCheckAt, nextProfileSortOrder, upsertSmtpConfig
from .database import getConnection, utcNowIso
from .mailer import (
    buildEmailHtml,
    buildSupportFooterPlain,
    formatCaseEmailTime,
    formatEmailTime,
    formatEmailTextTimes,
    getSupportImagePath,
    getSystemSmtpConfig,
    getUserEmailTimezone,
    recordEmailDelivery,
    sendEmail,
    SUPPORT_IMAGE_CONTENT_ID,
)
from .schemas import IrccCaseInput, IrccCasePatch, IrccDiscoverRequest
from .secrets import decryptIfNeeded, decryptSecret, encryptSecret


IRCC_PORTAL_URL = "https://portal-portail.apps.cic.gc.ca"
IRCC_API_BASE_URL = "https://api.portal-portail.apps.cic.gc.ca/portal/v1"
COGNITO_REGION = "ca-central-1"
COGNITO_CLIENT_ID = "661ccpl4rd23hoo47eub0nt9t3"
COGNITO_USER_POOL_ID = "ca-central-1_zNXgwqKji"
COGNITO_POOL_NAME = COGNITO_USER_POOL_ID.split("_", 1)[1]
COGNITO_ENDPOINT = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
IRCC_QUERY_TRIGGER_PREFIX = "ircc_"
IRCC_QUERY_TIMEOUT_ERROR_MESSAGE = "IRCC Portal 查询运行超过系统设定时间仍未完成，已标记为失败；请稍后重试或重新验证 IRCC 账号。"
COGNITO_N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E08"
    "8A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD"
    "3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E"
    "7EC6F44C42E9A637ED6B0BFF5CB6F406B7EDEE386BFB5A899F"
    "A5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF05"
    "98DA48361C55D39A69163FA8FD24CF5F83655D23DCA3AD961C"
    "62F356208552BB9ED529077096966D670C354E4ABC9804F1746"
    "C08CA18217C32905E462E36CE3BE39E772C180E86039B2783A2"
    "EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CE"
    "A956AE515D2261898FA051015728E5A8AAAC42DAD33170D045"
    "07A33A85521ABDF1CBA64ECFB850458DBEF0A8AEA71575D060"
    "C7DB3970F85A6E1E4C7ABF5AE8CDB0933D71E8C94E04A256"
    "19DCEE3D2261AD2EE6BF12FFA06D98A0864D87602733EC86A6"
    "4521F2B18177B200CBBE117577A615D6C770988C0BAD946E2"
    "08E24FA074E5AB3143DB5BFCE0FD108E4B82D120A93AD2CAFF"
    "FFFFFFFFFFFFFF"
)
COGNITO_N = int(COGNITO_N_HEX, 16)
COGNITO_G = 2


STATUS_LABELS = {
    "applicationStatus": "总申请状态",
    "applicationInfoStatus": "首页申请状态",
    "homeUpdatedDate": "首页更新时间",
    "eligibility": "资格审查",
    "medical": "体检结果",
    "additionalDocuments": "补充文件",
    "interviewOrAppointment": "面试/预约",
    "biometricInformation": "指纹/生物信息",
    "backgroundChecks": "背景调查",
    "finalDecision": "最终决定",
    "profileStatus": "档案状态",
    "processingTimeBarTitle": "处理时间标题",
    "processingTimeBarMessage": "处理时间说明",
    "estimatedCompletionDate": "预计完成日期",
    "estimatedRemainingProcessingTime": "预计剩余处理时间",
    "processingTimeExceeded": "是否超过处理时间",
    "documentStatus": "文件状态",
    "listOfApplicants": "申请人信息",
    "messages": "申请消息",
}

IRCC_GHOST_UPDATE_KEYS = {"homeUpdatedDate"}
IRCC_RAW_APPLICANT_DIFF_PATTERN = re.compile(
    r"(\[\s*\{|\{\s*['\"]?(?:fullName|uci|appNumber|biometricNumber)['\"]?\s*:).*(?:->|-&gt;)",
    re.IGNORECASE,
)
IRCC_RAW_DOCUMENT_DIFF_PATTERN = re.compile(
    r"(\[\s*\{|\{\s*['\"]?(?:documentNumber|travelDocumentNumber|documentStatus|documentType)['\"]?\s*:).*(?:->|-&gt;)",
    re.IGNORECASE,
)
IRCC_LEGACY_STATUS_TIME_PATTERN = re.compile(r"，时间：(?=\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})")
IRCC_MESSAGE_TAG_LABELS = {
    "Online.RECEIPT": "在线申请提交收据",
    "CorrespondenceSent": "IRCC 已发送信件",
}
IRCC_DOCUMENT_TYPE_LABELS: dict[str, str] = {}
IRCC_DOCUMENT_STATUS_LABELS: dict[str, str] = {}
IRCC_COUNTRY_OF_ISSUE_LABELS: dict[str, str] = {}

# 这些 code/key 来自 IRCC Portal 当前前端 bundle（用户提供 HAR 中的 main-es2015）。
# IRCC 未承诺它们是公开稳定 API；未知 code 仍会保留原始值显示。
STATUS_CODE_MAP = {
    "A0": "",
    "A1": "IRCC 已收到你的申请。若有更新或需要更多信息，IRCC 会发送消息。",
    "A2": "已作出最终决定。请查看下方最终决定。",
    "A3": "你的申请已取消。",
    "A4": "申请处于暂停状态。",
    "A5": "档案不符合资格。",
    "A6": "档案已过期。",
    "A7": "已收到邀请。",
    "A8": "资料不完整。",
    "A9": "因资料不完整而取消。",
    "A10": "等待额外条件。",
    "A11": "我们正在处理你的申请。若有更新或需要更多信息，IRCC 会发送消息。",
    "A12": "你的申请已撤回。",
    "A13": "你的申请已被视为放弃。请查看下方最终决定。",
    "A14": "你的申请有延迟。请查看下方消息了解详情。",
    "A16": "你的申请有延迟。IRCC 会通过信件或邮件发送详情。",
    "A17": "你的申请有延迟。",
    "A18": "你的申请已完成。",
    "A19": "IRCC 正在处理你的申请。若有更新、预约已安排或需要更多信息，IRCC 会发送消息。",
    "A20": "你的难民申请已暂停。请查看下方消息。",
    "A21": "你的难民申请已有资格决定。该决定将会或已经发送给你。",
    "SUBMITTED": "已提交",
    "IN_PROGRESS": "进行中",
    "E0": "不适用。",
    "E1": "申请正在处理中。IRCC 会在开始审查资格时发送消息。",
    "E2": "IRCC 正在审查你是否符合资格要求。",
    "E3": "资格审查已通过，请查看最终决定。",
    "E4": "资格审查未通过，请查看最终决定。",
    "E5": "不适用。",
    "M0": "不适用。",
    "M1": "不需要体检；如有变化，IRCC 会发送消息。",
    "M2": "IRCC 已要求体检，请查看消息。",
    "M3": "IRCC 正在审查体检结果。",
    "M4": "体检结果已通过。",
    "M5": "体检结果未通过，请查看最终决定。",
    "M6": "IRCC 未收到你所需体检的结果。请查看体检请求消息了解详情。",
    "M7": "IRCC 已要求体检。IRCC 会通过信件或邮件发送详情。",
    "M8": "IRCC 未收到你所需体检的结果。请查看体检请求消息了解详情。",
    "AD0": "不适用。",
    "AD1": "不需要补充文件。",
    "AD2": "IRCC 需要补充文件，并会发送更详细消息。",
    "AD3": "补充文件已上传。",
    "AD4": "补充文件已收到，正在审查。",
    "AD5": "IRCC 需要补充文件来处理你的申请。IRCC 会通过信件或邮件发送详情。",
    "AD6": "IRCC 已收到你提供的补充文件。",
    "IA0": "不适用。",
    "IA1": "不需要面试；如有变化，IRCC 会发送消息。",
    "IA2": "需要面试，请查看消息。",
    "IA3": "面试已完成。",
    "IA4": "面试已取消，请查看消息。",
    "IA5": "面试已重新安排。请查看消息了解详情。",
    "IA6": "你没有参加已安排的面试。请查看面试请求消息了解详情。",
    "IA7": "你需要参加面试。IRCC 会通过信件或邮件发送详情。",
    "IA8": "你没有参加已安排的面试。IRCC 会通过信件或邮件发送详情。",
    "IA9": "面试尚未安排；如有变化，IRCC 会发送消息。",
    "IA10": "你已参加预约。如需再次见面，IRCC 会通知你。",
    "B0": "不适用。",
    "B1": "不需要提供指纹；如有变化，IRCC 会发送消息。",
    "B2": "需要提供指纹，请查看消息。",
    "B3": "指纹/生物信息已完成。",
    "B5": "IRCC 尚未收到你的指纹。请查看生物信息请求消息了解详情。",
    "B6": "IRCC 需要你的指纹来处理申请。IRCC 会通过信件或邮件发送详情。",
    "B7": "IRCC 尚未收到你的指纹。请查看生物信息请求消息了解详情。",
    "B8": "IRCC 不需要你的指纹。",
    "B9": "已完成。你已提供指纹；如有问题，IRCC 会联系你。",
    "BC0": "不适用。",
    "BC1": "申请正在处理中。IRCC 会在开始背景调查时发送消息。",
    "BC2": "IRCC 正在处理背景调查；如需更多信息会发送消息。",
    "BC3": "背景调查已完成。",
    "BC4": "不适用。",
    "FD0": "",
    "FD1": "申请正在处理中。最终决定作出后，IRCC 会发送消息。",
    "FD2": "申请已获批，请查看消息。",
    "FD3": "申请已被拒，请查看消息。",
    "FD4": "申请已撤回，请查看消息。",
    "FD5": "申请已取消，IRCC 会发送更详细消息。",
    "FD6": "申请已获批。你需要提交有效护照以完成申请。请查看下方消息了解详情。",
    "FD7": "申请因资料不完整而取消。请查看下方消息了解详情。",
    "FD8": "申请无法撤回。请查看下方消息了解详情。",
    "FD9": "申请已获批。你需要提交有效护照以完成申请。IRCC 会通过信件或邮件发送详情。",
    "FD10": "申请已被拒。IRCC 会通过信件或邮件发送详情。",
    "FD11": "申请已撤回。IRCC 会通过信件或邮件发送详情。",
    "FD12": "申请无法撤回。IRCC 会通过信件或邮件发送详情。",
    "FD13": "已找到公民身份记录。请查看下方消息了解详情。",
    "FD14": "已找到公民身份记录。IRCC 会通过信件或邮件发送详情。",
    "FD15": "未找到公民身份记录。请查看下方消息了解详情。",
    "FD16": "未找到公民身份记录。IRCC 会通过信件或邮件发送详情。",
    "FD17": "申请已获批。IRCC 会通过信件或邮件发送详情。",
    "FD18": "申请已取消。IRCC 会发送包含详情的消息。",
    "FD20": "IRCC 无法处理你的申请，因为该申请已被视为放弃。请查看下方消息了解详情。",
    "FD21": "IRCC 无法处理你的申请，因为该申请已被视为放弃。IRCC 会通过信件或邮件发送详情。",
    "FD22": "你的难民申请不符合转交 IRB 的资格。",
    "FD23": "IRCC 很快会向你提供决定。",
    "FD24": "申请正在处理中。",
    "PS0": "档案处理中",
    "PBT0": "",
    "PBT1": "预计剩余处理时间",
    "PBT2": "你的申请已撤回。",
    "PBT3": "你的申请已完成。",
    "PBT4": "你的申请已取消。",
    "PBT5": "你的申请处理时间比通常更长。",
    "PBT6": "IRCC 已完成你的申请处理。",
    "PBT7": "你的申请已被视为放弃。",
    "PBS0": "",
    "PBS1": "为帮助你估计 IRCC 何时可能作出决定，IRCC 已在你的账户中加入处理时间。",
    "PBS2": "你可能暂时不会收到 IRCC 消息，这是正常情况。大多数申请进展会在接近预计完成日期时发生。",
    "PBS3": "请确保阅读消息并在 IRCC 要求时采取行动，这有助于推进申请处理。",
    "PBS4": "你的申请处理时间比通常更长。申请量可能逐月变化。请阅读消息并在 IRCC 要求时采取行动。",
    "PBS5": "你的申请处理时间比通常更长。约 20% 的申请更复杂，需要更久处理。请阅读消息并在 IRCC 要求时采取行动。",
    "01": "天",
    "02": "周",
    "03": "个月",
    "04": "年",
}

IRCC_STATUS_STAGE_FIELDS = (
    ("eligibility", "资格审查"),
    ("medical", "体检结果"),
    ("additionalDocuments", "补充文件"),
    ("interviewOrAppointment", "面试/预约"),
    ("biometricInformation", "指纹/生物信息"),
    ("backgroundChecks", "背景调查"),
    ("finalDecision", "最终决定"),
)
IRCC_NON_SUBSTANTIVE_FINAL_DECISION_CODES = {"", "FD0", "FD1", "FD24"}
IRCC_ISSUED_EQUIVALENT_CODES = {"FD2"}
IRCC_APPROVED_CODES = {"FD2", "FD6", "FD9", "FD13", "FD14", "FD17"}
IRCC_NEGATIVE_CODES = {"FD3", "FD7", "FD10", "FD15", "FD16", "FD20", "FD21", "FD22"}
IRCC_CLOSED_CODES = {"FD4", "FD5", "FD8", "FD11", "FD12", "FD18"}
IRCC_HEADLINE_TEXT_OVERRIDES = {
    "FD2": "已获批",
    "FD3": "已被拒",
    "FD4": "已撤回",
    "FD5": "已取消",
    "FD6": "已获批，需要提交护照",
    "FD7": "因资料不完整而取消",
    "FD8": "无法撤回",
    "FD9": "已获批，需要提交护照",
    "FD10": "已被拒",
    "FD11": "已撤回",
    "FD12": "无法撤回",
    "FD13": "已找到公民身份记录",
    "FD14": "已找到公民身份记录",
    "FD15": "未找到公民身份记录",
    "FD16": "未找到公民身份记录",
    "FD17": "已获批",
    "FD18": "已取消",
    "FD20": "已视为放弃",
    "FD21": "已视为放弃",
    "FD22": "不符合转交 IRB 的资格",
    "FD23": "即将提供决定",
}


class IrccAuthenticationError(RuntimeError):
    pass


def shouldStopIrccAutomaticQuery(errorMessage: str) -> bool:
    text = str(errorMessage or "")
    lowered = text.lower()
    if "http 403" in lowered:
        return False
    return "登录" in text or "MFA" in text or "鉴权" in text or "token" in lowered


def isIrccIssuedEquivalentCode(code: Any) -> bool:
    return str(code or "").strip().upper() in IRCC_ISSUED_EQUIVALENT_CODES


def getIrccHeadlineCode(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return str(buildIrccStatusOverview(snapshot).get("headlineCode") or "")


def computeNextIrccCheckAt(base: datetime | None = None, headlineCode: Any = None) -> str:
    base = base or datetime.now(UTC)
    if isIrccIssuedEquivalentCode(headlineCode):
        return computeNextDailyCheckAt(base)
    nextHour = (base + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (nextHour + timedelta(minutes=random.randint(0, 59))).isoformat()


def canonicalJson(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stableHash(value: Any) -> str:
    return hashlib.sha256(canonicalJson(value).encode()).hexdigest()


def maskEmail(email: str) -> str:
    if "@" not in email:
        return email[:2] + "***"
    name, domain = email.split("@", 1)
    prefix = name[:2] if len(name) >= 2 else name[:1]
    return f"{prefix}***@{domain}"


def formatIrccValue(value: Any) -> str:
    if isinstance(value, dict) and "status" in value:
        statusValue = str(value.get("status") or "")
        label = STATUS_CODE_MAP.get(statusValue, f"未知状态码：{statusValue}" if statusValue else "空") or "-"
        timeStamp = value.get("timeStamp")
        return f"{label}（{statusValue}）" + (f"，IRCC Portal 原始时间：{timeStamp}" if timeStamp else "")
    if isinstance(value, str):
        return STATUS_CODE_MAP.get(value, value) or "-"
    if value in (None, ""):
        return "-"
    return str(value)


def formatIrccStatusText(code: Any) -> str:
    text = str(code or "")
    if not text:
        return "-"
    return STATUS_CODE_MAP.get(text, f"未知状态码：{text}") or "-"


def formatIrccHeadlineText(code: Any) -> str:
    text = str(code or "")
    return IRCC_HEADLINE_TEXT_OVERRIDES.get(text, formatIrccStatusText(text))


def parseIrccStatusTimestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for dateFormat in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, dateFormat)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parseIrccIso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def getIrccHeadlineTone(code: Any) -> str:
    text = str(code or "")
    if text in IRCC_ISSUED_EQUIVALENT_CODES:
        return "issued"
    if text in IRCC_APPROVED_CODES:
        return "approved"
    if text in IRCC_NEGATIVE_CODES:
        return "negative"
    if text in IRCC_CLOSED_CODES:
        return "closed"
    if text in STATUS_CODE_MAP:
        return "pending"
    return "unknown"


def buildIrccStatusOverview(snapshot: dict[str, Any]) -> dict[str, Any]:
    appStatus = snapshot.get("appStatus") if isinstance(snapshot.get("appStatus"), dict) else {}
    overallCode = str(appStatus.get("applicationStatus") or "")
    latestUpdate: dict[str, Any] | None = None
    latestSortKey: tuple[datetime, int] | None = None

    # IRCC 官网页面会把总体说明和最新阶段更新同时展示。这里保留相同语义，
    # 再额外生成一个适合列表和邮件首屏阅读的概括状态。
    for index, (field, label) in enumerate(IRCC_STATUS_STAGE_FIELDS):
        value = appStatus.get(field)
        if not isinstance(value, dict):
            continue
        code = str(value.get("status") or "")
        timeStamp = str(value.get("timeStamp") or "").strip()
        parsedTime = parseIrccStatusTimestamp(timeStamp)
        if not code or not parsedTime:
            continue
        sortKey = (parsedTime, index)
        if latestSortKey is None or sortKey > latestSortKey:
            latestSortKey = sortKey
            latestUpdate = {
                "field": field,
                "label": label,
                "code": code,
                "text": formatIrccStatusText(code),
                "timeStamp": timeStamp,
            }

    finalDecision = appStatus.get("finalDecision")
    finalDecisionCode = str(finalDecision.get("status") or "") if isinstance(finalDecision, dict) else ""
    if finalDecisionCode not in IRCC_NON_SUBSTANTIVE_FINAL_DECISION_CODES:
        headlineCode = finalDecisionCode
    elif latestUpdate:
        headlineCode = str(latestUpdate["code"])
    else:
        headlineCode = overallCode

    return {
        "headlineCode": headlineCode,
        "headlineText": formatIrccHeadlineText(headlineCode),
        "tone": getIrccHeadlineTone(headlineCode),
        "overallCode": overallCode,
        "overallText": formatIrccStatusText(overallCode),
        "latestUpdate": latestUpdate,
    }


def formatIrccStatusOverview(snapshot: dict[str, Any]) -> str:
    overview = buildIrccStatusOverview(snapshot)
    headlineCode = overview["headlineCode"]
    overallCode = overview["overallCode"]
    lines = [
        f"当前概括状态：{overview['headlineText']}" + (f"（{headlineCode}）" if headlineCode else ""),
        f"总体状态：{overview['overallText']}" + (f"（{overallCode}）" if overallCode else ""),
    ]
    latestUpdate = overview.get("latestUpdate")
    if latestUpdate:
        lines.append(
            f"Latest update：{latestUpdate['label']} - {latestUpdate['timeStamp']}："
            f"{latestUpdate['text']}（{latestUpdate['code']}）"
        )
    return "\n".join(lines)


def hasIrccHeadlineChanged(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if not previous:
        return False
    return buildIrccStatusOverview(previous)["headlineCode"] != buildIrccStatusOverview(current)["headlineCode"]


def hasIrccIssuedEquivalentHeadlineChanged(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    previousCode = getIrccHeadlineCode(previous)
    currentCode = getIrccHeadlineCode(current)
    return previousCode != currentCode and isIrccIssuedEquivalentCode(currentCode)


def maskTail(value: Any, visible: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= visible:
        return "*" * len(text)
    return f"{'*' * (len(text) - visible)}{text[-visible:]}"


def formatIrccDocumentType(value: Any) -> str:
    code = str(value or "").strip()
    if not code:
        return "-"
    label = IRCC_DOCUMENT_TYPE_LABELS.get(code)
    return f"{label}（{code}）" if label else code


def formatIrccDocumentStatusCode(value: Any) -> str:
    code = str(value or "").strip()
    if not code:
        return "-"
    label = IRCC_DOCUMENT_STATUS_LABELS.get(code)
    return f"{label}（{code}）" if label else code


def formatIrccCountryOfIssue(value: Any) -> str:
    code = str(value or "").strip()
    if not code:
        return "-"
    label = IRCC_COUNTRY_OF_ISSUE_LABELS.get(code)
    return f"{label}（{code}）" if label else code


def formatIrccDocumentNumber(value: Any) -> str:
    text = str(value or "").strip()
    return text or "-"


def normalizeDocumentStatusItems(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def getDocumentStatusMatchKey(item: dict[str, Any], index: int) -> str:
    for key in ("documentNumber", "travelDocumentNumber"):
        value = item.get(key)
        if value:
            return f"{key}:{value}"
    typeValue = item.get("documentType") or "unknown"
    applicantName = item.get("name") or "unknown"
    return f"fallback:{typeValue}:{applicantName}:{index}"


def formatIrccDocumentStatusItem(item: dict[str, Any]) -> str:
    parts = [
        f"文件类型：{formatIrccDocumentType(item.get('documentType'))}",
        f"文件状态：{formatIrccDocumentStatusCode(item.get('documentStatus'))}",
    ]
    if item.get("statusUpdatedDate"):
        parts.append(f"状态更新时间：{item.get('statusUpdatedDate')}")
    if item.get("expiryDate") and str(item.get("showNAExpiryDate") or "").upper() != "Y":
        parts.append(f"过期日期：{item.get('expiryDate')}")
    if item.get("countryOfIssue"):
        parts.append(f"签发国家/地区：{formatIrccCountryOfIssue(item.get('countryOfIssue'))}")
    if item.get("documentNumber"):
        parts.append(f"文件编号：{formatIrccDocumentNumber(item.get('documentNumber'))}")
    if item.get("travelDocumentNumber"):
        parts.append(f"旅行证件号：{formatIrccDocumentNumber(item.get('travelDocumentNumber'))}")
    return "；".join(parts)


def summarizeDocumentStatuses(value: Any) -> list[str]:
    items = normalizeDocumentStatusItems(value)
    return [formatIrccDocumentStatusItem(item) for item in items]


def formatDocumentStatusFieldValue(field: str, value: Any) -> str:
    if field == "documentType":
        return formatIrccDocumentType(value)
    if field == "documentStatus":
        return formatIrccDocumentStatusCode(value)
    if field == "countryOfIssue":
        return formatIrccCountryOfIssue(value)
    if field in {"documentNumber", "travelDocumentNumber"}:
        return formatIrccDocumentNumber(value)
    if value in (None, ""):
        return "-"
    return str(value)


def formatDocumentStatusChanges(previousValue: Any, currentValue: Any) -> list[str]:
    previousItems = normalizeDocumentStatusItems(previousValue)
    currentItems = normalizeDocumentStatusItems(currentValue)
    previousByKey = {
        getDocumentStatusMatchKey(item, index): item
        for index, item in enumerate(previousItems)
    }
    currentByKey = {
        getDocumentStatusMatchKey(item, index): item
        for index, item in enumerate(currentItems)
    }
    fieldLabels = {
        "documentType": "文件类型",
        "documentStatus": "文件状态",
        "expiryDate": "过期日期",
        "statusUpdatedDate": "状态更新时间",
        "travelDocumentNumber": "旅行证件号",
        "countryOfIssue": "签发国家/地区",
        "showNAExpiryDate": "过期日期显示",
        "documentNumber": "文件编号",
    }
    lines: list[str] = []
    for key, currentItem in currentByKey.items():
        previousItem = previousByKey.get(key)
        if previousItem is None:
            lines.append(f"新增文件状态：{formatIrccDocumentStatusItem(currentItem)}。")
            continue
        fieldChanges: list[str] = []
        for field, label in fieldLabels.items():
            if stableHash(previousItem.get(field)) == stableHash(currentItem.get(field)):
                continue
            fieldChanges.append(
                f"{label} 从 {formatDocumentStatusFieldValue(field, previousItem.get(field))} "
                f"变为 {formatDocumentStatusFieldValue(field, currentItem.get(field))}"
            )
        if fieldChanges:
            lines.append(f"文件状态已更新：{'；'.join(fieldChanges)}。")
        elif stableHash(previousItem) != stableHash(currentItem):
            lines.append(f"文件状态已更新：{formatIrccDocumentStatusItem(currentItem)}。")

    for key, previousItem in previousByKey.items():
        if key not in currentByKey:
            lines.append(f"文件状态已移除：{formatIrccDocumentStatusItem(previousItem)}。")

    if not lines and stableHash(previousItems) != stableHash(currentItems):
        lines.append("文件状态已更新。")
    return lines


def formatBiometricChange(previousApplicant: dict[str, Any], currentApplicant: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    previousNumber = previousApplicant.get("biometricNumber")
    currentNumber = currentApplicant.get("biometricNumber")
    if previousNumber != currentNumber:
        if currentNumber:
            tail = maskTail(currentNumber)[-4:]
            action = "已生成" if not previousNumber else "已更新"
            changes.append(f"指纹编号{action}（末 4 位：{tail}）")
        elif previousNumber:
            changes.append("指纹编号已移除")

    previousEnrolmentDate = previousApplicant.get("dateOfBiometricEnrolment")
    currentEnrolmentDate = currentApplicant.get("dateOfBiometricEnrolment")
    if previousEnrolmentDate != currentEnrolmentDate and currentEnrolmentDate:
        changes.append(f"录指纹日期：{currentEnrolmentDate}")

    previousExpiryDate = previousApplicant.get("biometricExpiryDate")
    currentExpiryDate = currentApplicant.get("biometricExpiryDate")
    if previousExpiryDate != currentExpiryDate and currentExpiryDate:
        changes.append(f"指纹有效期至：{currentExpiryDate}")

    return changes


def getApplicantMatchKey(applicant: dict[str, Any], index: int) -> str:
    for key in ("appNumber", "uci", "fullName"):
        value = applicant.get(key)
        if value:
            return f"{key}:{value}"
    return f"index:{index}"


def formatApplicantChanges(previousApplicants: Any, currentApplicants: Any) -> list[str]:
    if not isinstance(previousApplicants, list) or not isinstance(currentApplicants, list):
        return ["申请人信息已更新。"]

    previousByKey = {
        getApplicantMatchKey(applicant, index): applicant
        for index, applicant in enumerate(previousApplicants)
        if isinstance(applicant, dict)
    }
    lines: list[str] = []
    hasGenericChange = len(previousApplicants) != len(currentApplicants)

    for index, currentApplicant in enumerate(currentApplicants):
        if not isinstance(currentApplicant, dict):
            hasGenericChange = True
            continue
        matchKey = getApplicantMatchKey(currentApplicant, index)
        previousApplicant = previousByKey.get(matchKey)
        if previousApplicant is None:
            hasGenericChange = True
            continue
        biometricChanges = formatBiometricChange(previousApplicant, currentApplicant)
        if biometricChanges:
            lines.append(f"申请人信息已更新：{'；'.join(biometricChanges)}。")
        elif stableHash(previousApplicant) != stableHash(currentApplicant):
            hasGenericChange = True

    if hasGenericChange and not lines:
        lines.append("申请人信息已更新。")
    return list(dict.fromkeys(lines))


def sanitizeIrccChangeSummaryForDisplay(summary: str) -> str:
    cleanedLines: list[str] = []
    for rawLine in str(summary or "").splitlines():
        line = rawLine.strip()
        if not line:
            continue
        if IRCC_RAW_APPLICANT_DIFF_PATTERN.search(line):
            cleanedLines.append("申请人信息已更新。")
            continue
        if IRCC_RAW_DOCUMENT_DIFF_PATTERN.search(line):
            cleanedLines.append("文件状态已更新。")
            continue
        cleanedLines.append(IRCC_LEGACY_STATUS_TIME_PATTERN.sub("，IRCC Portal 原始时间：", line))
    return "\n".join(dict.fromkeys(cleanedLines))


def buildIrccDisplayChangeSummary(storedSummary: str, previousSnapshot: dict[str, Any] | None, currentSnapshot: dict[str, Any]) -> str:
    if previousSnapshot:
        return sanitizeIrccChangeSummaryForDisplay(buildChangeSummary(previousSnapshot, currentSnapshot))
    return sanitizeIrccChangeSummaryForDisplay(storedSummary)


def cleanIrccMessageText(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]*>", " ", text)
    replacements = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return " ".join(text.split()).strip()


def getIrccMessageKey(message: dict[str, Any], index: int) -> str:
    messageId = message.get("messageId")
    if messageId:
        return f"id:{messageId}"
    subject = cleanIrccMessageText(message.get("subject") or message.get("attachmentFileName"))
    if subject:
        return f"subject:{subject}"
    return f"index:{index}"


def describeIrccMessage(message: dict[str, Any]) -> str:
    subject = cleanIrccMessageText(message.get("subject") or message.get("attachmentFileName")) or "未命名消息"
    tag = IRCC_MESSAGE_TAG_LABELS.get(str(message.get("messageTag") or ""), str(message.get("messageTag") or "申请消息"))
    timeValue = message.get("updatedDttm") or message.get("createdDttm")
    timePart = f"，时间：{timeValue}" if timeValue else ""
    return f"{subject}（{tag}{timePart}）"


def formatIrccMessageChanges(previousMessages: Any, currentMessages: Any) -> list[str]:
    if not isinstance(previousMessages, list) or not isinstance(currentMessages, list):
        return ["申请消息已更新。"]
    previousByKey = {
        getIrccMessageKey(message, index): message
        for index, message in enumerate(previousMessages)
        if isinstance(message, dict)
    }
    added: list[str] = []
    updated: list[str] = []
    for index, currentMessage in enumerate(currentMessages):
        if not isinstance(currentMessage, dict):
            continue
        key = getIrccMessageKey(currentMessage, index)
        previousMessage = previousByKey.get(key)
        if previousMessage is None:
            added.append(describeIrccMessage(currentMessage))
        elif stableHash(previousMessage) != stableHash(currentMessage):
            updated.append(describeIrccMessage(currentMessage))

    lines: list[str] = []
    if added:
        shown = "；".join(added[:5])
        suffix = f"；另有 {len(added) - 5} 条新增消息" if len(added) > 5 else ""
        lines.append(f"申请消息新增：{shown}{suffix}。")
    if updated:
        shown = "；".join(updated[:5])
        suffix = f"；另有 {len(updated) - 5} 条更新消息" if len(updated) > 5 else ""
        lines.append(f"申请消息更新：{shown}{suffix}。")
    if not lines:
        lines.append(f"申请消息发生变化：{len(previousMessages)} 条 -> {len(currentMessages)} 条。")
    return lines


def normalizeMessage(message: dict[str, Any]) -> dict[str, Any]:
    details = message.get("messageDetails") if isinstance(message.get("messageDetails"), dict) else {}
    attachment = details.get("attachment") if isinstance(details.get("attachment"), dict) else {}
    status = details.get("status") if isinstance(details.get("status"), dict) else {}
    return {
        "messageId": message.get("messageId"),
        "createdDttm": message.get("createdDttm"),
        "updatedDttm": message.get("updatedDttm"),
        "messageTag": details.get("messageTag"),
        "subject": details.get("subject"),
        "attachmentFileName": attachment.get("attachmentFileName"),
        "viewedDate": status.get("viewedDate"),
    }


def normalizeApplicationInfo(applicationList: list[Any], appId: str) -> dict[str, Any]:
    selected = None
    for item in applicationList:
        if isinstance(item, dict) and str(item.get("id")) == str(appId):
            selected = item
            break
    if selected is None and applicationList:
        first = applicationList[0]
        selected = first if isinstance(first, dict) else None
    if not selected:
        return {}
    applicant = selected.get("applicant") if isinstance(selected.get("applicant"), dict) else {}
    updatedDate = selected.get("updatedDate") if isinstance(selected.get("updatedDate"), dict) else {}
    return {
        "id": selected.get("id"),
        "appStatus": selected.get("appStatus"),
        "appRefIdNumber": selected.get("appRefIdNumber"),
        "lineOfBusiness": selected.get("lineOfBusiness"),
        "gcmsActionRequired": selected.get("gcmsActionRequired"),
        "gcmsSubmittedDate": selected.get("gcmsSubmittedDate"),
        "updatedDate": updatedDate,
        "updatedTimestamp": updatedDate.get("timestamp"),
        "applicant": {
            "firstName": applicant.get("firstName"),
            "lastName": applicant.get("lastName"),
            "applicantType": applicant.get("applicantType"),
        },
    }


def normalizeSnapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    appStatus = snapshot.get("appStatus") if isinstance(snapshot.get("appStatus"), dict) else {}
    messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
    applicationInfo = snapshot.get("applicationInfo") if isinstance(snapshot.get("applicationInfo"), dict) else {}
    return {
        "applicationStatus": appStatus.get("applicationStatus"),
        "applicationInfoStatus": applicationInfo.get("appStatus"),
        "homeUpdatedDate": applicationInfo.get("updatedTimestamp") or applicationInfo.get("updatedDate"),
        "eligibility": appStatus.get("eligibility"),
        "medical": appStatus.get("medical"),
        "additionalDocuments": appStatus.get("additionalDocuments"),
        "interviewOrAppointment": appStatus.get("interviewOrAppointment"),
        "biometricInformation": appStatus.get("biometricInformation"),
        "backgroundChecks": appStatus.get("backgroundChecks"),
        "finalDecision": appStatus.get("finalDecision"),
        "profileStatus": appStatus.get("profileStatus"),
        "processingTimeCompleted": appStatus.get("processingTimeCompleted"),
        "percentageCompleted": appStatus.get("percentageCompleted"),
        "estimatedCompletionDate": appStatus.get("estimatedCompletionDate"),
        "estimatedRemainingProcessingTime": appStatus.get("estimatedRemainingProcessingTime"),
        "estimatedRemainingProcessingTimeUnitOfMeasure": appStatus.get("estimatedRemainingProcessingTimeUnitOfMeasure"),
        "processingTimeAvailable": appStatus.get("processingTimeAvailable"),
        "processingTimeBarTitle": appStatus.get("processingTimeBarTitle"),
        "processingTimeBarMessage": appStatus.get("processingTimeBarMessage"),
        "processingTimeExceeded": appStatus.get("processingTimeExceeded"),
        "documentStatus": appStatus.get("documentStatus"),
        "listOfApplicants": appStatus.get("listOfApplicants"),
        "messages": [normalizeMessage(item) for item in messages if isinstance(item, dict)],
    }


def summarizeSnapshot(snapshot: dict[str, Any]) -> str:
    normalized = normalizeSnapshot(snapshot)
    documentStatusLines = summarizeDocumentStatuses(normalized.get("documentStatus"))
    lines = [
        f"总申请状态：{formatIrccValue(normalized.get('applicationStatus'))}",
        f"首页申请状态：{formatIrccValue(normalized.get('applicationInfoStatus'))}",
        f"资格审查：{formatIrccValue(normalized.get('eligibility'))}",
        f"体检结果：{formatIrccValue(normalized.get('medical'))}",
        f"补充文件：{formatIrccValue(normalized.get('additionalDocuments'))}",
        f"面试/预约：{formatIrccValue(normalized.get('interviewOrAppointment'))}",
        f"指纹/生物信息：{formatIrccValue(normalized.get('biometricInformation'))}",
        f"背景调查：{formatIrccValue(normalized.get('backgroundChecks'))}",
        f"最终决定：{formatIrccValue(normalized.get('finalDecision'))}",
        f"处理时间标题：{formatIrccValue(normalized.get('processingTimeBarTitle'))}",
        f"处理时间说明：{formatIrccValue(normalized.get('processingTimeBarMessage'))}",
        f"预计完成日期：{formatIrccValue(normalized.get('estimatedCompletionDate'))}",
        f"预计剩余处理时间：{formatIrccValue(normalized.get('estimatedRemainingProcessingTime'))} {formatIrccValue(normalized.get('estimatedRemainingProcessingTimeUnitOfMeasure'))}",
        f"是否超过处理时间：{formatIrccValue(normalized.get('processingTimeExceeded'))}",
        f"文件状态数量：{len(documentStatusLines)}",
        f"消息数量：{len(normalized.get('messages') or [])}",
    ]
    if documentStatusLines:
        lines.append("文件状态：")
        lines.extend(f"- {line}" for line in documentStatusLines)
    return "\n".join(lines)


def summarizeSnapshotBrief(snapshot: dict[str, Any]) -> str:
    normalized = normalizeSnapshot(snapshot)
    overview = buildIrccStatusOverview(snapshot)
    parts = [
        f"当前概括状态：{overview['headlineText']}（{overview['headlineCode']}）",
        f"总体状态：{overview['overallText']}（{overview['overallCode']}）",
        f"消息：{len(normalized.get('messages') or [])} 条",
    ]
    return " · ".join(parts)


def getChangedSnapshotKeys(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if not previous:
        return []
    previousNormalized = normalizeSnapshot(previous)
    currentNormalized = normalizeSnapshot(current)
    return [
        key
        for key in STATUS_LABELS
        if stableHash(previousNormalized.get(key)) != stableHash(currentNormalized.get(key))
    ]


def classifyIrccChange(previous: dict[str, Any] | None, current: dict[str, Any]) -> str:
    changedKeys = getChangedSnapshotKeys(previous, current)
    if not changedKeys:
        return "initial" if previous is None else "ghost"
    visibleKeys = [key for key in changedKeys if key not in IRCC_GHOST_UPDATE_KEYS]
    if visibleKeys:
        return "visible"
    if changedKeys == ["homeUpdatedDate"]:
        return "home_ghost"
    return "ghost"


def irccEmailSubjectAction(changeType: str) -> str:
    if changeType == "home_ghost":
        return "检测到首页 Ghost update"
    if changeType == "ghost":
        return "检测到 Ghost update"
    return "申请状态发生变化"


def irccEmailIntro(changeType: str) -> str:
    if changeType == "home_ghost":
        return "IRCC Portal Alpha 监控检测到首页 Ghost update：首页 submitted applications 更新时间变化，但详情页暂无可见变化。"
    if changeType == "ghost":
        return "IRCC Portal Alpha 监控检测到 Ghost update：后台更新时间变化，但暂无明确可见状态变化。"
    return "IRCC Portal Alpha 监控检测到申请信息变化。"


def buildChangeSummary(previous: dict[str, Any] | None, current: dict[str, Any]) -> str:
    if not previous:
        return "首次记录 IRCC Portal 快照。"
    previousNormalized = normalizeSnapshot(previous)
    currentNormalized = normalizeSnapshot(current)
    changedKeys = getChangedSnapshotKeys(previous, current)
    if changedKeys == ["homeUpdatedDate"]:
        return (
            f"首页 Ghost update：首页 submitted applications 更新时间从 {previousNormalized.get('homeUpdatedDate') or '-'} "
            f"变为 {currentNormalized.get('homeUpdatedDate') or '-'}；详情页暂无可见变化。"
        )
    changes: list[str] = []
    for key, label in STATUS_LABELS.items():
        previousValue = previousNormalized.get(key)
        currentValue = currentNormalized.get(key)
        if stableHash(previousValue) == stableHash(currentValue):
            continue
        if key == "homeUpdatedDate":
            changes.append(f"首页 Ghost update：首页 submitted applications 更新时间从 {previousValue or '-'} 变为 {currentValue or '-'}。")
        elif key == "messages":
            previousMessages = previousValue or []
            currentMessages = currentValue or []
            changes.extend(formatIrccMessageChanges(previousMessages, currentMessages))
        elif key == "listOfApplicants":
            changes.extend(formatApplicantChanges(previousValue, currentValue))
        elif key == "documentStatus":
            changes.extend(formatDocumentStatusChanges(previousValue, currentValue))
        else:
            changes.append(f"{label} 发生变化：{formatIrccValue(previousValue)} -> {formatIrccValue(currentValue)}。")
    return "\n".join(changes[:20]) if changes else "后台 Ghost update：快照发生变化，但七项状态、申请消息和申请人信息暂无可见变化。"


def hashSha256(value: bytes | str) -> bytes:
    raw = value.encode() if isinstance(value, str) else value
    # AWS Cognito SRP 要求对登录挑战参数做 SHA-256 协议计算；这里不是密码存储。
    return hashlib.sha256(raw).digest()  # lgtm[py/weak-sensitive-data-hashing]


def hexHash(value: bytes | str) -> int:
    return int(hashSha256(value).hex(), 16)


def padHex(value: int) -> str:
    hexValue = f"{value:x}"
    if len(hexValue) % 2 == 1:
        hexValue = f"0{hexValue}"
    if hexValue[0] in "89ABCDEFabcdef":
        hexValue = f"00{hexValue}"
    return hexValue


def computeHkdf(ikm: bytes, salt: bytes) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    infoBits = b"Caldera Derived Key" + b"\x01"
    return hmac.new(prk, infoBits, hashlib.sha256).digest()[:16]


def cognitoTimestamp() -> str:
    now = datetime.now(UTC)
    weekDays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{weekDays[now.weekday()]} {months[now.month - 1]} {now.day} {now:%H:%M:%S} UTC {now.year}"


def cognitoRequest(payload: dict[str, Any], target: str = "AWSCognitoIdentityProviderService.InitiateAuth") -> dict[str, Any]:
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": target,
    }
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = client.post(COGNITO_ENDPOINT, headers=headers, json=payload)
    try:
        data = response.json()
    except ValueError as exc:
        raise IrccAuthenticationError(f"IRCC 登录服务返回非 JSON：HTTP {response.status_code}") from exc
    if response.status_code >= 400:
        message = data.get("message") or data.get("__type") or f"HTTP {response.status_code}"
        raise IrccAuthenticationError(f"IRCC 登录失败：{message}")
    return data


def loginWithSrp(portalEmail: str, portalPassword: str) -> dict[str, Any]:
    smallA = int.from_bytes(stdlibSecrets.token_bytes(128), "big")
    largeA = pow(COGNITO_G, smallA, COGNITO_N)
    if largeA % COGNITO_N == 0:
        raise IrccAuthenticationError("IRCC SRP 参数生成失败，请重试。")
    auth = cognitoRequest(
        {
            "AuthFlow": "USER_SRP_AUTH",
            "ClientId": COGNITO_CLIENT_ID,
            "AuthParameters": {
                "USERNAME": portalEmail,
                "SRP_A": f"{largeA:x}",
            },
            "ClientMetadata": {},
        },
    )
    if auth.get("ChallengeName") != "PASSWORD_VERIFIER":
        return buildTokenCacheFromAuthResult(auth)
    challenge = auth.get("ChallengeParameters") if isinstance(auth.get("ChallengeParameters"), dict) else {}
    userIdForSrp = str(challenge.get("USER_ID_FOR_SRP") or portalEmail)
    saltHex = str(challenge.get("SALT") or "")
    srpBHex = str(challenge.get("SRP_B") or "")
    secretBlock = str(challenge.get("SECRET_BLOCK") or "")
    if not saltHex or not srpBHex or not secretBlock:
        raise IrccAuthenticationError("IRCC SRP 登录缺少挑战参数。")
    salt = int(saltHex, 16)
    largeB = int(srpBHex, 16)
    if largeB % COGNITO_N == 0:
        raise IrccAuthenticationError("IRCC SRP 服务端参数无效。")
    k = hexHash(bytes.fromhex(padHex(COGNITO_N) + padHex(COGNITO_G)))
    uValue = hexHash(bytes.fromhex(padHex(largeA) + padHex(largeB)))
    if uValue == 0:
        raise IrccAuthenticationError("IRCC SRP 随机扰码无效，请重试。")
    userPasswordHash = hashSha256(f"{COGNITO_POOL_NAME}{userIdForSrp}:{portalPassword}")
    xValue = hexHash(bytes.fromhex(padHex(salt)) + userPasswordHash)
    sValue = pow((largeB - k * pow(COGNITO_G, xValue, COGNITO_N)) % COGNITO_N, smallA + uValue * xValue, COGNITO_N)
    hkdf = computeHkdf(bytes.fromhex(padHex(sValue)), bytes.fromhex(padHex(uValue)))
    timestamp = cognitoTimestamp()
    signatureMessage = COGNITO_POOL_NAME.encode() + userIdForSrp.encode() + b64decode(secretBlock) + timestamp.encode()
    signature = b64encode(hmac.new(hkdf, signatureMessage, hashlib.sha256).digest()).decode()
    response = cognitoRequest(
        {
            "ChallengeName": "PASSWORD_VERIFIER",
            "ClientId": COGNITO_CLIENT_ID,
            "Session": auth.get("Session"),
            "ChallengeResponses": {
                "USERNAME": userIdForSrp,
                "PASSWORD_CLAIM_SECRET_BLOCK": secretBlock,
                "TIMESTAMP": timestamp,
                "PASSWORD_CLAIM_SIGNATURE": signature,
            },
            "ClientMetadata": {},
        },
        target="AWSCognitoIdentityProviderService.RespondToAuthChallenge",
    )
    return buildTokenCacheFromAuthResult(response)


def buildTokenCacheFromAuthResult(result: dict[str, Any]) -> dict[str, Any]:
    authResult = result.get("AuthenticationResult") if isinstance(result.get("AuthenticationResult"), dict) else {}
    if not authResult:
        challenge = str(result.get("ChallengeName") or "")
        if challenge:
            raise IrccAuthenticationError(f"IRCC 登录需要额外验证（{challenge}），Alpha 暂不支持自动处理 MFA。")
        raise IrccAuthenticationError("IRCC 登录未返回 token")
    expiresIn = int(authResult.get("ExpiresIn") or 3600)
    expiresAt = (datetime.now(UTC) + timedelta(seconds=max(60, expiresIn - 60))).replace(microsecond=0).isoformat()
    return {
        "idToken": authResult.get("IdToken"),
        "accessToken": authResult.get("AccessToken"),
        "refreshToken": authResult.get("RefreshToken"),
        "expiresAt": expiresAt,
    }


def loginWithPassword(portalEmail: str, portalPassword: str) -> dict[str, Any]:
    return loginWithSrp(portalEmail, portalPassword)


def refreshTokenCache(tokenCache: dict[str, Any]) -> dict[str, Any]:
    refreshToken = tokenCache.get("refreshToken")
    if not refreshToken:
        raise IrccAuthenticationError("IRCC token 已失效，需要重新登录。")
    result = cognitoRequest(
        {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": COGNITO_CLIENT_ID,
            "AuthParameters": {"REFRESH_TOKEN": refreshToken},
            "ClientMetadata": {},
        },
    )
    nextCache = buildTokenCacheFromAuthResult(result)
    nextCache["refreshToken"] = refreshToken
    return nextCache


def tokenCacheExpired(tokenCache: dict[str, Any]) -> bool:
    expiresAt = str(tokenCache.get("expiresAt") or "")
    if not expiresAt:
        return True
    try:
        parsed = datetime.fromisoformat(expiresAt)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) <= datetime.now(UTC)


def getAuthorizedToken(account: dict[str, Any]) -> dict[str, Any]:
    tokenJson = decryptIfNeeded(account.get("token_cache_encrypted") or "") or ""
    tokenCache = json.loads(tokenJson) if tokenJson else {}
    try:
        if tokenCache and not tokenCacheExpired(tokenCache):
            return tokenCache
        if tokenCache.get("refreshToken"):
            return refreshTokenCache(tokenCache)
    except Exception:
        pass
    email = decryptIfNeeded(account["portal_email_encrypted"]) or ""
    password = decryptIfNeeded(account["portal_password_encrypted"]) or ""
    return loginWithPassword(email, password)


def irccHeaders(tokenCache: dict[str, Any]) -> dict[str, str]:
    token = tokenCache.get("idToken") or tokenCache.get("accessToken")
    if not token:
        raise IrccAuthenticationError("IRCC token 为空，需要重新登录。")
    return {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Origin": IRCC_PORTAL_URL,
        "Referer": f"{IRCC_PORTAL_URL}/home?lang=en",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }


def buildIrccApiUrl(path: str) -> str:
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise ValueError("Unexpected IRCC API request path")
    url = f"{IRCC_API_BASE_URL}{path}"
    parsed = urlparse(url)
    baseParsed = urlparse(IRCC_API_BASE_URL)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != baseParsed.netloc.lower()
        or not parsed.path.startswith(f"{baseParsed.path}/")
    ):
        raise ValueError("Unexpected IRCC API request target")
    return url


def apiGet(path: str, tokenCache: dict[str, Any], *, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = client.get(buildIrccApiUrl(path), headers=irccHeaders(tokenCache), params=params)
    if response.status_code == 401:
        raise IrccAuthenticationError(f"IRCC API 鉴权失败：HTTP {response.status_code}")
    if response.status_code == 403:
        raise RuntimeError("IRCC API 当前返回 HTTP 403，可能是官网维护、临时拦截或服务异常，请稍后重试。")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"IRCC API 返回非 JSON：HTTP {response.status_code}") from exc


def fetchSubmittedApplications(tokenCache: dict[str, Any]) -> list[dict[str, Any]]:
    data = apiGet(
        "/applicationInfo",
        tokenCache,
        params={
            "appStatus": "SUBMITTED",
            "pageSize": 50,
            "pageIndex": 0,
            "sortBy": "UPDATED_DATE",
            "sortOrder": "DESC",
        },
    )
    applications = data.get("applicationList") if isinstance(data, dict) else []
    return [item for item in applications if isinstance(item, dict)]


def fetchIrccSnapshot(appId: str, tokenCache: dict[str, Any]) -> dict[str, Any]:
    submitted = apiGet(
        "/applicationInfo",
        tokenCache,
        params={
            "appStatus": "SUBMITTED",
            "pageSize": 50,
            "pageIndex": 0,
            "sortBy": "UPDATED_DATE",
            "sortOrder": "DESC",
        },
    )
    applicationList = submitted.get("applicationList") if isinstance(submitted, dict) else []
    appStatus = apiGet("/appStatus", tokenCache, params={"appId": appId})
    messages = apiGet(
        "/messages",
        tokenCache,
        params={"messageRefType": "Application", "messageRefId": appId, "messageType": "Online"},
    )
    return {
        "applicationInfo": normalizeApplicationInfo(applicationList if isinstance(applicationList, list) else [], appId),
        "appStatus": appStatus if isinstance(appStatus, dict) else {},
        "messages": messages if isinstance(messages, list) else [],
    }


def normalizeDiscoveredApplication(item: dict[str, Any]) -> dict[str, Any]:
    applicant = item.get("applicant") if isinstance(item.get("applicant"), dict) else {}
    firstName = str(applicant.get("firstName") or "").strip()
    lastName = str(applicant.get("lastName") or "").strip()
    return {
        "appId": str(item.get("id") or ""),
        "applicationNumber": str(item.get("appRefIdNumber") or ""),
        "principalApplicant": " ".join(part for part in [firstName, lastName] if part),
        "status": str(item.get("appStatus") or ""),
        "submittedAt": str(item.get("gcmsSubmittedDate") or ""),
        "raw": item,
    }


def upsertIrccAccount(userId: int, portalEmail: str, portalPassword: str, tokenCache: dict[str, Any] | None = None) -> int:
    now = utcNowIso()
    normalizedEmail = portalEmail.strip().lower()
    with getConnection() as connection:
        accountRows = connection.execute("SELECT * FROM ircc_portal_accounts WHERE user_id = ?", (userId,)).fetchall()
        existing = None
        for row in accountRows:
            if (decryptIfNeeded(row["portal_email_encrypted"]) or "").lower() == normalizedEmail:
                existing = row
                break
        if existing:
            connection.execute(
                """
                UPDATE ircc_portal_accounts
                SET portal_password_encrypted = ?,
                    token_cache_encrypted = ?,
                    auth_status = 'ok',
                    last_auth_error = '',
                    last_authenticated_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    encryptSecret(portalPassword),
                    encryptSecret(json.dumps(tokenCache or {}, ensure_ascii=False)),
                    now if tokenCache else existing.get("last_authenticated_at"),
                    now,
                    existing["id"],
                ),
            )
            return int(existing["id"])
        cursor = connection.execute(
            """
            INSERT INTO ircc_portal_accounts (
                user_id, portal_email_encrypted, portal_password_encrypted, token_cache_encrypted,
                auth_status, last_auth_error, last_authenticated_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'ok', '', ?, ?, ?)
            """,
            (
                userId,
                encryptSecret(normalizedEmail),
                encryptSecret(portalPassword),
                encryptSecret(json.dumps(tokenCache or {}, ensure_ascii=False)),
                now if tokenCache else None,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)


def updateAccountAuthState(accountId: int, tokenCache: dict[str, Any] | None = None, errorMessage: str = "") -> None:
    now = utcNowIso()
    with getConnection() as connection:
        if errorMessage:
            connection.execute(
                """
                UPDATE ircc_portal_accounts
                SET auth_status = 'error', last_auth_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (errorMessage[:500], now, accountId),
            )
        else:
            connection.execute(
                """
                UPDATE ircc_portal_accounts
                SET auth_status = 'ok', last_auth_error = '', token_cache_encrypted = ?,
                    last_authenticated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (encryptSecret(json.dumps(tokenCache or {}, ensure_ascii=False)), now, now, accountId),
            )


def discoverIrccApplications(userId: int, payload: IrccDiscoverRequest) -> dict[str, Any]:
    tokenCache = loginWithPassword(str(payload.portalEmail).lower(), payload.portalPassword)
    accountId = upsertIrccAccount(userId, str(payload.portalEmail), payload.portalPassword, tokenCache)
    applications = [normalizeDiscoveredApplication(item) for item in fetchSubmittedApplications(tokenCache)]
    updateAccountAuthState(accountId, tokenCache)
    return {"accountId": accountId, "applications": applications}


def normalizeIrccCaseRow(row: dict[str, Any]) -> dict[str, Any]:
    email = decryptIfNeeded(row.get("portal_email_encrypted")) or ""
    rawPayload = decryptIfNeeded(row.get("latest_raw_payload") or "") or ""
    latestSnapshot = json.loads(rawPayload) if rawPayload else None
    lastSummary = summarizeSnapshotBrief(latestSnapshot) if latestSnapshot else (row.get("last_summary") or "")
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "displayName": row["display_name"],
        "portalEmailMasked": maskEmail(email),
        "appId": row["app_id"],
        "applicationNumber": row["application_number"],
        "principalApplicant": row["principal_applicant"],
        "receiveEmail": decryptIfNeeded(row["receive_email"]) or "",
        "senderMode": row["sender_mode"],
        "isEnabled": bool(row["is_enabled"]),
        "emailNotificationsEnabled": bool(row["email_notifications_enabled"]),
        "sortOrder": int(row.get("sort_order") or 0),
        "nextCheckAt": row["next_check_at"],
        "lastCheckedAt": row["last_checked_at"],
        "lastTriggerType": row.get("last_trigger_type"),
        "lastSnapshotHash": row.get("last_snapshot_hash") or "",
        "lastSummary": lastSummary,
        "lastErrorMessage": row.get("last_error_message") or "",
        "latestSnapshot": latestSnapshot,
        "statusOverview": buildIrccStatusOverview(latestSnapshot) if latestSnapshot else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def listIrccCases(userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if userId is not None:
        where = "WHERE c.user_id = ?"
        params = (userId,)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT c.*, a.portal_email_encrypted,
                   (
                       SELECT h.raw_payload
                       FROM ircc_status_history h
                       WHERE h.case_id = c.id
                       ORDER BY h.id DESC
                       LIMIT 1
                   ) AS latest_raw_payload
            FROM ircc_cases c
            JOIN ircc_portal_accounts a ON a.id = c.account_id
            {where}
            ORDER BY c.sort_order ASC, c.updated_at DESC, c.id DESC
            """,
            params,
        ).fetchall()
    return [normalizeIrccCaseRow(row) for row in rows]


def getIrccCase(caseId: int, userId: int | None = None) -> dict[str, Any] | None:
    params: tuple[Any, ...] = (caseId,)
    extraWhere = ""
    if userId is not None:
        extraWhere = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT c.*, a.portal_email_encrypted,
                   (
                       SELECT h.raw_payload
                       FROM ircc_status_history h
                       WHERE h.case_id = c.id
                       ORDER BY h.id DESC
                       LIMIT 1
                   ) AS latest_raw_payload
            FROM ircc_cases c
            JOIN ircc_portal_accounts a ON a.id = c.account_id
            WHERE c.id = ? {extraWhere}
            """,
            params,
        ).fetchone()
    return normalizeIrccCaseRow(row) if row else None


def countUserProfiles(connection: Any, userId: int) -> int:
    ceacRow = connection.execute("SELECT COUNT(*) AS case_count FROM ceac_cases WHERE user_id = ?", (userId,)).fetchone()
    irccRow = connection.execute("SELECT COUNT(*) AS case_count FROM ircc_cases WHERE user_id = ?", (userId,)).fetchone()
    koreaRow = connection.execute("SELECT COUNT(*) AS case_count FROM korea_cases WHERE user_id = ?", (userId,)).fetchone()
    return (
        int(ceacRow["case_count"] if ceacRow else 0)
        + int(irccRow["case_count"] if irccRow else 0)
        + int(koreaRow["case_count"] if koreaRow else 0)
    )


def createIrccCase(userId: int, payload: IrccCaseInput) -> dict[str, Any]:
    now = utcNowIso()
    if payload.emailNotificationsEnabled and not payload.receiveEmail:
        raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
    tokenCache = loginWithPassword(str(payload.portalEmail).lower(), payload.portalPassword)
    accountId = upsertIrccAccount(userId, str(payload.portalEmail), payload.portalPassword, tokenCache)
    with getConnection() as connection:
        user = connection.execute("SELECT role, account_tier FROM users WHERE id = ?", (userId,)).fetchone()
        if not user:
            raise ValueError("用户不存在")
        if user.get("role") != "admin":
            profileLimit = PREMIUM_CASE_LIMIT if user.get("account_tier") == "premium" else STANDARD_CASE_LIMIT
            if countUserProfiles(connection, userId) >= profileLimit:
                raise ValueError(f"当前账号最多可添加 {profileLimit} 个档案，请联系管理员升级账号。")
        duplicate = connection.execute("SELECT id FROM ircc_cases WHERE user_id = ? AND app_id = ?", (userId, payload.appId)).fetchone()
        if duplicate:
            raise ValueError("该 IRCC 申请已经存在。")
        upsertSmtpConfig(connection, userId, payload.smtpConfig)
        cursor = connection.execute(
            """
            INSERT INTO ircc_cases (
                user_id, account_id, display_name, app_id, application_number, principal_applicant,
                receive_email, sender_mode, is_enabled, email_notifications_enabled,
                sort_order, next_check_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                userId,
                accountId,
                payload.displayName,
                payload.appId,
                payload.applicationNumber or "",
                payload.principalApplicant or "",
                encryptSecret(str(payload.receiveEmail or "")),
                payload.senderMode,
                int(payload.isEnabled),
                int(payload.emailNotificationsEnabled),
                nextProfileSortOrder(connection, userId),
                computeNextIrccCheckAt() if payload.isEnabled else None,
                now,
                now,
            ),
        )
        connection.execute("UPDATE users SET has_application_profile_history = 1, updated_at = ? WHERE id = ?", (now, userId))
    updateAccountAuthState(accountId, tokenCache)
    case = getIrccCase(int(cursor.lastrowid), userId)
    if case is None:
        raise RuntimeError("创建 IRCC 档案失败")
    return case


def patchIrccCase(caseId: int, userId: int, payload: IrccCasePatch) -> dict[str, Any] | None:
    current = getIrccCase(caseId, userId)
    if not current:
        return None
    data = payload.model_dump(exclude_unset=True)
    nextEmailNotificationsEnabled = data.get("emailNotificationsEnabled", current.get("emailNotificationsEnabled"))
    nextReceiveEmail = data.get("receiveEmail", current.get("receiveEmail"))
    if nextEmailNotificationsEnabled and not nextReceiveEmail:
        raise ValueError("开启邮件推送时必须填写接收提醒邮箱。")
    now = utcNowIso()
    with getConnection() as connection:
        row = connection.execute("SELECT * FROM ircc_cases WHERE id = ? AND user_id = ?", (caseId, userId)).fetchone()
        if not row:
            return None
        accountId = int(row["account_id"])
        if payload.smtpConfig:
            upsertSmtpConfig(connection, userId, payload.smtpConfig)
        if data.get("portalEmail") and data.get("portalPassword"):
            tokenCache = loginWithPassword(str(data["portalEmail"]).lower(), str(data["portalPassword"]))
            accountId = upsertIrccAccount(userId, str(data["portalEmail"]), str(data["portalPassword"]), tokenCache)
        assignments: list[str] = []
        values: list[Any] = []
        columnMap = {
            "displayName": "display_name",
            "appId": "app_id",
            "applicationNumber": "application_number",
            "principalApplicant": "principal_applicant",
            "receiveEmail": "receive_email",
            "senderMode": "sender_mode",
            "isEnabled": "is_enabled",
            "emailNotificationsEnabled": "email_notifications_enabled",
        }
        if accountId != int(row["account_id"]):
            assignments.append("account_id = ?")
            values.append(accountId)
        for key, column in columnMap.items():
            if key not in data:
                continue
            value = data[key]
            if key == "receiveEmail" and value is not None:
                value = encryptSecret(str(value))
            if key == "isEnabled":
                value = int(value)
                assignments.append("next_check_at = ?")
                values.append(computeNextIrccCheckAt() if value else None)
            if key == "emailNotificationsEnabled":
                value = int(value)
            assignments.append(f"{column} = ?")
            values.append(value)
        if not assignments:
            return getIrccCase(caseId, userId)
        assignments.append("updated_at = ?")
        values.extend([now, caseId, userId])
        connection.execute(f"UPDATE ircc_cases SET {', '.join(assignments)} WHERE id = ? AND user_id = ?", tuple(values))
        if data.get("isEnabled") is False:
            connection.execute(
                """
                DELETE FROM ircc_query_jobs
                WHERE case_id = ?
                  AND trigger_type = 'ircc_automatic'
                  AND status = 'queued'
                """,
                (caseId,),
            )
    return getIrccCase(caseId, userId)


def deleteIrccCase(caseId: int, userId: int) -> bool:
    with getConnection() as connection:
        cursor = connection.execute("DELETE FROM ircc_cases WHERE id = ? AND user_id = ?", (caseId, userId))
        return cursor.rowcount > 0


def sendIrccNotification(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    subject: str,
    body: str,
    connection: Any | None = None,
    *,
    includeSupport: bool = False,
) -> None:
    config = None
    if case["sender_mode"] == "custom" and smtpConfig:
        config = {
            "fromEmail": smtpConfig["from_email"],
            "password": decryptSecret(smtpConfig["password_encrypted"]),
            "host": smtpConfig["host"],
            "port": int(smtpConfig["port"]),
            "useSsl": bool(smtpConfig["use_ssl"]),
        }
    else:
        systemConfig = getSystemSmtpConfig()
        config = {
            "fromEmail": systemConfig["fromEmail"],
            "password": systemConfig["password"],
            "host": systemConfig["host"],
            "port": int(systemConfig["port"]),
            "useSsl": bool(systemConfig["useSsl"]),
        }
    if not config["fromEmail"] or not config["password"]:
        print("[mail] IRCC email is not configured.")
        return
    inlineImages = {SUPPORT_IMAGE_CONTENT_ID: getSupportImagePath()} if includeSupport else None
    plainBody = body + (buildSupportFooterPlain() if includeSupport else "")
    htmlBody = buildEmailHtml(body, includeSupport=includeSupport)
    sendEmail(
        fromEmail=config["fromEmail"],
        toEmail=case["receive_email"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        useSsl=config["useSsl"],
        subject=subject,
        body=plainBody,
        htmlBody=htmlBody,
        inlineImages=inlineImages,
    )
    recordEmailDelivery(
        userId=int(case["user_id"]),
        caseId=None,
        emailType="ircc_status",
        recipient=case["receive_email"],
        subject=subject,
        body=plainBody,
        connection=connection,
    )


def sendIrccIssuedAutoStopNotification(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    issuedAt: str,
    connection: Any | None = None,
) -> None:
    subject = f"[IRCC Alpha] {case['application_number'] or case['app_id']} 已自动停止查询"
    issuedTime = formatCaseEmailTime(case, issuedAt, connection)
    body = "\n".join(
        [
            "IRCC Portal Alpha 监控检测到该申请已保持获批状态一段时间。",
            "",
            f"档案：{case['display_name']}",
            f"Application number：{case['application_number'] or '-'}",
            f"appId：{case['app_id']}",
            f"申请人：{case['principal_applicant'] or '-'}",
            "当前概括状态：已获批（FD2）",
            f"首次记录 FD2 时间：{issuedTime}",
            "",
            "该档案进入 FD2 已超过一周，且你尚未在站内停止自动查询。",
            "系统已按策略自动关闭该 IRCC 档案的自动查询，避免继续请求 IRCC Portal。",
            "你仍然可以登录网站，在档案详情页手动执行立即查询。",
        ],
    )
    sendIrccNotification(case, smtpConfig, subject, body, connection, includeSupport=True)


def getFirstIrccIssuedEquivalentAt(caseId: int) -> datetime | None:
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT raw_payload, fetched_at
            FROM ircc_status_history
            WHERE case_id = ?
            ORDER BY fetched_at ASC, id ASC
            """,
            (caseId,),
        ).fetchall()
    for row in rows:
        try:
            snapshot = json.loads(decryptIfNeeded(row["raw_payload"]) or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isIrccIssuedEquivalentCode(getIrccHeadlineCode(snapshot)):
            return parseIrccIso(str(row["fetched_at"]))
    return None


def stopIrccIssuedEquivalentCaseIfExpired(caseId: int, now: datetime, issuedAt: datetime | None = None) -> bool:
    with getConnection() as connection:
        case = connection.execute(
            """
            SELECT c.*, a.portal_email_encrypted
            FROM ircc_cases c
            JOIN ircc_portal_accounts a ON a.id = c.account_id
            WHERE c.id = ? AND c.is_enabled = 1
            """,
            (caseId,),
        ).fetchone()
        if not case:
            return False
        latest = connection.execute(
            """
            SELECT raw_payload
            FROM ircc_status_history
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
        if not latest:
            return False
        try:
            snapshot = json.loads(decryptIfNeeded(latest["raw_payload"]) or "{}")
        except (json.JSONDecodeError, TypeError):
            return False
        if not isIrccIssuedEquivalentCode(getIrccHeadlineCode(snapshot)):
            return False
        issuedAt = issuedAt or getFirstIrccIssuedEquivalentAt(caseId)
        if not issuedAt or now - issuedAt < timedelta(days=7):
            return False
        connection.execute(
            """
            UPDATE ircc_cases
            SET is_enabled = 0, next_check_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now.isoformat(), caseId),
        )
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (case["user_id"],)).fetchone()

    caseDict = dict(case)
    caseDict["receive_email"] = decryptIfNeeded(caseDict["receive_email"]) or ""
    try:
        sendIrccIssuedAutoStopNotification(caseDict, smtpConfig, issuedAt.isoformat())
    except Exception as exc:
        print(f"[scheduler] IRCC FD2 auto-stop notification failed for case {caseId}: {exc}")
    return True


def handleIrccIssuedEquivalentDueCase(caseId: int, now: datetime) -> bool:
    issuedAt = getFirstIrccIssuedEquivalentAt(caseId)
    if not issuedAt:
        return False
    if now - issuedAt >= timedelta(days=7):
        return stopIrccIssuedEquivalentCaseIfExpired(caseId, now, issuedAt)
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE ircc_cases
            SET next_check_at = ?, updated_at = ?
            WHERE id = ? AND is_enabled = 1
            """,
            (computeNextIrccCheckAt(now, "FD2"), now.isoformat(), caseId),
        )
    return True


def runIrccCaseQuery(caseId: int, triggerType: str = "ircc_automatic") -> dict[str, Any]:
    started = datetime.now(UTC)
    startedIso = started.replace(microsecond=0).isoformat()
    success = False
    changed = False
    notificationSent = False
    errorMessage = ""
    snapshot: dict[str, Any] = {}
    changeSummary = ""
    changeType = "unknown"
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT c.*, a.portal_email_encrypted, a.portal_password_encrypted, a.token_cache_encrypted
            FROM ircc_cases c
            JOIN ircc_portal_accounts a ON a.id = c.account_id
            WHERE c.id = ?
            """,
            (caseId,),
        ).fetchone()
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone() if row else None
        previous = connection.execute(
            """
            SELECT raw_payload
            FROM ircc_status_history
            WHERE case_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
    if not row:
        raise RuntimeError("IRCC 档案不存在")
    case = dict(row)
    case["receive_email"] = decryptIfNeeded(case["receive_email"]) or ""
    try:
        tokenCache = getAuthorizedToken(row)
        updateAccountAuthState(int(row["account_id"]), tokenCache)
        snapshot = fetchIrccSnapshot(str(row["app_id"]), tokenCache)
        snapshotHash = stableHash(normalizeSnapshot(snapshot))
        previousSnapshot = json.loads(decryptIfNeeded(previous["raw_payload"]) or "{}") if previous else None
        previousSnapshotHash = stableHash(normalizeSnapshot(previousSnapshot)) if previousSnapshot else ""
        changed = previous is None or previousSnapshotHash != snapshotHash
        changeSummary = buildChangeSummary(previousSnapshot, snapshot)
        changeType = classifyIrccChange(previousSnapshot, snapshot)
        success = True
    except IrccAuthenticationError as exc:
        errorMessage = str(exc)
        updateAccountAuthState(int(row["account_id"]), errorMessage=errorMessage)
    except Exception as exc:
        errorMessage = str(exc)

    finished = datetime.now(UTC)
    finishedIso = finished.replace(microsecond=0).isoformat()
    durationMs = int((finished - started).total_seconds() * 1000)
    with getConnection() as connection:
        currentCaseRow = connection.execute("SELECT is_enabled, email_notifications_enabled FROM ircc_cases WHERE id = ?", (caseId,)).fetchone()
        isEnabledNow = bool(currentCaseRow["is_enabled"]) if currentCaseRow else False
        emailNotificationsEnabledNow = bool(currentCaseRow["email_notifications_enabled"]) if currentCaseRow else False
        if success:
            snapshotHash = stableHash(normalizeSnapshot(snapshot))
            normalized = normalizeSnapshot(snapshot)
            messageCount = len(normalized.get("messages") or [])
            if changed:
                shouldNotify = previous is not None and emailNotificationsEnabledNow
                if shouldNotify:
                    try:
                        emailTimezone = getUserEmailTimezone(int(row["user_id"]), connection)
                        queryTime = formatEmailTime(finishedIso, emailTimezone)
                        emailChangeSummary = formatEmailTextTimes(sanitizeIrccChangeSummaryForDisplay(changeSummary), emailTimezone)
                        overview = buildIrccStatusOverview(snapshot)
                        subjectAction = (
                            f"当前概括状态：{overview['headlineText']}"
                            if hasIrccHeadlineChanged(previousSnapshot, snapshot)
                            else irccEmailSubjectAction(changeType)
                        )
                        includeSupport = hasIrccIssuedEquivalentHeadlineChanged(previousSnapshot, snapshot)
                        subject = f"[IRCC Alpha] {row['application_number'] or row['app_id']} {subjectAction}"
                        body = "\n".join(
                            [
                                irccEmailIntro(changeType),
                                "提示：该功能仍处于 Alpha，结果依赖 IRCC Portal，可能因为官网变化而延迟或失败。",
                                "",
                                f"档案：{row['display_name']}",
                                f"Application number：{row['application_number'] or '-'}",
                                f"appId：{row['app_id']}",
                                f"申请人：{row['principal_applicant'] or '-'}",
                                f"查询时间：{queryTime}",
                                "",
                                "状态概览：",
                                formatEmailTextTimes(formatIrccStatusOverview(snapshot), emailTimezone),
                                "",
                                "变化摘要：",
                                emailChangeSummary,
                                "",
                                "当前状态详情：",
                                formatEmailTextTimes(summarizeSnapshot(snapshot), emailTimezone),
                            ],
                        )
                        sendIrccNotification(case, smtpConfig, subject, body, connection, includeSupport=includeSupport)
                        notificationSent = True
                    except Exception as exc:
                        errorMessage = f"Notification failed: {exc}"
                connection.execute(
                    """
                    INSERT INTO ircc_status_history (
                        case_id, snapshot_hash, application_status, application_info_status,
                        message_count, change_summary, fetched_at, raw_payload, notification_sent
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        caseId,
                        snapshotHash,
                        str(normalized.get("applicationStatus") or ""),
                        str(normalized.get("applicationInfoStatus") or ""),
                        messageCount,
                        changeSummary,
                        finishedIso,
                        encryptSecret(json.dumps(snapshot, ensure_ascii=False, default=str)),
                        int(notificationSent),
                    ),
                )
            connection.execute(
                """
                UPDATE ircc_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_trigger_type = ?,
                    last_snapshot_hash = ?,
                    last_summary = ?,
                    last_error_message = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    finishedIso,
                    computeNextIrccCheckAt(finished, getIrccHeadlineCode(snapshot)) if isEnabledNow else None,
                    triggerType,
                    snapshotHash,
                    summarizeSnapshotBrief(snapshot),
                    finishedIso,
                    caseId,
                ),
            )
        else:
            stopAuto = shouldStopIrccAutomaticQuery(errorMessage)
            connection.execute(
                """
                UPDATE ircc_cases
                SET last_checked_at = ?,
                    next_check_at = ?,
                    last_trigger_type = ?,
                    is_enabled = CASE WHEN ? THEN 0 ELSE is_enabled END,
                    last_error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    finishedIso,
                    None if (stopAuto or not isEnabledNow) else computeNextIrccCheckAt(finished),
                    triggerType,
                    int(stopAuto),
                    errorMessage,
                    finishedIso,
                    caseId,
                ),
            )
        connection.execute(
            """
            INSERT INTO ircc_query_runs (case_id, started_at, finished_at, success, error_message, duration_ms, trigger_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (caseId, startedIso, finishedIso, int(success), errorMessage, durationMs, triggerType),
        )
    return {"success": success, "changed": success and changed, "notified": notificationSent, "error": errorMessage, "result": snapshot, "summary": changeSummary}


def listIrccHistory(caseId: int, userId: int | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        rows = connection.execute(
            f"""
            SELECT h.*
            FROM ircc_status_history h
            JOIN ircc_cases c ON c.id = h.case_id
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
            "applicationStatus": row["application_status"],
            "applicationInfoStatus": row["application_info_status"],
            "messageCount": row["message_count"],
            "changeSummary": row["change_summary"],
            "fetchedAt": row["fetched_at"],
            "rawPayload": json.loads(decryptIfNeeded(row["raw_payload"]) or "{}"),
            "notificationSent": bool(row["notification_sent"]),
        }
        for row in rows
    ]


def normalizeIrccQueryJob(row: dict[str, Any]) -> dict[str, Any]:
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


def enqueueIrccCaseQuery(caseId: int, triggerType: str, userId: int | None = None) -> dict[str, Any] | None:
    now = utcNowIso()
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        case = connection.execute(f"SELECT id FROM ircc_cases WHERE id = ? {userFilter}", params).fetchone()
        if not case:
            return None
        existing = connection.execute(
            """
            SELECT *
            FROM ircc_query_jobs
            WHERE case_id = ? AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (caseId,),
        ).fetchone()
        if existing:
            return normalizeIrccQueryJob(existing)
        cursor = connection.execute(
            """
            INSERT INTO ircc_query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, ?, 'queued', ?, ?)
            """,
            (caseId, triggerType, now, now),
        )
        row = connection.execute("SELECT * FROM ircc_query_jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return normalizeIrccQueryJob(row)


def enqueueDueIrccCases(limit: int = 20) -> list[dict[str, Any]]:
    now = datetime.now(UTC).replace(microsecond=0)
    nowIso = now.isoformat()
    queued: list[dict[str, Any]] = []
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT c.id,
                   (
                       SELECT h.raw_payload
                       FROM ircc_status_history h
                       WHERE h.case_id = c.id
                       ORDER BY h.id DESC
                       LIMIT 1
                   ) AS latest_raw_payload
            FROM ircc_cases c
            WHERE c.is_enabled = 1
              AND c.next_check_at IS NOT NULL
              AND c.next_check_at <= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM ircc_query_jobs j
                  WHERE j.case_id = c.id AND j.status IN ('queued', 'running')
              )
            ORDER BY c.next_check_at ASC
            LIMIT ?
            """,
            (nowIso, limit),
        ).fetchall()
    for row in rows:
        latestPayload = decryptIfNeeded(row["latest_raw_payload"] or "") or ""
        latestSnapshot = {}
        if latestPayload:
            try:
                latestSnapshot = json.loads(latestPayload)
            except json.JSONDecodeError:
                latestSnapshot = {}
        if isIrccIssuedEquivalentCode(getIrccHeadlineCode(latestSnapshot)) and handleIrccIssuedEquivalentDueCase(int(row["id"]), now):
            continue
        job = enqueueIrccCaseQuery(int(row["id"]), "ircc_automatic")
        if job:
            queued.append(job)
    return queued


def claimNextIrccQueryJob(workerId: str | None = None) -> dict[str, Any] | None:
    workerId = workerId or f"ircc-worker-{uuid.uuid4()}"
    nowIso = utcNowIso()
    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT j.*
            FROM ircc_query_jobs j
            JOIN ircc_cases c ON c.id = j.case_id
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
            UPDATE ircc_query_jobs
            SET status = 'running', attempts = attempts + 1, locked_at = ?, locked_by = ?,
                started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (nowIso, workerId, nowIso, nowIso, row["id"]),
        )
        claimed = connection.execute("SELECT * FROM ircc_query_jobs WHERE id = ?", (row["id"],)).fetchone()
    return normalizeIrccQueryJob(claimed)


def failTimedOutIrccQueryJobs(now: datetime | None = None, timeoutSeconds: int = 360) -> int:
    now = now or datetime.now(UTC)
    timeoutAt = (now - timedelta(seconds=timeoutSeconds)).replace(microsecond=0).isoformat()
    nowIso = now.replace(microsecond=0).isoformat()
    result = {"success": False, "changed": False, "error": IRCC_QUERY_TIMEOUT_ERROR_MESSAGE, "timeout": True}
    with getConnection() as connection:
        cursor = connection.execute(
            """
            UPDATE ircc_query_jobs
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
                IRCC_QUERY_TIMEOUT_ERROR_MESSAGE,
                encryptSecret(json.dumps(result, ensure_ascii=False)),
                nowIso,
                nowIso,
                timeoutAt,
            ),
        )
    return int(cursor.rowcount)


def runIrccQueryJob(job: dict[str, Any]) -> dict[str, Any]:
    try:
        result = runIrccCaseQuery(int(job["caseId"]), triggerType=str(job["triggerType"]))
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
            UPDATE ircc_query_jobs
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
        row = connection.execute("SELECT * FROM ircc_query_jobs WHERE id = ?", (job["id"],)).fetchone()
    return normalizeIrccQueryJob(row)


def getIrccQueryJob(jobId: int, userId: int | None = None) -> dict[str, Any] | None:
    params: tuple[Any, ...] = (jobId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (jobId, userId)
    with getConnection() as connection:
        row = connection.execute(
            f"""
            SELECT j.*
            FROM ircc_query_jobs j
            JOIN ircc_cases c ON c.id = j.case_id
            WHERE j.id = ? {userFilter}
            """,
            params,
        ).fetchone()
    return normalizeIrccQueryJob(row) if row else None


def sendCurrentIrccEmail(caseId: int, userId: int | None = None) -> dict[str, Any]:
    params: tuple[Any, ...] = (caseId,)
    userFilter = ""
    if userId is not None:
        userFilter = "AND c.user_id = ?"
        params = (caseId, userId)
    with getConnection() as connection:
        row = connection.execute(f"SELECT c.* FROM ircc_cases c WHERE c.id = ? {userFilter}", params).fetchone()
        if not row:
            return {"success": False, "error": "IRCC 档案不存在"}
        latest = connection.execute(
            "SELECT * FROM ircc_status_history WHERE case_id = ? ORDER BY id DESC LIMIT 1",
            (caseId,),
        ).fetchone()
        previous = connection.execute(
            "SELECT raw_payload FROM ircc_status_history WHERE case_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
            (caseId, latest["id"] if latest else 0),
        ).fetchone()
        smtpConfig = connection.execute("SELECT * FROM smtp_configs WHERE user_id = ?", (row["user_id"],)).fetchone()
    if not latest:
        return {"success": False, "error": "暂无 IRCC 状态快照，请先立即查询一次"}
    case = dict(row)
    case["receive_email"] = decryptIfNeeded(case["receive_email"]) or ""
    snapshot = json.loads(decryptIfNeeded(latest["raw_payload"]) or "{}")
    previousSnapshot = json.loads(decryptIfNeeded(previous["raw_payload"]) or "{}") if previous else None
    changeSummary = buildIrccDisplayChangeSummary(latest["change_summary"], previousSnapshot, snapshot)
    emailTimezone = getUserEmailTimezone(int(case["user_id"]))
    body = "\n".join(
        [
            "这是一封 IRCC Portal Alpha 测试邮件。",
            "",
            f"档案：{case['display_name']}",
            f"Application number：{case['application_number'] or '-'}",
            f"appId：{case['app_id']}",
            f"申请人：{case['principal_applicant'] or '-'}",
            f"快照时间：{formatCaseEmailTime(case, latest['fetched_at'])}",
            "",
            "状态概览：",
            formatEmailTextTimes(formatIrccStatusOverview(snapshot), emailTimezone),
            "",
            "最近变化摘要：",
            formatEmailTextTimes(changeSummary, emailTimezone),
            "",
            "当前状态详情：",
            formatEmailTextTimes(summarizeSnapshot(snapshot), emailTimezone),
        ],
    )
    try:
        sendIrccNotification(
            case,
            smtpConfig,
            f"[IRCC Alpha] {case['display_name']} 测试邮件",
            body,
            includeSupport=isIrccIssuedEquivalentCode(getIrccHeadlineCode(snapshot)),
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "error": ""}


def isIrccTrigger(triggerType: str | None) -> bool:
    return str(triggerType or "").startswith(IRCC_QUERY_TRIGGER_PREFIX)
