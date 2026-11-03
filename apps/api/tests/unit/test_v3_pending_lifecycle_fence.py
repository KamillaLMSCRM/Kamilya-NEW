from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.modules.ai import job_service, router


@pytest.mark.parametrize("value", [None, {}, {"malformed": True}])
@pytest.mark.asyncio
async def test_pending_presence_blocks_locked_refund_and_resume(monkeypatch, value):
    job = SimpleNamespace(course_id=None, status="interrupted", result={"v3_pending_stages": value},
        params={"documents": ["x"], "source_analysis": {"generation_engine": "evidence_v3", "analysis_mode": "direct_source"}})
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    assert not await job_service.release_generation_reservation_once(SimpleNamespace(), job_id="job", tenant_id=uuid4())
    assert not job_service.is_resumable_generation_job(job)


@pytest.mark.parametrize("value", [None, {}, {"bad": True}])
@pytest.mark.asyncio
async def test_owner_cancellation_and_resume_blocked_under_pending(monkeypatch, value):
    tenant = uuid4()
    job = SimpleNamespace(status="running", result={"v3_pending_stages": value}, params={}, tenant_id=tenant)
    monkeypatch.setattr(router, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(router, "get_ai_job", AsyncMock(return_value=job))
    update = AsyncMock()
    monkeypatch.setattr(router, "update_ai_job", update)
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant, role="methodologist")
    with pytest.raises(HTTPException) as error:
        await router.cancel_generation("job", SimpleNamespace(), user)
    assert error.value.status_code == 409 and error.value.detail["code"] == "v3_stage_pending_or_unknown"
    update.assert_not_awaited()
    job.status = "interrupted"
    with pytest.raises(HTTPException) as error:
        await router.resume_generation("job", SimpleNamespace(), user)
    assert error.value.status_code == 409


def test_sql_lifecycle_predicate_preserves_null_and_key_presence():
    statement = job_service._no_pending_stage()
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "v3_pending_stages" in compiled.params.values()
    assert "coalesce" in str(compiled).lower() and " ? " in str(compiled)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, {}, {"unexpected": True}])
async def test_admin_recovery_skips_pending_after_locked_recheck(monkeypatch, value):
    from datetime import UTC, datetime, timedelta

    from app.modules.admin.superadmin.operations import SuperadminOperationsService

    job = SimpleNamespace(tenant_id=uuid4(), status="running", params={"source_analysis": {
        "generation_engine": "evidence_v3"}}, result={"v3_pending_stages": value},
        updated_at=datetime.now(UTC) - timedelta(days=2), created_at=datetime.now(UTC) - timedelta(days=3))
    db = SimpleNamespace(flush=AsyncMock())
    service = SuperadminOperationsService(db)
    monkeypatch.setattr(service, "_stale_ai_job_candidates", AsyncMock(return_value=([job], False)))
    monkeypatch.setattr(service, "_set_tenant_context", AsyncMock())
    result = await service.recover_stale_ai_jobs(dry_run=False, min_age_hours=24, confirm=True,
                                                 confirm_token="RECOVER_STALE_AI_JOBS")
    assert result.recovered_count == 0 and result.skipped_count == 1 and job.status == "running"
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_foreign_tenant_job_does_not_mutate(monkeypatch):
    tenant = uuid4()
    monkeypatch.setattr(router, "_lock_tenant_row", AsyncMock())
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(router, "get_ai_job", lookup)
    update = AsyncMock()
    monkeypatch.setattr(router, "update_ai_job", update)
    with pytest.raises(HTTPException) as error:
        await router.cancel_generation("foreign-job", SimpleNamespace(),
            SimpleNamespace(id=uuid4(), tenant_id=tenant, role="methodologist"))
    assert error.value.status_code == 404
    assert lookup.await_args.kwargs["tenant_id"] == str(tenant) and lookup.await_args.kwargs["for_update"] is True
    update.assert_not_awaited()


def test_legacy_sql_null_predicate_compiles_as_negated_coalesced_existence():
    from app.modules.ai.v3.pending_stage_transactions import pending_sql_predicate

    compiled = (~pending_sql_predicate()).compile(dialect=postgresql.dialect())
    expression = str(compiled).lower()
    assert "case" in expression and "coalesce" in expression and " ? " in expression and "false" in expression
    assert "v3_pending_stages" in compiled.params.values()


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", [None, {}, {"private": "synthetic-marker-secret"}])
async def test_visible_pending_projection_is_safe_and_completed_unchanged(marker):
    from datetime import UTC, datetime

    job = SimpleNamespace(id="job", tenant_id=uuid4(), user_id=uuid4(), status="running", stage="generating",
        progress=20, message="running", errors=None, course_id=None, created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC), started_at=None, params={"documents": ["x"]},
        result={"v3_pending_stages": marker})
    response = await router._job_response(SimpleNamespace(), job, queue_metadata={})
    assert response.status == "running" and response.message == "running" and response.errors is None
    assert "synthetic-marker-secret" not in str(response.model_dump())
    for status in ("interrupted", "failed", "cancelled", "completed"):
        job.status = status
        held = await router._job_response(SimpleNamespace(), job, queue_metadata={})
        assert held.status == "reconciliation_required"
        assert "source_first_commit_pending_or_unknown" in held.errors
        assert "генерац" in held.message.lower() and "администратору" in held.message
        assert "synthetic-marker-secret" not in str(held.model_dump())


@pytest.mark.asyncio
async def test_visible_absent_marker_preserves_status():
    from datetime import UTC, datetime

    job = SimpleNamespace(id="job", tenant_id=uuid4(), user_id=uuid4(), status="running", stage="generating",
        progress=20, message="running", errors=None, course_id=None, created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC), started_at=None, params={"documents": ["x"]}, result=None)
    response = await router._job_response(SimpleNamespace(), job, queue_metadata={})
    assert response.status == "running" and response.message == "running" and response.errors is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,projected", [("running", "running"), ("completed", "reconciliation_required")])
async def test_pending_projection_websocket_matches_rest(monkeypatch, status, projected):
    from datetime import UTC, datetime

    from fastapi import WebSocketDisconnect

    from app.core import db as db_module

    tenant, user_id = uuid4(), uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant, role="methodologist")
    job = SimpleNamespace(id="job", user_id=user_id, tenant_id=tenant, status=status, stage="generating",
        progress=20, message="running", errors=None, course_id=None, created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC), started_at=None, params={"documents": ["x"]},
        result={"v3_pending_stages": None})
    response = await router._job_response(SimpleNamespace(), job, queue_metadata={})
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    class Socket:
        def __init__(self): self.events = []
        async def accept(self): pass
        async def send_json(self, value): self.events.append(value)
    monkeypatch.setattr(db_module, "async_session_factory", Session)
    monkeypatch.setattr(router, "get_ai_job", AsyncMock(return_value=job))
    monkeypatch.setattr(router, "get_current_user", AsyncMock(return_value=user))
    monkeypatch.setattr(router, "get_current_active_user", AsyncMock(return_value=user))
    monkeypatch.setattr(router, "require_ai_job_access", AsyncMock())
    monkeypatch.setattr(router.asyncio, "sleep", AsyncMock(side_effect=WebSocketDisconnect()))
    socket = Socket()
    await router.job_progress_ws(socket, "job", token="synthetic")
    assert response.status == projected == socket.events[0]["status"]
    assert response.message == socket.events[0]["message"] and response.errors == socket.events[0]["errors"]


def test_sqlite_presence_distinguishes_sql_null_absent_and_json_null():
    from sqlalchemy import create_engine, select, text

    from app.models.ai_job import AIJob
    from app.modules.ai.v3.pending_stage_transactions import pending_sql_predicate

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ai_jobs (id TEXT PRIMARY KEY, result TEXT)"))
        connection.execute(text("INSERT INTO ai_jobs (id, result) VALUES (:id, :result)"), [
            {"id": "sql_null", "result": None}, {"id": "absent", "result": '{}'},
            {"id": "json_null", "result": '{"v3_pending_stages":null}'},
            {"id": "present", "result": '{"v3_pending_stages":{}}'},
            {"id": "top_null", "result": "null"}, {"id": "array", "result": "[]"},
            {"id": "string", "result": '"text"'}, {"id": "number", "result": "1"},
            {"id": "invalid", "result": "not-json"},
        ])
        actual = dict(connection.execute(select(AIJob.id, pending_sql_predicate())).all())
        allowed = dict(connection.execute(select(AIJob.id, ~pending_sql_predicate())).all())
    assert actual == {"sql_null": False, "absent": False, "json_null": True, "present": True,
                      "top_null": False, "array": True, "string": True, "number": True, "invalid": True}
    assert allowed == {key: not value for key, value in actual.items()}


def test_pending_key_expression_rejects_unsupported_dialect():
    from sqlalchemy.dialects import mysql
    from sqlalchemy.exc import UnsupportedCompilationError

    from app.modules.ai.v3.pending_stage_transactions import pending_sql_predicate

    with pytest.raises(UnsupportedCompilationError):
        pending_sql_predicate().compile(dialect=mysql.dialect())


def test_malformed_top_level_array_is_held():
    from app.modules.ai.v3.pending_stage_transactions import has_pending

    assert has_pending(["v3_pending_stages"]) is True
    assert has_pending([]) is True
    assert has_pending(None) is False


@pytest.mark.parametrize("value", [[], ["x"], "text", 1, True, 1.5])
def test_non_null_non_object_job_results_are_held(value):
    from app.modules.ai.v3.pending_stage_transactions import has_pending

    assert has_pending(value) is True
