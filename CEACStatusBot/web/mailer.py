from email.header import Header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
import re
from smtplib import SMTP, SMTP_SSL
from typing import Any
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import getSettings
from .database import getConnection, utcNowIso
from .secrets import decryptSecret, encryptSecret


class DailyEmailLimitExceeded(RuntimeError):
    pass


SUPPORT_IMAGE_CONTENT_ID = "ceacstatusbot-support-qr"
DEFAULT_EMAIL_TIMEZONE = "Asia/Shanghai"
ISO_TIME_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


def resolveEmailTimezone(timezoneName: str | None) -> str:
    candidate = (timezoneName or "").strip() or DEFAULT_EMAIL_TIMEZONE
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return DEFAULT_EMAIL_TIMEZONE
    return candidate


def getUserEmailTimezone(userId: int | None, connection: Any | None = None) -> str:
    if userId is None:
        return DEFAULT_EMAIL_TIMEZONE
    if connection is not None:
        row = connection.execute("SELECT timezone FROM users WHERE id = ?", (userId,)).fetchone()
        return resolveEmailTimezone(row["timezone"] if row else "")
    with getConnection() as localConnection:
        row = localConnection.execute("SELECT timezone FROM users WHERE id = ?", (userId,)).fetchone()
    return resolveEmailTimezone(row["timezone"] if row else "")


def parseEmailTime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(f"{text[:-1]}+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return None


def formatEmailTime(value: str, timezoneName: str | None = None) -> str:
    parsed = parseEmailTime(value)
    if parsed is None:
        return str(value or "")
    localTime = parsed.astimezone(ZoneInfo(resolveEmailTimezone(timezoneName)))
    return localTime.strftime("%Y/%m/%d %H:%M:%S %Z")


def formatCaseEmailTime(case: dict[str, Any], value: str, connection: Any | None = None) -> str:
    timezoneName = getUserEmailTimezone(int(case["user_id"]) if case.get("user_id") is not None else None, connection)
    return formatEmailTime(value, timezoneName)


def formatEmailTextTimes(text: str, timezoneName: str | None = None) -> str:
    if not text:
        return ""
    return ISO_TIME_PATTERN.sub(lambda match: formatEmailTime(match.group(0), timezoneName), text)


def isKeyValueLine(line: str) -> bool:
    if "://" in line:
        return False
    separators = ["：", ":"]
    for separator in separators:
        if separator not in line:
            continue
        key, value = line.split(separator, 1)
        key = key.strip()
        if re.fullmatch(r"[0-9\\/\-:\s]+", key):
            return False
        if 1 <= len(key) <= 32 and value.strip():
            return True
    return False


def splitKeyValueLine(line: str) -> tuple[str, str]:
    separator = "：" if "：" in line else ":"
    key, value = line.split(separator, 1)
    return key.strip(), value.strip()


def isSectionHeading(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and stripped.endswith("：") and not isKeyValueLine(stripped)


def splitEmailBlocks(body: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for rawLine in body.splitlines():
        line = rawLine.rstrip()
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def renderKeyValueTable(lines: list[str]) -> str:
    rows = []
    for line in lines:
        key, value = splitKeyValueLine(line)
        rows.append(
            f"""
            <tr>
              <td style="width:34%;padding:8px 12px;border-bottom:1px solid #eef2f7;color:#64748b;font-size:13px;vertical-align:top;">{escape(key)}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eef2f7;color:#0f172a;font-size:14px;font-weight:600;vertical-align:top;word-break:break-word;">{escape(value)}</td>
            </tr>
            """,
        )
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;background:#ffffff;margin:0;">
        <tbody>{''.join(rows)}</tbody>
      </table>
    """


def renderParagraphLines(lines: list[str], *, color: str = "#334155", fontSize: int = 14, fontWeight: int = 400) -> str:
    return "".join(
        f'<p style="margin:0 0 8px;color:{color};font-size:{fontSize}px;font-weight:{fontWeight};line-height:1.7;word-break:break-word;">{escape(line)}</p>'
        for line in lines
    )


def renderTextLines(lines: list[str], *, emphasized: bool = False) -> str:
    if len(lines) == 1:
        return renderParagraphLines(lines, fontSize=15 if emphasized else 14, fontWeight=600 if emphasized else 400)
    return renderParagraphLines(lines, fontSize=14, fontWeight=500 if emphasized else 400)


def renderContentCard(contentHtml: str, *, tone: str = "neutral") -> str:
    borderColor = "#c7d2fe" if tone == "highlight" else "#e5e7eb"
    background = "#f8fafc" if tone == "neutral" else "#eef2ff"
    return f"""
      <div style="padding:14px 16px;border:1px solid {borderColor};border-left:4px solid {'#5e6ad2' if tone == 'highlight' else '#cbd5e1'};border-radius:10px;background:{background};">
        {contentHtml}
      </div>
    """


def renderSection(title: str, contentHtml: str, *, tone: str = "neutral") -> str:
    return f"""
      <section style="margin:24px 0 0;">
        <h2 style="margin:0 0 8px;color:#64748b;font-size:12px;font-weight:800;line-height:1.3;letter-spacing:0.08em;text-transform:uppercase;">{escape(title)}</h2>
        {renderContentCard(contentHtml, tone=tone)}
      </section>
    """


def renderEmailBlocks(body: str) -> str:
    blocks = splitEmailBlocks(body)
    htmlParts: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block and isSectionHeading(block[0]):
            title = block[0].strip()[:-1]
            contentHtml = ""
            inlineContent = block[1:]
            if inlineContent:
                if all(isKeyValueLine(line) for line in inlineContent):
                    contentHtml = renderKeyValueTable(inlineContent)
                else:
                    contentHtml = renderTextLines(inlineContent, emphasized=len(inlineContent) <= 2)
            elif index + 1 < len(blocks):
                nextBlock = blocks[index + 1]
                if nextBlock and all(isKeyValueLine(line) for line in nextBlock):
                    contentHtml = renderKeyValueTable(nextBlock)
                else:
                    contentHtml = renderTextLines(nextBlock, emphasized=len(nextBlock) <= 2)
                index += 1
            titleTone = "highlight" if any(keyword in title for keyword in ("变化", "摘要", "可预约", "决定")) else "neutral"
            htmlParts.append(renderSection(title, contentHtml, tone=titleTone))
        elif all(isKeyValueLine(line) for line in block):
            htmlParts.append(f'<section style="margin:16px 0 0;">{renderKeyValueTable(block)}</section>')
        else:
            marginTop = "0" if not htmlParts else "16px"
            htmlParts.append(f'<section style="margin:{marginTop} 0 0;">{renderTextLines(block)}</section>')
        index += 1
    return "".join(htmlParts)


def getSupportImagePath() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend" / "public" / "support" / "buy-me-a-coffee.jpg"


def buildSupportFooterPlain() -> str:
    return "\n".join(
        [
            "",
            "支持这个非盈利项目：如果 CEACStatusBot 对你有帮助，欢迎自愿扫码赞赏，支持服务器和维护成本。",
            "赞赏码图片见本邮件 HTML 版本；如果邮件客户端未显示图片，也可以登录网站查看赞赏码。",
            f"网站入口：{getSettings().appBaseUrl}",
            "小字说明：赞赏完全自愿，不购买官方服务，不保证签证结果、护照进度、slot 可用性或预约成功。",
        ],
    )


def buildEmailHtml(body: str, *, includeSupport: bool = False) -> str:
    bodyHtml = renderEmailBlocks(body)
    supportHtml = ""
    if includeSupport:
        supportHtml = f"""
          <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 16px;" />
          <div style="padding:14px 16px;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc;font-size:14px;line-height:1.6;color:#111827;">
            <strong style="display:block;margin:0 0 6px;font-size:15px;">支持这个非盈利项目</strong>
            <p style="margin:0 0 12px;color:#334155;">如果 CEACStatusBot 对你有帮助，欢迎自愿扫码赞赏，支持服务器和维护成本。</p>
            <img src="cid:{SUPPORT_IMAGE_CONTENT_ID}" alt="支持 CEACStatusBot" style="display:block;width:180px;max-width:100%;height:auto;border-radius:8px;margin:8px 0 12px;border:1px solid #e5e7eb;" />
            <p style="margin:0;color:#6b7280;font-size:12px;">赞赏完全自愿，不购买官方服务，不保证签证结果、护照进度、slot 可用性或预约成功。</p>
          </div>
        """
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#111827;">
    <div style="max-width:680px;margin:0 auto;">
      <div style="padding:22px 24px;background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;box-shadow:0 12px 32px rgba(15,23,42,0.06);">
        <div style="display:flex;align-items:center;gap:10px;margin:0 0 16px;">
          <div style="width:10px;height:10px;border-radius:999px;background:#5e6ad2;"></div>
          <div style="color:#475569;font-size:13px;font-weight:700;letter-spacing:0.02em;">CEACStatusBot</div>
        </div>
        {bodyHtml}
      </div>
      {supportHtml}
    </div>
  </body>
</html>"""


def sendEmail(
    *,
    fromEmail: str,
    toEmail: str,
    password: str,
    host: str,
    port: int,
    useSsl: bool,
    subject: str,
    body: str,
    htmlBody: str | None = None,
    inlineImages: dict[str, Path] | None = None,
) -> None:
    msg = MIMEMultipart("related")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = fromEmail
    msg["To"] = toEmail
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(body, "plain", "utf-8"))
    if htmlBody:
        alternative.attach(MIMEText(htmlBody, "html", "utf-8"))
    msg.attach(alternative)

    for contentId, imagePath in (inlineImages or {}).items():
        if not imagePath.exists():
            continue
        image = MIMEImage(imagePath.read_bytes())
        image.add_header("Content-ID", f"<{contentId}>")
        image.add_header("Content-Disposition", "inline", filename=imagePath.name)
        msg.attach(image)

    client: SMTP | SMTP_SSL
    if useSsl:
        client = SMTP_SSL(host, port, timeout=30)
    else:
        client = SMTP(host, port, timeout=30)
        client.starttls()
    try:
        client.login(fromEmail, password)
        client.sendmail(fromEmail, [toEmail], msg.as_string())
    finally:
        client.quit()


def sendSystemEmail(toEmail: str, subject: str, body: str, htmlBody: str | None = None, inlineImages: dict[str, Path] | None = None) -> None:
    config = getSystemSmtpConfig()
    if not config["fromEmail"] or not config["password"]:
        print("[mail] System email is not configured.")
        return
    renderedHtmlBody = htmlBody or buildEmailHtml(body)
    sendEmail(
        fromEmail=config["fromEmail"],
        toEmail=toEmail,
        password=config["password"],
        host=config["host"],
        port=config["port"],
        useSsl=config["useSsl"],
        subject=subject,
        body=body,
        htmlBody=renderedHtmlBody,
        inlineImages=inlineImages,
    )


def enforceDailyEmailLimit(userId: int | None, connection: Any | None = None) -> None:
    if userId is None:
        return
    settings = getSettings()
    now = datetime.now(UTC)
    todayStart = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrowStart = todayStart + timedelta(days=1)
    if connection is not None:
        user = connection.execute(
            "SELECT role, account_tier FROM users WHERE id = ?",
            (userId,),
        ).fetchone()
        if not user or user["role"] == "admin":
            return
        emailLimit = settings.premiumDailyEmailLimit if user["account_tier"] == "premium" else settings.standardDailyEmailLimit
        row = connection.execute(
            """
            SELECT COUNT(*) AS email_count
            FROM email_delivery_logs
            WHERE user_id = ?
              AND created_at >= ?
              AND created_at < ?
            """,
            (userId, todayStart.isoformat(), tomorrowStart.isoformat()),
        ).fetchone()
    else:
        with getConnection() as localConnection:
            user = localConnection.execute(
                "SELECT role, account_tier FROM users WHERE id = ?",
                (userId,),
            ).fetchone()
            if not user or user["role"] == "admin":
                return
            emailLimit = settings.premiumDailyEmailLimit if user["account_tier"] == "premium" else settings.standardDailyEmailLimit
            row = localConnection.execute(
                """
                SELECT COUNT(*) AS email_count
                FROM email_delivery_logs
                WHERE user_id = ?
                  AND created_at >= ?
                  AND created_at < ?
                """,
                (userId, todayStart.isoformat(), tomorrowStart.isoformat()),
            ).fetchone()
    emailCount = int(row["email_count"] if row else 0)
    if emailCount >= emailLimit:
        raise DailyEmailLimitExceeded(f"今日邮件发送数量已达上限（{emailLimit} 封），请明天再试。")


def recordEmailDelivery(
    *,
    userId: int | None,
    caseId: int | None,
    emailType: str,
    recipient: str,
    subject: str,
    body: str = "",
    connection: Any | None = None,
) -> None:
    if userId is None:
        return
    bodyEncrypted = encryptSecret(body) if body else ""
    if connection is not None:
        connection.execute(
            """
            INSERT INTO email_delivery_logs (user_id, case_id, email_type, recipient, subject, body_encrypted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (userId, caseId, emailType, recipient, subject, bodyEncrypted, utcNowIso()),
        )
        return
    with getConnection() as localConnection:
        localConnection.execute(
            """
            INSERT INTO email_delivery_logs (user_id, case_id, email_type, recipient, subject, body_encrypted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (userId, caseId, emailType, recipient, subject, bodyEncrypted, utcNowIso()),
        )


def getSystemSmtpConfig() -> dict[str, Any]:
    settings = getSettings()
    with getConnection() as connection:
        row = connection.execute("SELECT * FROM system_smtp_config WHERE id = 1").fetchone()
    if row:
        return {
            "fromEmail": row["from_email"],
            "host": row["host"],
            "port": int(row["port"]),
            "useSsl": bool(row["use_ssl"]),
            "password": decryptSecret(row["password_encrypted"]),
            "source": "database",
            "isConfigured": True,
        }
    return {
        "fromEmail": settings.systemFromEmail,
        "host": settings.systemSmtpHost,
        "port": settings.systemSmtpPort,
        "useSsl": settings.systemSmtpUseSsl,
        "password": settings.systemEmailPassword,
        "source": "environment",
        "isConfigured": bool(settings.systemFromEmail and settings.systemEmailPassword),
    }


def getSystemSmtpConfigPublic() -> dict[str, Any]:
    config = getSystemSmtpConfig()
    return {
        "fromEmail": config["fromEmail"],
        "host": config["host"],
        "port": config["port"],
        "useSsl": config["useSsl"],
        "source": config["source"],
        "isConfigured": config["isConfigured"],
        "hasPassword": bool(config["password"]),
    }


def saveSystemSmtpConfig(*, fromEmail: str, host: str, port: int, useSsl: bool, password: str | None) -> dict[str, Any]:
    now = utcNowIso()
    with getConnection() as connection:
        current = connection.execute("SELECT password_encrypted FROM system_smtp_config WHERE id = 1").fetchone()
        if password:
            passwordEncrypted = encryptSecret(password)
        elif current:
            passwordEncrypted = current["password_encrypted"]
        else:
            settings = getSettings()
            if not settings.systemEmailPassword:
                raise RuntimeError("System SMTP password is required")
            passwordEncrypted = encryptSecret(settings.systemEmailPassword)
        connection.execute(
            """
            INSERT INTO system_smtp_config (id, from_email, host, port, use_ssl, password_encrypted, created_at, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                from_email = excluded.from_email,
                host = excluded.host,
                port = excluded.port,
                use_ssl = excluded.use_ssl,
                password_encrypted = excluded.password_encrypted,
                updated_at = excluded.updated_at
            """,
            (fromEmail, host, port, int(useSsl), passwordEncrypted, now, now),
        )
    return getSystemSmtpConfigPublic()


def sendCaseNotification(case: dict[str, Any], smtpConfig: dict[str, Any] | None, result: dict[str, Any], connection: Any | None = None, *, isTest: bool = False) -> None:
    subject = f"[CEAC] {case['application_num']} 状态更新：{result['status']}"
    if isTest:
        subject = f"[CEAC] {case['application_num']} 测试邮件：当前状态 {result['status']}"
    lines = [
        f"档案：{case['display_name']}",
        f"申请号：{case['application_num']}",
        f"状态：{result['status']}",
        f"CEAC 更新时间：{result.get('case_last_updated', '')}",
        f"签证类型：{result.get('visa_type', '')}",
        "",
        str(result.get("description", "")),
    ]
    if str(result.get("status", "")).strip().lower() == "issued":
        lines.extend(
            [
                "",
                "提示：该档案已进入 Issued，系统会将自动查询频率降为每天一次。",
                "你可以登录站内档案详情页停止自动查询；如果一周内未停止，系统将自动停止该档案的自动查询并邮件通知你。",
            ],
        )
    if str(result.get("status", "")).strip().lower() in {"approved", "issued"}:
        lines.extend(
            [
                "",
                "护照预约提醒：你现在可以登录 CEACStatusBot，在该档案详情页填写 UID 或 HAL，开启 GTS 护照预约 slot 监控。",
                "系统会监控“暂不具备预约资格 / 暂无 slot / 发现 slot”三种状态，并在进入可预约阶段、发现 slot 或 slot 时间变化时邮件通知你。",
                f"登录入口：{getSettings().appBaseUrl}",
            ],
        )
    status = str(result.get("status", "")).strip().lower()
    includeSupport = status in {"approved", "issued"}
    body = "\n".join(lines)
    sendCaseEmail(
        case,
        smtpConfig,
        subject,
        body,
        emailType="ceac_status",
        connection=connection,
        includeSupport=includeSupport,
    )


def sendPassportSlotNotification(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    *,
    identifierFull: str,
    identifierMasked: str,
    fetchedAt: str,
    slotStatus: str,
    statusMessage: str,
    slotLines: list[str],
    rawSummary: str,
    autoStopped: bool = False,
    slotListChanged: bool = False,
    connection: Any | None = None,
) -> None:
    sendPassportSlotStatusEmail(
        case,
        smtpConfig,
        identifierFull=identifierFull,
        identifierMasked=identifierMasked,
        fetchedAt=fetchedAt,
        slotStatus=slotStatus,
        statusMessage=statusMessage,
        slotLines=slotLines,
        rawSummary=rawSummary,
        hasSlots=slotStatus == "has_slot",
        isTest=False,
        autoStopped=autoStopped,
        slotListChanged=slotListChanged,
        connection=connection,
    )


def sendPassportSlotStatusEmail(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    *,
    identifierFull: str,
    identifierMasked: str,
    fetchedAt: str,
    slotStatus: str,
    statusMessage: str,
    slotLines: list[str],
    rawSummary: str,
    hasSlots: bool,
    isTest: bool = False,
    autoStopped: bool = False,
    slotListChanged: bool = False,
    connection: Any | None = None,
) -> None:
    subject = f"[GTS] 发现可预约时间：{case['display_name']}"
    if slotListChanged:
        subject = f"[GTS] 可预约时间有变化：{case['display_name']}"
    if slotStatus == "no_slot":
        subject = f"[GTS] 护照已可预约但暂无 slot：{case['display_name']}"
    elif slotStatus == "not_eligible":
        subject = f"[GTS] 暂不具备护照预约资格：{case['display_name']}"
    if autoStopped:
        subject = f"[GTS] 护照预约监控已自动停止：{case['display_name']}"
    if isTest:
        subject = f"[GTS] 护照预约监控测试：{case['display_name']}"
    statusLabel = statusMessage or ("可预约时间有变化" if slotListChanged else "发现可预约时间" if hasSlots else "暂无可预约时间")
    appEntry = getSettings().appBaseUrl
    queryTime = formatCaseEmailTime(case, fetchedAt, connection)
    lines = [
        f"档案：{case['display_name']}",
        f"申请号：{case['application_num']}",
        f"UID/HAL：{identifierFull or identifierMasked}",
        f"查询时间：{queryTime}",
        "",
        f"当前状态：{statusLabel}",
    ]
    if hasSlots:
        lines.append("")
        lines.append("更新后的可预约时间：" if slotListChanged else "当前可预约时间：")
        lines.extend(slotLines or ["接口返回了可用 slot，但未能解析为标准日期 / 时间字段。"])
        lines.extend(
            [
                "",
                "系统已将该档案的 slot 自动查询放缓到随机 50-70 分钟一次，并且不会再参与零点加频。",
                "如果你已经在 GTS 官网预约成功，请回到站内档案详情页点击“我已预约，停止监控”。",
            ],
        )
    elif autoStopped:
        lines.extend(
            [
                "系统检测到该 UID/HAL 从可预约阶段回到暂不具备预约资格。",
                "这通常表示你可能已经完成预约，或 GTS 已关闭该 UID/HAL 的预约入口。",
                "系统已自动停止该档案的 GTS 护照预约监控，避免继续无意义查询。",
            ],
        )
    elif slotStatus == "not_eligible":
        lines.append("这通常表示护照还在签证处/使馆，尚未送达中信银行。系统会继续按常规频率监控。")
    elif slotStatus == "no_slot":
        lines.append("这通常表示护照已进入可预约阶段，但当前没有可选时间；系统会继续监控，并在零点附近加密查询。")
    elif isTest:
        lines.append("这是一封测试邮件，用于确认护照预约监控的发信配置可用。")
    lines.extend(
        [
            "",
            "预约入口：https://schedule.gtspremium.com/",
            f"站内入口：{appEntry}",
            "操作提示：打开官网，输入上方 UID/HAL，勾选条款后查询。",
            "安全提醒：本邮件包含完整 UID/HAL，请勿转发或公开截图。",
        ],
    )
    body = "\n".join(lines)
    sendCaseEmail(
        case,
        smtpConfig,
        subject,
        body,
        emailType="passport_slot",
        connection=connection,
        includeSupport=True,
    )


def sendPassportSlotLongNoSlotNoticeEmail(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    *,
    identifierFull: str,
    identifierMasked: str,
    noticeAt: str,
    stopAt: str,
    monitorStartedAt: str,
    connection: Any | None = None,
) -> None:
    subject = f"[GTS] 长期未发现 slot，7 天后将自动停止：{case['display_name']}"
    noticeTime = formatCaseEmailTime(case, noticeAt, connection)
    stopTime = formatCaseEmailTime(case, stopAt, connection)
    monitorStartTime = formatCaseEmailTime(case, monitorStartedAt, connection)
    appEntry = getSettings().appBaseUrl
    body = "\n".join(
        [
            f"档案：{case['display_name']}",
            f"申请号：{case['application_num']}",
            f"UID/HAL：{identifierFull or identifierMasked}",
            f"监控开始时间：{monitorStartTime}",
            f"提醒时间：{noticeTime}",
            "",
            "当前状态：长期未发现可预约 slot",
            "",
            "系统检测到该 GTS 护照预约监控已经连续运行超过 15 天，期间从未发现可预约 slot。",
            "为了避免长期空跑和持续请求 GTS，系统已将该监控降频为约 1 小时随机查询一次。",
            f"如果 7 天后仍然没有发现 slot，系统将在 {stopTime} 之后自动停止该监控。",
            "",
            "如果你仍希望继续监控，可在自动停止后回到站内手动重新开启；你也可以随时手动立即查询。",
            "说明：GTS 查询结果依赖官方接口，本服务不保证 slot 完整性、实时性或预约成功。",
            "",
            "预约入口：https://schedule.gtspremium.com/",
            f"站内入口：{appEntry}",
            "安全提醒：本邮件包含完整 UID/HAL，请勿转发或公开截图。",
        ],
    )
    sendCaseEmail(
        case,
        smtpConfig,
        subject,
        body,
        emailType="passport_slot",
        connection=connection,
        includeSupport=True,
    )


def sendPassportSlotLongNoSlotStoppedEmail(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    *,
    identifierFull: str,
    identifierMasked: str,
    stoppedAt: str,
    noticeAt: str,
    connection: Any | None = None,
) -> None:
    subject = f"[GTS] 长期未发现 slot，已自动停止：{case['display_name']}"
    stoppedTime = formatCaseEmailTime(case, stoppedAt, connection)
    noticeTime = formatCaseEmailTime(case, noticeAt, connection)
    appEntry = getSettings().appBaseUrl
    body = "\n".join(
        [
            f"档案：{case['display_name']}",
            f"申请号：{case['application_num']}",
            f"UID/HAL：{identifierFull or identifierMasked}",
            f"提醒时间：{noticeTime}",
            f"停止时间：{stoppedTime}",
            "",
            "当前状态：长期未发现可预约 slot，监控已自动停止",
            "",
            "系统已在提醒后继续低频查询 7 天，期间仍未发现可预约 slot。",
            "为避免继续长期空跑，系统已自动停止该档案的 GTS 护照预约监控。",
            "",
            "你仍然可以回到站内手动重新开启监控，或手动立即查询。",
            "说明：GTS 查询结果依赖官方接口，本服务不保证 slot 完整性、实时性或预约成功。",
            "",
            "预约入口：https://schedule.gtspremium.com/",
            f"站内入口：{appEntry}",
            "安全提醒：本邮件包含完整 UID/HAL，请勿转发或公开截图。",
        ],
    )
    sendCaseEmail(
        case,
        smtpConfig,
        subject,
        body,
        emailType="passport_slot",
        connection=connection,
        includeSupport=True,
    )


def sendIssuedAutoStopNotification(case: dict[str, Any], smtpConfig: dict[str, Any] | None, issuedAt: str, connection: Any | None = None) -> None:
    subject = f"[CEAC] {case['application_num']} 已自动停止查询"
    issuedTime = formatCaseEmailTime(case, issuedAt, connection)
    body = "\n".join(
        [
            f"档案：{case['display_name']}",
            f"申请号：{case['application_num']}",
            "状态：Issued",
            f"首次记录 Issued 时间：{issuedTime}",
            "",
            "该档案进入 Issued 已超过一周，且你尚未在站内停止自动查询。",
            "系统已按策略自动关闭该档案的自动查询，避免继续请求 CEAC。",
            "你仍然可以登录网站，在档案详情页手动执行立即查询。",
        ],
    )
    sendCaseEmail(
        case,
        smtpConfig,
        subject,
        body,
        emailType="issued_auto_stop",
        connection=connection,
        includeSupport=True,
    )


def sendCeacConsecutiveFailureNotification(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    *,
    errorCount: int,
    errorMessage: str,
    stopped: bool,
    slowed: bool = False,
    connection: Any | None = None,
) -> None:
    subject = f"[CEAC] {case['application_num']} 连续查询失败 {errorCount} 次"
    if slowed:
        subject = f"[CEAC] {case['application_num']} 连续失败已降为每天一次查询"
    if stopped:
        subject = f"[CEAC] {case['application_num']} 已因连续失败停止自动查询"
    lines = [
        f"档案：{case['display_name']}",
        f"申请号：{case['application_num']}",
        f"连续失败次数：{errorCount}",
        f"最近失败原因：{errorMessage or 'CEAC 查询失败'}",
        "",
    ]
    if stopped:
        lines.extend(
            [
                "该档案连续失败后已进入每天一次的降频查询阶段，且 7 天内仍未查询成功。",
                "系统已自动停止 CEAC 自动查询，避免继续无效请求。",
                "你仍然可以登录网站核对信息，并手动执行“立即查询”。如果确认信息无误但仍失败，请联系管理员。",
            ],
        )
    elif slowed:
        lines.extend(
            [
                "该档案已经连续 10 次查询失败。",
                "系统不会立刻停止自动查询，而是先降为每天一次，继续观察 7 天。",
                "如果 7 天内仍然持续失败且信息没有修改，系统会自动停止该档案的 CEAC 自动查询。",
                "请尽快登录网站核对办理地点、Application ID 或 Case Number、护照号、姓氏前 5 个字母是否填写正确。",
            ],
        )
    else:
        lines.extend(
            [
                "该档案已经至少连续 5 次查询失败。",
                "请登录网站核对办理地点、Application ID 或 Case Number、护照号、姓氏前 5 个字母是否填写正确。",
                "如果信息没有修改，后续仍然连续失败到 10 次，系统会先把自动查询降为每天一次；若降频后 7 天内仍然持续失败，系统才会停止该档案的 CEAC 自动查询。",
            ],
        )
    lines.extend(["", f"登录入口：{getSettings().appBaseUrl}"])
    sendCaseEmail(
        case,
        smtpConfig,
        subject,
        "\n".join(lines),
        emailType="ceac_consecutive_failure",
        connection=connection,
        includeSupport=False,
    )


def sendCaseEmail(
    case: dict[str, Any],
    smtpConfig: dict[str, Any] | None,
    subject: str,
    body: str,
    *,
    emailType: str = "case",
    connection: Any | None = None,
    includeSupport: bool = False,
) -> None:
    userId = int(case["user_id"]) if case.get("user_id") is not None else None
    caseId = int(case["id"]) if case.get("id") is not None else None
    enforceDailyEmailLimit(userId, connection)
    inlineImages = {SUPPORT_IMAGE_CONTENT_ID: getSupportImagePath()} if includeSupport else None
    plainBody = body + (buildSupportFooterPlain() if includeSupport else "")
    htmlBody = buildEmailHtml(body, includeSupport=includeSupport)
    if case["sender_mode"] == "custom" and smtpConfig:
        sendEmail(
            fromEmail=smtpConfig["from_email"],
            toEmail=case["receive_email"],
            password=decryptSecret(smtpConfig["password_encrypted"]),
            host=smtpConfig["host"],
            port=int(smtpConfig["port"]),
            useSsl=bool(smtpConfig["use_ssl"]),
            subject=subject,
            body=plainBody,
            htmlBody=htmlBody,
            inlineImages=inlineImages,
        )
        recordEmailDelivery(userId=userId, caseId=caseId, emailType=emailType, recipient=case["receive_email"], subject=subject, body=plainBody, connection=connection)
        return
    sendSystemEmail(case["receive_email"], subject, plainBody, htmlBody=htmlBody, inlineImages=inlineImages)
    recordEmailDelivery(userId=userId, caseId=caseId, emailType=emailType, recipient=case["receive_email"], subject=subject, body=plainBody, connection=connection)
