from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.modules.training_evidence import share_service
from app.modules.training_evidence.export_router import _share_url


def _request(ip: str = "203.0.113.10") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/v1/training-evidence/shares/tenant/token",
        "headers": [],
        "client": (ip, 443),
        "scheme": "https",
        "server": ("app.kml.kz", 443),
    })


def test_share_token_is_stored_as_sha256_not_raw_token():
    raw = "opaque-one-time-secret"
    hashed = share_service._token_hash(raw)

    assert hashed != raw
    assert len(hashed) == 64
    assert share_service._token_hash(raw) == hashed


def test_public_share_metadata_is_generic():
    assert share_service._package_metadata("pdf") == (
        "application/pdf",
        "kamilya-training-evidence-package.pdf",
    )


def test_create_response_url_uses_api_request_url_not_frontend_public_url():
    tenant_id = uuid4()
    token = "one-time-token"

    class RequestWithApiUrl:
        def url_for(self, name: str, **params: str) -> str:
            assert name == "download_public_training_evidence_share"
            return f"https://kamilya-lms-api.example/api/v1/training-evidence/shares/{params['tenant_id']}/{params['token']}"

    url = _share_url(RequestWithApiUrl(), tenant_id, token)  # type: ignore[arg-type]
    assert url.startswith("https://kamilya-lms-api.example/api/v1/")
    assert "app.kml.kz/api/v1" not in url


@pytest.mark.asyncio
async def test_public_tenant_context_sets_rls_before_share_lookup():
    calls: list[object] = []

    class FakeDb:
        async def execute(self, statement, params):
            calls.append((statement, params))

    tenant_id = uuid4()
    assert await share_service.set_public_tenant_context(FakeDb(), tenant_id)  # type: ignore[arg-type]
    assert len(calls) == 1
    assert str(calls[0][0]) == "SELECT set_current_tenant(:tenant_id)"
    assert calls[0][1] == {"tenant_id": str(tenant_id)}


def test_package_integrity_mismatch_fails_closed():
    package = b"immutable bytes"
    share = SimpleNamespace(
        package_bytes=package,
        package_sha256=share_service._token_hash("different"),
    )

    assert not share_service.package_integrity_valid(share)  # type: ignore[arg-type]


def test_migration_has_database_level_tenant_invariants_and_force_rls():
    migration = Path("alembic/versions/0087_training_evidence_shares.py").read_text(encoding="utf-8")

    assert 'down_revision = "0086"' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "validate_training_evidence_share_ownership" in migration
    assert "validate_training_evidence_share_access_tenant" in migration
    assert "creator_tenant <> NEW.tenant_id" in migration
    assert "share_tenant <> NEW.tenant_id" in migration
    assert "training_evidence_share_access_logs" in migration
    assert "ip_address" not in migration
    assert "user_agent" not in migration
    assert "raw_token" not in migration
    assert "NEW.id IS DISTINCT FROM OLD.id" in migration
    assert "foreign_key_violation" in migration
    assert share_service._package_metadata("zip") == (
        "application/zip",
        "kamilya-training-evidence-package.zip",
    )


@pytest.mark.asyncio
async def test_public_share_rate_limit_uses_bounded_project_limiter(monkeypatch):
    calls: list[tuple[str, int, int]] = []

    class FakeLimiter:
        async def check_rate_limit(self, key: str, limit: int, window: int):
            calls.append((key, limit, window))
            return True, {"remaining": 19, "reset": 60}

    monkeypatch.setattr(share_service, "_public_share_rate_limiter", FakeLimiter())
    await share_service.enforce_public_share_rate_limit(_request())

    assert calls == [(calls[0][0], share_service.PUBLIC_SHARE_RATE_LIMIT, share_service.PUBLIC_SHARE_RATE_WINDOW_SECONDS)]
    assert "203.0.113.10" not in calls[0][0]
    assert calls[0][0].startswith("public_training_evidence_share:ip:")


@pytest.mark.asyncio
async def test_public_share_rate_limit_returns_429_for_bounded_window(monkeypatch):
    class FakeLimiter:
        async def check_rate_limit(self, key: str, limit: int, window: int):
            return False, {"remaining": 0, "reset": int(time.time()) + 30}

    monkeypatch.setattr(share_service, "_public_share_rate_limiter", FakeLimiter())

    with pytest.raises(HTTPException) as error:
        await share_service.enforce_public_share_rate_limit(_request())

    assert error.value.status_code == 429
    assert error.value.headers is not None
    assert 1 <= int(error.value.headers["Retry-After"]) <= 30


@pytest.mark.asyncio
async def test_public_share_rate_limit_fails_closed_when_valkey_unavailable(monkeypatch):
    class FakeLimiter:
        async def check_rate_limit(self, key: str, limit: int, window: int):
            return False, {"unavailable": True, "reset": 5}

    monkeypatch.setattr(share_service, "_public_share_rate_limiter", FakeLimiter())

    with pytest.raises(HTTPException) as error:
        await share_service.enforce_public_share_rate_limit(_request())

    assert error.value.status_code == 503
