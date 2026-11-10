"""Synthetic custody and continuation checks; no provider or database calls."""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaCompletedJsonError
from app.modules.ai.source_editorial_model import (
    compile_editorial_author_response,
    prepare_source_working_edition,
    source_editorial_result_valid,
)
from app.modules.source_editorial_review.continuation import handoff, lineage, valid_continuation
from app.modules.source_editorial_review.request_custody import (
    BeforePostDeferred,
    CompletedResponseRejected,
    RequestOutcomeUnknown,
    RequestRejected,
    choose_attempt,
    identity,
    invoke_once,
)
from app.modules.source_preparation.domain import PreparedSource, digest
from app.modules.source_preparation.extraction import NativeSource
from app.modules.source_preparation.preparation import _VISUAL_REVIEW_POLICY, prepare_native_source


def _alias_patch(alias):
    return {"alias": alias, "before": "A  B", "after": "A B", "category": "layout",
            "reason": "spacing", "supporting_original_context_quotes": ["A  B"]}


@pytest.mark.asyncio
async def test_unicode_author_alias_is_canonical_for_review_and_custody():
    wire = {"patches": [_alias_patch("p_expert_ocenka_obязан")], "unresolved": []}
    original = deepcopy(wire)
    async def complete(messages):
        data = json.loads(messages[-1]["content"])
        if "proposal_sha256" in data:
            alias = data["patches"][0]["alias"]
            assert alias.isascii() and alias != original["patches"][0]["alias"]
            axes = ("digits_preserved", "numeric_values_preserved", "units_preserved", "operators_preserved",
                    "negation_modality_preserved", "coordination_logic_preserved", "actors_preserved",
                    "content_complete", "no_inferred_list_logic")
            return {"proposal_sha256": data["proposal_sha256"], "rows": [{"patch_alias": alias,
                "relation": "preserved", "reason": "spacing", **{key: True for key in axes}}]}
        return wire
    result = await prepare_source_working_edition("A  B", source_id="source", chunk_id="chunk", complete_json=complete)
    assert wire == original and result.author_wire == original
    assert source_editorial_result_valid(result, source_text="A  B", source_id="source", chunk_id="chunk")
    assert not source_editorial_result_valid(result, source_text="A  B", source_id="source", chunk_id="other")


def test_author_alias_ascii_and_invalids():
    def compile_rows(rows):
        return compile_editorial_author_response("A  B", source_id="source", chunk_id="chunk",
                                                 wire={"patches": rows, "unresolved": []})
    assert compile_rows([_alias_patch("Valid_1")]).patches[0].alias == "Valid_1"
    for alias in (None, "", " ", "a" * 65, "a.b", "2alias"):
        with pytest.raises(ValueError):
            compile_rows([_alias_patch(alias)])
    for alias in ("duplicate", "дубликат"):
        with pytest.raises(ValueError):
            compile_rows([_alias_patch(alias), _alias_patch(alias)])
    missing = _alias_patch("safe")
    del missing["alias"]
    with pytest.raises(ValueError):
        compile_rows([missing])
    canonical = compile_rows([_alias_patch("слово")]).patches[0].alias
    with pytest.raises(ValueError, match="duplicate_alias"):
        compile_rows([_alias_patch("слово"), _alias_patch(canonical)])


def test_unicode_alias_does_not_bypass_unsafe_patch_guards():
    patch = {"alias": "правка", "before": "10 days", "after": "20 days", "category": "typo",
             "reason": "change", "supporting_original_context_quotes": ["10 days"]}
    proposal = compile_editorial_author_response("Wait 10 days.", source_id="source", chunk_id="chunk",
        wire={"patches": [patch], "unresolved": []})
    assert not proposal.patches and len(proposal.unresolved) == 1


def test_unicode_unresolved_alias_and_generated_collision(monkeypatch):
    from app.modules.ai import source_editorial_model as model
    gap = {"alias": "срок", "excerpt": "A  B", "category": "typo", "reason": "check"}
    wire = {"patches": [], "unresolved": [gap]}
    original = deepcopy(wire)
    proposal = compile_editorial_author_response("A  B", source_id="source", chunk_id="chunk", wire=wire)
    assert proposal.unresolved[0].alias.isascii() and wire == original
    monkeypatch.setattr(model, "sha256", lambda _: SimpleNamespace(hexdigest=lambda: "0" * 64))
    with pytest.raises(ValueError, match="duplicate_alias"):
        compile_editorial_author_response("A  B", source_id="source", chunk_id="chunk", wire={
            "patches": [_alias_patch("слово"), _alias_patch("другое")], "unresolved": []})

def stage_key(text="one", source="a" * 64):
    return identity(tenant="tenant", document="document", original_sha=source, selected_sha="selected",
                    policy="v2", route="route", messages=[{"role": "user", "content": text}])


def test_attempt_selection_requires_exact_ack_or_explicit_known_rejection_retry():
    key, request_id = stage_key(), uuid4()
    queue = SimpleNamespace(request_id=request_id)
    preceding = SimpleNamespace(payload={"code": "source_review_provider_unavailable"})
    prefix = f"source-review-request-custody-v2:{key}:"
    assert choose_attempt(key, {}, None, None, queue, preceding) == "initial"
    rejected = {prefix + "initial:completed": {"status": "rejected"}}
    assert choose_attempt(key, rejected, None, None, queue, preceding) == str(request_id)
    assert choose_attempt(key, rejected, None, None, SimpleNamespace(request_id=None), preceding) == "initial"
    ack = {"request_id": str(uuid4())}
    assert choose_attempt(key, {}, ack, SimpleNamespace(payload={"unknown_request_key": key}), queue, None) == ack["request_id"]
    assert choose_attempt(key, {}, ack, SimpleNamespace(payload={"unknown_request_key": "other"}), queue, None) == "initial"
    retained = {**rejected, prefix + "prior:completed": {"status": "ok"}}
    assert choose_attempt(key, retained, ack, SimpleNamespace(payload={"unknown_request_key": key}), queue, preceding) == "prior"


def test_consecutive_known_rejections_require_new_explicit_start_not_auto_continuation():
    key, first, second = stage_key(), uuid4(), uuid4()
    prefix = f"source-review-request-custody-v2:{key}:"
    retained = {prefix + "initial:completed": {"status": "rejected"},
                prefix + f"{first}:completed": {"status": "rejected"}}
    failure = SimpleNamespace(payload={"code": "source_review_provider_unavailable"})
    assert choose_attempt(key, retained, None, None, SimpleNamespace(request_id=first), failure) == str(first)
    assert choose_attempt(key, retained, None, None, SimpleNamespace(request_id=second), failure) == str(second)
    retained[prefix + f"{first}:intent"] = {"state": "started"}
    del retained[prefix + f"{first}:completed"]
    assert choose_attempt(key, retained, None, None, SimpleNamespace(request_id=second), failure) == str(first)


@pytest.mark.asyncio
async def test_completed_response_replays_without_post_and_usage_counts_once():
    saved = {}
    receipts = {}
    async def save(key, value):
        saved[key] = value
    def usage(key, value):
        receipts.setdefault(key, value)
    post = AsyncMock(return_value=({"answer": "complete"}, {"input_tokens": 4, "output_tokens": 2}))
    kwargs = dict(key=stage_key(), attempt="initial", retained=saved, save=save, before_post=lambda: None,
                  invoke=post, usage=usage)
    assert await invoke_once(**kwargs) == {"answer": "complete"}
    assert await invoke_once(**kwargs) == {"answer": "complete"}
    assert post.await_count == 1 and len(receipts) == 1
    assert stage_key("two") != stage_key() and stage_key(source="b" * 64) != stage_key()


@pytest.mark.asyncio
async def test_before_post_defer_has_no_intent_or_call():
    saved = {}
    async def save(key, value):
        saved[key] = value
    def deferred():
        raise BeforePostDeferred()
    post = AsyncMock()
    with pytest.raises(BeforePostDeferred):
        await invoke_once(key=stage_key(), attempt="initial", retained=saved, save=save,
                          before_post=deferred, invoke=post, usage=Mock())
    assert not saved
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_response_is_fenced_and_explicit_new_attempt_is_distinct():
    saved = {}
    async def save(key, value):
        saved[key] = value
    post = AsyncMock(side_effect=TimeoutError())
    kwargs = dict(key=stage_key(), retained=saved, save=save, before_post=lambda: None, usage=Mock())
    with pytest.raises(RequestOutcomeUnknown):
        await invoke_once(attempt="initial", invoke=post, **kwargs)
    with pytest.raises(RequestOutcomeUnknown):
        await invoke_once(attempt="initial", invoke=post, **kwargs)
    assert post.await_count == 1
    explicit = AsyncMock(return_value=({"answer": "new attempt"}, None))
    assert await invoke_once(attempt=str(uuid4()), invoke=explicit, **kwargs) == {"answer": "new attempt"}
    assert len(saved) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ManagedLunaCompletedJsonError("managed_luna_response_invalid"),
                                    RequestRejected("rejected"), CompletedResponseRejected({"complete": True})])
async def test_known_completed_error_replays_without_post(error):
    saved = {}
    async def save(key, value):
        saved[key] = value
    post = AsyncMock(side_effect=error)
    kwargs = dict(key=stage_key(), attempt="initial", retained=saved, save=save,
                  before_post=lambda: None, invoke=post, usage=Mock())
    with pytest.raises(type(error)):
        await invoke_once(**kwargs)
    with pytest.raises(type(error)):
        await invoke_once(**kwargs)
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_interruption_after_durable_response_does_not_repeat():
    saved = {}
    async def save_then_die(key, value):
        saved[key] = value
        if key.endswith(":completed"):
            raise InterruptedError()
    post = AsyncMock(return_value=({"answer": "saved"}, {"input_tokens": 9}))
    kwargs = dict(key=stage_key(), attempt="initial", retained=saved, before_post=lambda: None, usage=Mock())
    with pytest.raises(InterruptedError):
        await invoke_once(save=save_then_die, invoke=post, **kwargs)
    assert await invoke_once(save=AsyncMock(), invoke=post, **kwargs) == {"answer": "saved"}
    assert post.await_count == 1


def row(kind, sequence, actor, source, payload=None, *, row_id=None, request_id=None):
    return SimpleNamespace(id=row_id or uuid4(), kind=kind, sequence=sequence, actor_id=actor,
                           original_blob_sha256=source, payload=payload or {}, request_id=request_id)


@pytest.mark.asyncio
async def test_handoff_commits_before_dispatch_and_lost_ack_keeps_exact_queued_event(monkeypatch):
    actor, source = uuid4(), "a" * 64
    parent = row("queued", 1, actor, source)
    claim = row("running", 2, actor, source, {"queued_event_id": str(parent.id)})
    checkpoint = row("analysis_block", 3, actor, source, {"claim_id": str(claim.id)})
    rows = [parent, claim, checkpoint]
    db = SimpleNamespace(commit=AsyncMock())
    doc = SimpleNamespace(content_sha256=source)
    @asynccontextmanager
    async def locked():
        yield db, doc
    def add(_db, _doc, sequence, payload):
        event = row("queued", sequence, actor, source, payload)
        rows.append(event)
        return event
    def lost(_event):
        assert db.commit.await_count == 1
        raise TimeoutError("dispatch acknowledgement lost")
    monkeypatch.setattr("app.modules.source_editorial_review.continuation.verified_preparation_binding", lambda *_: True)
    result = await handoff(claim=claim, binding={"binding": "verified"}, pages=None, open_locked=locked,
        read_rows=AsyncMock(side_effect=lambda _: rows), add_queued=add,
        owns=lambda item: item.id == checkpoint.id, dispatch=lost)
    assert result == "continuation_pending" and len(rows) == 4
    assert valid_continuation(rows, rows[-1], source)
    assert await handoff(claim=claim, binding={"binding": "verified"}, pages=None, open_locked=locked,
        read_rows=AsyncMock(side_effect=lambda _: rows), add_queued=add,
        owns=lambda item: item.id == checkpoint.id, dispatch=lost) == "claim_changed"
    assert len(rows) == 4


def test_continuation_lineage_and_ack_are_exactly_bound():
    actor, source, request = uuid4(), "b" * 64, uuid4()
    failure = row("failed", 1, actor, source, {"code": "source_review_timeout", "phase": "editor_request"})
    ack = {"failure_event_id": str(failure.id), "request_id": str(request), "actor_id": str(actor)}
    queued = row("queued", 2, actor, source, {"acknowledged_unknown": ack}, request_id=request)
    claim = row("running", 3, actor, source, {"queued_event_id": str(queued.id)})
    continuation = row("queued", 4, actor, source, {"continuation_from": str(claim.id)})
    rows = [failure, queued, claim, continuation]
    assert valid_continuation(rows, continuation, source)
    ids, actual, previous, root = lineage(rows, continuation)
    assert ids == [str(claim.id)] and actual == ack and previous is failure and root is queued
    failure.payload["unknown_visual_outcome"] = True
    with pytest.raises(ValueError, match="acknowledgement_invalid"):
        lineage(rows, continuation)


@pytest.mark.asyncio
async def test_legacy_verified_manifest_reuses_image_and_parts_without_calls():
    source_sha, block_id = "d" * 64, "block-" + "c" * 24
    part_id = "part-" + digest(source_sha + block_id + block_id)[:24]
    package = PreparedSource.model_validate({"original_blob_sha256": source_sha,
        "blocks": [{"id": block_id, "text": "Source", "kind": "text"}],
        "parts": [{"id": part_id, "title": "Source", "role": "learning", "reason": "Relevant",
                   "first_block": block_id, "last_block": block_id}]})
    key = "source-preparation-v1:manifest:" + source_sha
    no_post = AsyncMock(side_effect=AssertionError("paid preparation repeated"))
    result = await prepare_native_source(NativeSource((), (), None, ()), original_sha256=source_sha,
        complete=no_post, visual_complete=no_post, checkpoint=AsyncMock(), persist_asset=AsyncMock(),
        retained={key: {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}},
        vision_batch_size=2, preview_chars=600)
    assert result == package
    no_post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_lost", [False, True])
async def test_worker_prepares_then_continues_and_cold_replays_without_extra_post(monkeypatch, dispatch_lost):
    from app.modules.source_editorial_review import analysis

    tenant, document, actor = uuid4(), uuid4(), uuid4()
    source_sha, block_id = "a" * 64, "block-" + "b" * 24
    part_id = "part-" + digest(source_sha + block_id + block_id)[:24]
    package = PreparedSource.model_validate({"original_blob_sha256": source_sha,
        "blocks": [{"id": block_id, "text": "Source", "kind": "text"}],
        "parts": [{"id": part_id, "title": "Source", "role": "learning", "reason": "Relevant",
                   "first_block": block_id, "last_block": block_id}]})
    parent = row("queued", 1, actor, source_sha)
    parent.created_at = datetime.now(UTC)
    rows = [parent]
    doc = SimpleNamespace(id=document, tenant_id=tenant, content_sha256=source_sha,
                          filename="source.docx", s3_key="fixture")
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    @asynccontextmanager
    async def sessions():
        yield session
    def add_event(_db, _doc, *, actor_id, sequence, kind, payload, **_):
        result = row(kind, sequence, actor_id, source_sha, payload)
        result.created_at = datetime.now(UTC)
        rows.append(result)
        return result
    async def prepare(_native, *, checkpoint, **_):
        await checkpoint("source-preparation-v1:manifest:" + source_sha,
                         {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY})
        return package
    async def analyze(_source, *, complete_json, **_):
        result = await complete_json([{"role": "system", "content": "review"},
                                      {"role": "user", "content": "{}"}])
        assert result == {"ok": True}
        return {"original": "Source", "issues": [], "automatic": [], "model_calls": 1}
    config = SimpleNamespace(name="synthetic", model="fixture", base_url="local-test", endpoint="/test",
                             timeout=5, extra_body={}, managed_evidence_profile=False)
    chain = SimpleNamespace(_clients=[SimpleNamespace(config=config)])
    llm_response = SimpleNamespace(content='{"ok":true}', provider_name="synthetic", model="fixture",
                                   prompt_tokens=3, completion_tokens=2, usage_complete=True)
    model_call = AsyncMock(return_value=llm_response)
    monkeypatch.setattr(analysis, "async_session_factory", sessions)
    monkeypatch.setattr(analysis, "owned_document", AsyncMock(return_value=doc))
    monkeypatch.setattr(analysis, "history", AsyncMock(side_effect=lambda *_: list(rows)))
    monkeypatch.setattr(analysis, "add_event", add_event)
    monkeypatch.setattr(analysis, "review_enabled", lambda: True)
    monkeypatch.setattr(analysis, "get_settings", lambda: SimpleNamespace(AI_MANAGED_LUNA_QA_DEV_ENABLED=False))
    monkeypatch.setattr(analysis, "extract_native_source", lambda *_args, **_kw: NativeSource((), (), None, ()))
    monkeypatch.setattr(analysis, "prepare_native_source", prepare)
    monkeypatch.setattr(analysis, "analyze", analyze)
    monkeypatch.setattr(analysis.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=chain))
    monkeypatch.setattr("app.modules.admin.runtime_configuration.runtime.resolve_runtime_settings",
                        AsyncMock(return_value=SimpleNamespace(integer=lambda _: 1000)))
    monkeypatch.setattr("app.core.storage.get_storage", lambda: SimpleNamespace(get_bytes=lambda _: b"synthetic"))
    monkeypatch.setattr("app.modules.ai.llm_client.LLMClient", lambda *_a, **_k: SimpleNamespace(ainvoke=model_call))
    dispatch = Mock(side_effect=TimeoutError("lost ack") if dispatch_lost else None)
    monkeypatch.setattr("app.core.celery_app.celery_app.send_task", dispatch)
    assert await analysis.run_analysis(tenant, document, parent.id) == (
        "continuation_pending" if dispatch_lost else "continued")
    continuation = rows[-1]
    assert continuation.kind == "queued" and continuation.payload["preparation"]["sha256"] == package.sha256
    model_call.assert_not_awaited()
    assert await analysis.run_analysis(tenant, document, parent.id) == "already_claimed"
    assert await analysis.run_analysis(tenant, document, continuation.id) == "analyzed"
    assert model_call.await_count == 1
    assert rows[-1].payload["model_calls"] == 1 and rows[-1].payload["usage_complete"] is True
