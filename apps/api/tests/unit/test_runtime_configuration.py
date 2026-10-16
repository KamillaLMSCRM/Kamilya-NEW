"""Executable operator/store/consumer contracts; no real DB/provider in units."""

import asyncio
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.admin.runtime_configuration import runtime
from app.modules.admin.runtime_configuration.catalog import (
    BY_KEY,
    CATALOG,
    InvalidSettings,
    RuntimeSnapshot,
    default_snapshot,
    effective_values,
)
from app.modules.admin.runtime_configuration.models import RuntimeSettings, RuntimeSettingsHistory
from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings as real_resolve
from app.modules.admin.runtime_configuration.schemas import SettingsRevert, SettingsUpdate
from app.modules.admin.runtime_configuration.service import RuntimeSettingsService, SettingsConflict


@pytest.mark.parametrize("role", ["admin", "methodologist", "student"])
async def test_all_operator_routes_reject_non_superadmin_before_store(role):
    import httpx
    from fastapi import FastAPI

    from app.core.auth import get_current_active_user
    from app.core.db import get_db
    from app.modules.admin.runtime_configuration.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role, id=UUID(int=1))
    app.dependency_overrides[get_db] = lambda: object()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = [await client.get("/admin/runtime-settings"), await client.get("/admin/runtime-settings/history"),
            await client.put("/admin/runtime-settings", json={"revision": 1, "changes": {"assignment.deepseek_seconds": 20}, "reason": "Synthetic"}),
            await client.post("/admin/runtime-settings/revert", json={"revision": 2, "target_revision": 1, "reason": "Synthetic"})]
    assert [response.status_code for response in responses] == [403] * 4


async def test_assignment_consumer_uses_changed_runtime_deadlines_without_mutating_defaults(monkeypatch):
    import json

    from app.modules.methodologist_workbench import intent_application as application
    from app.modules.methodologist_workbench.assignment_schemas import AssignmentInterpretRequest
    from app.modules.methodologist_workbench.plan_contract import ActorContext

    policy = RuntimeSnapshot(2, effective_values({"assignment.deepseek_seconds": 20, "assignment.chatgpt_seconds": 30}))
    monkeypatch.setattr(application, "check_and_charge_llm_budget", AsyncMock())
    provider = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=json.dumps({
        "action": "assignment_preview", "course_query": "Synthetic", "department_query": "QA",
        "due_date": "2030-12-31", "due_time": "18:00:00", "notify": False, "include_descendants": False}))))
    with runtime.runtime_settings_scope(policy):
        result = await application.interpret_assignment(SimpleNamespace(commit=AsyncMock()),
            ActorContext(tenant_id=UUID(int=2), actor_id=UUID(int=3), active_role="methodologist"),
            AssignmentInterpretRequest(instruction="Synthetic QA 2030-12-31 18:00", timezone_name="UTC"),
            provider_resolver=AsyncMock(return_value=provider))
    assert result.state == "interpreted"
    assert provider.ainvoke.await_args.kwargs["provider_deadline_overrides"] == {"deepseek": 20, "chatgpt-reserve": 30}
    assert default_snapshot().integer("assignment.deepseek_seconds") == 30


async def test_evidence_profile_uses_actual_hot_caps_not_hidden_literals(monkeypatch):
    from app.modules.ai import llm_client as llm
    policy = RuntimeSnapshot(2, effective_values({"evidence_low.deepseek_seconds": 20, "evidence_low.max_tokens": 4096}))
    provider = llm.ResilientLLMClient([llm.LLMProviderConfig("deepseek", "https://example.invalid/v1", "synthetic", "same-model", managed_evidence_profile=True)], max_tokens=2000)
    seen, deadlines = [], []
    timeout = asyncio.timeout
    def capture_timeout(seconds):
        deadlines.append(seconds)
        return timeout(seconds)
    async def request(client, payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": "synthetic"}}]}
    monkeypatch.setattr(llm.asyncio, "timeout", capture_timeout)
    monkeypatch.setattr(llm.LLMClient, "_request", request)
    with runtime.runtime_settings_scope(policy):
        await provider.ainvoke("synthetic", request_profile="evidence_low", provider_deadline_seconds=8)
    assert seen[0]["max_tokens"] == 4096 and deadlines == [20]
    assert default_snapshot().integer("evidence_low.max_tokens") == 8192


def test_frozen_sql_catalog_matches_runtime_types_and_bounds():
    path = Path(__file__).parents[2] / "alembic/versions/0182_runtime_settings.py"
    spec = importlib.util.spec_from_file_location("runtime_migration_contract", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert set(migration.NUMBERS) | set(migration.MODEL_KEYS) == set(BY_KEY)
    for key, (default, minimum, maximum, integer) in migration.NUMBERS.items():
        item = BY_KEY[key]
        assert (item.default, item.minimum, item.maximum, item.kind == "integer") == (default, minimum, maximum, integer)
    sql = []
    class Context:
        opts = {"version_table_schema": "public"}
    original_context, original_execute = migration.op.get_context, migration.op.execute
    try:
        migration.op.get_context = lambda: Context()
        migration.op.execute = sql.append
        with pytest.raises(RuntimeError, match="audit_retained"):
            migration.downgrade()
        assert not sql
    finally:
        migration.op.get_context, migration.op.execute = original_context, original_execute


@pytest.mark.parametrize("key,bad", [
    ("assignment.deepseek_seconds", True), ("assignment.deepseek_seconds", 30.0),
    ("assignment.deepseek_seconds", 61), ("assignment.deepseek_seconds", -1),
    ("generation.temperature", float("nan")), ("generation.temperature", float("inf")),
    ("generation.temperature", "0.2"), ("generation.temperature", 2),
    ("provider.deepseek.model", "https://evil.invalid/model"),
    ("provider.glm.model", "../escape"), ("provider.deepseek.model", "api key secret"),
    ("provider.chatgpt.model", "gpt-other"), ("outbox.crm.batch_size", 0),
    ("DATABASE_URL", "not-a-config-editor"),
])
def test_closed_catalog_rejects_unsafe_types_values_and_keys(key, bad):
    with pytest.raises(InvalidSettings):
        effective_values({key: bad})


def test_default_catalog_preserves_existing_policies_and_names():
    snapshot = default_snapshot()
    assert len(CATALOG) == len(BY_KEY) == 31
    assert snapshot.integer("assignment.deepseek_seconds") == 30
    assert snapshot.integer("assignment.chatgpt_seconds") == 40
    assert snapshot.integer("assignment.total_seconds") == 90
    assert snapshot.number("generation.temperature") == 0.2
    with pytest.raises(TypeError):
        snapshot.values["assignment.deepseek_seconds"] = 1


def test_cross_field_budget_validated_atomically_not_key_by_key():
    with pytest.raises(InvalidSettings, match="assignment_deadline_budget"):
        effective_values({"assignment.total_seconds": 60})
    values = effective_values({"assignment.total_seconds": 60, "assignment.deepseek_seconds": 15, "assignment.chatgpt_seconds": 30})
    assert values["assignment.total_seconds"] == 60
    with pytest.raises(InvalidSettings, match="document_deadline_budget"):
        effective_values({"document_intent.total_seconds": 10, "document_dialogue.provider_seconds": 20})


@pytest.mark.parametrize("payload", [
    {"revision": True, "changes": {"assignment.deepseek_seconds": 20}, "reason": "test"},
    {"revision": 1, "changes": {}, "reason": "test"},
    {"revision": 1, "changes": {"assignment.deepseek_seconds": 20}, "reason": "x"},
    {"revision": 1, "changes": {"assignment.deepseek_seconds": 20}, "reason": "test", "confirmed": True},
])
def test_write_commands_are_strict(payload):
    with pytest.raises(ValidationError):
        SettingsUpdate.model_validate(payload)


def test_revert_cannot_accept_fake_revision():
    with pytest.raises(ValidationError):
        SettingsRevert(revision=1, target_revision=False, reason="test")


class Store:
    def __init__(self):
        self.row = RuntimeSettings(id=1, revision=1, overrides={}, updated_at=datetime.now(UTC))
        self.audit = []
        self.commits = 0

    async def scalar(self, statement):
        if statement.column_descriptions[0]["entity"] is RuntimeSettings:
            return self.row
        return self.audit[0] if self.audit else None

    def add(self, row):
        self.audit.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


async def test_atomic_update_history_conflict_reset_and_revert():
    db, actor = Store(), UUID(int=3)
    service = RuntimeSettingsService(db)
    updated = await service.update(revision=1, changes={"assignment.deepseek_seconds": 20}, reason="Synthetic DEV check", actor_id=actor)
    assert updated["revision"] == 2 and db.commits == 1
    assert len(db.audit) == 1 and isinstance(db.audit[0], RuntimeSettingsHistory)
    assert db.audit[0].before == {} and db.audit[0].after == {"assignment.deepseek_seconds": 20}
    with pytest.raises(SettingsConflict):
        await service.update(revision=1, changes={"assignment.deepseek_seconds": 15}, reason="Stale", actor_id=actor)
    assert len(db.audit) == 1 and db.row.revision == 2
    await service.update(revision=2, changes={"assignment.deepseek_seconds": 20}, reason="No operation", actor_id=actor)
    assert len(db.audit) == 1 and db.commits == 1
    reverted = await service.revert(revision=2, target_revision=1, reason="Return initial defaults", actor_id=actor)
    assert reverted["revision"] == 3 and db.row.overrides == {} and len(db.audit) == 2
    await service.update(revision=3, changes={"provider.deepseek.model": "deepseek-test-model"}, reason="Synthetic model", actor_id=actor)
    assert db.row.overrides["provider.deepseek.model"] == "deepseek-test-model"
    await service.update(revision=4, changes={"provider.deepseek.model": None}, reason="Reset model", actor_id=actor)
    assert db.row.overrides == {}


async def test_invalid_bundle_never_writes_or_commits():
    db = Store()
    with pytest.raises(InvalidSettings):
        await RuntimeSettingsService(db).update(revision=1, changes={"assignment.total_seconds": 50}, reason="Invalid bundle", actor_id=UUID(int=3))
    assert db.row.revision == 1 and db.audit == [] and db.commits == 0


async def test_scoped_snapshot_is_stable_isolated_and_reset_on_cancellation():
    initial = runtime._scope.get()
    custom = RuntimeSnapshot(2, effective_values({"assignment.deepseek_seconds": 20}))
    async def operation():
        with runtime.runtime_settings_scope(custom):
            assert await real_resolve() is custom
            await asyncio.sleep(0)
            assert await real_resolve() is custom
            raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await operation()
    assert runtime._scope.get() is initial


async def test_runtime_reader_does_not_hide_outage_or_invalid_row(monkeypatch):
    from app.core import db
    class Session:
        async def __aenter__(self):
            raise OSError("sensitive-db-address-not-to-log")
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(db, "async_session_factory", Session)
    token = runtime._scope.set(None)
    try:
        with pytest.raises(runtime.RuntimeSettingsUnavailable, match="^runtime_settings_unavailable$"):
            await real_resolve()
    finally:
        runtime._scope.reset(token)


async def test_managed_provider_policy_changes_names_not_endpoints_or_route(monkeypatch):
    from app.modules.ai import llm_client as llm
    policy = RuntimeSnapshot(2, effective_values({"provider.deepseek.model": "deepseek-synthetic", "provider.deepseek.timeout_seconds": 90}))
    monkeypatch.setattr(llm, "resolve_runtime_settings", AsyncMock(return_value=policy))
    monkeypatch.setattr(llm, "resolve_runtime_generation_model_order", AsyncMock(return_value=("deepseek",)))
    monkeypatch.setattr(llm, "_resolve_db_key", AsyncMock(return_value="synthetic-key"))
    client = await llm.ResilientLLMClient.from_settings_async()
    assert client.provider_names == ["deepseek"]
    config = client._clients[0].config
    assert config.model == "deepseek-synthetic" and config.timeout == 90
    assert config.base_url == llm._openai_base_url(llm.get_settings().DEEPSEEK_BASE_URL)
    assert config.api_key == "synthetic-key"


async def test_byok_is_not_overridden_by_global_policy(monkeypatch):
    from app.modules.admin.tenant_ai_providers import service
    from app.modules.ai import llm_client as llm
    override = llm.LLMProviderConfig(name="byok", base_url="https://example.invalid/v1", api_key="synthetic", model="tenant-owned", timeout=17)
    monkeypatch.setattr(service, "resolve_tenant_provider", AsyncMock(return_value=override))
    forbidden = AsyncMock(side_effect=AssertionError("global policy must not touch BYOK"))
    monkeypatch.setattr(llm, "resolve_runtime_settings", forbidden)
    client = await llm.ResilientLLMClient.from_settings_async(tenant_id=UUID(int=2))
    assert client._clients[0].config is override and forbidden.await_count == 0
