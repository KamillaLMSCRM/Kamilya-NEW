"""Tests for the provider_keys feature.

Covers:
- Encryption helper (encrypt/decrypt roundtrip, missing-key error, masking)
- ProviderKeyService CRUD with the repository module mocked
- Test/probe endpoint logic (mock httpx)

These tests intentionally do NOT exercise the actual DeepSeek/Voyage
APIs or a real Postgres connection — they mock both.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from app.core import encryption as enc_module
from app.core.config import get_settings
from app.modules.admin.provider_keys.models import ProviderKey
from app.modules.admin.provider_keys import repository as repo_module
from app.modules.admin.provider_keys.service import ProviderKeyService
from app.modules.admin.provider_keys.schemas import (
    ProviderKeyCreate,
    ProviderKeyUpdate,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide a fresh Fernet key for every test."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PROVIDER_KEY_ENCRYPTION_KEY", key)
    # Reset lru_cache so get_settings() picks up the new env.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _RepoSpy:
    """In-memory replacement for `app.modules.admin.provider_keys.repository`."""

    def __init__(self):
        self.rows: dict[uuid.UUID, ProviderKey] = {}
        self.deactivate_calls: list = []

    async def list_global_keys(self, db):
        return sorted(
            self.rows.values(),
            key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    async def get_key_by_id(self, db, key_id):
        return self.rows.get(key_id)

    async def get_active_global_key(self, db, provider):
        candidates = [
            r for r in self.rows.values()
            if r.provider == provider and r.is_active and r.tenant_id is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.created_at)

    async def deactivate_existing(self, db, provider, tenant_id):
        for r in self.rows.values():
            if r.provider == provider and r.is_active:
                if tenant_id is None and r.tenant_id is None:
                    r.is_active = False
                    self.deactivate_calls.append(r.id)
                elif tenant_id is not None and r.tenant_id == tenant_id:
                    r.is_active = False
                    self.deactivate_calls.append(r.id)

    async def insert_key(self, db, key):
        if key.id is None:
            key.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if key.created_at is None:
            key.created_at = now
        key.updated_at = now
        self.rows[key.id] = key
        return key

    async def delete_key(self, db, key):
        self.rows.pop(key.id, None)


class _FakeAsyncSession:
    """Bare-minimum stand-in for AsyncSession.

    The service uses only: add(), commit(), refresh(), flush(), delete(),
    execute() — and the repository's spy intercepts execute() before the
    service ever sees its return value. So this only needs to satisfy
    attribute access, not actually run SQL.
    """

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None

    def add(self, obj):
        if obj.id is None:
            obj.id = uuid.uuid4()
        return None

    async def delete(self, obj):
        return None

    async def execute(self, stmt):
        # The repo is fully spied out, so execute() should never be
        # called directly on the session. If it is, raise so we notice.
        raise AssertionError(
            "execute() called directly on session — repo spy should intercept"
        )


@pytest.fixture
def db_session():
    """Fake AsyncSession — no Postgres required."""
    return _FakeAsyncSession()


@pytest.fixture
def spy(monkeypatch):
    """Patch the repository module with our in-memory spy."""
    spy = _RepoSpy()
    monkeypatch.setattr(repo_module, "list_global_keys", spy.list_global_keys)
    monkeypatch.setattr(repo_module, "get_key_by_id", spy.get_key_by_id)
    monkeypatch.setattr(repo_module, "get_active_global_key", spy.get_active_global_key)
    monkeypatch.setattr(repo_module, "deactivate_existing", spy.deactivate_existing)
    monkeypatch.setattr(repo_module, "insert_key", spy.insert_key)
    monkeypatch.setattr(repo_module, "delete_key", spy.delete_key)
    return spy


# ── Encryption ────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    secret = "sk-test-abc-1234567890"
    cipher = enc_module.encrypt_secret(secret)
    assert cipher != secret
    assert enc_module.decrypt_secret(cipher) == secret


def test_encrypt_without_key_raises():
    get_settings.cache_clear()
    saved = os.environ.pop("PROVIDER_KEY_ENCRYPTION_KEY", None)
    try:
        with pytest.raises(enc_module.EncryptionKeyMissingError):
            enc_module.encrypt_secret("x")
    finally:
        if saved is not None:
            os.environ["PROVIDER_KEY_ENCRYPTION_KEY"] = saved
        get_settings.cache_clear()


def test_decrypt_with_tampered_cipher_raises():
    cipher = enc_module.encrypt_secret("hello")
    tampered = cipher[:-2] + ("A" if cipher[-1] != "A" else "B") + cipher[-1]
    with pytest.raises(ValueError, match="invalid or was tampered"):
        enc_module.decrypt_secret(tampered)


def test_mask_secret():
    assert enc_module.mask_secret("") == ""
    assert enc_module.mask_secret("short") == "*" * 5
    masked = enc_module.mask_secret("sk-abcdefghijklmnop")
    assert masked.startswith("sk-")
    assert masked.endswith("klmnop")
    assert "***" in masked


# ── ProviderKeyService CRUD ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_active(db_session, spy):
    svc = ProviderKeyService(db_session)
    user_id = uuid.uuid4()
    resp = await svc.create_key(
        payload=ProviderKeyCreate(
            provider="deepseek", api_key="sk-deepseek-test-1234", label="prod"
        ),
        user_id=user_id,
    )
    assert resp.provider == "deepseek"
    assert resp.source == "db"
    assert resp.is_active is True
    assert resp.key_preview.startswith("sk-")
    assert "***" in resp.key_preview

    active = await svc.get_active_key_value("deepseek")
    assert active == "sk-deepseek-test-1234"


@pytest.mark.asyncio
async def test_create_deactivates_previous(db_session, spy):
    svc = ProviderKeyService(db_session)
    user_id = uuid.uuid4()

    await svc.create_key(
        ProviderKeyCreate(provider="voyage", api_key="sk-old-key-12345"),
        user_id,
    )
    await svc.create_key(
        ProviderKeyCreate(provider="voyage", api_key="sk-new-key-67890"),
        user_id,
    )

    active = await svc.get_active_key_value("voyage")
    assert active == "sk-new-key-67890"

    listed = await svc.list_providers()
    assert len(listed.providers) == 2
    actives = [p for p in listed.providers if p.is_active]
    assert len(actives) == 1
    assert actives[0].key_preview.endswith("67890")


@pytest.mark.asyncio
async def test_update_label_and_deactivate(db_session, spy):
    svc = ProviderKeyService(db_session)
    user_id = uuid.uuid4()
    created = await svc.create_key(
        ProviderKeyCreate(provider="deepseek", api_key="sk-original-key-1"),
        user_id,
    )

    updated = await svc.update_key(
        created.id, ProviderKeyUpdate(label="Renamed", is_active=False)
    )
    assert updated.label == "Renamed"
    assert updated.is_active is False

    assert await svc.get_active_key_value("deepseek") is None


@pytest.mark.asyncio
async def test_delete_key(db_session, spy):
    svc = ProviderKeyService(db_session)
    user_id = uuid.uuid4()
    created = await svc.create_key(
        ProviderKeyCreate(provider="voyage", api_key="sk-voyage-to-delete-1"),
        user_id,
    )
    await svc.delete_key(created.id)

    assert await svc.get_active_key_value("voyage") is None
    listed = await svc.list_providers()
    assert listed.providers == []


@pytest.mark.asyncio
async def test_update_unknown_id_raises_lookup_error(db_session, spy):
    svc = ProviderKeyService(db_session)
    with pytest.raises(LookupError):
        await svc.update_key(uuid.uuid4(), ProviderKeyUpdate(label="nope"))


# ── test_key (network probe) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_key_success(db_session, spy, monkeypatch):
    svc = ProviderKeyService(db_session)
    user_id = uuid.uuid4()
    created = await svc.create_key(
        ProviderKeyCreate(provider="deepseek", api_key="sk-deepseek-good-1"),
        user_id,
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: fake_client)

    result = await svc.test_key(created.id)
    assert result.ok is True
    assert result.provider == "deepseek"
    assert result.error is None
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_test_key_auth_failure(db_session, spy, monkeypatch):
    svc = ProviderKeyService(db_session)
    user_id = uuid.uuid4()
    created = await svc.create_key(
        ProviderKeyCreate(provider="voyage", api_key="sk-voyage-bad-auth-1"),
        user_id,
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 401
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: fake_client)

    result = await svc.test_key(created.id)
    assert result.ok is False
    assert "auth failed" in (result.error or "")
    assert result.provider == "voyage"


@pytest.mark.asyncio
async def test_cohere_key_probe_uses_native_embed_api(db_session, spy, monkeypatch):
    svc = ProviderKeyService(db_session)
    created = await svc.create_key(
        ProviderKeyCreate(provider="cohere", api_key="cohere-test-key-12345"),
        uuid.uuid4(),
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.post = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: fake_client)

    result = await svc.test_key(created.id)

    assert result.ok is True
    assert result.provider == "cohere"
    url = fake_client.post.await_args.args[0]
    payload = fake_client.post.await_args.kwargs["json"]
    assert url == "https://api.cohere.com/v2/embed"
    assert payload["input_type"] == "search_document"
    assert payload["output_dimension"] == 1024
