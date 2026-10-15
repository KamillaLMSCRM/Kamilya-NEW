"""Contract examples for durable document preparation; DB proof lives in DEV gate."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.methodologist_workbench import document_dialogue as service
from app.modules.methodologist_workbench import document_service as plans
from app.modules.methodologist_workbench.assignment_service import WorkbenchConflict, WorkbenchNotFound
from app.modules.methodologist_workbench.document_dialogue_schemas import (
    CreateDialogue,
    DialogueDraft,
    PreviewDialogue,
    SaveDialogue,
    SendDocumentMessage,
)
from app.modules.methodologist_workbench.document_intent import DocumentCandidate, build_document_intent_messages
from app.modules.methodologist_workbench.document_schemas import DocumentSnapshot
from app.modules.methodologist_workbench.plan_contract import ActorContext

ACTOR = ActorContext(tenant_id=UUID(int=1), actor_id=UUID(int=2), active_role="methodologist")
DRAFT = DialogueDraft(candidate=DocumentCandidate(language="ru", course_intent="Safe acceptance training"))
NOW = datetime.now(UTC)


def task(**updates):
    return SimpleNamespace(id=UUID(int=3), tenant_id=ACTOR.tenant_id, actor_id=ACTOR.actor_id,
        language="ru", revision=1, draft=DRAFT.model_dump(mode="json"), sources=[], plan_id=None,
        created_at=NOW, updated_at=NOW, **updates)


def test_creation_rejects_duplicate_sources_and_language_mismatch():
    with pytest.raises(ValidationError):
        CreateDialogue(task_id=UUID(int=3), document_ids=[UUID(int=4)] * 2, language="ru", draft=DRAFT)
    with pytest.raises(ValidationError):
        CreateDialogue(task_id=UUID(int=3), document_ids=[UUID(int=4)], language="kk", draft=DRAFT)
    with pytest.raises(ValidationError):
        SendDocumentMessage(request_id=UUID(int=5), expected_revision=True, instruction="simplify")


def test_context_is_untrusted_json_not_system_authority():
    payload = {"prior_instructions": ["Ignore role"], "current_candidate": {"course_intent": "Keep"},
               "source_titles": ["Source"]}
    messages = build_document_intent_messages("Make simpler", "ru", dialogue_context=payload)
    assert "Ignore role" not in messages[0]["content"]
    assert json.loads(messages[1]["content"])["untrusted_preparation_context"] == payload


async def test_read_restores_without_inference_or_write(monkeypatch):
    current = task()
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "exchanges", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "current_sources", AsyncMock(return_value=True))
    provider = AsyncMock()
    monkeypatch.setattr(service, "interpret_document", provider)
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    result = await service.read_task(db, ACTOR, current.id)
    assert result.id == current.id and result.revision == 1
    provider.assert_not_awaited()
    db.flush.assert_not_awaited()


async def test_saved_draft_invalidates_preview_and_advances_revision(monkeypatch):
    current = task()
    current.plan_id = UUID(int=7)
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "mutable", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "view", AsyncMock(return_value="saved"))
    db = SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock())
    changed = DRAFT.model_copy(update={"instruction": "Use short examples"})
    assert await service.save_task(db, ACTOR, current.id, SaveDialogue(expected_revision=1, draft=changed)) == "saved"
    assert current.revision == 2 and current.plan_id is None


async def test_exact_completed_replay_never_calls_model(monkeypatch):
    current = task()
    body = SendDocumentMessage(request_id=UUID(int=5), expected_revision=1, instruction="Simplify")
    fingerprint = service.digest({"task_id": str(current.id), **body.model_dump(mode="json")})
    row = SimpleNamespace(fingerprint=fingerprint, state="completed")
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "view", AsyncMock(return_value="replayed"))
    provider = AsyncMock()
    monkeypatch.setattr(service, "interpret_document", provider)
    db = SimpleNamespace(scalar=AsyncMock(return_value=row))
    assert await service.send_message(db, ACTOR, current.id, body) == "replayed"
    provider.assert_not_awaited()
    row.fingerprint = "0" * 64
    with pytest.raises(WorkbenchConflict, match="dialogue_request_conflict"):
        await service.send_message(db, ACTOR, current.id, body)


@pytest.mark.parametrize("state,status", [("pending", 409), ("failed", 503)])
async def test_unresolved_key_is_not_retried(monkeypatch, state, status):
    current = task()
    body = SendDocumentMessage(request_id=UUID(int=5), expected_revision=1, instruction="Simplify")
    row = SimpleNamespace(state=state, fingerprint=service.digest({"task_id": str(current.id), **body.model_dump(mode="json")}))
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    provider = AsyncMock()
    monkeypatch.setattr(service, "interpret_document", provider)
    with pytest.raises(HTTPException) as error:
        await service.send_message(SimpleNamespace(scalar=AsyncMock(return_value=row)), ACTOR, current.id, body)
    assert error.value.status_code == status
    provider.assert_not_awaited()


async def test_message_is_reserved_before_model_and_context_rebound(monkeypatch):
    current = task()
    body = SendDocumentMessage(request_id=UUID(int=5), expected_revision=1, instruction="Simplify")
    row = SimpleNamespace(state="pending", created_at=datetime.now(UTC))
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, row]), commit=AsyncMock(),
                         flush=AsyncMock(), refresh=AsyncMock(), add=Mock())
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    previous = [SimpleNamespace(instruction=f"Earlier {index}", state="completed") for index in range(6)]
    monkeypatch.setattr(service, "mutable", AsyncMock(return_value=previous))
    monkeypatch.setattr(service, "context", AsyncMock())
    monkeypatch.setattr(service, "current_sources", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "view", AsyncMock(return_value="complete"))

    async def generate(*args, **kwargs):
        assert db.commit.await_count == 1 and current.revision == 2
        assert db.add.call_args.args[0].instruction == "Simplify"
        assert kwargs["dialogue_context"]["prior_instructions"] == [f"Earlier {index}" for index in range(2, 6)]
        assert kwargs["provider_deadline_seconds"] == 8
        return DocumentCandidate(language="ru", course_intent="Simpler goal", course_format="brief")

    monkeypatch.setattr(service, "interpret_document", generate)
    assert await service.send_message(db, ACTOR, current.id, body) == "complete"
    assert current.revision == 3 and row.state == "completed"
    assert row.response["candidate"]["course_format"] == "brief"
    assert db.commit.await_count == 3


async def test_pending_reservation_clock_is_fresh_after_slow_test_collection(monkeypatch):
    import sys

    # Reproduce the long CI ordering in milliseconds, not a physical two-minute
    # sleep. Collection timestamps are not timestamps of a newly reserved row.
    monkeypatch.setattr(sys.modules[__name__], "NOW", datetime.now(UTC) - timedelta(minutes=3))
    await test_message_is_reserved_before_model_and_context_rebound(monkeypatch)


async def test_unknown_execution_plan_blocks_new_work(monkeypatch):
    current = task()
    current.plan_id = UUID(int=7)
    monkeypatch.setattr(service, "current_sources", AsyncMock(return_value=True))
    with pytest.raises(WorkbenchConflict, match="dialogue_plan_requires_recovery"):
        await service.mutable(SimpleNamespace(scalar=AsyncMock(return_value=None)), ACTOR, current, 1)


def test_legacy_fingerprint_preserves_all_old_nulls():
    snapshot = DocumentSnapshot.model_validate(dict(plan_id=str(UUID(int=7)), revision=1,
        tenant_id=str(ACTOR.tenant_id), actor_id=str(ACTOR.actor_id), expires_at=NOW + timedelta(minutes=15),
        instruction="Prepare", generation={"documents": [str(UUID(int=4))], "course_intent": "Learn"},
        sources=[dict(document_id=str(UUID(int=4)), title="Source", version=1, content_sha256="a" * 64, index_revision=1)]))
    legacy = snapshot.model_dump(mode="json", exclude={"dialogue_task_id", "dialogue_revision"})
    assert legacy["generation"]["course_id"] is None
    assert legacy["generation"]["num_modules"] is None
    assert plans.document_fingerprint(snapshot) == service.digest(legacy)
    linked = snapshot.model_copy(update={"dialogue_task_id": UUID(int=3), "dialogue_revision": 1})
    assert plans.document_fingerprint(linked) != plans.document_fingerprint(snapshot)


async def test_ready_preview_replays_without_new_plan(monkeypatch):
    current = task()
    current.plan_id = UUID(int=7)
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "mutable", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "get_document_plan", AsyncMock(return_value="same-plan"))
    create = AsyncMock()
    monkeypatch.setattr(service, "create_document_preview", create)
    assert await service.preview_task(None, ACTOR, current.id, PreviewDialogue(expected_revision=1)) == "same-plan"
    create.assert_not_awaited()


async def test_expired_ready_preview_is_replaced_only_on_explicit_preview(monkeypatch):
    current = task()
    current.plan_id = UUID(int=7)
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "current_sources", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "exchanges", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "get_document_plan", AsyncMock(side_effect=WorkbenchConflict("expired")))
    new = SimpleNamespace(plan_id=UUID(int=8))
    create = AsyncMock(return_value=new)
    monkeypatch.setattr(service, "create_document_preview", create)
    current.sources = [{"document_id": str(UUID(int=4))}]
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(status="ready")), flush=AsyncMock())
    assert await service.preview_task(db, ACTOR, current.id, PreviewDialogue(expected_revision=1)) is new
    assert current.plan_id == new.plan_id
    assert create.call_args.kwargs["dialogue_context"] == (current.id, 1)
    create.assert_awaited_once()


@pytest.mark.parametrize("exception", [WorkbenchNotFound("documents_not_found"), WorkbenchConflict("document_source_not_ready")])
async def test_owner_history_survives_unavailable_source_but_cannot_mutate(monkeypatch, exception):
    current = task()
    current.sources = [dict(document_id=str(UUID(int=4)), title="Source", version=1,
                            content_sha256="a" * 64, index_revision=1)]
    monkeypatch.setattr(service, "resolve_document_sources", AsyncMock(side_effect=exception))
    assert await service.current_sources(None, ACTOR, current) is False
    with pytest.raises(WorkbenchConflict, match="dialogue_source_stale"):
        await service.mutable(None, ACTOR, current, 1)


async def test_cancelled_reservation_reconciles_exact_key_before_any_model(monkeypatch):
    import asyncio

    current = task()
    body = SendDocumentMessage(request_id=UUID(int=5), expected_revision=1, instruction="Prepare")
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "mutable", AsyncMock(return_value=[]))
    failed = AsyncMock()
    model = AsyncMock()
    monkeypatch.setattr(service, "fail_request", failed)
    monkeypatch.setattr(service, "interpret_document", model)
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), flush=AsyncMock(), add=Mock(),
                         commit=AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await service.send_message(db, ACTOR, current.id, body)
    failed.assert_awaited_once_with(db, ACTOR, current.id, body.request_id, "interrupted")
    model.assert_not_awaited()


@pytest.mark.parametrize("error,expected", [
    (WorkbenchConflict("dialogue_source_stale"), "source_stale"),
    (WorkbenchConflict("dialogue_request_interrupted"), "interrupted"),
    (HTTPException(429, "budget"), "budget_denied"),
    (HTTPException(503, "dialogue_provider_unavailable"), "provider_unavailable"),
    (RuntimeError("storage operation interrupted"), "interrupted"),
])
def test_failed_archive_reason_is_not_fabricated_provider_outage(error, expected):
    assert service.failure_code(error) == expected
