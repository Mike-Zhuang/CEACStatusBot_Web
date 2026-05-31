import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import getSettings


AES_GCM_PREFIX = "v2"
DEFAULT_KEY_ID = "local"


def _decodeBase64Url(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def _encodeBase64Url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@lru_cache(maxsize=1)
def getCredentialMasterKey() -> bytes:
    settings = getSettings()
    if settings.credentialKeyFile:
        keyPath = settings.credentialKeyFile
        try:
            rawKey = open(keyPath, "rb").read().strip()
        except FileNotFoundError as exc:
            raise RuntimeError(f"Credential key file does not exist: {keyPath}") from exc
        try:
            key = _decodeBase64Url(rawKey.decode())
        except Exception:
            key = rawKey
        if len(key) != 32:
            raise RuntimeError("Credential key must be exactly 32 bytes after base64 decoding")
        return key

    # 本地开发允许从 SECRET_KEY 派生稳定密钥；生产必须使用 CREDENTIAL_KEY_FILE。
    if settings.cookieSecure:
        raise RuntimeError("CREDENTIAL_KEY_FILE is required when COOKIE_SECURE=true")
    return hashlib.sha256(settings.secretKey.encode()).digest()


def isEncryptedSecret(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith(f"{AES_GCM_PREFIX}:") or value.startswith("gAAAA")


def encryptSecret(value: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(getCredentialMasterKey()).encrypt(nonce, value.encode(), None)
    return f"{AES_GCM_PREFIX}:{DEFAULT_KEY_ID}:{_encodeBase64Url(nonce)}:{_encodeBase64Url(ciphertext)}"


def decryptSecret(value: str) -> str:
    if value.startswith(f"{AES_GCM_PREFIX}:"):
        try:
            _, _keyId, nonceEncoded, ciphertextEncoded = value.split(":", 3)
            return AESGCM(getCredentialMasterKey()).decrypt(
                _decodeBase64Url(nonceEncoded),
                _decodeBase64Url(ciphertextEncoded),
                None,
            ).decode()
        except Exception as exc:
            raise RuntimeError("Encrypted credential cannot be decrypted; check CREDENTIAL_KEY_FILE") from exc

    try:
        return getSettings().getFernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Legacy encrypted credential cannot be decrypted; check ENCRYPTION_KEY") from exc


def encryptIfNeeded(value: str | None) -> str | None:
    if value is None:
        return None
    if isEncryptedSecret(value):
        return value
    return encryptSecret(value)


def decryptIfNeeded(value: str | None) -> str | None:
    if value is None:
        return None
    if isEncryptedSecret(value):
        return decryptSecret(value)
    return value
