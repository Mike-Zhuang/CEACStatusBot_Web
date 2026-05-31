from __future__ import annotations

import base64
import os

import pytest

from CEACStatusBot.web.config import getSettings
from CEACStatusBot.web.secrets import decryptSecret, encryptSecret, getCredentialMasterKey


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
