import base64
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, get_settings

NONCE_BYTES = 12
CIPHERTEXT_PREFIX = "ag1"


class IntegrationCryptoError(ValueError):
    """Safe exception: messages never include keys, ciphertext or plaintext."""


@dataclass(frozen=True)
class EncryptionConfiguration:
    keys: dict[str, bytes]
    active_version: str | None


def _decode_key(value: str) -> bytes:
    try:
        padded = value.strip() + "=" * (-len(value.strip()) % 4)
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise IntegrationCryptoError("Integration encryption configuration is invalid") from exc
    if len(key) != 32:
        raise IntegrationCryptoError("Integration encryption configuration is invalid")
    return key


def load_encryption_configuration(
    settings: Settings | None = None,
    *,
    required: bool = False,
) -> EncryptionConfiguration:
    settings = settings or get_settings()
    raw = settings.integration_encryption_keys_json.strip()
    active = settings.integration_encryption_active_key_version.strip() or None
    if not raw:
        if required:
            raise IntegrationCryptoError("Integration encryption configuration is required")
        return EncryptionConfiguration({}, active)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise IntegrationCryptoError("Integration encryption configuration is invalid") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise IntegrationCryptoError("Integration encryption configuration is invalid")
    keys: dict[str, bytes] = {}
    for version, value in parsed.items():
        if not isinstance(version, str) or not version.strip() or not isinstance(value, str):
            raise IntegrationCryptoError("Integration encryption configuration is invalid")
        keys[version.strip()] = _decode_key(value)
    if not active or active not in keys:
        raise IntegrationCryptoError("Active integration encryption key version is unavailable")
    return EncryptionConfiguration(keys, active)


def validate_encryption_configuration(
    settings: Settings | None = None,
    *,
    required: bool = False,
) -> None:
    load_encryption_configuration(settings, required=required)


def encrypt_secret(
    plaintext: str,
    key_version: str | None = None,
    *,
    settings: Settings | None = None,
) -> tuple[str, str]:
    if not isinstance(plaintext, str) or not plaintext.strip():
        raise IntegrationCryptoError("Integration secret is required")
    configuration = load_encryption_configuration(settings, required=True)
    version = key_version or configuration.active_version
    if not version or version not in configuration.keys:
        raise IntegrationCryptoError("Integration encryption key version is unavailable")
    nonce = os.urandom(NONCE_BYTES)
    associated_data = f"{CIPHERTEXT_PREFIX}:{version}".encode("utf-8")
    encrypted = AESGCM(configuration.keys[version]).encrypt(
        nonce,
        plaintext.encode("utf-8"),
        associated_data,
    )
    encoded = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")
    return f"{CIPHERTEXT_PREFIX}:{version}:{encoded}", version


def decrypt_secret(
    ciphertext: str,
    key_version: str,
    *,
    settings: Settings | None = None,
) -> str:
    configuration = load_encryption_configuration(settings, required=True)
    if key_version not in configuration.keys:
        raise IntegrationCryptoError("Integration encryption key version is unavailable")
    try:
        prefix, embedded_version, encoded = ciphertext.split(":", 2)
        if prefix != CIPHERTEXT_PREFIX or embedded_version != key_version:
            raise ValueError
        packed = base64.urlsafe_b64decode(encoded.encode("ascii"))
        if len(packed) <= NONCE_BYTES:
            raise ValueError
        nonce, encrypted = packed[:NONCE_BYTES], packed[NONCE_BYTES:]
        plaintext = AESGCM(configuration.keys[key_version]).decrypt(
            nonce,
            encrypted,
            f"{CIPHERTEXT_PREFIX}:{key_version}".encode("utf-8"),
        )
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeError) as exc:
        raise IntegrationCryptoError("Integration secret could not be decrypted") from exc


def mask_secret_for_logs(_value: str | None) -> str:
    return "[REDACTED]"


def generate_encryption_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
