import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import getSettings


def utcNowIso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def dictFactory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    fields = [column[0] for column in cursor.description]
    return {key: row[index] for index, key in enumerate(fields)}


@contextmanager
def getConnection() -> Iterator[sqlite3.Connection]:
    databasePath = getSettings().databasePath
    databasePath.parent.mkdir(parents=True, exist_ok=True)
    # Web 请求、调度器和 Worker 会同时写入 SQLite。给短暂写锁留出等待时间，
    # 避免瞬时竞争直接变成对用户可见的 "database is locked"。
    connection = sqlite3.connect(databasePath, timeout=20)
    connection.row_factory = dictFactory
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 20000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initializeDatabase() -> None:
    with getConnection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                account_tier TEXT NOT NULL DEFAULT 'standard',
                worker_priority INTEGER NOT NULL DEFAULT 100,
                is_email_verified INTEGER NOT NULL DEFAULT 0,
                terms_version TEXT NOT NULL DEFAULT '',
                terms_accepted_at TEXT,
                terms_acceptance_ip_hash TEXT NOT NULL DEFAULT '',
                terms_acceptance_device_hash TEXT NOT NULL DEFAULT '',
                has_application_profile_history INTEGER NOT NULL DEFAULT 0,
                inactivity_notice_sent_at TEXT,
                timezone TEXT NOT NULL DEFAULT '',
                account_status TEXT NOT NULL DEFAULT 'active',
                suspended_at TEXT,
                suspension_reason TEXT NOT NULL DEFAULT '',
                suspension_note_encrypted TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                device_hash TEXT NOT NULL DEFAULT '',
                ip_hash TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rate_limit_counters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                subject_hash TEXT NOT NULL,
                window_start TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(scope, subject_hash, window_start)
            );

            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                user_id INTEGER,
                email_hash TEXT NOT NULL DEFAULT '',
                ip_hash TEXT NOT NULL DEFAULT '',
                device_hash TEXT NOT NULL DEFAULT '',
                actor_summary TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS email_verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                purpose TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS smtp_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                from_email TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                use_ssl INTEGER NOT NULL DEFAULT 1,
                password_encrypted TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS system_smtp_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                from_email TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                use_ssl INTEGER NOT NULL DEFAULT 1,
                password_encrypted TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ceac_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                location TEXT NOT NULL,
                application_num TEXT NOT NULL,
                application_num_hash TEXT NOT NULL DEFAULT '',
                passport_number TEXT NOT NULL,
                passport_number_hash TEXT NOT NULL DEFAULT '',
                surname TEXT NOT NULL,
                surname_hash TEXT NOT NULL DEFAULT '',
                receive_email TEXT NOT NULL,
                sender_mode TEXT NOT NULL DEFAULT 'system',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                ceac_auto_locked_by_passport_slot INTEGER NOT NULL DEFAULT 0,
                ceac_consecutive_error_count INTEGER NOT NULL DEFAULT 0,
                ceac_error_notice_sent_at TEXT,
                ceac_failure_slow_started_at TEXT,
                email_notifications_enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                next_check_at TEXT,
                last_checked_at TEXT,
                last_trigger_type TEXT,
                last_status_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (last_status_id) REFERENCES status_catalog(id)
            );

            CREATE TABLE IF NOT EXISTS status_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(status, description)
            );

            CREATE TABLE IF NOT EXISTS case_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                status_id INTEGER NOT NULL,
                ceac_last_updated TEXT NOT NULL DEFAULT '',
                visa_type TEXT NOT NULL DEFAULT '',
                case_created TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES ceac_cases(id) ON DELETE CASCADE,
                FOREIGN KEY (status_id) REFERENCES status_catalog(id)
            );

            CREATE TABLE IF NOT EXISTS query_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                success INTEGER NOT NULL,
                status_id INTEGER,
                error_message TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                trigger_type TEXT NOT NULL DEFAULT 'unknown',
                FOREIGN KEY (case_id) REFERENCES ceac_cases(id) ON DELETE CASCADE,
                FOREIGN KEY (status_id) REFERENCES status_catalog(id)
            );

            CREATE TABLE IF NOT EXISTS query_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                locked_at TEXT,
                locked_by TEXT,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES ceac_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS passport_slot_monitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL UNIQUE,
                identifier_encrypted TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                email_notifications_enabled INTEGER NOT NULL DEFAULT 1,
                next_check_at TEXT,
                last_checked_at TEXT,
                last_slot_fingerprint TEXT NOT NULL DEFAULT '',
                last_slot_count INTEGER NOT NULL DEFAULT 0,
                last_result_json TEXT NOT NULL DEFAULT '',
                last_error_message TEXT NOT NULL DEFAULT '',
                long_no_slot_notice_sent_at TEXT,
                long_no_slot_stop_at TEXT,
                long_no_slot_stopped_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES ceac_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS passport_slot_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id INTEGER NOT NULL,
                case_id INTEGER NOT NULL,
                slot_fingerprint TEXT NOT NULL,
                slot_count INTEGER NOT NULL DEFAULT 0,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                notification_sent INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (monitor_id) REFERENCES passport_slot_monitors(id) ON DELETE CASCADE,
                FOREIGN KEY (case_id) REFERENCES ceac_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ircc_portal_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                portal_email_encrypted TEXT NOT NULL,
                portal_password_encrypted TEXT NOT NULL,
                token_cache_encrypted TEXT NOT NULL DEFAULT '',
                auth_status TEXT NOT NULL DEFAULT 'unknown',
                last_auth_error TEXT NOT NULL DEFAULT '',
                last_authenticated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, portal_email_encrypted)
            );

            CREATE TABLE IF NOT EXISTS ircc_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                app_id TEXT NOT NULL,
                application_number TEXT NOT NULL DEFAULT '',
                principal_applicant TEXT NOT NULL DEFAULT '',
                receive_email TEXT NOT NULL,
                sender_mode TEXT NOT NULL DEFAULT 'system',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                email_notifications_enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                next_check_at TEXT,
                last_checked_at TEXT,
                last_trigger_type TEXT,
                last_snapshot_hash TEXT NOT NULL DEFAULT '',
                last_summary TEXT NOT NULL DEFAULT '',
                last_error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (account_id) REFERENCES ircc_portal_accounts(id) ON DELETE CASCADE,
                UNIQUE(user_id, app_id)
            );

            CREATE TABLE IF NOT EXISTS ircc_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                snapshot_hash TEXT NOT NULL,
                application_status TEXT NOT NULL DEFAULT '',
                application_info_status TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                change_summary TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                notification_sent INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (case_id) REFERENCES ircc_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ircc_query_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                success INTEGER NOT NULL,
                error_message TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                trigger_type TEXT NOT NULL DEFAULT 'unknown',
                FOREIGN KEY (case_id) REFERENCES ircc_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ircc_query_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                locked_at TEXT,
                locked_by TEXT,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES ircc_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS korea_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                display_name TEXT NOT NULL,
                passport_number TEXT NOT NULL,
                english_name TEXT NOT NULL,
                birth_date TEXT NOT NULL,
                receive_email TEXT NOT NULL,
                sender_mode TEXT NOT NULL DEFAULT 'system',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                email_notifications_enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                next_check_at TEXT,
                last_checked_at TEXT,
                last_trigger_type TEXT,
                last_snapshot_hash TEXT NOT NULL DEFAULT '',
                last_application_no TEXT NOT NULL DEFAULT '',
                last_application_date TEXT NOT NULL DEFAULT '',
                last_entry_purpose TEXT NOT NULL DEFAULT '',
                last_visa_type TEXT NOT NULL DEFAULT '',
                last_stay_qualification TEXT NOT NULL DEFAULT '',
                last_entry_expiry_date TEXT NOT NULL DEFAULT '',
                last_visa_certificate_available INTEGER NOT NULL DEFAULT 0,
                last_status TEXT NOT NULL DEFAULT '',
                last_error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, passport_number, english_name, birth_date)
            );

            CREATE TABLE IF NOT EXISTS korea_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                snapshot_hash TEXT NOT NULL,
                application_no TEXT NOT NULL DEFAULT '',
                application_date TEXT NOT NULL DEFAULT '',
                entry_purpose TEXT NOT NULL DEFAULT '',
                visa_type TEXT NOT NULL DEFAULT '',
                stay_qualification TEXT NOT NULL DEFAULT '',
                entry_expiry_date TEXT NOT NULL DEFAULT '',
                visa_certificate_available INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                notification_sent INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (case_id) REFERENCES korea_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS korea_query_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                success INTEGER NOT NULL,
                error_message TEXT NOT NULL DEFAULT '',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                trigger_type TEXT NOT NULL DEFAULT 'unknown',
                FOREIGN KEY (case_id) REFERENCES korea_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS korea_query_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                locked_at TEXT,
                locked_by TEXT,
                started_at TEXT,
                finished_at TEXT,
                error_message TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES korea_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS email_delivery_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                case_id INTEGER,
                email_type TEXT NOT NULL DEFAULT 'case',
                recipient TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                body_encrypted TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (case_id) REFERENCES ceac_cases(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS account_risk_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                reason_code TEXT NOT NULL DEFAULT '',
                admin_note_encrypted TEXT NOT NULL DEFAULT '',
                enforcement_state TEXT NOT NULL DEFAULT 'review',
                shared_standard_profile_limit INTEGER NOT NULL DEFAULT 1,
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS account_risk_group_members (
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                evidence_type TEXT NOT NULL DEFAULT 'admin_review',
                evidence_reference_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY (group_id, user_id),
                FOREIGN KEY (group_id) REFERENCES account_risk_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS account_risk_flags (
                user_id INTEGER PRIMARY KEY,
                risk_level TEXT NOT NULL DEFAULT 'review',
                reason_code TEXT NOT NULL DEFAULT '',
                admin_note_encrypted TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS account_appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                message_encrypted TEXT NOT NULL,
                review_note_encrypted TEXT NOT NULL DEFAULT '',
                admin_note_encrypted TEXT NOT NULL DEFAULT '',
                submitted_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by_user_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_email_delivery_logs_user_created
            ON email_delivery_logs(user_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_user_sessions_token
            ON user_sessions(token_hash);

            CREATE INDEX IF NOT EXISTS idx_security_events_created
            ON security_events(created_at);

            CREATE INDEX IF NOT EXISTS idx_rate_limit_counters_expires
            ON rate_limit_counters(expires_at);

            CREATE INDEX IF NOT EXISTS idx_ircc_cases_due
            ON ircc_cases(is_enabled, next_check_at);

            CREATE INDEX IF NOT EXISTS idx_ircc_query_jobs_status
            ON ircc_query_jobs(status, created_at);

            CREATE INDEX IF NOT EXISTS idx_korea_cases_due
            ON korea_cases(is_enabled, next_check_at);

            CREATE INDEX IF NOT EXISTS idx_korea_query_jobs_status
            ON korea_query_jobs(status, created_at);

            CREATE INDEX IF NOT EXISTS idx_account_risk_group_members_user
            ON account_risk_group_members(user_id, group_id);

            CREATE INDEX IF NOT EXISTS idx_account_appeals_user_status
            ON account_appeals(user_id, status, id DESC);
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(ceac_cases)").fetchall()
        }
        userColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "worker_priority" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN worker_priority INTEGER NOT NULL DEFAULT 100",
            )
        if "account_tier" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN account_tier TEXT NOT NULL DEFAULT 'standard'",
            )
        if "terms_version" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN terms_version TEXT NOT NULL DEFAULT ''",
            )
        if "terms_accepted_at" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN terms_accepted_at TEXT",
            )
        if "terms_acceptance_ip_hash" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN terms_acceptance_ip_hash TEXT NOT NULL DEFAULT ''",
            )
        if "terms_acceptance_device_hash" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN terms_acceptance_device_hash TEXT NOT NULL DEFAULT ''",
            )
        if "has_application_profile_history" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN has_application_profile_history INTEGER NOT NULL DEFAULT 0",
            )
        if "inactivity_notice_sent_at" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN inactivity_notice_sent_at TEXT",
            )
        if "timezone" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT ''",
            )
        if "account_status" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active'",
            )
        if "suspended_at" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN suspended_at TEXT",
            )
        if "suspension_reason" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN suspension_reason TEXT NOT NULL DEFAULT ''",
            )
        if "suspension_note_encrypted" not in userColumns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN suspension_note_encrypted TEXT NOT NULL DEFAULT ''",
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_account_status ON users(account_status)",
        )
        connection.execute(
            """
            UPDATE users
            SET has_application_profile_history = 1
            WHERE has_application_profile_history = 0
              AND (
                  EXISTS (SELECT 1 FROM ceac_cases c WHERE c.user_id = users.id)
                  OR EXISTS (SELECT 1 FROM ircc_cases ic WHERE ic.user_id = users.id)
                  OR EXISTS (SELECT 1 FROM korea_cases kc WHERE kc.user_id = users.id)
              )
            """,
        )
        if "email_notifications_enabled" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN email_notifications_enabled INTEGER NOT NULL DEFAULT 1",
            )
        if "sort_order" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
            )
        if "ceac_auto_locked_by_passport_slot" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN ceac_auto_locked_by_passport_slot INTEGER NOT NULL DEFAULT 0",
            )
        if "ceac_consecutive_error_count" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN ceac_consecutive_error_count INTEGER NOT NULL DEFAULT 0",
            )
        if "ceac_error_notice_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN ceac_error_notice_sent_at TEXT",
            )
        if "ceac_failure_slow_started_at" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN ceac_failure_slow_started_at TEXT",
            )
        if "last_trigger_type" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN last_trigger_type TEXT",
            )
        if "application_num_hash" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN application_num_hash TEXT NOT NULL DEFAULT ''",
            )
        if "passport_number_hash" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN passport_number_hash TEXT NOT NULL DEFAULT ''",
            )
        if "surname_hash" not in columns:
            connection.execute(
                "ALTER TABLE ceac_cases ADD COLUMN surname_hash TEXT NOT NULL DEFAULT ''",
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ceac_cases_application_num_hash ON ceac_cases(application_num_hash)",
        )
        irccColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(ircc_cases)").fetchall()
        }
        if "sort_order" not in irccColumns:
            connection.execute(
                "ALTER TABLE ircc_cases ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
            )
        koreaCaseColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(korea_cases)").fetchall()
        }
        if "last_visa_type" not in koreaCaseColumns:
            connection.execute(
                "ALTER TABLE korea_cases ADD COLUMN last_visa_type TEXT NOT NULL DEFAULT ''",
            )
        if "last_stay_qualification" not in koreaCaseColumns:
            connection.execute(
                "ALTER TABLE korea_cases ADD COLUMN last_stay_qualification TEXT NOT NULL DEFAULT ''",
            )
        if "last_entry_expiry_date" not in koreaCaseColumns:
            connection.execute(
                "ALTER TABLE korea_cases ADD COLUMN last_entry_expiry_date TEXT NOT NULL DEFAULT ''",
            )
        if "last_visa_certificate_available" not in koreaCaseColumns:
            connection.execute(
                "ALTER TABLE korea_cases ADD COLUMN last_visa_certificate_available INTEGER NOT NULL DEFAULT 0",
            )
        koreaHistoryColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(korea_status_history)").fetchall()
        }
        if "visa_type" not in koreaHistoryColumns:
            connection.execute(
                "ALTER TABLE korea_status_history ADD COLUMN visa_type TEXT NOT NULL DEFAULT ''",
            )
        if "stay_qualification" not in koreaHistoryColumns:
            connection.execute(
                "ALTER TABLE korea_status_history ADD COLUMN stay_qualification TEXT NOT NULL DEFAULT ''",
            )
        if "entry_expiry_date" not in koreaHistoryColumns:
            connection.execute(
                "ALTER TABLE korea_status_history ADD COLUMN entry_expiry_date TEXT NOT NULL DEFAULT ''",
            )
        if "visa_certificate_available" not in koreaHistoryColumns:
            connection.execute(
                "ALTER TABLE korea_status_history ADD COLUMN visa_certificate_available INTEGER NOT NULL DEFAULT 0",
            )
        emailDeliveryLogColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(email_delivery_logs)").fetchall()
        }
        if "body_encrypted" not in emailDeliveryLogColumns:
            connection.execute(
                "ALTER TABLE email_delivery_logs ADD COLUMN body_encrypted TEXT NOT NULL DEFAULT ''",
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ceac_cases_user_sort ON ceac_cases(user_id, sort_order, updated_at)",
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_ircc_cases_user_sort ON ircc_cases(user_id, sort_order, updated_at)",
        )
        queryRunColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(query_runs)").fetchall()
        }
        if "trigger_type" not in queryRunColumns:
            connection.execute(
                "ALTER TABLE query_runs ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'unknown'",
            )
        queryJobColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(query_jobs)").fetchall()
        }
        if "result_json" not in queryJobColumns:
            connection.execute(
                "ALTER TABLE query_jobs ADD COLUMN result_json TEXT NOT NULL DEFAULT ''",
            )
        passportSlotMonitorColumns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(passport_slot_monitors)").fetchall()
        }
        if "email_notifications_enabled" not in passportSlotMonitorColumns:
            connection.execute(
                "ALTER TABLE passport_slot_monitors ADD COLUMN email_notifications_enabled INTEGER NOT NULL DEFAULT 1",
            )
        if "long_no_slot_notice_sent_at" not in passportSlotMonitorColumns:
            connection.execute(
                "ALTER TABLE passport_slot_monitors ADD COLUMN long_no_slot_notice_sent_at TEXT",
            )
        if "long_no_slot_stop_at" not in passportSlotMonitorColumns:
            connection.execute(
                "ALTER TABLE passport_slot_monitors ADD COLUMN long_no_slot_stop_at TEXT",
            )
        if "long_no_slot_stopped_at" not in passportSlotMonitorColumns:
            connection.execute(
                "ALTER TABLE passport_slot_monitors ADD COLUMN long_no_slot_stopped_at TEXT",
            )


def databaseExists() -> bool:
    return Path(getSettings().databasePath).exists()
