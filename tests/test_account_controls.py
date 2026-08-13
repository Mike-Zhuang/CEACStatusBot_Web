from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from http.cookies import SimpleCookie

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from CEACStatusBot.web.account_controls import (
    createRiskGroup,
    enforceProfileCreationLimit,
    evaluateNewRegistrationAssociation,
    getQuotaScope,
    reviewAccountAppeal,
    submitAccountAppeal,
    suspendUserAccount,
)
from CEACStatusBot.web.config import getSettings
from CEACStatusBot.web.database import getConnection, initializeDatabase
from CEACStatusBot.web.ircc_portal_service import sendIrccNotification
from CEACStatusBot.web.mailer import (
    DailyEmailLimitExceeded,
    enforceDailyEmailLimit,
    recordEmailDelivery,
    sendAccountRestrictionEmail,
)
from CEACStatusBot.web.main import app, enforceDailyManualQueryLimit
from CEACStatusBot.web.security import SESSION_COOKIE_NAME, getCurrentUser, setSessionCookie
from CEACStatusBot.web.secrets import decryptIfNeeded


def nowIso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def buildRequest(cookie: str = "") -> Request:
    headers = [(b"user-agent", b"pytest")]
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE_NAME}={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/api/me", "headers": headers, "client": ("127.0.0.1", 1234)})


def sessionToken(user: dict) -> str:
    response = Response()
    setSessionCookie(response, user, buildRequest())
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    return cookies[SESSION_COOKIE_NAME].value


def insertCeacCase(connection, userId: int, *, suffix: str = "A") -> int:
    now = nowIso()
    cursor = connection.execute(
        """
        INSERT INTO ceac_cases (
            user_id, display_name, location, application_num, passport_number, surname,
            receive_email, is_enabled, next_check_at, created_at, updated_at
        )
        VALUES (?, ?, 'Shanghai', ?, ?, 'TEST', ?, 1, ?, ?, ?)
        """,
        (userId, f"CEAC {suffix}", f"AA00{suffix}", f"P0000{suffix}", f"user{suffix}@example.com", now, now, now),
    )
    return int(cursor.lastrowid)


def insertIrccCase(connection, userId: int) -> int:
    now = nowIso()
    accountCursor = connection.execute(
        """
        INSERT INTO ircc_portal_accounts (
            user_id, portal_email_encrypted, portal_password_encrypted, created_at, updated_at
        )
        VALUES (?, 'portal-email', 'portal-password', ?, ?)
        """,
        (userId, now, now),
    )
    caseCursor = connection.execute(
        """
        INSERT INTO ircc_cases (
            user_id, account_id, display_name, app_id, receive_email,
            is_enabled, next_check_at, created_at, updated_at
        )
        VALUES (?, ?, 'IRCC', 'app-id', 'user@example.com', 1, ?, ?, ?)
        """,
        (userId, accountCursor.lastrowid, now, now, now),
    )
    return int(caseCursor.lastrowid)


def insertKoreaCase(connection, userId: int) -> int:
    now = nowIso()
    cursor = connection.execute(
        """
        INSERT INTO korea_cases (
            user_id, display_name, passport_number, english_name, birth_date, receive_email,
            is_enabled, next_check_at, created_at, updated_at
        )
        VALUES (?, 'Korea', 'P0000000', 'TEST USER', '2000-01-01', 'user@example.com', 1, ?, ?, ?)
        """,
        (userId, now, now, now),
    )
    return int(cursor.lastrowid)


def test_initialize_database_is_idempotent_for_account_control_tables() -> None:
    initializeDatabase()
    initializeDatabase()
    with getConnection() as connection:
        userColumns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert {"account_status", "suspended_at", "suspension_reason", "suspension_note_encrypted"} <= userColumns
    assert {"account_risk_groups", "account_risk_group_members", "account_risk_flags", "account_appeals"} <= tables


def test_suspension_revokes_sessions_stops_all_monitoring_and_discards_queued_jobs(createUser) -> None:
    user = createUser()
    token = sessionToken(user)
    now = nowIso()
    with getConnection() as connection:
        ceacCaseId = insertCeacCase(connection, int(user["id"]))
        irccCaseId = insertIrccCase(connection, int(user["id"]))
        koreaCaseId = insertKoreaCase(connection, int(user["id"]))
        connection.execute(
            """
            INSERT INTO passport_slot_monitors (case_id, identifier_encrypted, is_enabled, next_check_at, created_at, updated_at)
            VALUES (?, 'identifier', 1, ?, ?, ?)
            """,
            (ceacCaseId, now, now, now),
        )
        connection.execute(
            "INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at) VALUES (?, 'automatic', 'queued', ?, ?)",
            (ceacCaseId, now, now),
        )
        connection.execute(
            "INSERT INTO ircc_query_jobs (case_id, trigger_type, status, created_at, updated_at) VALUES (?, 'ircc_automatic', 'queued', ?, ?)",
            (irccCaseId, now, now),
        )
        connection.execute(
            "INSERT INTO korea_query_jobs (case_id, trigger_type, status, created_at, updated_at) VALUES (?, 'korea_automatic', 'queued', ?, ?)",
            (koreaCaseId, now, now),
        )
        assert suspendUserAccount(connection, userId=int(user["id"]), reasonCode="test_restriction", adminNote="测试")

    with pytest.raises(HTTPException) as excInfo:
        getCurrentUser(buildRequest(token))
    assert excInfo.value.status_code == 401

    with getConnection() as connection:
        account = connection.execute("SELECT account_status FROM users WHERE id = ?", (user["id"],)).fetchone()
        ceac = connection.execute("SELECT is_enabled, next_check_at FROM ceac_cases WHERE id = ?", (ceacCaseId,)).fetchone()
        ircc = connection.execute("SELECT is_enabled, next_check_at FROM ircc_cases WHERE id = ?", (irccCaseId,)).fetchone()
        korea = connection.execute("SELECT is_enabled, next_check_at FROM korea_cases WHERE id = ?", (koreaCaseId,)).fetchone()
        monitor = connection.execute("SELECT is_enabled, next_check_at FROM passport_slot_monitors WHERE case_id = ?", (ceacCaseId,)).fetchone()
        jobStatuses = [
            connection.execute("SELECT status, error_message FROM query_jobs WHERE case_id = ?", (ceacCaseId,)).fetchone(),
            connection.execute("SELECT status, error_message FROM ircc_query_jobs WHERE case_id = ?", (irccCaseId,)).fetchone(),
            connection.execute("SELECT status, error_message FROM korea_query_jobs WHERE case_id = ?", (koreaCaseId,)).fetchone(),
        ]
    assert account["account_status"] == "suspended"
    for profile in (ceac, ircc, korea, monitor):
        assert profile["is_enabled"] == 0
        assert profile["next_check_at"] is None
    assert all(job["status"] == "failed" and "账号当前不可用" in job["error_message"] for job in jobStatuses)


def test_appeal_approval_restores_access_without_restarting_monitoring(createUser) -> None:
    user = createUser()
    admin = createUser(email="admin@example.com", role="admin")
    with getConnection() as connection:
        caseId = insertCeacCase(connection, int(user["id"]))
        assert suspendUserAccount(connection, userId=int(user["id"]), reasonCode="test_restriction")
        appeal = submitAccountAppeal(connection, userId=int(user["id"]), message="这是用于验证恢复通道的测试申诉说明。")
        reviewed = reviewAccountAppeal(
            connection,
            appealId=int(appeal["id"]),
            reviewerUserId=int(admin["id"]),
            decision="approved",
            reviewNote="已核实并恢复访问。",
            adminNote="测试处理。",
            removeFromEnforcedGroups=False,
        )
        account = connection.execute("SELECT account_status FROM users WHERE id = ?", (user["id"],)).fetchone()
        case = connection.execute("SELECT is_enabled, next_check_at FROM ceac_cases WHERE id = ?", (caseId,)).fetchone()
    assert reviewed and reviewed["status"] == "approved"
    assert account["account_status"] == "active"
    assert case["is_enabled"] == 0
    assert case["next_check_at"] is None


def test_enforced_linked_standard_accounts_share_profile_manual_and_email_limits(createUser) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    now = nowIso()
    with getConnection() as connection:
        caseId = insertCeacCase(connection, int(first["id"]))
        createRiskGroup(
            connection,
            userIds=[int(first["id"]), int(second["id"])],
            label="测试关联组",
            reasonCode="test_linked_accounts",
            adminNote="测试",
            createdByUserId=None,
            enforcementState="enforced",
            sharedStandardProfileLimit=1,
        )
        scope = getQuotaScope(connection, int(second["id"]))
        assert scope["scope"] == "linked_standard"
        assert set(scope["userIds"]) == {int(first["id"]), int(second["id"])}
        with pytest.raises(ValueError, match="关联账号"):
            enforceProfileCreationLimit(connection, int(second["id"]))
        connection.execute(
            "INSERT INTO query_jobs (case_id, trigger_type, status, created_at, updated_at) VALUES (?, 'manual', 'queued', ?, ?)",
            (caseId, now, now),
        )

    with pytest.raises(HTTPException) as queryError:
        enforceDailyManualQueryLimit(second)
    assert queryError.value.status_code == 429

    for index in range(5):
        recordEmailDelivery(
            userId=int(first["id"]),
            caseId=None,
            emailType="test",
            recipient="first@example.com",
            subject=f"test {index}",
        )
    with pytest.raises(DailyEmailLimitExceeded):
        enforceDailyEmailLimit(int(second["id"]))


def test_overlapping_enforced_groups_share_one_transitive_quota_scope(createUser) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    third = createUser(email="third@example.com")
    with getConnection() as connection:
        createRiskGroup(
            connection,
            userIds=[int(first["id"]), int(second["id"])],
            label="组一",
            reasonCode="test_overlap",
            adminNote="测试",
            createdByUserId=None,
            enforcementState="enforced",
        )
        createRiskGroup(
            connection,
            userIds=[int(second["id"]), int(third["id"])],
            label="组二",
            reasonCode="test_overlap",
            adminNote="测试",
            createdByUserId=None,
            enforcementState="enforced",
        )
        scope = getQuotaScope(connection, int(first["id"]))
    assert set(scope["userIds"]) == {int(first["id"]), int(second["id"]), int(third["id"])}


def test_ircc_email_respects_linked_account_daily_email_quota(createUser) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    with getConnection() as connection:
        createRiskGroup(
            connection,
            userIds=[int(first["id"]), int(second["id"])],
            label="IRCC 额度测试组",
            reasonCode="test_linked_accounts",
            adminNote="测试",
            createdByUserId=None,
            enforcementState="enforced",
        )
    for index in range(getSettings().standardDailyEmailLimit):
        recordEmailDelivery(
            userId=int(first["id"]),
            caseId=None,
            emailType="ceac_status",
            recipient=str(first["email"]),
            subject=f"普通通知 {index}",
        )
    with pytest.raises(DailyEmailLimitExceeded):
        sendIrccNotification(
            {
                "user_id": int(second["id"]),
                "sender_mode": "system",
                "receive_email": str(second["email"]),
            },
            None,
            "IRCC 测试通知",
            "用于验证关联账号邮件额度。",
        )


def test_repeated_device_registration_only_places_new_account_in_review(createUser) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    third = createUser(email="third@example.com")
    deviceHash = "same-device-hash"
    with getConnection() as connection:
        connection.execute(
            "UPDATE users SET terms_acceptance_device_hash = ? WHERE id IN (?, ?)",
            (deviceHash, first["id"], second["id"]),
        )
        assert evaluateNewRegistrationAssociation(
            connection,
            userId=int(third["id"]),
            deviceHash=deviceHash,
            ipHash="shared-ip-hash",
        )
        statuses = connection.execute(
            "SELECT id, account_status FROM users WHERE id IN (?, ?, ?) ORDER BY id",
            (first["id"], second["id"], third["id"]),
        ).fetchall()
        scope = getQuotaScope(connection, int(first["id"]))
        group = connection.execute(
            "SELECT enforcement_state FROM account_risk_groups ORDER BY id DESC LIMIT 1",
        ).fetchone()
    assert [row["account_status"] for row in statuses] == ["active", "active", "review"]
    assert scope["scope"] == "standard"
    assert group["enforcement_state"] == "review"


def test_restricted_account_can_submit_appeal_but_cannot_use_query_api(createUser) -> None:
    user = createUser()
    with getConnection() as connection:
        suspendUserAccount(connection, userId=int(user["id"]), reasonCode="test_restriction")

    client = TestClient(app, base_url="http://localhost")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost"},
        json={"email": user["email"], "password": "correct-password"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["account_status"] == "suspended"
    assert client.get("/api/me").status_code == 200
    assert client.get("/api/cases").status_code == 403
    appeal = client.post(
        "/api/account-appeals",
        headers={"Origin": "http://localhost"},
        json={"message": "这是用于验证受限账号申诉接口的说明。"},
    )
    assert appeal.status_code == 200
    assert appeal.json()["appeal"]["status"] == "pending"


def test_admin_restriction_sends_account_notice_after_the_database_change(createUser, monkeypatch) -> None:
    admin = createUser(email="admin@example.com", role="admin")
    target = createUser(email="target@example.com")
    notices: list[dict] = []

    def fakeNotice(**kwargs: object) -> bool:
        notices.append(dict(kwargs))
        return True

    monkeypatch.setattr("CEACStatusBot.web.main.sendAccountRestrictionEmail", fakeNotice)
    client = TestClient(app, base_url="http://localhost")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost"},
        json={"email": admin["email"], "password": "correct-password"},
    )
    assert login.status_code == 200
    response = client.post(
        f"/api/admin/users/{target['id']}/suspend",
        headers={"Origin": "http://localhost"},
        json={"reasonCode": "manual_review", "adminNote": "测试"},
    )
    assert response.status_code == 200
    assert len(notices) == 1
    assert notices[0]["userId"] == int(target["id"])
    assert notices[0]["recipient"] == str(target["email"])
    assert notices[0]["accountStatus"] == "suspended"
    assert notices[0]["restrictedAt"]
    with getConnection() as connection:
        row = connection.execute("SELECT account_status FROM users WHERE id = ?", (target["id"],)).fetchone()
    assert row["account_status"] == "suspended"


def test_admin_group_restriction_notifies_every_newly_restricted_member_after_commit(createUser, monkeypatch) -> None:
    admin = createUser(email="admin@example.com", role="admin")
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")
    notices: list[int] = []

    def fakeNotice(**kwargs: object) -> bool:
        userId = int(kwargs["userId"])
        with getConnection() as connection:
            row = connection.execute("SELECT account_status FROM users WHERE id = ?", (userId,)).fetchone()
        assert row and row["account_status"] == "suspended"
        notices.append(userId)
        return True

    monkeypatch.setattr("CEACStatusBot.web.main.sendAccountRestrictionEmail", fakeNotice)
    client = TestClient(app, base_url="http://localhost")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost"},
        json={"email": admin["email"], "password": "correct-password"},
    )
    assert login.status_code == 200
    response = client.post(
        "/api/admin/risk-groups",
        headers={"Origin": "http://localhost"},
        json={
            "userIds": [first["id"], second["id"]],
            "label": "测试关联限制组",
            "reasonCode": "test_linked_accounts",
            "adminNote": "测试",
            "enforcementState": "enforced",
            "sharedStandardProfileLimit": 1,
            "suspendMembers": True,
        },
    )
    assert response.status_code == 200
    assert set(notices) == {int(first["id"]), int(second["id"])}
    with getConnection() as connection:
        statuses = connection.execute(
            "SELECT account_status FROM users WHERE id IN (?, ?) ORDER BY id",
            (first["id"], second["id"]),
        ).fetchall()
    assert [row["account_status"] for row in statuses] == ["suspended", "suspended"]


def test_account_restriction_email_is_neutral_and_logged(createUser, monkeypatch) -> None:
    user = createUser()
    sent: list[tuple[str, str, str]] = []

    def fakeSend(toEmail: str, subject: str, body: str, **_: object) -> bool:
        sent.append((toEmail, subject, body))
        return True

    monkeypatch.setattr("CEACStatusBot.web.mailer.sendSystemEmail", fakeSend)
    assert sendAccountRestrictionEmail(
        userId=int(user["id"]),
        recipient=str(user["email"]),
        accountStatus="suspended",
        restrictedAt=nowIso(),
    )
    assert len(sent) == 1
    assert "风控依据" in sent[0][2]
    assert "申诉" in sent[0][2]
    with getConnection() as connection:
        row = connection.execute(
            "SELECT email_type, subject, body_encrypted FROM email_delivery_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    assert row["email_type"] == "account_restriction"
    assert "账号访问已受限" in (decryptIfNeeded(row["subject"]) or "")
    assert "档案和历史记录仍会保留" in (decryptIfNeeded(row["body_encrypted"]) or "")


def test_account_restriction_notice_does_not_consume_normal_email_quota(createUser) -> None:
    user = createUser()
    for index in range(getSettings().standardDailyEmailLimit):
        recordEmailDelivery(
            userId=int(user["id"]),
            caseId=None,
            emailType="account_restriction",
            recipient=str(user["email"]),
            subject=f"限制通知 {index}",
        )
    enforceDailyEmailLimit(int(user["id"]))


def test_legacy_users_table_receives_account_control_columns(tmp_path, monkeypatch, refreshTestSettings) -> None:
    legacyPath = tmp_path / "legacy.sqlite3"
    legacyConnection = sqlite3.connect(legacyPath)
    legacyConnection.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
    )
    legacyConnection.commit()
    legacyConnection.close()
    monkeypatch.setenv("DATABASE_PATH", str(legacyPath))
    refreshTestSettings()
    initializeDatabase()
    initializeDatabase()
    with getConnection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    assert {"account_status", "suspended_at", "suspension_reason", "suspension_note_encrypted"} <= columns
