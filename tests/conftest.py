from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from CEACStatusBot.web.config import getSettings
from CEACStatusBot.web.database import getConnection, initializeDatabase
from CEACStatusBot.web.secrets import getCredentialMasterKey
from CEACStatusBot.web.security import hashPassword


def refreshSettings() -> None:
    getSettings.cache_clear()
    getCredentialMasterKey.cache_clear()
    try:
        from CEACStatusBot.web import main

        main.settings = getSettings()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def isolatedRuntime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    keyPath = tmp_path / "credential-master.key"
    keyPath.write_text(base64.urlsafe_b64encode(os.urandom(32)).decode(), encoding="ascii")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("CREDENTIAL_KEY_FILE", str(keyPath))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "http://localhost,http://127.0.0.1")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost,http://127.0.0.1")
    refreshSettings()
    initializeDatabase()
    yield
    refreshSettings()


@pytest.fixture
def refreshTestSettings():
    return refreshSettings


@pytest.fixture
def createUser():
    def createUserRecord(email: str = "user@example.com", role: str = "user", accountTier: str = "standard") -> dict:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with getConnection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    email, password_hash, role, account_tier, is_email_verified, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (email, hashPassword("correct-password"), role, accountTier, now, now),
            )
            return connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()

    return createUserRecord
