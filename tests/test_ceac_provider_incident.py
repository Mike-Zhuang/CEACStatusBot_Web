from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib

import pytest

from CEACStatusBot.web.case_service import (
    CEAC_PROVIDER_BLOCKED_ERROR_CODE,
    CeacProviderUnavailableError,
    countRecentCeacFailureRuns,
    createCase,
    enqueueCaseQuery,
    enqueueDueCases,
    markCeacProviderBlocked,
    runCaseQuery,
)
from CEACStatusBot.web.database import getConnection
from CEACStatusBot.web.mailer import sendCeacProviderIncidentNotification
from CEACStatusBot.web.schemas import CeacCaseInput
from CEACStatusBot.web.secrets import decryptIfNeeded


def caseInput(applicationNum: str) -> CeacCaseInput:
    return CeacCaseInput(
        displayName="CEAC 通道测试",
        location="Shanghai",
        applicationNum=applicationNum,
        passportNumber="P1234567",
        surname="TEST",
        receiveEmail=None,
        senderMode="system",
        isEnabled=True,
        emailNotificationsEnabled=False,
    )


def cloudflareResult() -> dict:
    return {
        "success": False,
        "error_code": CEAC_PROVIDER_BLOCKED_ERROR_CODE,
        "error": "CEAC 当前阻止服务器自动访问，系统已暂停继续重试。这不代表档案信息填写错误。",
        "attempts": 1,
    }


def successResult(applicationNum: str) -> dict:
    return {
        "success": True,
        "status": "Refused",
        "description": "Status description",
        "case_last_updated": "01-Sep-2026",
        "visa_type": "NONIMMIGRANT VISA APPLICATION",
        "case_created": "01-Aug-2026",
        "application_num": applicationNum,
        "application_num_origin": applicationNum,
    }


def test_cloudflare_response_fails_fast_without_retry(monkeypatch) -> None:
    queryModule = importlib.import_module("CEACStatusBot.request.query")

    class FakeResponse:
        status_code = 403
        headers = {"server": "cloudflare", "cf-ray": "test"}
        text = "<html><title>Attention Required! | Cloudflare</title>Sorry, you have been blocked</html>"

    class FakeSession:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    session = FakeSession()
    monkeypatch.setattr(queryModule.requests, "Session", lambda: session)
    monkeypatch.setattr(queryModule.time, "sleep", lambda _: pytest.fail("Cloudflare 403 不应重试"))

    result = queryModule.query_status("Shanghai", "AA00TEST01", "P1234567", "TEST", captchaHandle=object())

    assert result["success"] is False
    assert result["error_code"] == CEAC_PROVIDER_BLOCKED_ERROR_CODE
    assert result["attempts"] == 1
    assert session.calls == 1


def test_provider_block_does_not_increment_case_failures_or_notify_user(createUser, monkeypatch) -> None:
    user = createUser()
    case = createCase(int(user["id"]), caseInput("AA00BLOCK01"))
    with getConnection() as connection:
        connection.execute(
            "UPDATE ceac_cases SET ceac_consecutive_error_count = 4 WHERE id = ?",
            (case["id"],),
        )

    notices: list[dict] = []
    monkeypatch.setattr("CEACStatusBot.web.case_service.query_status", lambda *args: cloudflareResult())
    monkeypatch.setattr(
        "CEACStatusBot.web.case_service.sendCeacConsecutiveFailureNotification",
        lambda *args, **kwargs: pytest.fail("通道故障不应发送用户连续失败邮件"),
    )
    monkeypatch.setattr(
        "CEACStatusBot.web.case_service.sendCeacProviderIncidentNotification",
        lambda **kwargs: notices.append(dict(kwargs)) or {"attempted": 1, "delivered": 1, "failed": 0},
    )

    result = runCaseQuery(int(case["id"]))

    assert result["success"] is False
    assert result["result"]["error_code"] == CEAC_PROVIDER_BLOCKED_ERROR_CODE
    assert len(notices) == 1
    assert notices[0]["recovered"] is False
    with getConnection() as connection:
        caseRow = connection.execute(
            "SELECT is_enabled, ceac_consecutive_error_count, ceac_error_notice_sent_at, next_check_at FROM ceac_cases WHERE id = ?",
            (case["id"],),
        ).fetchone()
        incident = connection.execute("SELECT * FROM ceac_provider_incident WHERE id = 1").fetchone()
        run = connection.execute("SELECT * FROM query_runs WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case["id"],)).fetchone()
    assert caseRow["is_enabled"] == 1
    assert caseRow["ceac_consecutive_error_count"] == 4
    assert caseRow["ceac_error_notice_sent_at"] is None
    assert caseRow["next_check_at"]
    assert incident["is_active"] == 1
    assert incident["alert_sent_at"]
    assert run["success"] == 0
    assert run["error_code"] == CEAC_PROVIDER_BLOCKED_ERROR_CODE


def test_active_incident_sends_one_alert_and_one_recovery(createUser, monkeypatch) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    firstCase = createCase(int(first["id"]), caseInput("AA00BLOCK02"))
    secondCase = createCase(int(second["id"]), caseInput("AA00BLOCK03"))
    notices: list[dict] = []
    monkeypatch.setattr("CEACStatusBot.web.case_service.query_status", lambda *args: cloudflareResult())
    monkeypatch.setattr(
        "CEACStatusBot.web.case_service.sendCeacProviderIncidentNotification",
        lambda **kwargs: notices.append(dict(kwargs)) or {"attempted": 1, "delivered": 1, "failed": 0},
    )

    runCaseQuery(int(firstCase["id"]))
    runCaseQuery(int(secondCase["id"]))
    assert [notice["recovered"] for notice in notices] == [False]

    monkeypatch.setattr(
        "CEACStatusBot.web.case_service.query_status",
        lambda *args: successResult("AA00BLOCK03"),
    )
    recovered = runCaseQuery(int(secondCase["id"]))

    assert recovered["success"] is True
    assert [notice["recovered"] for notice in notices] == [False, True]
    with getConnection() as connection:
        incident = connection.execute("SELECT * FROM ceac_provider_incident WHERE id = 1").fetchone()
    assert incident["is_active"] == 0
    assert incident["recovered_at"]
    assert incident["recovery_alert_sent_at"]


def test_active_incident_blocks_manual_jobs_and_allows_one_due_probe(createUser) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    firstCase = createCase(int(first["id"]), caseInput("AA00PROBE01"))
    secondCase = createCase(int(second["id"]), caseInput("AA00PROBE02"))
    past = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    with getConnection() as connection:
        markCeacProviderBlocked(connection, past - timedelta(hours=2))
        connection.execute(
            "UPDATE ceac_provider_incident SET next_probe_at = ? WHERE id = 1",
            (past.isoformat(),),
        )
        connection.execute(
            "UPDATE ceac_cases SET next_check_at = ? WHERE id IN (?, ?)",
            (past.isoformat(), firstCase["id"], secondCase["id"]),
        )

    with pytest.raises(CeacProviderUnavailableError):
        enqueueCaseQuery(int(firstCase["id"]), "manual", int(first["id"]))

    queued = enqueueDueCases()

    assert len(queued) == 1
    with getConnection() as connection:
        queuedCount = connection.execute(
            "SELECT COUNT(*) AS count FROM query_jobs WHERE status = 'queued'",
        ).fetchone()
        incident = connection.execute("SELECT next_probe_at FROM ceac_provider_incident WHERE id = 1").fetchone()
    assert queuedCount["count"] == 1
    assert datetime.fromisoformat(incident["next_probe_at"]) > datetime.now(UTC)


def test_incident_cancels_queued_ceac_jobs_but_preserves_slot_jobs(createUser) -> None:
    user = createUser()
    case = createCase(int(user["id"]), caseInput("AA00QUEUE01"))
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    with getConnection() as connection:
        connection.execute(
            """
            INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, 'automatic', 'queued', ?, ?)
            """,
            (case["id"], now, now),
        )
        connection.execute(
            """
            INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at)
            VALUES (?, 'passport_slot_automatic', 'queued', ?, ?)
            """,
            (case["id"], now, now),
        )
        markCeacProviderBlocked(connection, datetime.now(UTC))
        jobs = connection.execute(
            "SELECT trigger_type, status FROM query_jobs ORDER BY id",
        ).fetchall()

    assert [(job["trigger_type"], job["status"]) for job in jobs] == [
        ("automatic", "failed"),
        ("passport_slot_automatic", "queued"),
    ]


def test_provider_failures_are_excluded_from_case_failure_streak(createUser) -> None:
    user = createUser()
    case = createCase(int(user["id"]), caseInput("AA00STREAK1"))
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    with getConnection() as connection:
        connection.execute(
            """
            INSERT INTO query_runs (
                case_id, started_at, finished_at, success, error_message,
                error_code, duration_ms, trigger_type
            )
            VALUES (?, ?, ?, 0, '普通查询失败', 'ceac_status_not_returned', 1, 'automatic')
            """,
            (case["id"], now, now),
        )
        connection.execute(
            """
            INSERT INTO query_runs (
                case_id, started_at, finished_at, success, error_message,
                error_code, duration_ms, trigger_type
            )
            VALUES (?, ?, ?, 0, 'Cloudflare blocked', ?, 1, 'automatic')
            """,
            (case["id"], now, now, CEAC_PROVIDER_BLOCKED_ERROR_CODE),
        )
        count = countRecentCeacFailureRuns(connection, int(case["id"]))

    assert count == 1


def test_provider_incident_admin_email_is_logged(createUser, monkeypatch) -> None:
    admin = createUser(email="admin@example.com", role="admin")
    sent: list[tuple[str, str, str]] = []

    def fakeSend(toEmail: str, subject: str, body: str, **_: object) -> bool:
        sent.append((toEmail, subject, body))
        return True

    monkeypatch.setattr("CEACStatusBot.web.mailer.sendSystemEmail", fakeSend)
    result = sendCeacProviderIncidentNotification(
        recovered=False,
        occurredAt=datetime.now(UTC).replace(microsecond=0).isoformat(),
        nextProbeAt=(datetime.now(UTC) + timedelta(hours=3)).replace(microsecond=0).isoformat(),
    )

    assert result == {"attempted": 1, "delivered": 1, "failed": 0}
    assert len(sent) == 1
    assert "Cloudflare" in sent[0][1]
    with getConnection() as connection:
        row = connection.execute(
            "SELECT user_id, email_type, subject FROM email_delivery_logs ORDER BY id DESC LIMIT 1",
        ).fetchone()
    assert row["user_id"] == admin["id"]
    assert row["email_type"] == "admin_ceac_provider_incident"
    assert "Cloudflare" in (decryptIfNeeded(row["subject"]) or "")
