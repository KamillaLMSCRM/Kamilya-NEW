from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.admin.model_routing import service as service_module
from app.modules.admin.model_routing.catalog import (
    DEFAULT_GENERATION_MODEL_ORDER,
    validate_generation_model_order,
)
from app.modules.admin.model_routing.schemas import GenerationModelRoutingUpdate
from app.modules.admin.model_routing.service import (
    GenerationModelRoutingService,
    RoutingPrimaryNotConfiguredError,
    RoutingRevisionConflictError,
)


class _FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _routing_row():
    return SimpleNamespace(
        id=1,
        ordered_model_ids=list(DEFAULT_GENERATION_MODEL_ORDER),
        revision=1,
        updated_by=None,
        updated_at=datetime.now(UTC),
    )


def test_route_validation_requires_deepseek_first_and_unique_approved_ids():
    assert validate_generation_model_order(["deepseek", "glm53_flash"]) == (
        "deepseek",
        "glm53_flash",
    )
    with pytest.raises(ValueError, match="deepseek_first"):
        validate_generation_model_order(["qwen38_flash_next", "deepseek"])
    with pytest.raises(ValueError, match="duplicates"):
        validate_generation_model_order(["deepseek", "deepseek"])
    with pytest.raises(ValueError, match="unknown"):
        validate_generation_model_order(["deepseek", "arbitrary_remote_model"])


@pytest.mark.asyncio
async def test_superadmin_response_is_secret_free_and_reports_configuration(monkeypatch):
    row = _routing_row()

    async def get_routing(db, *, for_update=False):
        return row

    async def get_key(db, provider):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(service_module.repo, "get_routing", get_routing)
    monkeypatch.setattr(service_module, "get_active_global_key", get_key)
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            DEEPSEEK_API_KEY="",
            DEEPSEEK_MODEL="deepseek-v4-flash",
            QWEN38_FLASH_URL="http://private-qwen.test/v1",
            QWEN38_FLASH_MODEL="qwen3.8-flash-next",
            GLM53_FLASH_URL="http://private-glm.test/v1",
            GLM53_FLASH_MODEL="GLM-5.3-Flash",
        ),
    )

    response = await GenerationModelRoutingService(_FakeSession()).get()
    payload = response.model_dump()

    assert [item.position for item in response.models] == [1, 2, 3]
    assert all(item.is_configured for item in response.models)
    assert "api_key" not in str(payload).lower()
    assert "private-qwen.test" not in str(payload)
    assert "private-glm.test" not in str(payload)


@pytest.mark.asyncio
async def test_update_is_atomic_and_rejects_stale_revision(monkeypatch):
    row = _routing_row()
    db = _FakeSession()

    async def get_routing(session, *, for_update=False):
        assert for_update is True
        return row

    async def get_key(session, provider):
        return None

    monkeypatch.setattr(service_module.repo, "get_routing", get_routing)
    monkeypatch.setattr(service_module, "get_active_global_key", get_key)
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(
            DEEPSEEK_API_KEY="configured",
            DEEPSEEK_MODEL="deepseek-v4-flash",
            QWEN38_FLASH_URL="http://qwen.test/v1",
            QWEN38_FLASH_MODEL="qwen3.8-flash-next",
            GLM53_FLASH_URL="http://glm.test/v1",
            GLM53_FLASH_MODEL="GLM-5.3-Flash",
        ),
    )

    actor = uuid.uuid4()
    saved = await GenerationModelRoutingService(db).update(
        GenerationModelRoutingUpdate(
            revision=1,
            ordered_model_ids=["deepseek", "glm53_flash"],
        ),
        user_id=actor,
    )

    assert row.ordered_model_ids == ["deepseek", "glm53_flash"]
    assert saved.revision == 2
    assert row.updated_by == actor
    assert db.commits == 1

    with pytest.raises(RoutingRevisionConflictError):
        await GenerationModelRoutingService(db).update(
            GenerationModelRoutingUpdate(
                revision=1,
                ordered_model_ids=["deepseek", "qwen38_flash_next"],
            ),
            user_id=actor,
        )
    assert db.commits == 1


@pytest.mark.asyncio
async def test_update_rejects_unconfigured_mandatory_primary(monkeypatch):
    db = _FakeSession()

    async def get_key(session, provider):
        return None

    monkeypatch.setattr(service_module, "get_active_global_key", get_key)
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: SimpleNamespace(DEEPSEEK_API_KEY=""),
    )

    with pytest.raises(RoutingPrimaryNotConfiguredError):
        await GenerationModelRoutingService(db).update(
            GenerationModelRoutingUpdate(
                revision=1,
                ordered_model_ids=["deepseek", "qwen38_flash_next"],
            ),
            user_id=uuid.uuid4(),
        )
    assert db.commits == 0


@pytest.mark.asyncio
async def test_runtime_route_read_failure_does_not_reactivate_defaults(monkeypatch):
    from app.core import db as db_module
    from app.modules.admin.model_routing import repository, runtime

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    async def fail_read(session):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(db_module, "async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(repository, "get_routing", fail_read)

    with pytest.raises(runtime.RuntimeGenerationModelRoutingUnavailableError):
        await runtime.resolve_runtime_generation_model_order()


def test_migration_enforces_rls_closed_catalog_and_seeded_owner_order():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "alembic" / "versions" / "0156_generation_model_routing.py").read_text(
        encoding="utf-8"
    )
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "app.is_superadmin" in source
    assert "REVOKE ALL" in source
    assert "ordered_model_ids ->> 1 <> ordered_model_ids ->> 2" in source
    assert "DeepSeek" not in source
    assert '\'["deepseek","qwen38_flash_next","glm53_flash"]\'::jsonb' in source


def test_router_is_superadmin_only():
    from app.modules.admin.model_routing.router import router

    assert {route.path for route in router.routes} == {"/admin/model-routing"}
    for route in router.routes:
        dependency_names = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }
        assert "role_checker" in dependency_names
