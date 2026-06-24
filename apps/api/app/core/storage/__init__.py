"""Storage abstraction for binary blobs (certificates, attachments, ...).

Two backends:
- LocalStorageBackend: filesystem under CERTIFICATE_STORAGE_DIR (default, dev/CI).
- SupabaseStorageBackend: Supabase Storage bucket (production, multi-instance).

The active backend is chosen via STORAGE_BACKEND env var. Failures to reach
Supabase in dev are not fatal — they fall back to local with a warning log.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract storage backend."""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload bytes at `key`. Returns the stored key (same as input)."""
        ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes | None:
        """Read bytes by key. Returns None if missing."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        ...

    @abstractmethod
    def get_url(self, key: str, expires_in: int = 300) -> str | None:
        """Return a URL the client can use to download the blob.

        For local backend, returns a relative API path; Supabase returns a signed URL.
        expires_in is ignored for local.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier for logging/diagnostics."""
        ...


# ── Local filesystem backend ───────────────────────────────


class LocalStorageBackend(StorageBackend):
    """Stores blobs as files under a single root directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Normalize: no absolute paths, no .. traversal
        safe = key.lstrip("/").replace("..", "_")
        return self.root / safe

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def get_bytes(self, key: str) -> bytes | None:
        target = self._path(key)
        if not target.exists():
            return None
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def get_url(self, key: str, expires_in: int = 300) -> str | None:
        # Local backend has no direct URL — caller must use the download endpoint
        return f"/api/v1/certificates/storage/{key}"

    @property
    def name(self) -> str:
        return f"local({self.root})"


# ── Supabase Storage backend ────────────────────────────────


class SupabaseStorageBackend(StorageBackend):
    """Stores blobs in a Supabase Storage bucket."""

    def __init__(self, url: str, key: str, bucket: str, signed_url_ttl: int = 300):
        if not url or not key:
            raise ValueError("Supabase URL and key are required")
        self.url = url
        self.key = key
        self.bucket = bucket
        self.signed_url_ttl = signed_url_ttl
        self._client = None  # lazy

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from supabase import create_client
            self._client = create_client(self.url, self.key)
            return self._client
        except Exception as e:
            logger.error(f"Failed to create Supabase client: {e}")
            raise

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        client = self._get_client()
        # supabase-py upload signature: from_/to/path, file_options
        client.storage.from_(self.bucket).upload(
            path=key,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return key

    def get_bytes(self, key: str) -> bytes | None:
        try:
            client = self._get_client()
            return client.storage.from_(self.bucket).download(key)
        except Exception as e:
            logger.warning(f"Supabase download failed for {key}: {e}")
            return None

    def exists(self, key: str) -> bool:
        try:
            client = self._get_client()
            # List files at the prefix; if the key appears, it exists
            parent = str(Path(key).parent).replace("\\", "/")
            items = client.storage.from_(self.bucket).list(parent)
            name = Path(key).name
            return any(item.get("name") == name for item in items)
        except Exception as e:
            logger.warning(f"Supabase exists check failed for {key}: {e}")
            return False

    def get_url(self, key: str, expires_in: int = 300) -> str | None:
        try:
            client = self._get_client()
            ttl = expires_in or self.signed_url_ttl
            res = client.storage.from_(self.bucket).create_signed_url(key, ttl)
            # supabase-py returns dict with 'signedURL' (newer) or 'signedUrl' (older)
            if isinstance(res, dict):
                return res.get("signedURL") or res.get("signedUrl")
            return None
        except Exception as e:
            logger.warning(f"Supabase signed URL failed for {key}: {e}")
            return None

    @property
    def name(self) -> str:
        return f"supabase(bucket={self.bucket})"


# ── Factory ─────────────────────────────────────────────────


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the active storage backend, instantiating it on first call."""
    global _backend
    if _backend is not None:
        return _backend

    settings = get_settings()
    backend_kind = (settings.STORAGE_BACKEND or "local").lower()

    if backend_kind == "supabase":
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            logger.warning(
                "STORAGE_BACKEND=supabase but SUPABASE_URL/KEY are not set. "
                "Falling back to local storage."
            )
        else:
            try:
                _backend = SupabaseStorageBackend(
                    url=settings.SUPABASE_URL,
                    key=settings.SUPABASE_KEY,
                    bucket=settings.SUPABASE_BUCKET,
                    signed_url_ttl=settings.SUPABASE_SIGNED_URL_TTL,
                )
                logger.info(f"Storage backend: {_backend.name}")
                return _backend
            except Exception as e:
                logger.error(f"Supabase storage init failed: {e}. Falling back to local.")

    # Default: local
    root = Path(settings.CERTIFICATE_STORAGE_DIR)
    if not root.is_absolute():
        root = Path.cwd() / root
    _backend = LocalStorageBackend(root)
    logger.info(f"Storage backend: {_backend.name}")
    return _backend


def reset_storage_for_tests() -> None:
    """Reset the cached backend. Tests use this to switch backends between cases."""
    global _backend
    _backend = None
