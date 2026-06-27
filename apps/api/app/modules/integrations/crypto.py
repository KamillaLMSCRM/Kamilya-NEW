"""Encryption helpers for tenant integration credentials.

Why Fernet?
  - Symmetric authenticated encryption (AES-128-CBC + HMAC-SHA256)
  - Part of `cryptography` package — battle-tested
  - Self-versioning: ciphertexts carry version byte so we can rotate
    keys without breaking old data

Key management:
  - MASTER_ENCRYPTION_KEY is set once via env (44-char base64)
  - Loss of key = all tenant creds unrecoverable (acceptable risk —
    tenants can re-enter credentials)
  - Rotating key requires re-encryption of all rows; out of scope for v1

Threat model:
  - Protects credentials at REST in case of DB backup leak
  - Does NOT protect against runtime SQL injection (defense in depth —
    also need parameterized queries, which we have)
  - Does NOT protect against admin compromise (admin can decrypt via
    the running app — by design)
"""

import logging
from cryptography.fernet import Fernet, InvalidToken
from app.core.config import get_settings

logger = logging.getLogger(__name__)
_settings = None
_fernet = None


def _get_fernet() -> Fernet:
    """Lazy-initialized Fernet instance. Crashes on first use if key is
    missing — better than silently storing plaintext.
    """
    global _settings, _fernet
    if _fernet is None:
        _settings = get_settings()
        key = _settings.MASTER_ENCRYPTION_KEY
        if not key:
            raise RuntimeError(
                "MASTER_ENCRYPTION_KEY not set. "
                "Generate one with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` "
                "and add to Render env + VPS .env."
            )
        try:
            _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as e:
            raise RuntimeError(
                f"MASTER_ENCRYPTION_KEY is invalid Fernet key: {e}. "
                f"Must be 44-char base64 (urlsafe)."
            )
    return _fernet


def encrypt_config(plaintext_dict: dict) -> bytes:
    """Serialize dict to JSON, then Fernet-encrypt. Returns bytes for
    BYTEA column storage."""
    import json
    f = _get_fernet()
    plaintext = json.dumps(plaintext_dict, separators=(",", ":"), default=str).encode()
    return f.encrypt(plaintext)


def decrypt_config(ciphertext: bytes) -> dict:
    """Decrypt ciphertext from DB and parse as dict. Raises InvalidToken
    if key changed or data corrupted.
    """
    import json
    f = _get_fernet()
    plaintext = f.decrypt(ciphertext)
    return json.loads(plaintext.decode())


def rotate_key_for_testing_only(old_ciphertext: bytes, new_key: str) -> bytes:
    """Helper for key rotation (NOT used in normal flow). Provided so ops
    can decrypt with one key + re-encrypt with another during rotation.
    """
    raise NotImplementedError(
        "Key rotation is a manual ops procedure — implement per-tenant "
        "re-encryption when needed. Out of v1 scope."
    )