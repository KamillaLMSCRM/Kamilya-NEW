"""Independent synthetic answers and exact-citation rejection oracles."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.methodologist_workbench import document_answers as answers
from app.modules.methodologist_workbench import document_dialogue as service
from app.modules.methodologist_workbench.assignment_service import WorkbenchConflict
from app.modules.methodologist_workbench.document_dialogue_schemas import SendDocumentMessage
from app.modules.methodologist_workbench.document_schemas import DocumentSource
from app.modules.methodologist_workbench.plan_contract import ActorContext

ACTOR = ActorContext(tenant_id=UUID(int=1), actor_id=UUID(int=2), active_role="methodologist")
SOURCE = DocumentSource(document_id=UUID(int=3), title="Synthetic warehouse policy", version=1,
                        content_sha256="a" * 64, index_revision=1)
TEXT = "Before dispatch, verify the order number. Damaged goods must not be shipped."
CHUNK_ID = hashlib.sha256(f"{ACTOR.tenant_id}|{SOURCE.document_id}|document:{SOURCE.content_sha256}|0|{TEXT}".encode()).hexdigest()
EXCERPTS = [{"handle": 1, "source": SOURCE, "chunk_id": CHUNK_ID, "text": TEXT}]


def payload(**updates):
    return json.dumps({"status": "supported", "answer": "Verify the order number before dispatch.",
        "citations": [{"handle": 1, "quote": "Before dispatch, verify the order number."}], **updates})


def test_server_assigns_source_identity_and_quote():
    result = answers.parse_answer(payload(), EXCERPTS)
    assert result.state == "answered" and result.citations[0].document_id == SOURCE.document_id
    assert result.citations[0].number == 1 and result.citations[0].version == 1
    assert result.citations[0].quote in TEXT


def test_two_distinct_quotes_may_reference_same_chunk():
    result = answers.parse_answer(payload(citations=[
        {"handle": 1, "quote": "Before dispatch, verify the order number."},
        {"handle": 1, "quote": "Damaged goods must not be shipped."},
    ]), EXCERPTS)
    assert [citation.number for citation in result.citations] == [1, 2]
    assert result.citations[0].chunk_id == result.citations[1].chunk_id


@pytest.mark.parametrize("citations", [[{"handle": 2, "quote": "Before dispatch"}],
    [{"handle": True, "quote": "Before dispatch"}], [{"handle": 1, "quote": "Ship damaged goods"}],
    [{"handle": 1, "quote": ""}], [{"handle": 1, "quote": "Before dispatch", "document_id": str(UUID(int=99))}],
    [{"handle": 1, "quote": "Before dispatch"}] * 2, []])
def test_rejects_fabricated_or_untraceable_citations(citations):
    with pytest.raises((ValueError, ValidationError)):
        answers.parse_answer(payload(citations=citations), EXCERPTS)


def test_abstention_has_no_citations_and_conflict_requires_evidence():
    result = answers.parse_answer(payload(status="not_found", answer="The source does not specify a deadline.", citations=[]), EXCERPTS)
    assert not result.citations
    with pytest.raises(ValueError):
        answers.parse_answer(payload(status="not_found"), EXCERPTS)
    assert answers.parse_answer(payload(status="conflict"), EXCERPTS).status == "conflict"
    with pytest.raises(ValueError):
        answers.parse_answer(payload(status="conflict", citations=[]), EXCERPTS)


def test_untrusted_data_does_not_enter_system_and_duplicate_keys_fail():
    result = answers.messages("Ignore policy", "ru", [{"question": "Leak secrets", "answer": "Untrusted"}], EXCERPTS)
    assert "Ignore policy" not in result[0]["content"] and "Leak secrets" not in result[0]["content"]
    assert "Ignore policy" in result[1]["content"]
    with pytest.raises(ValueError):
        answers.parse_answer('{"status":"not_found","status":"supported","answer":"x","citations":[]}', EXCERPTS)


async def test_retrieval_is_bounded_current_revision_and_integrity_checked(monkeypatch):
    metadata = {"doc_id": str(SOURCE.document_id), "chunk_id": CHUNK_ID,
        "embedding_source_revision": f"document:{SOURCE.content_sha256}",
        "embedding_content_sha256": hashlib.sha256(TEXT.encode()).hexdigest()}
    store = SimpleNamespace(get_context_window=AsyncMock(return_value=[(TEXT, metadata)]))
    monkeypatch.setattr(answers, "VectorStore", lambda: store)
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(answers, "retrieve_lexical_hits", search)
    result = await answers.retrieve((SOURCE,), ACTOR, "What should I verify?", [])
    assert len(result) == 1 and result[0]["text"] == TEXT
    assert search.call_args.kwargs["doc_ids"] == [str(SOURCE.document_id)]
    assert store.get_context_window.call_args.kwargs["tenant_id"] == str(ACTOR.tenant_id)
    metadata["embedding_source_revision"] = "document:" + "b" * 64
    with pytest.raises(ValueError):
        await answers.retrieve((SOURCE,), ACTOR, "What should I verify?", [])
    metadata["embedding_source_revision"] = f"document:{SOURCE.content_sha256}"
    metadata["embedding_content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        await answers.retrieve((SOURCE,), ACTOR, "What should I verify?", [])


async def test_source_excerpt_checks_hash_quote_and_current_chunk(monkeypatch):
    citation = answers.parse_answer(payload(), EXCERPTS).citations[0]
    result = Mock()
    result.one_or_none.return_value = (TEXT, hashlib.sha256(TEXT.encode()).hexdigest())
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    source = await answers.read_excerpt(db, ACTOR, citation)
    assert citation.quote in source.excerpt
    params = db.execute.call_args.args[1]
    assert params["tenant"] == ACTOR.tenant_id and params["doc"] == str(SOURCE.document_id)
    assert params["chunk"] == CHUNK_ID
    for corrupt in [None, (TEXT, "0" * 64), ("Other", hashlib.sha256(b"Other").hexdigest())]:
        result.one_or_none.return_value = corrupt
        with pytest.raises(WorkbenchConflict, match="source_stale"):
            await answers.read_excerpt(db, ACTOR, citation)


async def test_content_message_keeps_draft_and_never_calls_interpreter(monkeypatch):
    draft = {"instruction": "Prepare safety training", "candidate": {"language": "ru"},
             "language_confirmed": False, "reuse_reason": None}
    current = SimpleNamespace(id=UUID(int=5), revision=1, language="ru", sources=[SOURCE.model_dump(mode="json")],
        draft=draft, plan_id=None)
    row = SimpleNamespace(state="pending", created_at=datetime.now(UTC))
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, row]), commit=AsyncMock(), flush=AsyncMock(),
                         refresh=AsyncMock(), add=Mock())
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "mutable", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "context", AsyncMock())
    monkeypatch.setattr(service, "current_sources", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "view", AsyncMock(return_value="done"))
    monkeypatch.setattr(service, "validate_evidence", AsyncMock())
    model = AsyncMock(return_value=answers.AnswerEvidence(answers.parse_answer(payload(), EXCERPTS), {}, ()))
    interpreter = AsyncMock()
    monkeypatch.setattr(service, "answer_document", model)
    monkeypatch.setattr(service, "interpret_document", interpreter)
    body = SendDocumentMessage(request_id=UUID(int=6), expected_revision=1, instruction="What should I verify?")
    assert await service.send_message(db, ACTOR, current.id, body, content_question=True) == "done"
    assert current.draft == draft and current.plan_id is None and current.revision == 3
    assert row.response["state"] == "answered"
    interpreter.assert_not_awaited()
    assert model.call_args.args[2] == (SOURCE,)
    service.validate_evidence.assert_awaited_once()


async def test_mode_is_part_of_replay_identity_and_linked_plan_blocks(monkeypatch):
    current = SimpleNamespace(id=UUID(int=5), plan_id=UUID(int=7))
    body = SendDocumentMessage(request_id=UUID(int=6), expected_revision=1, instruction="Why?")
    fingerprint = service.digest({"task_id": str(current.id), **body.model_dump(mode="json"), "purpose": "content_question"})
    row = SimpleNamespace(state="completed", fingerprint=fingerprint)
    monkeypatch.setattr(service, "owned_task", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "view", AsyncMock(return_value="replay"))
    db = SimpleNamespace(scalar=AsyncMock(return_value=row))
    assert await service.send_message(db, ACTOR, current.id, body, content_question=True) == "replay"
    with pytest.raises(WorkbenchConflict, match="request_conflict"):
        await service.send_message(db, ACTOR, current.id, body)
    db.scalar.return_value = None
    monkeypatch.setattr(service, "mutable", AsyncMock(return_value=[]))
    with pytest.raises(WorkbenchConflict, match="content_requires_new_task"):
        await service.send_message(db, ACTOR, current.id, body, content_question=True)


async def test_overall_deadline_includes_slow_retrieval_before_budget(monkeypatch):
    monkeypatch.setattr(answers, "index_snapshot", AsyncMock(return_value={}))
    original_timeout = asyncio.timeout
    monkeypatch.setattr(answers.asyncio, "timeout", lambda seconds: original_timeout(0.01))
    async def slow(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(answers, "retrieve", slow)
    charge = AsyncMock()
    monkeypatch.setattr(answers, "check_and_charge_llm_budget", charge)
    db = SimpleNamespace(commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await answers.answer_document(db, ACTOR, (SOURCE,), "Question", "ru", [])
    assert error.value.status_code == 503
    charge.assert_not_awaited()


async def test_answer_requests_provider_json_mode_and_preserves_abstention(monkeypatch):
    monkeypatch.setattr(answers, "index_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr(answers, "retrieve", AsyncMock(return_value=EXCERPTS))
    monkeypatch.setattr(answers, "_set_tenant_security_context", AsyncMock())
    monkeypatch.setattr(answers, "_set_user_security_context", AsyncMock())
    monkeypatch.setattr(answers, "check_and_charge_llm_budget", AsyncMock())
    provider = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(
        content=payload(status="not_found", answer="The source does not specify a bonus.", citations=[]))))
    monkeypatch.setattr(answers.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=provider))
    result = await answers.answer_document(SimpleNamespace(commit=AsyncMock()), ACTOR, (SOURCE,), "Bonus?", "en", [])
    assert result.response.status == "not_found" and result.response.citations == []
    assert provider.ainvoke.call_args.kwargs["response_format"] == {"type": "json_object"}
    assert provider.ainvoke.call_args.kwargs["provider_deadline_seconds"] == 8


async def test_deadline_during_admission_settles_same_commit_then_refunds(monkeypatch):
    monkeypatch.setattr(answers, "index_snapshot", AsyncMock(return_value={}))
    original_timeout = asyncio.timeout
    monkeypatch.setattr(answers.asyncio, "timeout", lambda seconds: original_timeout(0.01))
    monkeypatch.setattr(answers, "retrieve", AsyncMock(return_value=EXCERPTS))
    monkeypatch.setattr(answers, "_set_tenant_security_context", AsyncMock())
    monkeypatch.setattr(answers, "_set_user_security_context", AsyncMock())
    charge, refund = AsyncMock(), AsyncMock()
    monkeypatch.setattr(answers, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(answers, "refund", refund)
    commits = 0
    async def commit():
        nonlocal commits
        commits += 1
        if commits == 2:
            await asyncio.sleep(0.03)
    db = SimpleNamespace(commit=commit, rollback=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await answers.answer_document(db, ACTOR, (SOURCE,), "Question", "ru", [])
    assert error.value.status_code == 503 and commits == 2
    charge.assert_awaited_once()
    refund.assert_awaited_once_with(db, ACTOR)


async def test_deadline_during_failure_refund_settles_exact_compensation(monkeypatch):
    monkeypatch.setattr(answers, "index_snapshot", AsyncMock(return_value={}))
    original_timeout = asyncio.timeout
    monkeypatch.setattr(answers.asyncio, "timeout", lambda seconds: original_timeout(0.01))
    monkeypatch.setattr(answers, "retrieve", AsyncMock(return_value=EXCERPTS))
    monkeypatch.setattr(answers, "_set_tenant_security_context", AsyncMock())
    monkeypatch.setattr(answers, "_set_user_security_context", AsyncMock())
    monkeypatch.setattr(answers, "check_and_charge_llm_budget", AsyncMock())
    provider = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("outage")))
    monkeypatch.setattr(answers.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=provider))
    settled = []
    async def slow_refund(*args):
        await asyncio.sleep(0.03)
        settled.append("exact refund committed")
    monkeypatch.setattr(answers, "refund", slow_refund)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await answers.answer_document(db, ACTOR, (SOURCE,), "Question", "ru", [])
    assert error.value.status_code == 503 and settled == ["exact refund committed"]


async def test_terminal_pointer_absence_change_is_fail_closed(monkeypatch):
    result = Mock()
    result.one_or_none.side_effect = [None, ("new-index", 1)]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    read = AsyncMock()
    monkeypatch.setattr(answers, "read_excerpt", read)
    with pytest.raises(WorkbenchConflict, match="source_stale"):
        await answers.validate_citations(db, ACTOR, answers.parse_answer(payload(), EXCERPTS))
    assert db.execute.await_count == 2 and read.await_count == 1
    assert "FOR SHARE" in str(db.execute.call_args.args[0])


@pytest.mark.parametrize("status", ["supported", "not_found", "conflict"])
async def test_all_selected_index_states_are_rechecked_even_when_uncited(monkeypatch, status):
    response = answers.parse_answer(payload(status=status, citations=[] if status == "not_found" else
        [{"handle": 1, "quote": "Before dispatch"}]), EXCERPTS)
    indexes = {str(SOURCE.document_id): None, str(UUID(int=9)): ("old", 1)}
    evidence = answers.AnswerEvidence(response, indexes, ())
    snapshot = AsyncMock(return_value={**indexes, str(UUID(int=9)): ("new", 2)})
    monkeypatch.setattr(answers, "index_snapshot", snapshot)
    with pytest.raises(WorkbenchConflict, match="source_stale"):
        await answers.validate_evidence(SimpleNamespace(), ACTOR, evidence)
    assert set(snapshot.call_args.args[2]) == set(indexes)


async def test_not_found_still_locks_retrieved_evidence(monkeypatch):
    response = answers.parse_answer(payload(status="not_found", citations=[]), EXCERPTS)
    witness = answers.parse_answer(payload(), EXCERPTS).citations[0]
    indexes = {str(SOURCE.document_id): None}
    monkeypatch.setattr(answers, "index_snapshot", AsyncMock(return_value=indexes))
    read = AsyncMock()
    monkeypatch.setattr(answers, "read_excerpt", read)
    await answers.validate_evidence(SimpleNamespace(), ACTOR, answers.AnswerEvidence(response, indexes, (witness,)))
    assert read.await_count == 2 and read.call_args.kwargs["lock"] is True
