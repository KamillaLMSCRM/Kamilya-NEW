"""Document plan public seams; no provider, database or broker required."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.methodologist_workbench.document_schemas import DocumentGenerationRequest, DocumentPreviewRequest
from app.modules.methodologist_workbench.plan_contract import ActorContext, ConfirmationRequest


def plan_fixture(*, submitted=False):
    from app.modules.methodologist_workbench import document_service as service
    from app.modules.methodologist_workbench.document_schemas import DocumentSnapshot, DocumentSource

    actor = ActorContext(tenant_id=UUID(int=1), actor_id=UUID(int=2), active_role="methodologist")
    now = datetime(2026, 10, 4, tzinfo=UTC)
    source = DocumentSource(document_id=UUID(int=3), title="Safety", version=1, content_sha256="a" * 64, index_revision=1)
    snapshot = DocumentSnapshot(plan_id=UUID(int=4), revision=1, tenant_id=actor.tenant_id,
                                actor_id=actor.actor_id, expires_at=now + timedelta(minutes=15),
                                instruction="Create safety training", generation=DocumentGenerationRequest(
                                    documents=[source.document_id], course_intent="Create safety training"), sources=(source,))
    row = SimpleNamespace(id=snapshot.plan_id, tenant_id=actor.tenant_id, actor_id=actor.actor_id,
                          snapshot=snapshot.model_dump(mode="json"), fingerprint=service.document_fingerprint(snapshot),
                          status="submitted" if submitted else "ready", job_id="job-id" if submitted else None,
                          expires_at=snapshot.expires_at)
    user = SimpleNamespace(id=actor.actor_id, tenant_id=actor.tenant_id, role="methodologist")
    request = ConfirmationRequest(plan_id=row.id, revision=1, fingerprint=row.fingerprint)
    return actor, now, source, row, user, request


@pytest.mark.asyncio
async def test_preview_persists_sources_and_does_not_submit_a_job(monkeypatch):
    from app.modules.methodologist_workbench import document_service as service

    actor = ActorContext(tenant_id=UUID(int=1), actor_id=UUID(int=2), active_role="methodologist")
    source = SimpleNamespace(id=UUID(int=3), title="Safety", version=2, content_sha256="a" * 64, index_revision=1, index_status="ready")
    rows = SimpleNamespace(all=lambda: [source])
    saved = []
    db = SimpleNamespace(scalars=AsyncMock(return_value=rows), scalar=AsyncMock(return_value=0),
                         add=saved.append, flush=AsyncMock())
    body = DocumentPreviewRequest(instruction="Create a safety course", generation=DocumentGenerationRequest(documents=[source.id], course_intent="Create a safety course"))
    now = datetime(2026, 10, 4, tzinfo=UTC)
    preview = await service.create_document_preview(db, actor, body, now=now)
    assert preview.state == "preview_ready"
    assert preview.sources[0].content_sha256 == "a" * 64
    assert preview.expires_at == now + timedelta(minutes=15)
    assert len(saved) == 1 and saved[0].job_id is None and saved[0].status == "ready"
    assert saved[0].snapshot["generation"]["documents"] == [str(source.id)]


@pytest.mark.asyncio
async def test_confirm_binds_exact_job_before_submission_commit(monkeypatch):
    from app.modules.ai import router as ai
    from app.modules.ai.schemas import AIJobResponse
    from app.modules.methodologist_workbench import document_service as service

    actor, now, source, row, user, request = plan_fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=row), flush=AsyncMock())
    monkeypatch.setattr(service, "resolve_document_sources", AsyncMock(return_value=(source,)))
    calls = []

    async def submit(generation, session, caller, *, before_commit):
        calls.append(generation)
        assert session is db and caller is user
        await before_commit(SimpleNamespace(id="exact-job"))
        assert row.status == "submitted" and row.job_id == "exact-job"
        return AIJobResponse(id="exact-job", status="pending", job_type="generation", course_id=None, created_at=now, updated_at=now)

    monkeypatch.setattr(ai, "submit_course_generation", submit)
    result = await service.confirm_document_plan(db, actor, request, user, now=now)
    assert result.job.id == "exact-job" and result.plan_id == row.id and len(calls) == 1
    assert calls[0].course_intent == "Create safety training"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_submitted_replay_returns_failed_job_even_after_expiry(monkeypatch):
    from app.modules.ai import router as ai
    from app.modules.ai.schemas import AIJobResponse
    from app.modules.methodologist_workbench import document_service as service
    from app.modules.methodologist_workbench.document_schemas import DocumentExecution

    actor, now, _, row, user, request = plan_fixture(submitted=True)
    db = SimpleNamespace(scalar=AsyncMock(return_value=row))
    submit = AsyncMock()
    monkeypatch.setattr(ai, "submit_course_generation", submit)
    replay = DocumentExecution(plan_id=row.id, job=AIJobResponse(id="job-id", status="failed", course_id=None, created_at=now, updated_at=now))
    monkeypatch.setattr(service, "_execution", AsyncMock(return_value=replay))
    assert await service.confirm_document_plan(db, actor, request, user, now=now + timedelta(days=1)) == replay
    submit.assert_not_awaited()


@pytest.mark.parametrize("cause", ["expired", "stale", "context_mismatch", "confirmation_mismatch"])
@pytest.mark.asyncio
async def test_invalid_confirmation_never_submits(monkeypatch, cause):
    from app.modules.ai import router as ai
    from app.modules.methodologist_workbench import document_service as service

    actor, now, source, row, user, request = plan_fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=row))
    submit = AsyncMock()
    monkeypatch.setattr(ai, "submit_course_generation", submit)
    if cause == "expired":
        now += timedelta(hours=1)
    elif cause == "stale":
        source = source.model_copy(update={"content_sha256": "b" * 64})
    elif cause == "context_mismatch":
        user.tenant_id = UUID(int=9)
    else:
        request = request.model_copy(update={"fingerprint": "b" * 64})
    monkeypatch.setattr(service, "resolve_document_sources", AsyncMock(return_value=(source,)))
    with pytest.raises(service.WorkbenchConflict, match=cause):
        await service.confirm_document_plan(db, actor, request, user, now=now)
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_or_missing_source_returns_not_found_without_plan_write():
    from app.modules.methodologist_workbench import document_service as service

    actor, now, source, _, _, _ = plan_fixture()
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    body = DocumentPreviewRequest(instruction="Create safety training", generation=DocumentGenerationRequest(
        documents=[source.document_id], course_intent="Create safety training"))
    with pytest.raises(service.WorkbenchNotFound):
        await service.create_document_preview(db, actor, body, now=now)


def test_preview_rejects_executable_authority_existing_course_and_empty_goal():
    from pydantic import ValidationError

    for extra in ({"course_id": UUID(int=9)}, {"tenant_id": UUID(int=9)}, {"publish": True}, {"course_intent": " "}):
        fields = {"documents": [UUID(int=3)], "course_intent": "Create safety training", **extra}
        with pytest.raises(ValidationError):
            DocumentGenerationRequest(**fields)
