"""Tests for scripts/setup_storage_bucket.py.

We don't hit real Supabase — we mock the client and exercise the script's
decision logic (idempotent if exists, error on missing creds, etc.).
"""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Resolve scripts/ relative to repo root (this test file is apps/api/tests/).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "setup_storage_bucket.py"
_spec = importlib.util.spec_from_file_location("setup_storage_bucket", str(_SCRIPT_PATH))
setup_storage_bucket = importlib.util.module_from_spec(_spec)
sys.modules["setup_storage_bucket"] = setup_storage_bucket
_spec.loader.exec_module(setup_storage_bucket)


def _mock_client(buckets: list[dict]):
    client = MagicMock()
    client.storage.list_buckets.return_value = buckets

    def fake_create_bucket(name, options=None):
        # Simulate supabase-py: it appends to the list internally
        buckets.append({"name": name, "public": (options or {}).get("public", False)})
        return {"name": name}

    client.storage.create_bucket.side_effect = fake_create_bucket
    return client


def test_no_env_returns_error(capsys, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    rc = setup_storage_bucket.main()
    assert rc == 1
    out = capsys.readouterr().err
    assert "SUPABASE_URL" in out
    assert "SUPABASE_KEY" in out


def test_bucket_already_exists_is_idempotent(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "certs")
    client = _mock_client([{"name": "certs"}])
    with patch("supabase.create_client", return_value=client):
        rc = setup_storage_bucket.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "already exists" in out
    client.storage.create_bucket.assert_not_called()


def test_creates_bucket_when_missing(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "new-bucket")
    client = _mock_client([{"name": "other"}])
    with patch("supabase.create_client", return_value=client):
        rc = setup_storage_bucket.main()
    assert rc == 0
    client.storage.create_bucket.assert_called_once_with(
        name="new-bucket",
        options={"public": False},
    )
    out = capsys.readouterr().out
    assert "created successfully" in out


def test_create_already_exists_message_does_not_fail(monkeypatch, capsys):
    """If create_bucket raises a 'duplicate' error, we treat it as success (race-safe)."""
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "certs")
    client = _mock_client([{"name": "certs"}])  # already there
    client.storage.create_bucket.side_effect = Exception("Bucket already exists")
    with patch("supabase.create_client", return_value=client):
        rc = setup_storage_bucket.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "already exists" in out


def test_create_real_error_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "certs")
    client = _mock_client([])
    client.storage.create_bucket.side_effect = Exception("403 Forbidden")
    with patch("supabase.create_client", return_value=client):
        rc = setup_storage_bucket.main()
    assert rc == 1


def test_list_buckets_error_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "certs")
    client = _mock_client([])
    client.storage.list_buckets.side_effect = Exception("network down")
    with patch("supabase.create_client", return_value=client):
        rc = setup_storage_bucket.main()
    assert rc == 1


def test_public_flag_passed_through(monkeypatch):
    """--public sets the public option to True (not recommended for certs)."""
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")
    monkeypatch.setenv("SUPABASE_BUCKET", "certs")
    client = _mock_client([])
    with patch("supabase.create_client", return_value=client):
        rc = setup_storage_bucket.main(argv=["--public"])
    assert rc == 0
    _, kwargs = client.storage.create_bucket.call_args
    assert kwargs["options"]["public"] is True
