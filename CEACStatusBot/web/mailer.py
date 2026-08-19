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

from .account_controls import getQuotaScope, isUserAccountActive
from .config import getSettings
from .database import getConnection, utcNowIso
from .secrets import decryptIfNeeded, decryptSecret, encryptSecret


class DailyEmailLimitExceeded(RuntimeError):
    pass


class EmailDeliverySuppressed(RuntimeError):
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


def sendSystemEmail(toEmail: str, subject: str, body: str, htmlBody: str | None = None, inlineImages: dict[str, Path] | None = None) -> bool:
    config = getSystemSmtpConfig()
    if not config["fromEmail"] or not config["password"]:
        print("[mail] System email is not configured.")
        return False
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
    return True


def sendAccountRestrictionEmail(
    *,
    userId: int,
    recipient: str,
    accountStatus: str,
    restrictedAt: str,
) -> bool:
    """限制通知绕过普通通知额度，确保用户能获知暂停与申诉入口。"""
    statusLabel = "等待人工审核" if accountStatus == "review" else "账号访问已受限"
    subject = f"[CEACStatusBot] {statusLabel}"
    formattedTime = formatEmailTime(restrictedAt, getUserEmailTimezone(userId))
    body = "\n".join(
        [
            "账号服务状态：",
            statusLabel,
            "",
            f"账号：{recipient}",
            f"发生时间：{formattedTime}",
            "",
            "为保护服务稳定性和所有用户的正常使用，当前账号的查询服务已暂停。",
            "你的档案和历史记录仍会保留；在恢复前，系统不会继续自动查询或发送档案状态通知。",
            "",
            "你可以登录 CEACStatusBot，在账号受限页面提交申诉，管理员会人工复核。",
            f"登录入口：{getSettings().appBaseUrl}",
            "",
            "本邮件不会披露具体风控依据。请勿回复邮件发送密码、护照号、UID/HAL 或 IRCC Portal 凭据。",
        ],
    )
    try:
        delivered = sendSystemEmail(recipient, subject, body, htmlBody=buildEmailHtml(body))
    except Exception as exc:
        print(f"[mail] Account restriction notice failed for user {userId}: {type(exc).__name__}")
        return False
    if delivered:
        recordEmailDelivery(
            userId=userId,
            caseId=None,
            emailType="account_restriction",
            recipient=recipient,
            subject=subject,
            body=body,
        )
    return delivered


def sendAccountReviewResolutionEmail(*, userId: int, recipient: str) -> bool:
    """说明误触发审核已纠正，不占用档案状态通知额度。"""
    subject = "[CEACStatusBot] 关于此前人工审核的说明 / Update on your account review"
    body = "\n".join(
        [
            "账号服务状态：已恢复正常访问",
            "",
            "近期网站检测到疑似中介批量注册多个账号的行为。为保护查询资源和正常用户的使用，"
            "系统曾临时收紧同一设备重复注册的自动审核规则。",
            "",
            "该规则设置得过于严格，你的账号因此被误触发人工审核。我们已完成核对并调整规则："
            "单纯的设备关联不再直接限制账号；只有较多账号且伴随短时间集中注册等更强信号时，"
            "新账号才会进入人工审核。",
            "",
            "你的账号、档案和历史记录均已保留并恢复正常访问。无需回复本邮件，也无需提供密码、"
            "护照号、UID/HAL 或 IRCC Portal 凭据。对此带来的不便，我们深表歉意。",
            f"登录入口：{getSettings().appBaseUrl}",
            "",
            "Account status: normal access restored",
            "",
            "We recently detected suspected bulk account registrations, including activity consistent with intermediary-operated registrations. "
            "To protect query capacity and normal users, we temporarily made the automatic review rule for repeated registrations from the same device too strict.",
            "",
            "Your account was incorrectly placed under manual review by that rule. We have completed a review and adjusted the rule: "
            "a device association alone will no longer restrict an account. A new account will be reviewed only when a larger number of associated accounts and stronger signals, such as concentrated registrations in a short period, are both present.",
            "",
            "Your account, profiles, and history have been retained and normal access has been restored. You do not need to reply or provide a password, passport number, UID/HAL, or IRCC Portal credentials. We apologize for the inconvenience.",
            f"Sign in: {getSettings().appBaseUrl}",
        ],
    )
    try:
        delivered = sendSystemEmail(recipient, subject, body, htmlBody=buildEmailHtml(body))
    except Exception as exc:
        print(f"[mail] Account review resolution notice failed for user {userId}: {type(exc).__name__}")
        return False
    if delivered:
        recordEmailDelivery(
            userId=userId,
            caseId=None,
            emailType="account_review_resolution",
            recipient=recipient,
            subject=subject,
            body=body,
        )
    return delivered


def sendAccountAppealRejectionEmail(
    *,
    userId: int,
    recipient: str,
    reviewNote: str,
    reviewedAt: str,
) -> bool:
    """驳回结果属于必要账号通知，不受普通状态邮件额度影响。"""
    subject = "[CEACStatusBot] 账号申诉处理结果：暂未通过"
    formattedTime = formatEmailTime(reviewedAt, getUserEmailTimezone(userId))
    visibleNote = reviewNote.strip() or "当前申诉提供的信息不足，暂不恢复账号访问。"
    body = "\n".join(
        [
            "申诉处理结果：暂未通过",
            "",
            f"账号：{recipient}",
            f"处理时间：{formattedTime}",
            "",
            "处理说明：",
            visibleNote,
            "",
            "你可以根据处理说明补充情况后重新提交申诉。",
            f"登录入口：{getSettings().appBaseUrl}",
            "",
            "请勿通过申诉或邮件发送密码、验证码、完整护照号、UID/HAL 或 IRCC Portal 凭据。",
        ],
    )
    try:
        delivered = sendSystemEmail(recipient, subject, body, htmlBody=buildEmailHtml(body))
    except Exception as exc:
        print(f"[mail] Account appeal rejection notice failed for user {userId}: {type(exc).__name__}")
        return False
    if delivered:
        try:
            recordEmailDelivery(
                userId=userId,
                caseId=None,
                emailType="account_appeal_rejected",
                recipient=recipient,
                subject=subject,
                body=body,
            )
        except Exception as exc:
            print(f"[mail] Account appeal rejection audit failed for user {userId}: {type(exc).__name__}")
    return delivered


def getAdministratorNotificationRecipients() -> list[dict[str, Any]]:
    """优先向已验证的管理员账号发告警；仅在没有管理员账号时回退部署配置。"""
    recipients: list[dict[str, Any]] = []
    seenEmails: set[str] = set()
    with getConnection() as connection:
        rows = connection.execute(
            """
            SELECT id, email, timezone
            FROM users
            WHERE role = 'admin' AND is_email_verified = 1
            ORDER BY id ASC
            """,
        ).fetchall()
    for row in rows:
        email = str(row["email"] or "").strip().lower()
        if not email or email in seenEmails:
            continue
        seenEmails.add(email)
        recipients.append(
            {
                "userId": int(row["id"]),
                "email": email,
                "timezone": resolveEmailTimezone(row.get("timezone") or ""),
            },
        )

    if recipients:
        return recipients

    fallbackEmail = getSettings().defaultAdminEmail.strip().lower()
    if fallbackEmail:
        recipients.append(
            {"userId": None, "email": fallbackEmail, "timezone": DEFAULT_EMAIL_TIMEZONE},
        )
    return recipients


def sendAdministratorAccountAlert(
    *,
    alertType: str,
    targetUserId: int,
    targetEmail: str,
    accountStatus: str,
    occurredAt: str,
    reasonCode: str = "",
    appealId: int | None = None,
) -> dict[str, int]:
    """发送账号风控和申诉告警；申诉正文只留在加密后台记录中。"""
    alertDefinitions = {
        "automatic_restriction": {
            "subject": "[CEACStatusBot 管理员告警] 自动规则已限制账号",
            "emailType": "admin_account_restriction_alert",
            "title": "自动规则已限制账号",
            "details": [
                f"账号状态：{'等待人工审核' if accountStatus == 'review' else '账号访问已受限'}",
                f"规则编号：{reasonCode or '-'}",
                "请在管理员页面核对关联证据和账号状态。",
            ],
        },
        "appeal_submitted": {
            "subject": "[CEACStatusBot 管理员告警] 收到账号申诉",
            "emailType": "admin_account_appeal_alert",
            "title": "收到账号申诉",
            "details": [
                f"当前账号状态：{'等待人工审核' if accountStatus == 'review' else '账号访问已受限'}",
                f"申诉编号：{appealId if appealId is not None else '-'}",
                "申诉正文未在邮件中转发，请在管理员页面查看，以避免扩散用户可能误填的敏感信息。",
            ],
        },
    }
    definition = alertDefinitions.get(alertType)
    if definition is None:
        raise ValueError("不支持的管理员账号告警类型")

    recipients = getAdministratorNotificationRecipients()
    result = {"attempted": len(recipients), "delivered": 0, "failed": 0}
    for recipient in recipients:
        formattedTime = formatEmailTime(occurredAt, str(recipient["timezone"]))
        body = "\n".join(
            [
                "账号风控通知：",
                str(definition["title"]),
                "",
                f"目标账号：{targetEmail}",
                f"账号 ID：{targetUserId}",
                f"发生时间：{formattedTime}",
                *[str(line) for line in definition["details"]],
                "",
                f"管理员入口：{getSettings().appBaseUrl}",
            ],
        )
        try:
            delivered = sendSystemEmail(
                str(recipient["email"]),
                str(definition["subject"]),
                body,
                htmlBody=buildEmailHtml(body),
            )
        except Exception as exc:
            print(f"[mail] Administrator account alert failed for user {targetUserId}: {type(exc).__name__}")
            result["failed"] += 1
            continue
        if not delivered:
            result["failed"] += 1
            continue
        result["delivered"] += 1
        recipientUserId = recipient["userId"]
        if recipientUserId is not None:
            try:
                recordEmailDelivery(
                    userId=int(recipientUserId),
                    caseId=None,
                    emailType=str(definition["emailType"]),
                    recipient=str(recipient["email"]),
                    subject=str(definition["subject"]),
                    body=body,
                )
            except Exception as exc:
                # 邮件已经发送时，不因为审计写入短暂失败而干扰其他管理员告警。
                print(f"[mail] Administrator account alert audit failed for user {targetUserId}: {type(exc).__name__}")
    return result


def enforceDailyEmailLimit(userId: int | None, connection: Any | None = None) -> None:
    if userId is None:
        return
    settings = getSettings()
    now = datetime.now(UTC)
    todayStart = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrowStart = todayStart + timedelta(days=1)
    def enforce(activeConnection: Any) -> None:
        scope = getQuotaScope(activeConnection, userId)
        if scope["profileLimit"] is None:
            return
        emailLimit = settings.premiumDailyEmailLimit if scope["accountTier"] == "premium" else settings.standardDailyEmailLimit
        scopedIds = tuple(int(value) for value in scope["userIds"])
        placeholders = ", ".join("?" for _ in scopedIds)
        row = activeConnection.execute(
            f"""
            SELECT COUNT(*) AS email_count
            FROM email_delivery_logs
            WHERE user_id IN ({placeholders})
              AND email_type NOT IN ('account_restriction', 'account_review_resolution', 'account_appeal_rejected')
              AND created_at >= ?
              AND created_at < ?
            """,
            (*scopedIds, todayStart.isoformat(), tomorrowStart.isoformat()),
        ).fetchone()
        emailCount = int(row["email_count"] if row else 0)
        if emailCount >= emailLimit:
            raise DailyEmailLimitExceeded(f"今日邮件发送数量已达上限（{emailLimit} 封），请明天再试。")

    if connection is not None:
        enforce(connection)
        return
    with getConnection() as localConnection:
        enforce(localConnection)


def ensureUserEmailDeliveryAllowed(userId: int | None, connection: Any | None = None) -> None:
    if userId is None:
        return
    if not isUserAccountActive(userId, connection):
        raise EmailDeliverySuppressed("账号当前不可用，已跳过邮件发送。")


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
    recipientEncrypted = encryptSecret(recipient) if recipient else ""
    subjectEncrypted = encryptSecret(subject) if subject else ""
    bodyEncrypted = encryptSecret(body) if body else ""
    if connection is not None:
        connection.execute(
            """
            INSERT INTO email_delivery_logs (user_id, case_id, email_type, recipient, subject, body_encrypted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (userId, caseId, emailType, recipientEncrypted, subjectEncrypted, bodyEncrypted, utcNowIso()),
        )
        return
    with getConnection() as localConnection:
        localConnection.execute(
            """
            INSERT INTO email_delivery_logs (user_id, case_id, email_type, recipient, subject, body_encrypted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (userId, caseId, emailType, recipientEncrypted, subjectEncrypted, bodyEncrypted, utcNowIso()),
        )


def getSystemSmtpConfig() -> dict[str, Any]:
    settings = getSettings()
    with getConnection() as connection:
        row = connection.execute("SELECT * FROM system_smtp_config WHERE id = 1").fetchone()
    if row:
        return {
            "fromEmail": decryptIfNeeded(row["from_email"]) or "",
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
            (encryptSecret(fromEmail), host, port, int(useSsl), passwordEncrypted, now, now),
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
    ensureUserEmailDeliveryAllowed(userId, connection)
    enforceDailyEmailLimit(userId, connection)
    inlineImages = {SUPPORT_IMAGE_CONTENT_ID: getSupportImagePath()} if includeSupport else None
    plainBody = body + (buildSupportFooterPlain() if includeSupport else "")
    htmlBody = buildEmailHtml(body, includeSupport=includeSupport)
    if case["sender_mode"] == "custom" and smtpConfig:
        sendEmail(
            fromEmail=decryptIfNeeded(smtpConfig["from_email"]) or "",
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
