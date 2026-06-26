"""Symmetric encryption helpers for secrets at rest.

Used to encrypt provider API keys before storing them in the
`provider_keys` table and decrypt them on read.

The encryption key is a Fernet key (base64-encoded 32-byte key) supplied
via `PROVIDER_KEY_ENCRYPTION_KEY` in the environment. Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

WARNING: Loss of this key makes all stored provider keys unreadable.
Keep an offline backup in your password manager.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionKeyMissingError(RuntimeError):
    """Raised when PROVIDER_KEY_ENCRYPTION_KEY is not configured."""


def _get_fernet() -> Fernet:
    """Return a Fernet instance bound to the configured key.

    Raises EncryptionKeyMissingError if the key is unset. We don't
    silently fall back to a default because that would be a security hole
    (every deployment would share the same key).
    """
    key = get_settings().PROVIDER_KEY_ENCRYPTION_KEY
    if not key:
        raise EncryptionKeyMissingError(
            "PROVIDER_KEY_ENCRYPTION_KEY is not set. Add it to your "
            "environment to use encrypted provider keys. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as e:
        raise EncryptionKeyMissingError(
            f"PROVIDER_KEY_ENCRYPTION_KEY is malformed: {e}. "
            "It must be a base64-encoded 32-byte Fernet key."
        ) from e


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string. Returns url-safe base64 ciphertext (str)."""
    if plaintext is None:
        raise ValueError("plaintext must not be None")
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a previously encrypted secret. Raises InvalidToken on tamper."""
    if not ciphertext:
        raise ValueError("ciphertext must not be empty")
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        # Don't leak the cipher in the log.
        logger.error("Failed to decrypt provider key: invalid token")
        raise ValueError("Stored provider key is invalid or was tampered with") from e


def mask_secret(plaintext: str) -> str:
    """Return a UI-safe masked version of a secret for display.

    Example: "sk-abc123def456" -> "sk-***def456"
    Shows first 3 and last 6 chars, masking the middle.
    """
    if not plaintext:
        return ""
    if len(plaintext) <= 12:
        return "*" * len(plaintext)
    return f"{plaintext[:3]}{'*' * (len(plaintext) - 9)}{plaintext[-6:]}"