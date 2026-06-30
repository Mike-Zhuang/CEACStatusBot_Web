from __future__ import annotations

import base64
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from CEACStatusBot.web.config import getSettings
from CEACStatusBot.web.database import getConnection, initializeDatabase
from CEACStatusBot.web.passport_slot_service import (
    PASSPORT_SLOT_EMPTY_FINGERPRINT,
    PASSPORT_SLOT_STATUS_HAS_SLOT,
    PASSPORT_SLOT_STATUS_NO_SLOT,
    computePassportSlotFingerprint,
    enqueueDuePassportSlotMonitors,
    runPassportSlotQuery,
    upsertPassportSlotMonitor,
)
from CEACStatusBot.web.secrets import getCredentialMasterKey
from CEACStatusBot.web.security import hashPassword


def refreshSettings() -> None:
    getSettings.cache_clear()
    getCredentialMasterKey.cache_clear()


class PassportSlotLongNoSlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempDirectory = tempfile.TemporaryDirectory()
        tempPath = Path(self.tempDirectory.name)
        keyPath = tempPath / "credential-master.key"
        keyPath.write_text(base64.urlsafe_b64encode(os.urandom(32)).decode(), encoding="ascii")
        os.environ["DATABASE_PATH"] = str(tempPath / "test.sqlite3")
        os.environ["SECRET_KEY"] = "test-secret-key"
        os.environ["CREDENTIAL_KEY_FILE"] = str(keyPath)
        os.environ["COOKIE_SECURE"] = "false"
        os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
        os.environ["CSRF_TRUSTED_ORIGINS"] = "http://localhost,http://127.0.0.1"
        os.environ["CORS_ORIGINS"] = "http://localhost,http://127.0.0.1"
        refreshSettings()
        initializeDatabase()
        self.userId = self.createUser()
        self.caseId = self.createCase(self.userId)
        upsertPassportSlotMonitor(self.caseId, self.userId, "141012288", True, True)

    def tearDown(self) -> None:
        self.tempDirectory.cleanup()
        refreshSettings()

    def createUser(self) -> int:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with getConnection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    email, password_hash, role, account_tier, is_email_verified, created_at, updated_at
                )
                VALUES ('user@example.com', ?, 'user', 'standard', 1, ?, ?)
                """,
                (hashPassword("correct-password"), now, now),
            )
            return int(cursor.lastrowid)

    def createCase(self, userId: int) -> int:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with getConnection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ceac_cases (
                    user_id, display_name, location, application_num, passport_number, surname,
                    receive_email, created_at, updated_at
                )
                VALUES (?, 'F1', 'Shanghai', 'AA00TEST', 'P0000000', 'TEST', 'user@example.com', ?, ?)
                """,
                (userId, now, now),
            )
            return int(cursor.lastrowid)

    def updateMonitor(self, **values: object) -> None:
        assignments = ", ".join(f"{key} = ?" for key in values)
        with getConnection() as connection:
            connection.execute(
                f"UPDATE passport_slot_monitors SET {assignments} WHERE case_id = ?",
                (*values.values(), self.caseId),
            )

    def getMonitor(self) -> dict:
        with getConnection() as connection:
            return connection.execute("SELECT * FROM passport_slot_monitors WHERE case_id = ?", (self.caseId,)).fetchone()

    def noSlotResult(self) -> dict:
        return {
            "success": True,
            "rateLimited": False,
            "slotStatus": PASSPORT_SLOT_STATUS_NO_SLOT,
            "statusMessage": "目前没有可用的预约，请稍后再试。",
            "availableSlots": [],
            "availableDates": [],
            "raw": {},
        }

    def hasSlotResult(self) -> dict:
        return {
            "success": True,
            "rateLimited": False,
            "slotStatus": PASSPORT_SLOT_STATUS_HAS_SLOT,
            "statusMessage": "发现可预约时间。",
            "availableSlots": [{"date": "2026-06-01", "times": ["09:00"]}],
            "availableDates": [{"date": "2026-06-01", "times": ["09:00"]}],
            "raw": {},
        }

    def test_no_notice_before_fifteen_days(self) -> None:
        createdAt = (datetime.now(UTC) - timedelta(days=14)).replace(microsecond=0).isoformat()
        self.updateMonitor(created_at=createdAt)

        with (
            patch("CEACStatusBot.web.passport_slot_service.fetchPassportSlotAvailability", return_value=self.noSlotResult()),
            patch("CEACStatusBot.web.passport_slot_service.sendPassportSlotLongNoSlotNoticeEmail") as noticeEmail,
        ):
            runPassportSlotQuery(self.caseId)

        monitor = self.getMonitor()
        self.assertIsNone(monitor["long_no_slot_notice_sent_at"])
        noticeEmail.assert_not_called()

    def test_notice_after_fifteen_days_and_schedule_low_frequency(self) -> None:
        createdAt = (datetime.now(UTC) - timedelta(days=16)).replace(microsecond=0).isoformat()
        self.updateMonitor(created_at=createdAt)

        with (
            patch("CEACStatusBot.web.passport_slot_service.fetchPassportSlotAvailability", return_value=self.noSlotResult()),
            patch("CEACStatusBot.web.passport_slot_service.sendPassportSlotLongNoSlotNoticeEmail") as noticeEmail,
            patch("CEACStatusBot.web.passport_slot_service.random.randint", return_value=60),
        ):
            runPassportSlotQuery(self.caseId)

        monitor = self.getMonitor()
        self.assertIsNotNone(monitor["long_no_slot_notice_sent_at"])
        self.assertIsNotNone(monitor["long_no_slot_stop_at"])
        noticeEmail.assert_called_once()
        lastCheckedAt = datetime.fromisoformat(monitor["last_checked_at"])
        nextCheckAt = datetime.fromisoformat(monitor["next_check_at"])
        self.assertEqual(timedelta(minutes=60), nextCheckAt - lastCheckedAt)

    def test_notice_not_repeated_during_grace_period(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        self.updateMonitor(
            created_at=(now - timedelta(days=16)).isoformat(),
            long_no_slot_notice_sent_at=(now - timedelta(days=1)).isoformat(),
            long_no_slot_stop_at=(now + timedelta(days=6)).isoformat(),
        )

        with (
            patch("CEACStatusBot.web.passport_slot_service.fetchPassportSlotAvailability", return_value=self.noSlotResult()),
            patch("CEACStatusBot.web.passport_slot_service.sendPassportSlotLongNoSlotNoticeEmail") as noticeEmail,
            patch("CEACStatusBot.web.passport_slot_service.random.randint", return_value=55),
        ):
            runPassportSlotQuery(self.caseId)

        monitor = self.getMonitor()
        noticeEmail.assert_not_called()
        lastCheckedAt = datetime.fromisoformat(monitor["last_checked_at"])
        nextCheckAt = datetime.fromisoformat(monitor["next_check_at"])
        self.assertEqual(timedelta(minutes=55), nextCheckAt - lastCheckedAt)

    def test_auto_stop_after_grace_period(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        self.updateMonitor(
            long_no_slot_notice_sent_at=(now - timedelta(days=8)).isoformat(),
            long_no_slot_stop_at=(now - timedelta(days=1)).isoformat(),
            next_check_at=(now - timedelta(minutes=1)).isoformat(),
            last_slot_fingerprint=PASSPORT_SLOT_EMPTY_FINGERPRINT,
            last_slot_count=0,
            last_result_json='{"slotStatus":"no_slot","availableSlots":[]}',
        )

        with patch("CEACStatusBot.web.passport_slot_service.sendPassportSlotLongNoSlotStoppedEmail") as stoppedEmail:
            queued = enqueueDuePassportSlotMonitors()

        monitor = self.getMonitor()
        self.assertEqual([], queued)
        self.assertEqual(0, monitor["is_enabled"])
        self.assertIsNone(monitor["next_check_at"])
        self.assertIsNotNone(monitor["long_no_slot_stopped_at"])
        stoppedEmail.assert_called_once()

    def test_has_slot_clears_long_no_slot_fields(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        self.updateMonitor(
            long_no_slot_notice_sent_at=(now - timedelta(days=1)).isoformat(),
            long_no_slot_stop_at=(now + timedelta(days=6)).isoformat(),
            last_slot_fingerprint=PASSPORT_SLOT_EMPTY_FINGERPRINT,
            last_slot_count=0,
            last_result_json='{"slotStatus":"no_slot","availableSlots":[]}',
        )

        with (
            patch("CEACStatusBot.web.passport_slot_service.fetchPassportSlotAvailability", return_value=self.hasSlotResult()),
            patch("CEACStatusBot.web.passport_slot_service.sendPassportSlotNotification"),
        ):
            runPassportSlotQuery(self.caseId)

        monitor = self.getMonitor()
        self.assertIsNone(monitor["long_no_slot_notice_sent_at"])
        self.assertIsNone(monitor["long_no_slot_stop_at"])
        self.assertIsNone(monitor["long_no_slot_stopped_at"])

    def test_positive_history_prevents_long_no_slot_notice(self) -> None:
        createdAt = (datetime.now(UTC) - timedelta(days=16)).replace(microsecond=0).isoformat()
        slotFingerprint = computePassportSlotFingerprint(PASSPORT_SLOT_STATUS_HAS_SLOT, [{"date": "2026-06-01"}])
        self.updateMonitor(created_at=createdAt)
        monitor = self.getMonitor()
        with getConnection() as connection:
            connection.execute(
                """
                INSERT INTO passport_slot_history (
                    monitor_id, case_id, slot_fingerprint, slot_count, raw_payload, fetched_at, notification_sent
                )
                VALUES (?, ?, ?, 1, '{}', ?, 1)
                """,
                (monitor["id"], self.caseId, slotFingerprint, createdAt),
            )

        with (
            patch("CEACStatusBot.web.passport_slot_service.fetchPassportSlotAvailability", return_value=self.noSlotResult()),
            patch("CEACStatusBot.web.passport_slot_service.sendPassportSlotLongNoSlotNoticeEmail") as noticeEmail,
        ):
            runPassportSlotQuery(self.caseId)

        monitor = self.getMonitor()
        self.assertIsNone(monitor["long_no_slot_notice_sent_at"])
        noticeEmail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
