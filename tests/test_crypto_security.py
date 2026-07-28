from __future__ import annotations

import base64
import os

import pytest

from CEACStatusBot.web.case_service import migrateEncryptedFields
from CEACStatusBot.web.config import getSettings
from CEACStatusBot.web.database import getConnection, utcNowIso
from CEACStatusBot.web.ircc_portal_service import getIrccCase, patchIrccCase
from CEACStatusBot.web.mailer import recordEmailDelivery
from CEACStatusBot.web.schemas import IrccCasePatch
from CEACStatusBot.web.secrets import (
    decryptIfNeeded,
    decryptSecret,
    encryptSecret,
    getCredentialMasterKey,
    hashSensitiveLookup,
    isEncryptedSecret,
)


def test_aes_gcm_ciphertext_does_not_contain_plaintext() -> None:
    ciphertext = encryptSecret("portal-password-123")

    assert ciphertext.startswith("v2:")
    assert "portal-password-123" not in ciphertext
    assert decryptSecret(ciphertext) == "portal-password-123"


def test_wrong_master_key_cannot_decrypt(monkeypatch: pytest.MonkeyPatch, tmp_path, refreshTestSettings) -> None:
    ciphertext = encryptSecret("sensitive-value")
    nextKeyPath = tmp_path / "different.key"
    nextKeyPath.write_text(base64.urlsafe_b64encode(os.urandom(32)).decode(), encoding="ascii")
    monkeypatch.setenv("CREDENTIAL_KEY_FILE", str(nextKeyPath))
    refreshTestSettings()

    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        decryptSecret(ciphertext)


def test_legacy_fernet_ciphertext_remains_decryptable() -> None:
    ciphertext = getSettings().getFernet().encrypt(b"legacy-value").decode()

    assert decryptSecret(ciphertext) == "legacy-value"


def test_secure_cookie_mode_requires_repository_external_key(monkeypatch: pytest.MonkeyPatch, refreshTestSettings) -> None:
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("CREDENTIAL_KEY_FILE", "")
    refreshTestSettings()

    with pytest.raises(RuntimeError, match="CREDENTIAL_KEY_FILE"):
        getCredentialMasterKey()


def test_sensitive_lookup_hash_is_stable_and_keyed() -> None:
    first = hashSensitiveLookup("User@Example.com")
    second = hashSensitiveLookup(" user@example.com ")

    assert first == second
    assert first.startswith("h1:")
    assert "user@example.com" not in first


def test_sensitive_metadata_migration_preserves_api_values_without_creating_email_logs(createUser) -> None:
    user = createUser(accountTier="premium")
    now = utcNowIso()
    with getConnection() as connection:
        accountCursor = connection.execute(
            """
            INSERT INTO ircc_portal_accounts (
                user_id, portal_email_encrypted, portal_password_encrypted, token_cache_encrypted,
                created_at, updated_at
            )
            VALUES (?, ?, ?, '', ?, ?)
            """,
            (
                user["id"],
                encryptSecret("portal@example.com"),
                encryptSecret("portal-password"),
                now,
                now,
            ),
        )
        caseCursor = connection.execute(
            """
            INSERT INTO ircc_cases (
                user_id, account_id, display_name, app_id, application_number, principal_applicant,
                receive_email, last_summary, created_at, updated_at
            )
            VALUES (?, ?, 'IRCC profile', '12345678', 'V000000000', 'TEST USER',
                    'notify@example.com', '状态摘要', ?, ?)
            """,
            (user["id"], accountCursor.lastrowid, now, now),
        )
        connection.execute(
            """
            INSERT INTO ircc_status_history (
                case_id, snapshot_hash, change_summary, fetched_at, raw_payload
            )
            VALUES (?, 'hash', '最终决定发生变化', ?, ?)
            """,
            (caseCursor.lastrowid, now, encryptSecret("{}")),
        )
        connection.execute(
            """
            INSERT INTO email_verification_codes (email, code_hash, purpose, expires_at, created_at)
            VALUES ('pending@example.com', 'hash', 'register', ?, ?)
            """,
            (now, now),
        )

    recordEmailDelivery(
        userId=int(user["id"]),
        caseId=None,
        emailType="ircc_status",
        recipient="notify@example.com",
        subject="[IRCC Alpha] 状态更新",
        body="邮件正文",
    )
    migrateEncryptedFields()

    with getConnection() as connection:
        caseRow = connection.execute("SELECT * FROM ircc_cases WHERE id = ?", (caseCursor.lastrowid,)).fetchone()
        historyRow = connection.execute(
            "SELECT change_summary FROM ircc_status_history WHERE case_id = ?",
            (caseCursor.lastrowid,),
        ).fetchone()
        verificationRow = connection.execute("SELECT email FROM email_verification_codes").fetchone()
        emailLog = connection.execute("SELECT recipient, subject, body_encrypted FROM email_delivery_logs").fetchone()
        emailLogCount = connection.execute("SELECT COUNT(*) AS count FROM email_delivery_logs").fetchone()

    assert all(
        isEncryptedSecret(caseRow[column])
        for column in ("app_id", "application_number", "principal_applicant", "receive_email", "last_summary")
    )
    assert decryptIfNeeded(historyRow["change_summary"]) == "最终决定发生变化"
    assert verificationRow["email"] == hashSensitiveLookup("pending@example.com")
    assert decryptIfNeeded(emailLog["recipient"]) == "notify@example.com"
    assert decryptIfNeeded(emailLog["subject"]) == "[IRCC Alpha] 状态更新"
    assert decryptIfNeeded(emailLog["body_encrypted"]) == "邮件正文"
    assert emailLogCount["count"] == 1

    case = getIrccCase(int(caseCursor.lastrowid), int(user["id"]))
    assert case is not None
    assert case["appId"] == "12345678"
    assert case["applicationNumber"] == "V000000000"
    assert case["principalApplicant"] == "TEST USER"
    assert case["receiveEmail"] == "notify@example.com"


def test_encrypted_ircc_app_id_remains_unique_when_case_is_edited(createUser) -> None:
    user = createUser(accountTier="premium")
    now = utcNowIso()
    with getConnection() as connection:
        accountCursor = connection.execute(
            """
            INSERT INTO ircc_portal_accounts (
                user_id, portal_email_encrypted, portal_password_encrypted, token_cache_encrypted,
                created_at, updated_at
            )
            VALUES (?, ?, ?, '', ?, ?)
            """,
            (
                user["id"],
                encryptSecret("portal@example.com"),
                encryptSecret("portal-password"),
                now,
                now,
            ),
        )
        caseIds = []
        for displayName, appId in (("First", "10000001"), ("Second", "10000002")):
            cursor = connection.execute(
                """
                INSERT INTO ircc_cases (
                    user_id, account_id, display_name, app_id, receive_email,
                    email_notifications_enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, '', 0, ?, ?)
                """,
                (user["id"], accountCursor.lastrowid, displayName, encryptSecret(appId), now, now),
            )
            caseIds.append(int(cursor.lastrowid))

    with pytest.raises(ValueError, match="该 IRCC 申请已经存在"):
        patchIrccCase(caseIds[0], int(user["id"]), IrccCasePatch(appId="10000002"))

    unchanged = getIrccCase(caseIds[0], int(user["id"]))
    assert unchanged is not None
    assert unchanged["appId"] == "10000001"
