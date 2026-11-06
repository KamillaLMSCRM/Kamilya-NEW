import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai.direct_source import DirectSourceError, build_direct_source_corpus
from app.modules.ai.router import submit_course_generation
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.source_editorial_review.analysis import analyze, blocks
from app.modules.source_editorial_review.domain import (
    POLICY,
    ApprovedEditorialDocument,
    ReviewCommand,
    ReviewConflictError,
    ReviewState,
    text_hash,
)
from app.modules.source_editorial_review.service import apply_command, pin_reviews

ORIGINAL = "До 45 МРП действует первый порядок. Свыше 45 МРП действует второй. Документ оформляет операотр."
QUOTE = "До 45 МРП действует первый порядок."
REPLACEMENT = "До 45 МРП включительно действует первый порядок."


def prepared() -> ReviewState:
    state = ReviewState()
    state.apply(1, "queued", {})
    state.apply(2, "running", {})
    start = ORIGINAL.index("операотр")
    state.apply(3, "analyzed", {"policy": POLICY, "original": ORIGINAL,
        "issues": [{"id": "boundary", "start": 0, "end": len(QUOTE), "quote": QUOTE,
                    "reason": "Какой порядок при 45 МРП?"}],
        "automatic": [{"id": "typo", "start": start, "end": start + len("операотр"),
                       "before": "операотр", "after": "оператор", "reason": "Опечатка."}]})
    return state


def command(state: ReviewState, action: str, **kwargs):
    return ReviewCommand(expected_revision=state.revision, request_id=uuid4(), action=action, **kwargs)


def enact(state: ReviewState, action: str, **kwargs):
    kind, payload = state.plan(command(state, action, **kwargs))
    state.apply(state.revision + 1, kind, payload)
    return payload


def test_boundary_human_decision_automatic_undo_and_historical_snapshot():
    state = prepared()
    with pytest.raises(ReviewConflictError, match="questions_open"):
        enact(state, "approve")
    assert "оператор" in state.working()[0]
    stale = command(state, "undo_auto", item_id="typo", reason="Сверено с регламентом")
    resolved = enact(state, "resolve", item_id="boundary", decision="replace",
                     replacement=REPLACEMENT, reason="Владелец подтвердил включение 45 МРП")
    assert (resolved["before"], resolved["after"]) == (QUOTE, REPLACEMENT)
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        state.plan(stale)
    undo = enact(state, "undo_auto", item_id="typo", reason="Проверка отмены")
    assert (undo["before"], undo["after"]) == ("оператор", "операотр")
    approved = enact(state, "approve")
    assert approved["working"] == ORIGINAL.replace(QUOTE, REPLACEMENT)
    assert approved["working_sha256"] == text_hash(approved["working"])
    enact(state, "reopen")
    enact(state, "reopen_issue", item_id="boundary", reason="Получен уточнённый ответ")
    assert state.approval is None and state.working()[0] == ORIGINAL
    assert approved["working"].startswith(REPLACEMENT)


def test_unbound_finding_requires_unique_original_quote_to_replace():
    state = prepared()
    state.issues["boundary"] = {"id": "boundary", "start": None, "end": None, "quote": "подозрение"}
    with pytest.raises(ReviewConflictError, match="quote_not_unique"):
        enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
              reason="Сверено с оригиналом", quote="несуществующая цитата")
    with pytest.raises(ReviewConflictError, match="requires_exact_change"):
        enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
              reason="Сверено с оригиналом")
    enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
          reason="Сверено с оригиналом", quote=QUOTE)
    assert enact(state, "approve")["working"].startswith(REPLACEMENT)


@pytest.mark.asyncio
async def test_source_model_flags_numeric_gap_with_original_quote_and_no_invented_rewrite():
    # Actual DEV failure: the first editor returned no ambiguity. The independent
    # check is mandatory even when a document has no proposed text corrections.
    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": []}
        assert "Test each boundary at the exact value" in messages[0]["content"]
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": [
            {"excerpt": QUOTE, "category": "boundary", "reason": "Какой порядок при 45 МРП?"},
            {"excerpt": "Несуществующая цитата", "category": "reference", "reason": "Какой пункт имеется в виду?"},
        ]}

    complete = AsyncMock(side_effect=answer)
    result = await analyze(ORIGINAL, source_id="document:" + "b" * 64, document_id=str(uuid4()),
                           complete_json=complete)
    assert complete.await_count == result["model_calls"] == 2
    assert result["issues"][0]["quote"] == QUOTE and result["issues"][0]["start"] == 0
    assert result["issues"][1]["start"] is None
    assert not result["automatic"] and result["original"] == ORIGINAL


@pytest.mark.asyncio
async def test_typo_uncertainty_does_not_require_a_human_policy_decision():
    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [
                {"alias": "Typo", "excerpt": "операотр", "category": "typo", "reason": "Ошибка написания."}]}
        assert incoming["author_candidate_uncertainties"][0]["excerpt"] == "операотр"
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": []}

    result = await analyze(ORIGINAL, source_id="document:" + "b" * 64, document_id=str(uuid4()), complete_json=answer)
    assert not result["issues"] and not result["automatic"] and result["original"] == ORIGINAL


def test_manual_edit_uses_same_history_and_cannot_override_existing_question():
    state = prepared()
    with pytest.raises(ReviewConflictError, match="overlapping_or_stale_edit"):
        enact(state, "add_edit", quote=QUOTE, replacement=REPLACEMENT, reason="Ответ владельца")
    with pytest.raises(ReviewConflictError, match="quote_not_unique"):
        enact(state, "add_edit", quote="Неверная цитата", replacement=REPLACEMENT, reason="Ответ владельца")
    quote = "Свыше 45 МРП действует второй."
    edit = enact(state, "add_edit", quote=quote, replacement="При сумме свыше 45 МРП применяется второй порядок.",
                 reason="Владелец подтвердил название порядка")
    assert state.issues[edit["id"]]["category"] == "manual" and state.decisions[edit["id"]] == edit
    enact(state, "resolve", item_id="boundary", decision="keep", reason="Владелец оставил текст")
    approved = enact(state, "approve")
    assert "применяется второй порядок" in approved["working"] and state.original == ORIGINAL
    enact(state, "reopen")
    enact(state, "reopen_issue", item_id=edit["id"], reason="Уточнён ответ владельца")
    assert quote in state.working()[0] and "применяется второй порядок" in approved["working"]


def test_long_source_blocks_preserve_tail_and_all_original_coordinates():
    source = "Порядок проверки.\n\n" * 7000 + "Последнее исключение."
    parts = list(blocks(source))
    assert len(parts) > 1
    assert "".join(body for _, body in parts) == source
    assert all(source[offset:offset + len(body)] == body for offset, body in parts)


@pytest.mark.asyncio
async def test_retry_reuses_exact_completed_source_block(monkeypatch):
    monkeypatch.setattr("app.modules.source_editorial_review.analysis._BLOCK_CHARS", 80)
    original = "Первый раздел с порядком проверки.\n\n" * 4 + "Последнее исключение."
    completed: dict = {}
    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" in incoming:
            return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": []}
        return {"patches": [], "unresolved": []}

    async def first_attempt(messages):
        if completed:
            raise TimeoutError()
        return await answer(messages)

    async def record(key, result):
        completed[key] = result

    args = {"source_id": "document:" + "d" * 64, "document_id": str(uuid4())}
    with pytest.raises(TimeoutError):
        await analyze(original, complete_json=first_attempt, checkpoint=record, **args)
    assert len(completed) == 1
    retry = AsyncMock(side_effect=answer)
    result = await analyze(original, complete_json=retry, retained=completed, **args)
    assert result["original"] == original
    assert retry.await_count == 2 * (len(list(blocks(original))) - 1)


@pytest.mark.asyncio
async def test_generation_gate_runs_before_quota_and_dispatch(monkeypatch):
    doc, tenant, actor = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr("app.modules.source_editorial_review.service.review_enabled", lambda: True)
    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", AsyncMock())
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, SimpleNamespace(content_sha256="a" * 64)]))
    quota, submit = AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.core.demo_limits.check_ai_generation_quota", quota)
    monkeypatch.setattr("app.modules.ai.router.submit_ai_job", submit)
    with pytest.raises(HTTPException) as blocked:
        await submit_course_generation(AIGenerateRequest(documents=[doc]), db, SimpleNamespace(id=actor, tenant_id=tenant))
    assert blocked.value.status_code == 409
    assert blocked.value.detail == {"code": "source_editorial_review_required", "document_ids": [str(doc)]}
    quota.assert_not_awaited()
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_current_approval_is_admitted_even_if_previous_snapshot_exists():
    doc, tenant = uuid4(), uuid4()
    row = SimpleNamespace(kind="reopened", original_blob_sha256="a" * 64)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[row, SimpleNamespace(content_sha256="a" * 64)]))
    with pytest.raises(HTTPException) as blocked:
        await pin_reviews(db, tenant, [doc])
    assert blocked.value.status_code == 409


@pytest.mark.asyncio
async def test_idempotency_preserves_receipt_and_rejects_key_reuse(monkeypatch):
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64)
    actor = uuid4()
    submitted = command(ReviewState(), "start")
    stored = SimpleNamespace(kind="queued", sequence=1, original_blob_sha256=doc.content_sha256,
                             payload={}, request_id=submitted.request_id, actor_id=actor,
                             command_sha256=text_hash(submitted.model_dump_json()))
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=[stored]))
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    _, _, receipt, _ = await apply_command(db, doc, actor, submitted)
    assert receipt is stored
    db.add.assert_not_called()
    with pytest.raises(ReviewConflictError, match="request_id_conflict"):
        await apply_command(db, doc, actor, submitted.model_copy(update={"expected_revision": 1}))


@pytest.mark.asyncio
async def test_worker_uses_pinned_working_text_without_reconverting_original():
    state = prepared()
    enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
          reason="Владелец документа подтвердил")
    saved = enact(state, "approve")
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), title="Source", filename="test.txt", category="general",
                          lifecycle_status="active", content_sha256="a" * 64)
    approved = ApprovedEditorialDocument(str(doc.id), "document:" + doc.content_sha256, str(uuid4()),
        ORIGINAL, saved["working"], saved["working_sha256"], tuple(saved["spans"]), {})
    storage = Mock()
    corpus = await build_direct_source_corpus([doc], tenant_id=doc.tenant_id, storage=storage,
                                              approved_documents={str(doc.id): approved})
    assert corpus.documents[0].source_text == saved["working"]
    assert "включительно" in corpus.documents[0].chunks[0].text
    storage.get_bytes.assert_not_called()
    doc.content_sha256 = "b" * 64
    with pytest.raises(DirectSourceError, match="editorial_unproved"):
        await build_direct_source_corpus([doc], tenant_id=doc.tenant_id, storage=storage,
                                         approved_documents={str(doc.id): approved})
