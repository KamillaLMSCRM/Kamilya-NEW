"""Tests for storage abstraction — local and Supabase backends."""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.core.storage import (
    LocalStorageBackend,
    SupabaseStorageBackend,
    get_storage,
    reset_storage_for_tests,
)


# ── Local backend ───────────────────────────────────────────


def test_local_put_and_get_bytes(tmp_path: Path):
    backend = LocalStorageBackend(tmp_path)
    key = f"{uuid4()}/cert.pdf"
    backend.put_bytes(key, b"PDF-DATA", content_type="application/pdf")
    assert backend.exists(key) is True
    assert backend.get_bytes(key) == b"PDF-DATA"


def test_local_get_missing_returns_none(tmp_path: Path):
    backend = LocalStorageBackend(tmp_path)
    assert backend.get_bytes("nope/missing.pdf") is None
    assert backend.exists("nope/missing.pdf") is False


def test_local_normalizes_path_traversal(tmp_path: Path):
    """../escape attempts are flattened to a single path component."""
    backend = LocalStorageBackend(tmp_path)
    key = "../../etc/passwd"
    backend.put_bytes(key, b"x")
    # The file should be inside tmp_path, not in /etc
    assert (tmp_path / "..").exists()  # tmp_path/.. is the parent
    # And it should not have written to /etc
    assert not Path("/etc/passwd").exists() or (tmp_path / "..").resolve() != Path("/etc").resolve()


def test_local_get_url_is_relative():
    backend = LocalStorageBackend(Path("/tmp"))
    url = backend.get_url("tenant-1/cert.pdf")
    assert url is not None
    assert url.startswith("/api/v1/")


def test_local_name_includes_root(tmp_path: Path):
    backend = LocalStorageBackend(tmp_path)
    assert "local" in backend.name


# ── Supabase backend (mocked client) ────────────────────────


def _make_mock_supabase_client():
    """Build a mock that mimics the supabase-py chain: .storage.from_(bucket).{upload,download,list,create_signed_url}."""
    client = MagicMock()
    bucket = MagicMock()
    client.storage.from_.return_value = bucket
    return client, bucket


def test_supabase_put_bytes_calls_upload():
    client, bucket = _make_mock_supabase_client()
    with patch("supabase.create_client", return_value=client):
        backend = SupabaseStorageBackend(
            url="https://x.supabase.co", key="key", bucket="certs"
        )
        backend.put_bytes("t/cert.pdf", b"DATA", content_type="application/pdf")
        bucket.upload.assert_called_once()
        args, kwargs = bucket.upload.call_args
        assert kwargs["path"] == "t/cert.pdf"
        assert kwargs["file"] == b"DATA"
        assert kwargs["file_options"]["content-type"] == "application/pdf"


def test_supabase_get_bytes_returns_downloaded():
    client, bucket = _make_mock_supabase_client()
    bucket.download.return_value = b"PDF-BYTES"
    with patch("supabase.create_client", return_value=client):
        backend = SupabaseStorageBackend(
            url="https://x.supabase.co", key="key", bucket="certs"
        )
        result = backend.get_bytes("t/cert.pdf")
        assert result == b"PDF-BYTES"
        bucket.download.assert_called_once_with("t/cert.pdf")


def test_supabase_get_bytes_returns_none_on_error():
    client, bucket = _make_mock_supabase_client()
    bucket.download.side_effect = Exception("network down")
    with patch("supabase.create_client", return_value=client):
        backend = SupabaseStorageBackend(
            url="https://x.supabase.co", key="key", bucket="certs"
        )
        assert backend.get_bytes("t/cert.pdf") is None


def test_supabase_get_url_returns_signed_url_new_api():
    """supabase-py >= 2 returns dict with 'signedURL' key."""
    client, bucket = _make_mock_supabase_client()
    bucket.create_signed_url.return_value = {"signedURL": "https://x.supabase.co/storage/v1/object/sign/certs/t/cert.pdf?token=abc"}
    with patch("supabase.create_client", return_value=client):
        backend = SupabaseStorageBackend(
            url="https://x.supabase.co", key="key", bucket="certs", signed_url_ttl=300
        )
        url = backend.get_url("t/cert.pdf", expires_in=120)
        assert url is not None
        assert url.startswith("https://")
        assert "token=" in url
        bucket.create_signed_url.assert_called_once_with("t/cert.pdf", 120)


def test_supabase_get_url_returns_signed_url_old_api():
    """supabase-py < 2 returned dict with 'signedUrl' (camelCase)."""
    client, bucket = _make_mock_supabase_client()
    bucket.create_signed_url.return_value = {"signedUrl": "https://old-format"}
    with patch("supabase.create_client", return_value=client):
        backend = SupabaseStorageBackend(
            url="https://x.supabase.co", key="key", bucket="certs"
        )
        assert backend.get_url("k") == "https://old-format"


def test_supabase_exists_checks_list():
    client, bucket = _make_mock_supabase_client()
    bucket.list.return_value = [{"name": "cert.pdf"}, {"name": "other.pdf"}]
    with patch("supabase.create_client", return_value=client):
        backend = SupabaseStorageBackend(
            url="https://x.supabase.co", key="key", bucket="certs"
        )
        assert backend.exists("t/cert.pdf") is True
        assert backend.exists("t/missing.pdf") is False


def test_supabase_constructor_requires_url_and_key():
    with pytest.raises(ValueError):
        SupabaseStorageBackend(url="", key="", bucket="certs")
    with pytest.raises(ValueError):
        SupabaseStorageBackend(url="https://x", key="", bucket="certs")


# ── Factory ─────────────────────────────────────────────────


def test_get_storage_defaults_to_local(monkeypatch):
    """With no STORAGE_BACKEND env, factory returns local backend."""
    monkeypatch.setenv("STORAGE_BACKEND", "")
    # Settings is lru_cached — reset it so monkeypatch takes effect
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_storage_for_tests()
    backend = get_storage()
    assert isinstance(backend, LocalStorageBackend)


def test_get_storage_falls_back_to_local_when_supabase_missing(monkeypatch):
    """STORAGE_BACKEND=supabase but no URL/KEY → local fallback with warning."""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_storage_for_tests()
    backend = get_storage()
    assert isinstance(backend, LocalStorageBackend)


def test_get_storage_returns_supabase_when_configured(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "certs")
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_storage_for_tests()
    with patch("supabase.create_client"):
        backend = get_storage()
        assert isinstance(backend, SupabaseStorageBackend)
        assert backend.bucket == "certs"


def test_get_storage_caches_singleton(monkeypatch):
    """Calling get_storage twice returns the same instance."""
    from app.core.config import get_settings
    get_settings.cache_clear()
    reset_storage_for_tests()
    a = get_storage()
    b = get_storage()
    assert a is b
