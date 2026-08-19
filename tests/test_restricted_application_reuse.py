from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from CEACStatusBot.web.account_controls import (
    createRiskGroup,
    getLatestAccountAppeal,
    placeUserAccountUnderReview,
    reviewAccountAppeal,
    submitAccountAppeal,
    suspendUserAccount,
)
from CEACStatusBot.web.case_service import (
    RESTRICTED_APPLICATION_REUSE_REASON,
    RestrictedApplicationReuseError,
    createCase,
    getCase,
    migrateEncryptedFields,
    patchCase,
)
from CEACStatusBot.web.database import getConnection, utcNowIso
from CEACStatusBot.web.main import app
from CEACStatusBot.web.schemas import CeacCaseInput, CeacCasePatch
from CEACStatusBot.web.secrets import encryptSecret, hashSensitiveLookup


def caseInput(applicationNum: str) -> CeacCaseInput:
    return CeacCaseInput(
        displayName="测试档案",
        location="Shanghai",
        applicationNum=applicationNum,
        passportNumber="P1234567",
        surname="TEST",
        receiveEmail="notify@example.com",
        senderMode="system",
        isEnabled=False,
        emailNotificationsEnabled=True,
    )


def test_duplicate_application_from_active_account_is_allowed(createUser) -> None:
    first = createUser(email="first@example.com")
    second = createUser(email="second@example.com")

    firstCase = createCase(int(first["id"]), caseInput("AA00ACTIVE1"))
    secondCase = createCase(int(second["id"]), caseInput("AA00ACTIVE1"))

    assert firstCase["applicationNum"] == "AA00ACTIVE1"
    assert secondCase["applicationNum"] == "AA00ACTIVE1"
    with getConnection() as connection:
        secondStatus = connection.execute(
            "SELECT account_status FROM users WHERE id = ?",
            (second["id"],),
        ).fetchone()
    assert secondStatus["account_status"] == "active"


def test_application_from_enforced_group_requires_review_even_if_owner_is_active(createUser) -> None:
    confirmedOwner = createUser(email="confirmed@example.com")
    newcomer = createUser(email="newcomer@example.com")
    createCase(int(confirmedOwner["id"]), caseInput("AA00ENFORCED1"))
    with getConnection() as connection:
        createRiskGroup(
            connection,
            userIds=[int(confirmedOwner["id"])],
            label="确认关联组",
            reasonCode="confirmed_abuse",
            adminNote="测试",
            createdByUserId=None,
            enforcementState="enforced",
            suspendMembers=False,
        )

    with pytest.raises(RestrictedApplicationReuseError):
        createCase(int(newcomer["id"]), caseInput("AA00ENFORCED1"))

    with getConnection() as connection:
        status = connection.execute(
            "SELECT account_status FROM users WHERE id = ?",
            (newcomer["id"],),
        ).fetchone()
    assert status["account_status"] == "review"


def test_reusing_suspended_accounts_application_places_new_account_under_review(createUser) -> None:
    restrictedOwner = createUser(email="restricted@example.com")
    newcomer = createUser(email="newcomer@example.com")
    createCase(int(restrictedOwner["id"]), caseInput("AA00BLOCKED1"))
    with getConnection() as connection:
        suspendUserAccount(
            connection,
            userId=int(restrictedOwner["id"]),
            reasonCode="confirmed_abuse",
        )

    with pytest.raises(RestrictedApplicationReuseError):
        createCase(int(newcomer["id"]), caseInput("AA00BLOCKED1"))

    with getConnection() as connection:
        statuses = connection.execute(
            "SELECT id, account_status FROM users WHERE id IN (?, ?) ORDER BY id",
            (restrictedOwner["id"], newcomer["id"]),
        ).fetchall()
        newCaseCount = connection.execute(
            "SELECT COUNT(*) AS count FROM ceac_cases WHERE user_id = ?",
            (newcomer["id"],),
        ).fetchone()
        flag = connection.execute(
            "SELECT risk_level, reason_code FROM account_risk_flags WHERE user_id = ?",
            (newcomer["id"],),
        ).fetchone()
        group = connection.execute(
            """
            SELECT g.enforcement_state, g.reason_code, m.evidence_type, m.evidence_reference_hash
            FROM account_risk_groups g
            JOIN account_risk_group_members m ON m.group_id = g.id
            WHERE m.user_id = ?
            ORDER BY g.id DESC
            LIMIT 1
            """,
            (newcomer["id"],),
        ).fetchone()

    assert [row["account_status"] for row in statuses] == ["suspended", "review"]
    assert newCaseCount["count"] == 0
    assert dict(flag) == {"risk_level": "review", "reason_code": RESTRICTED_APPLICATION_REUSE_REASON}
    assert group["enforcement_state"] == "review"
    assert group["reason_code"] == RESTRICTED_APPLICATION_REUSE_REASON
    assert group["evidence_type"] == "reused_ceac_application"
    assert group["evidence_reference_hash"] == hashSensitiveLookup("AA00BLOCKED1")


def test_editing_case_cannot_bypass_restricted_application_rule(createUser) -> None:
    restrictedOwner = createUser(email="restricted@example.com")
    newcomer = createUser(email="newcomer@example.com")
    createCase(int(restrictedOwner["id"]), caseInput("AA00BLOCKED2"))
    newcomerCase = createCase(int(newcomer["id"]), caseInput("AA00ORIGINAL2"))
    with getConnection() as connection:
        suspendUserAccount(
            connection,
            userId=int(restrictedOwner["id"]),
            reasonCode="confirmed_abuse",
        )

    with pytest.raises(RestrictedApplicationReuseError):
        patchCase(
            int(newcomerCase["id"]),
            int(newcomer["id"]),
            CeacCasePatch(applicationNum="AA00BLOCKED2"),
        )

    unchanged = getCase(int(newcomerCase["id"]), int(newcomer["id"]))
    assert unchanged is not None
    assert unchanged["applicationNum"] == "AA00ORIGINAL2"
    with getConnection() as connection:
        account = connection.execute(
            "SELECT account_status FROM users WHERE id = ?",
            (newcomer["id"],),
        ).fetchone()
    assert account["account_status"] == "review"


def test_approved_appeal_allows_only_the_reviewed_application(createUser) -> None:
    restrictedOwner = createUser(email="restricted@example.com", accountTier="premium")
    newcomer = createUser(email="newcomer@example.com")
    admin = createUser(email="admin@example.com", role="admin")
    createCase(int(restrictedOwner["id"]), caseInput("AA00APPEAL1"))
    createCase(int(restrictedOwner["id"]), caseInput("AA00APPEAL2"))
    with getConnection() as connection:
        suspendUserAccount(
            connection,
            userId=int(restrictedOwner["id"]),
            reasonCode="confirmed_abuse",
        )

    with pytest.raises(RestrictedApplicationReuseError):
        createCase(int(newcomer["id"]), caseInput("AA00APPEAL1"))

    with getConnection() as connection:
        appeal = submitAccountAppeal(
            connection,
            userId=int(newcomer["id"]),
            message="我是申请人本人，希望审核后允许添加该档案。",
        )
        reviewAccountAppeal(
            connection,
            appealId=int(appeal["id"]),
            reviewerUserId=int(admin["id"]),
            decision="approved",
            reviewNote="已核实该申请归属。",
            adminNote="测试批准。",
            removeFromEnforcedGroups=False,
        )

    approvedCase = createCase(int(newcomer["id"]), caseInput("AA00APPEAL1"))
    assert approvedCase["applicationNum"] == "AA00APPEAL1"

    with pytest.raises(RestrictedApplicationReuseError):
        patchCase(
            int(approvedCase["id"]),
            int(newcomer["id"]),
            CeacCasePatch(applicationNum="AA00APPEAL2"),
        )


def test_admin_appeal_includes_verified_risk_evidence_counts(createUser) -> None:
    target = createUser(email="target@example.com")
    suspendedOwner = createUser(email="suspended@example.com")
    restoredOwner = createUser(email="restored@example.com")
    admin = createUser(email="admin@example.com", role="admin")
    for user in (target, suspendedOwner, restoredOwner):
        createCase(int(user["id"]), caseInput("AA00EVIDENCE1"))

    with getConnection() as connection:
        connection.execute(
            """
            UPDATE users
            SET terms_acceptance_device_hash = 'shared-device'
            WHERE id IN (?, ?, ?)
            """,
            (target["id"], suspendedOwner["id"], restoredOwner["id"]),
        )
        connection.execute(
            "UPDATE users SET terms_acceptance_ip_hash = 'shared-ip' WHERE id IN (?, ?)",
            (target["id"], suspendedOwner["id"]),
        )
        connection.execute(
            "UPDATE users SET terms_acceptance_ip_hash = 'different-ip' WHERE id = ?",
            (restoredOwner["id"],),
        )
        suspendUserAccount(
            connection,
            userId=int(suspendedOwner["id"]),
            reasonCode="confirmed_abuse",
        )
        suspendUserAccount(
            connection,
            userId=int(restoredOwner["id"]),
            reasonCode="temporary_review",
        )
        restoredAppeal = submitAccountAppeal(
            connection,
            userId=int(restoredOwner["id"]),
            message="这是用于验证恢复账号证据分类的申诉说明。",
        )
        reviewAccountAppeal(
            connection,
            appealId=int(restoredAppeal["id"]),
            reviewerUserId=int(admin["id"]),
            decision="approved",
            reviewNote="已核实并恢复。",
            adminNote="测试。",
            removeFromEnforcedGroups=False,
        )
        placeUserAccountUnderReview(
            connection,
            userId=int(target["id"]),
            reasonCode=RESTRICTED_APPLICATION_REUSE_REASON,
            adminNote="测试风险证据。",
        )
        submitAccountAppeal(
            connection,
            userId=int(target["id"]),
            message="这是用于验证管理员可见风险证据的申诉说明。",
        )
        appeal = getLatestAccountAppeal(connection, int(target["id"]), adminView=True)

    assert appeal is not None
    assert appeal["riskReasonCode"] == RESTRICTED_APPLICATION_REUSE_REASON
    assert appeal["riskEvidence"] == {
        "sameRegistrationDeviceAccountCount": 2,
        "sameRegistrationIpAccountCount": 1,
        "reusedApplicationSuspendedAccountCount": 1,
        "reusedApplicationRestoredAccountCount": 1,
        "reusedApplicationOtherAccountCount": 0,
    }


def test_restricted_application_api_notifies_user_and_administrator_after_commit(createUser, monkeypatch) -> None:
    restrictedOwner = createUser(email="restricted@example.com")
    newcomer = createUser(email="newcomer@example.com")
    createCase(int(restrictedOwner["id"]), caseInput("AA00BLOCKED3"))
    with getConnection() as connection:
        suspendUserAccount(
            connection,
            userId=int(restrictedOwner["id"]),
            reasonCode="confirmed_abuse",
        )

    userNotices: list[dict] = []
    adminAlerts: list[dict] = []

    def fakeUserNotice(**kwargs: object) -> bool:
        userNotices.append(dict(kwargs))
        return True

    def fakeAdminAlert(**kwargs: object) -> dict[str, int]:
        with getConnection() as connection:
            account = connection.execute(
                "SELECT account_status FROM users WHERE id = ?",
                (kwargs["targetUserId"],),
            ).fetchone()
        assert account and account["account_status"] == "review"
        adminAlerts.append(dict(kwargs))
        return {"attempted": 1, "delivered": 1, "failed": 0}

    monkeypatch.setattr("CEACStatusBot.web.main.sendAccountRestrictionEmail", fakeUserNotice)
    monkeypatch.setattr("CEACStatusBot.web.main.sendAdministratorAccountAlert", fakeAdminAlert)

    client = TestClient(app, base_url="http://localhost")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost"},
        json={"email": newcomer["email"], "password": "correct-password"},
    )
    assert login.status_code == 200
    response = client.post(
        "/api/cases",
        headers={"Origin": "http://localhost"},
        json=caseInput("AA00BLOCKED3").model_dump(mode="json"),
    )

    assert response.status_code == 403
    assert "人工审核" in response.json()["detail"]
    assert len(userNotices) == 1
    assert len(adminAlerts) == 1
    assert adminAlerts[0]["alertType"] == "automatic_restriction"
    assert adminAlerts[0]["reasonCode"] == RESTRICTED_APPLICATION_REUSE_REASON


def test_migration_backfills_restricted_application_lookup_hashes(createUser) -> None:
    user = createUser()
    now = utcNowIso()
    with getConnection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO ceac_cases (
                user_id, display_name, location, application_num, passport_number, surname,
                receive_email, is_enabled, created_at, updated_at
            )
            VALUES (?, '旧档案', 'Shanghai', ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                user["id"],
                encryptSecret("AA00LEGACY1"),
                encryptSecret("P7654321"),
                encryptSecret("TEST"),
                encryptSecret("notify@example.com"),
                now,
                now,
            ),
        )

    migrateEncryptedFields()

    with getConnection() as connection:
        row = connection.execute(
            """
            SELECT application_num_hash, passport_number_hash, surname_hash
            FROM ceac_cases WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    assert row["application_num_hash"] == hashSensitiveLookup("AA00LEGACY1")
    assert row["passport_number_hash"] == hashSensitiveLookup("P7654321")
    assert row["surname_hash"] == hashSensitiveLookup("TEST")
