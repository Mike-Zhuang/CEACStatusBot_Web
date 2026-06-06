#!/usr/bin/env python3
"""Seed a local-only database with rich UI review fixtures."""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = REPO_ROOT / ".local-review"
KEY_FILE = LOCAL_DIR / "credential-master.key"
DATABASE_FILE = LOCAL_DIR / "ui-review.sqlite3"

ADMIN_EMAIL = "admin@local.review"
ADMIN_PASSWORD = "ReviewAdmin!123"
USER_EMAIL = "user@local.review"
USER_PASSWORD = "ReviewUser!123"


def configureEnvironment() -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        KEY_FILE.write_text(base64.urlsafe_b64encode(os.urandom(32)).decode(), encoding="ascii")
    os.environ.setdefault("DATABASE_PATH", str(DATABASE_FILE))
    os.environ.setdefault("CREDENTIAL_KEY_FILE", str(KEY_FILE))
    os.environ.setdefault("SECRET_KEY", "local-ui-review-only-secret")
    os.environ.setdefault("COOKIE_SECURE", "false")
    os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
    os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")


def nowIso(minutesAgo: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutesAgo)).replace(microsecond=0).isoformat()


def buildIrccSnapshot(**overrides: object) -> dict[str, object]:
    appStatus: dict[str, object] = {
        "UpdatedDate": "2026-05-28T10:00:00.000Z",
        "applicationStatus": "A11",
        "eligibility": {"status": "E2", "timeStamp": None},
        "medical": {"status": "M1", "timeStamp": None},
        "additionalDocuments": {"status": "AD1", "timeStamp": None},
        "interviewOrAppointment": {"status": "IA1", "timeStamp": None},
        "biometricInformation": {"status": "B3", "timeStamp": "05/22/2026 18:22:23"},
        "backgroundChecks": {"status": "BC2", "timeStamp": None},
        "finalDecision": {"status": "FD1", "timeStamp": None},
        "processingTimeAvailable": True,
        "processingTimeBarTitle": "Processing time",
        "processingTimeBarMessage": "We are processing your application.",
        "estimatedCompletionDate": "2026-09-15",
        "estimatedRemainingProcessingTime": {"months": 2, "days": 10},
    }
    appStatus.update(overrides)
    return {
        "appStatus": appStatus,
        "applicationInfo": {
            "appStatus": "In progress",
            "updatedTimestamp": "2026-05-28T10:00:00.000Z",
            "applicant": {
                "fullName": "REVIEW APPLICANT",
                "uci": "1234-5678",
                "appNumber": "E123456789",
                "receivedDate": "2025-11-02",
                "biometricNumber": "BIO-7788",
                "biometricExpiryDate": "2026-11-02",
            },
        },
        "messages": [
            {
                "messageTag": "MSG1",
                "messageType": "Application update",
                "messageSubject": "We received your documents",
                "messageBody": "Your additional documents were received.",
            }
        ],
    }


def main() -> int:
    configureEnvironment()
    sys.path.insert(0, str(REPO_ROOT))

    from CEACStatusBot.web.config import getSettings
    from CEACStatusBot.web.database import getConnection, initializeDatabase
    from CEACStatusBot.web.ircc_portal_service import stableHash, normalizeSnapshot
    from CEACStatusBot.web.korea_visa_service import createKoreaCase
    from CEACStatusBot.web.passport_slot_service import upsertPassportSlotMonitor
    from CEACStatusBot.web.schemas import CeacCaseInput, KoreaCaseInput
    from CEACStatusBot.web.secrets import encryptSecret
    from CEACStatusBot.web.security import hashPassword
    from CEACStatusBot.web.case_service import createCase

    getSettings.cache_clear()

    if DATABASE_FILE.exists():
        DATABASE_FILE.unlink()
    initializeDatabase()

    now = nowIso()
    with getConnection() as connection:
        adminCursor = connection.execute(
            """
            INSERT INTO users (
                email, password_hash, role, account_tier, is_email_verified, worker_priority, created_at, updated_at
            )
            VALUES (?, ?, 'admin', 'premium', 1, 1, ?, ?)
            """,
            (ADMIN_EMAIL, hashPassword(ADMIN_PASSWORD), now, now),
        )
        userCursor = connection.execute(
            """
            INSERT INTO users (
                email, password_hash, role, account_tier, is_email_verified, worker_priority, created_at, updated_at
            )
            VALUES (?, ?, 'user', 'premium', 1, 50, ?, ?)
            """,
            (USER_EMAIL, hashPassword(USER_PASSWORD), now, now),
        )
        adminId = int(adminCursor.lastrowid)
        userId = int(userCursor.lastrowid)

    def ensureStatus(status: str, description: str = "") -> int:
        with getConnection() as connection:
            row = connection.execute(
                "SELECT id FROM status_catalog WHERE status = ? AND description = ?",
                (status, description),
            ).fetchone()
            if row:
                return int(row["id"])
            cursor = connection.execute(
                "INSERT INTO status_catalog (status, description, created_at) VALUES (?, ?, ?)",
                (status, description, nowIso()),
            )
            return int(cursor.lastrowid)

    def attachCeacStatus(caseId: int, status: str, description: str = "", *, minutesAgo: int = 0) -> None:
        statusId = ensureStatus(status, description)
        fetchedAt = nowIso(minutesAgo)
        with getConnection() as connection:
            connection.execute(
                """
                INSERT INTO case_status_history (
                    case_id, status_id, ceac_last_updated, visa_type, case_created, fetched_at, raw_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (caseId, statusId, fetchedAt, "B1/B2", "2024-01-15", fetchedAt, encryptSecret("{}")),
            )
            connection.execute(
                """
                UPDATE ceac_cases
                SET last_status_id = ?, last_checked_at = ?, last_trigger_type = 'automatic', next_check_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (statusId, fetchedAt, nowIso(-30), nowIso(), caseId),
            )

    issuedCase = createCase(
        userId,
        CeacCaseInput(
            displayName="US Issued",
            location="SHANGHAI",
            applicationNum="AA00ISSUED1",
            passportNumber="E12345678",
            surname="ZHANG",
            receiveEmail=USER_EMAIL,
            senderMode="system",
            isEnabled=True,
            emailNotificationsEnabled=True,
            smtpConfig=None,
        ),
    )
    refusedCase = createCase(
        userId,
        CeacCaseInput(
            displayName="US Refused",
            location="BEIJING",
            applicationNum="AA00REFUSE2",
            passportNumber="E87654321",
            surname="LI",
            receiveEmail=USER_EMAIL,
            senderMode="system",
            isEnabled=True,
            emailNotificationsEnabled=False,
            smtpConfig=None,
        ),
    )
    adminCase = createCase(
        adminId,
        CeacCaseInput(
            displayName="US Admin GTS",
            location="GUANGZHOU",
            applicationNum="AA00ADMIN3",
            passportNumber="G11223344",
            surname="WANG",
            receiveEmail=ADMIN_EMAIL,
            senderMode="system",
            isEnabled=True,
            emailNotificationsEnabled=True,
            smtpConfig=None,
        ),
    )

    attachCeacStatus(int(issuedCase["id"]), "Issued", "Your visa is in final processing")
    attachCeacStatus(int(refusedCase["id"]), "Refused", "Application was refused")
    attachCeacStatus(int(adminCase["id"]), "Administrative Processing", "Case is under review", minutesAgo=15)

    slotResult = {
        "slotStatus": "has_slot",
        "availableSlots": ["2026-06-12", "2026-06-13", "2026-06-14"],
        "statusMessage": "Eligible with available slots",
    }
    upsertPassportSlotMonitor(int(adminCase["id"]), adminId, "123456789", True, True)
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE passport_slot_monitors
            SET last_checked_at = ?, last_slot_count = 3, last_result_json = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (nowIso(5), encryptSecret(json.dumps(slotResult, ensure_ascii=False)), nowIso(), int(adminCase["id"])),
        )

    koreaReview = createKoreaCase(
        userId,
        KoreaCaseInput(
            displayName="KR Under review",
            passportNumber="M12345678",
            englishName="KIM REVIEW",
            birthDate="1998-03-21",
            receiveEmail=USER_EMAIL,
            senderMode="system",
            isEnabled=True,
            emailNotificationsEnabled=True,
            smtpConfig=None,
        ),
    )
    koreaIssued = createKoreaCase(
        userId,
        KoreaCaseInput(
            displayName="KR Issued",
            passportNumber="M87654321",
            englishName="PARK ISSUED",
            birthDate="1995-07-09",
            receiveEmail=USER_EMAIL,
            senderMode="system",
            isEnabled=False,
            emailNotificationsEnabled=False,
            smtpConfig=None,
        ),
    )
    with getConnection() as connection:
        connection.execute(
            """
            UPDATE korea_cases
            SET last_status = ?, last_application_no = ?, last_application_date = ?, last_entry_purpose = ?,
                last_checked_at = ?, last_trigger_type = 'korea_automatic', updated_at = ?
            WHERE id = ?
            """,
            ("审核中", "KR-APP-1001", "2026-02-01", "短期商务", nowIso(20), nowIso(), int(koreaReview["id"])),
        )
        connection.execute(
            """
            UPDATE korea_cases
            SET last_status = ?, last_visa_type = ?, last_stay_qualification = ?, last_entry_expiry_date = ?,
                last_visa_certificate_available = 1, last_checked_at = ?, last_trigger_type = 'korea_automatic', updated_at = ?
            WHERE id = ?
            """,
            ("签发 (2026.06.04.)", "多次", "C-3-9", "(2036.06.04.)", nowIso(40), nowIso(), int(koreaIssued["id"])),
        )
        for caseId, status, minutesAgo in (
            (int(koreaReview["id"]), "审核中", 20),
            (int(koreaIssued["id"]), "签发 (2026.06.04.)", 40),
        ):
            connection.execute(
                """
                INSERT INTO korea_status_history (
                    case_id, snapshot_hash, application_no, application_date, entry_purpose, visa_type, stay_qualification,
                    entry_expiry_date, visa_certificate_available, status, fetched_at, raw_payload, notification_sent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    caseId,
                    f"korea-review-{caseId}-{minutesAgo}",
                    "KR-APP-1001",
                    "2026-02-01",
                    "短期商务",
                    "多次" if "签发" in status else "",
                    "C-3-9" if "签发" in status else "",
                    "(2036.06.04.)" if "签发" in status else "",
                    1 if "签发" in status else 0,
                    status,
                    nowIso(minutesAgo),
                    encryptSecret("{}"),
                ),
            )

    pendingSnapshot = buildIrccSnapshot()
    approvedSnapshot = buildIrccSnapshot(
        finalDecision={"status": "FD6", "timeStamp": "05/28/2026"},
        applicationStatus="A2",
    )
    issuedStatusId = ensureStatus("Issued")

    with getConnection() as connection:
        accountCursor = connection.execute(
            """
            INSERT INTO ircc_portal_accounts (
                user_id, portal_email_encrypted, portal_password_encrypted, token_cache_encrypted,
                auth_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'ok', ?, ?)
            """,
            (
                userId,
                encryptSecret("review.portal@example.com"),
                encryptSecret("portal-password"),
                encryptSecret("{}"),
                now,
                now,
            ),
        )
        accountId = int(accountCursor.lastrowid)
        for displayName, appId, snapshot in (
            ("CA Pending review", "IRCC-PENDING-01", pendingSnapshot),
            ("CA Approved passport", "IRCC-APPROVED-02", approvedSnapshot),
        ):
            normalized = normalizeSnapshot(snapshot)
            payload = encryptSecret(json.dumps(normalized, ensure_ascii=False))
            snapshotHash = stableHash(normalized)
            caseCursor = connection.execute(
                """
                INSERT INTO ircc_cases (
                    user_id, account_id, display_name, app_id, application_number, principal_applicant,
                    receive_email, sender_mode, is_enabled, email_notifications_enabled,
                    sort_order, next_check_at, last_checked_at, last_trigger_type,
                    last_snapshot_hash, last_summary, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'system', 1, 1, 0, ?, ?, 'ircc_automatic', ?, ?, ?, ?)
                """,
                (
                    userId,
                    accountId,
                    displayName,
                    appId,
                    f"E-{appId[-2:]}123456",
                    "REVIEW APPLICANT",
                    encryptSecret(USER_EMAIL),
                    nowIso(-20),
                    nowIso(10),
                    snapshotHash,
                    "IRCC snapshot updated",
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO ircc_status_history (
                    case_id, snapshot_hash, application_status, application_info_status, message_count,
                    change_summary, fetched_at, raw_payload, notification_sent
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    int(caseCursor.lastrowid),
                    snapshotHash,
                    str(snapshot["appStatus"]["applicationStatus"]),
                    "In progress",
                    len(snapshot.get("messages", [])),
                    "Initial review seed",
                    nowIso(10),
                    payload,
                ),
            )

        connection.execute(
            """
            INSERT INTO query_runs (
                case_id, started_at, finished_at, success, status_id, error_message, duration_ms, trigger_type
            )
            VALUES (?, ?, ?, 1, ?, '', 842, 'automatic')
            """,
            (int(issuedCase["id"]), nowIso(12), nowIso(11), issuedStatusId),
        )
        connection.execute(
            """
            INSERT INTO query_runs (
                case_id, started_at, finished_at, success, error_message, duration_ms, trigger_type
            )
            VALUES (?, ?, ?, 0, 'Captcha recognition failed after retries', 1520, 'manual')
            """,
            (int(refusedCase["id"]), nowIso(8), nowIso(7)),
        )
        connection.execute(
            """
            INSERT INTO email_delivery_logs (
                user_id, case_id, email_type, recipient, subject, body_encrypted, created_at
            )
            VALUES (?, ?, 'status_change', ?, ?, ?, ?)
            """,
            (
                userId,
                int(issuedCase["id"]),
                USER_EMAIL,
                "CEAC status changed to Issued",
                encryptSecret("Your CEAC case status changed."),
                nowIso(6),
            ),
        )
        connection.execute(
            """
            INSERT INTO security_events (
                user_id, event_type, severity, actor_summary, path, detail, created_at
            )
            VALUES (?, 'login_success', 'info', ?, '/api/auth/login', 'UI review seed login', ?)
            """,
            (userId, USER_EMAIL, nowIso(3)),
        )

    print("UI review database ready.")
    print(f"Database: {DATABASE_FILE}")
    print(f"Credential key: {KEY_FILE}")
    print(f"Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"User:  {USER_EMAIL} / {USER_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
