from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.admin.tenant_ai_providers import service as service_module
from app.modules.admin.tenant_ai_providers.schemas import TenantAIProviderUpdate
from app.modules.admin.tenant_ai_providers.service import TenantAIProviderService, TenantProviderConfigurationError


class _FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _row(*, tenant_id: uuid.UUID, purpose: str = "generation", enabled: bool = True):
    return SimpleNamespace(
        tenant_id=tenant_id,
        purpose=purpose,
        provider="openrouter",
        model="nvidia/nemotron-3-embed-1b:free",
        encrypted_key="ciphertext",
        enabled=enabled,
        free_only=True,
        output_dimensions=None,
    )


def test_payload_and_response_contract_are_secret_free():
    payload = TenantAIProviderUpdate(provider="openrouter", model="google/gemma-4-26b-a4b-it:free")
    assert payload.free_only is True
    response = service_module._sanitized(_row(tenant_id=uuid.uuid4()))
    assert response.model_dump() == {
        "purpose": "generation", "provider": "openrouter", "model": "nvidia/nemotron-3-embed-1b:free",
        "enabled": True, "free_only": True, "output_dimensions": None, "has_key": True,
    }
    assert "key" not in response.model_dump(exclude={"has_key"}).__repr__().lower()


def test_provider_validation_is_purpose_bound_and_openrouter_free_only_requires_free_model():
    generation = TenantAIProviderUpdate(provider="openrouter", model="vendor/paid-model")
    with pytest.raises(ValueError, match="openrouter_free_model_required"):
        service_module._validate("generation", generation)
    embedding = TenantAIProviderUpdate(provider="openrouter", model="nvidia/nemotron-3-embed-1b:free")
    service_module._validate("embedding", embedding)
    with pytest.raises(ValueError, match="openrouter_free_model_required"):
        service_module._validate("embedding", TenantAIProviderUpdate(provider="openrouter", model="openrouter/free"))
    with pytest.raises(ValueError, match="output_dimensions_unsupported"):
        service_module._validate("embedding", TenantAIProviderUpdate(provider="voyage", model="voyage-4-lite", output_dimensions=1024))
    with pytest.raises(ValueError, match="invalid_model"):
        TenantAIProviderUpdate(provider="voyage", model=" voyage-4-lite ")
    with pytest.raises(ValueError, match="provider_not_allowed_for_purpose"):
        service_module._validate("generation", TenantAIProviderUpdate(provider="voyage", model="voyage-4-lite"))


@pytest.mark.asyncio
async def test_put_retains_existing_key_and_returns_has_key_only(monkeypatch):
    tenant_id = uuid.uuid4()
    current = _row(tenant_id=tenant_id)
    captured = {}

    async def get_for_tenant(db, tid, purpose):
        return current

    async def upsert_for_tenant(db, **kwargs):
        captured.update(kwargs)
        return _row(tenant_id=tenant_id)

    monkeypatch.setattr(service_module.repository, "get_for_tenant", get_for_tenant)
    monkeypatch.setattr(service_module.repository, "upsert_for_tenant", upsert_for_tenant)
    response = await TenantAIProviderService(_FakeSession()).put(
        tenant_id, "generation", TenantAIProviderUpdate(provider="openrouter", model="google/gemma-4-26b-a4b-it:free")
    )
    assert captured["values"]["encrypted_key"] == "ciphertext"
    assert response.has_key is True
    assert "ciphertext" not in str(response.model_dump())


@pytest.mark.asyncio
async def test_put_requires_fresh_key_when_provider_changes(monkeypatch):
    tenant_id = uuid.uuid4()

    async def get_for_tenant(db, tid, purpose):
        return _row(tenant_id=tenant_id)

    monkeypatch.setattr(service_module.repository, "get_for_tenant", get_for_tenant)
    with pytest.raises(ValueError, match="api_key_required_for_provider_change"):
        await TenantAIProviderService(_FakeSession()).put(
            tenant_id,
            "generation",
            TenantAIProviderUpdate(provider="deepseek", model="deepseek-v4-flash"),
        )


@pytest.mark.asyncio
async def test_explicit_tenant_override_error_never_calls_global_resolver(monkeypatch):
    from app.modules.ai import llm_client

    tenant_id = uuid.uuid4()

    async def fail_override(tid, purpose):
        raise TenantProviderConfigurationError("tenant_provider_resolution_unavailable")

    async def global_key(*args):
        raise AssertionError("global credentials must not be read")

    monkeypatch.setattr(service_module, "resolve_tenant_provider", fail_override, raising=False)
    monkeypatch.setattr(llm_client, "_resolve_db_key", global_key)
    monkeypatch.setattr("app.modules.admin.tenant_ai_providers.service.resolve_tenant_provider", fail_override)
    with pytest.raises(TenantProviderConfigurationError):
        await llm_client.ResilientLLMClient.from_settings_async(tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_openrouter_override_has_official_endpoint_and_zero_price_caps(monkeypatch):
    tenant_id = uuid.uuid4()
    row = _row(tenant_id=tenant_id, purpose="embedding")

    class SessionContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, statement, parameters):
            assert parameters == {"tenant_id": str(tenant_id)}

    async def get_for_tenant(db, tid, purpose):
        return row

    monkeypatch.setattr("app.core.db.async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(service_module.repository, "get_for_tenant", get_for_tenant)
    monkeypatch.setattr(service_module, "decrypt_secret", lambda value: "synthetic-test-key")
    config = await service_module.resolve_tenant_provider(tenant_id, "embedding")
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.extra_body["provider"]["allow_fallbacks"] is False
    assert config.extra_body["provider"]["data_collection"] == "deny"
    assert config.extra_body["provider"]["max_price"] == {"prompt": 0, "completion": 0, "image": 0, "request": 0}


def test_migration_has_force_rls_and_no_secret_defaults():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "alembic" / "versions" / "0157_tenant_ai_providers.py").read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "REVOKE ALL" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON" in source
    assert "encrypted_key text NOT NULL" in source
    assert "DEFAULT '" not in source


def test_router_contract_and_roles_are_tenant_admin_only():
    from app.modules.admin.tenant_ai_providers.router import router

    assert {route.path for route in router.routes} == {"/admin/ai-providers", "/admin/ai-providers/{purpose}"}
    for route in router.routes:
        calls = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert "role_checker" in calls
