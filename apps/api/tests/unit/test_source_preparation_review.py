from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.source_editorial_review.domain import (
    ApprovedEditorialDocument,
    ReviewCommand,
    ReviewConflictError,
    ReviewState,
    text_hash,
)
from app.modules.source_editorial_review.service import (
    _command_digest,
    apply_command,
    public_preparation,
    read_approval,
    read_state,
    review_view,
    verified_preparation_binding,
)
from app.modules.source_preparation.domain import PreparedSource, digest
from app.modules.source_preparation.preparation import _VISUAL_REVIEW_POLICY


def manifest():
    sha = "a" * 64
    blocks = [{"id": "block-" + c * 24, "text": text, "kind": "paragraph", "page": page}
              for c, text, page in [("1", "First teaching material", 1), ("2", "Second teaching material", 2)]]
    parts = [{"id": "part-" + digest(sha + block["id"] + block["id"])[:24],
              "title": str(index), "role": "learning", "reason": "Relevant", "first_block": block["id"],
              "last_block": block["id"]} for index, block in enumerate(blocks)]
    return PreparedSource.model_validate({"original_blob_sha256": sha, "blocks": blocks, "parts": parts})


def prepared():
    package = manifest()
    binding = package.binding([package.parts[0].id])
    state = ReviewState()
    state.apply(1, "queued", {})
    state.apply(2, "running", {})
    state.apply(3, "analyzed", {"original": "First teaching material", "preparation": binding,
                                "issues": [], "automatic": []})
    return state, package


def command(state, action, **kwargs):
    return ReviewCommand(expected_revision=state.revision, request_id=uuid4(), action=action, **kwargs)


def event(sequence, kind, payload, sha="a" * 64):
    return SimpleNamespace(sequence=sequence, kind=kind, payload=payload, original_blob_sha256=sha)


def test_first_manifest_survives_failed_analysis_and_supports_human_selection():
    package = manifest()
    rows = [event(1, "queued", {}), event(2, "running", {}),
            event(3, "analysis_block", {"key": "source-preparation-v1:manifest:" + "a" * 64,
                                        "result": {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}}),
            event(4, "failed", {"code": "provider_failure"})]
    state = read_state(rows, "a" * 64)
    assert state.status == "failed" and state.preparation is not None
    assert state.original == "First teaching material\n\nSecond teaching material"
    view = public_preparation(SimpleNamespace(id=uuid4(), content_sha256="a" * 64), state)
    assert view["selected_part_ids"] == [part.id for part in package.parts]
    with pytest.raises(ReviewConflictError, match="action_not_available"):
        state.plan(command(state, "approve"))
    _, retry = state.plan(command(state, "start"))
    assert retry["preparation"] == state.preparation
    kind, selected = state.plan(command(state, "select_parts", selected_part_ids=[package.parts[1].id],
                                        preparation_sha256=package.sha256))
    assert kind == "queued" and selected["preparation"]["selected_part_ids"] == [package.parts[1].id]


def test_initial_administrative_only_manifest_still_offers_a_selection():
    package = manifest()
    data = package.model_dump()
    for part in data["parts"]:
        part["role"] = "administrative"
    rows = [event(1, "queued", {}), event(2, "running", {}),
            event(3, "analysis_block", {"key": "source-preparation-v1:manifest:" + "a" * 64,
                                        "result": {"manifest": data, "visual_review_policy": _VISUAL_REVIEW_POLICY}}), event(4, "failed", {"code": "no_learning"})]
    state = read_state(rows, "a" * 64)
    assert state.preparation["selected_part_ids"] == [package.parts[0].id]


def test_prior_review_and_decisions_survive_pending_manifest_replay():
    package = manifest()
    first = package.binding([package.parts[0].id])
    next_binding = package.binding([package.parts[1].id])
    issue = {"id": "issue", "start": 0, "end": 5, "quote": "First", "reason": "Check"}
    decision = {"item_id": "issue", "decision": "keep", "start": 0, "end": 5,
                "before": "First", "after": "First", "reason": "Checked"}
    rows = [event(1, "queued", {}), event(2, "running", {}),
            event(3, "analyzed", {"original": "First teaching material", "preparation": first,
                                  "issues": [issue], "automatic": []}), event(4, "resolved", decision),
            event(5, "queued", {"preparation": next_binding}), event(6, "running", {}),
            event(7, "analysis_block", {"key": "source-preparation-v1:manifest:" + "a" * 64,
                                        "result": {"manifest": package.model_dump()}}),
            event(8, "failed", {"code": "provider_failure"})]
    state = read_state(rows, "a" * 64)
    assert state.preparation == first and state.pending_preparation == next_binding
    assert state.original == "First teaching material" and state.decisions["issue"] == decision


def test_legacy_provisional_manifest_is_not_hydrated_or_verified():
    package = manifest()
    checkpoint = event(3, "analysis_block", {"key": "source-preparation-v1:manifest:" + "a" * 64,
                       "result": {"manifest": package.model_dump()}})
    rows = [event(1, "queued", {}), event(2, "running", {}), checkpoint,
            event(4, "failed", {"code": "provider_failure"})]
    state = read_state(rows, "a" * 64)
    assert state.preparation is None and not state.original
    binding = package.binding([package.parts[0].id])
    assert not verified_preparation_binding(rows, "a" * 64, binding)
    checkpoint.payload["result"]["visual_review_policy"] = _VISUAL_REVIEW_POLICY
    assert verified_preparation_binding(rows, "a" * 64, binding)
    changed = deepcopy(binding)
    changed["manifest"]["blocks"][0]["text"] = "Changed"
    assert not verified_preparation_binding(rows, "a" * 64, changed)


def test_legacy_analyzed_and_approved_snapshot_stays_readable():
    package = manifest()
    binding = package.binding([package.parts[0].id])
    rows = [event(1, "queued", {}), event(2, "running", {}), event(3, "analysis_block", {
        "key": "source-preparation-v1:manifest:" + "a" * 64,
        "result": {"manifest": package.model_dump()}}), event(4, "analyzed", {
        "original": "First teaching material", "preparation": binding, "issues": [], "automatic": []})]
    state = read_state(rows, "a" * 64)
    _, approval = state.plan(command(state, "approve"))
    rows.append(event(5, "approved", approval))
    historical = read_state(rows, "a" * 64)
    assert historical.approval == approval and historical.preparation == binding
    assert historical.original == "First teaching material"


@pytest.mark.asyncio
async def test_legacy_failed_binding_retry_is_unbound_and_preserves_prior_snapshot(monkeypatch):
    package = manifest()
    first = package.binding([package.parts[0].id])
    pending = package.binding([package.parts[1].id])
    rows = [event(1, "queued", {}), event(2, "analyzed", {"original": "First teaching material",
            "preparation": first, "issues": [], "automatic": []}), event(3, "queued", {"preparation": pending}),
            event(4, "failed", {"code": "source_review_preparation_stale"})]
    for row in rows:
        row.request_id = None
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64)
    state = read_state(rows, "a" * 64)
    with pytest.raises(ReviewConflictError, match="preparation_stale"):
        await apply_command(db, doc, uuid4(), command(state, "select_parts",
            selected_part_ids=[package.parts[1].id], preparation_sha256=package.sha256))
    _, after, queued, dispatch = await apply_command(db, doc, uuid4(), command(state, "start"))
    assert dispatch and queued.payload == {} and after.pending_preparation is None
    assert after.preparation == first and after.original == "First teaching material"


@pytest.mark.asyncio
async def test_verified_failed_binding_reselection_remains_bound(monkeypatch):
    package = manifest()
    rows = [event(1, "queued", {}), event(2, "running", {}), event(3, "analysis_block", {
        "key": "source-preparation-v1:manifest:" + "a" * 64,
        "result": {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}}),
        event(4, "failed", {"code": "provider_failure"})]
    for row in rows:
        row.request_id = None
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64)
    state = read_state(rows, "a" * 64)
    _, _, queued, dispatch = await apply_command(db, doc, uuid4(), command(state, "select_parts",
        selected_part_ids=[package.parts[1].id], preparation_sha256=package.sha256))
    assert dispatch and queued.payload["preparation"]["selected_part_ids"] == [package.parts[1].id]


@pytest.mark.asyncio
@pytest.mark.parametrize("reopened", [False, True])
async def test_legacy_in_review_blocks_approval_and_allows_revision_bound_fresh_retry(monkeypatch, reopened):
    package = manifest()
    binding = package.binding([package.parts[0].id])
    rows = [event(1, "queued", {}), event(2, "running", {}), event(3, "analyzed", {
        "policy": "legacy", "original": "First teaching material", "preparation": binding,
        "issues": [{"id": "q", "start": 0, "end": 5, "quote": "First", "reason": "Review"}],
        "automatic": []}), event(4, "resolved", {"item_id": "q", "decision": "keep", "start": 0,
        "end": 5, "before": "First", "after": "First", "reason": "Checked"})]
    if reopened:
        state = read_state(rows, "a" * 64)
        _, approval = state.plan(command(state, "approve"))
        rows.extend([event(5, "approved", approval), event(6, "reopened", {})])
    for row in rows:
        row.request_id = None
        row.id, row.actor_id, row.created_at = uuid4(), uuid4(), datetime.now(UTC)
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64,
                          title="Synthetic", version=1, filename="source.txt")
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    state = read_state(rows, doc.content_sha256)
    assert review_view(doc, rows, state)["error"] == "source_review_preparation_stale"
    with pytest.raises(ReviewConflictError, match="preparation_stale"):
        await apply_command(db, doc, uuid4(), command(state, "approve"))
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        await apply_command(db, doc, uuid4(), ReviewCommand(action="start", request_id=uuid4(),
                                                             expected_revision=state.revision - 1))
    _, after, queued, dispatch = await apply_command(db, doc, uuid4(), command(state, "start"))
    assert dispatch and queued.payload == {} and after.preparation == binding
    assert after.original == "First teaching material" and after.decisions["q"]["decision"] == "keep"


def test_verified_in_review_and_legacy_approved_have_no_stale_projection():
    package = manifest()
    binding = package.binding([package.parts[0].id])
    rows = [event(1, "queued", {}), event(2, "analysis_block", {
        "key": "source-preparation-v1:manifest:" + "a" * 64,
        "result": {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}}),
        event(3, "analyzed", {"policy": "current", "original": "First teaching material",
                               "preparation": binding, "issues": [], "automatic": []})]
    for row in rows:
        row.request_id = None
        row.id, row.actor_id, row.created_at = uuid4(), uuid4(), datetime.now(UTC)
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64,
                          title="Synthetic", version=1, filename="source.txt")
    state = read_state(rows, doc.content_sha256)
    assert review_view(doc, rows, state)["error"] is None
    _, approval = state.plan(command(state, "approve"))
    row = event(4, "approved", approval)
    row.request_id = None
    row.id, row.actor_id, row.created_at = uuid4(), uuid4(), datetime.now(UTC)
    row.document_id = doc.id
    legacy_rows = [rows[0], event(2, "running", {}), rows[2], row]
    legacy_rows[1].request_id = None
    legacy = read_state(legacy_rows, doc.content_sha256)
    assert review_view(doc, legacy_rows, legacy)["error"] is None


@pytest.mark.asyncio
async def test_verified_in_review_can_approve(monkeypatch):
    package = manifest()
    binding = package.binding([package.parts[0].id])
    rows = [event(1, "queued", {}), event(2, "analysis_block", {
        "key": "source-preparation-v1:manifest:" + "a" * 64,
        "result": {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}}),
        event(3, "analyzed", {"original": "First teaching material", "preparation": binding,
                               "issues": [], "automatic": []})]
    for row in rows:
        row.request_id = None
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64)
    _, after, approved, dispatch = await apply_command(db, doc, uuid4(), command(read_state(rows, "a" * 64), "approve"))
    assert approved.kind == "approved" and after.status == "approved" and not dispatch


def test_selection_is_revision_bound_canonical_and_only_invalidates_after_success():
    state, package = prepared()
    ids = [package.parts[1].id, package.parts[0].id]
    cmd = command(state, "select_parts", selected_part_ids=ids, preparation_sha256=package.sha256)
    kind, payload = state.plan(cmd)
    assert payload["preparation"]["selected_part_ids"] == list(reversed(ids))
    state.apply(4, kind, payload)
    assert state.original == "First teaching material"
    assert state.preparation["selected_part_ids"] == [package.parts[0].id]
    state.apply(5, "failed", {"code": "failed"})
    _, retry = state.plan(command(state, "start"))
    assert retry == payload
    state.apply(6, "queued", retry)
    with pytest.raises(ReviewConflictError, match="preparation_changed"):
        state.apply(7, "analyzed", {"original": "First teaching material", "preparation": state.preparation,
                                    "issues": [], "automatic": []})


def test_rejects_unknown_duplicate_and_stale_selections():
    state, package = prepared()
    for ids, sha in [([package.parts[0].id] * 2, package.sha256), (["part-" + "f" * 24], package.sha256),
                     ([package.parts[0].id], "b" * 64)]:
        with pytest.raises(ReviewConflictError):
            state.plan(command(state, "select_parts", selected_part_ids=ids, preparation_sha256=sha))
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        state.plan(ReviewCommand(expected_revision=2, request_id=uuid4(), action="select_parts",
                                 selected_part_ids=[package.parts[0].id], preparation_sha256=package.sha256))


def test_approved_binding_validates_text_and_blob_identity_and_public_view():
    state, package = prepared()
    _, payload = state.plan(command(state, "approve"))
    approved = ApprovedEditorialDocument("doc", "document:" + "a" * 64, "approval", state.original,
        payload["working"], payload["working_sha256"], tuple(payload["spans"]), {}, payload["preparation"])
    assert approved.valid(document_id="doc", source_revision="document:" + "a" * 64)
    assert not approved.valid(document_id="doc", source_revision="document:" + "b" * 64)
    tampered = deepcopy(payload["preparation"])
    tampered["selected_part_ids"] = [package.parts[1].id]
    assert not ApprovedEditorialDocument("doc", "document:" + "a" * 64, "approval", state.original,
        payload["working"], payload["working_sha256"], tuple(payload["spans"]), {}, tampered).valid(
            document_id="doc", source_revision="document:" + "a" * 64)
    view = public_preparation(SimpleNamespace(id=uuid4(), content_sha256="a" * 64), state)
    assert view["parts"][0]["page_first"] == 1 and view["parts"][0]["block_count"] == 1
    assert "manifest" not in view and "storage_key" not in str(view)


def test_old_request_digest_excludes_only_new_absent_fields():
    request = ReviewCommand(expected_revision=0, request_id=uuid4(), action="start")
    old_json = (f'{{"expected_revision":0,"request_id":"{request.request_id}","action":"start",'
                '"item_id":null,"decision":null,"replacement":null,"reason":null,"quote":null}')
    assert _command_digest(request) == text_hash(old_json)


@pytest.mark.asyncio
async def test_selection_replay_returns_original_receipt_without_a_second_event(monkeypatch):
    state, package = prepared()
    actor, doc_id, tenant_id = uuid4(), uuid4(), uuid4()
    request = command(state, "select_parts", selected_part_ids=[package.parts[1].id], preparation_sha256=package.sha256)
    _, payload = state.plan(request)
    rows = [SimpleNamespace(sequence=1, kind="queued", payload={}, original_blob_sha256="a" * 64, request_id=None),
            SimpleNamespace(sequence=2, kind="running", payload={}, original_blob_sha256="a" * 64, request_id=None),
            SimpleNamespace(sequence=3, kind="analyzed", original_blob_sha256="a" * 64, request_id=None,
                payload={"original": state.original, "preparation": state.preparation, "issues": [], "automatic": []})]
    receipt = SimpleNamespace(sequence=4, kind="queued", payload=payload, original_blob_sha256="a" * 64,
                              request_id=request.request_id, actor_id=actor, command_sha256=_command_digest(request))
    rows.append(receipt)
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    _, _, replay, dispatch = await apply_command(db, SimpleNamespace(id=doc_id, tenant_id=tenant_id,
        content_sha256="a" * 64), actor, request)
    assert replay is receipt and dispatch
    db.add.assert_not_called()
    with pytest.raises(ReviewConflictError, match="request_id_conflict"):
        await apply_command(db, SimpleNamespace(id=doc_id, tenant_id=tenant_id, content_sha256="a" * 64), actor,
                            request.model_copy(update={"selected_part_ids": [package.parts[0].id]}))


@pytest.mark.asyncio
@pytest.mark.parametrize("pages", [None, {"first_page": 3, "last_page": 9}])
async def test_historical_approval_readback_preserves_page_range(monkeypatch, pages):
    state = ReviewState()
    initial = {"pages": pages} if pages else {}
    state.apply(1, "queued", initial)
    state.apply(2, "analyzed", {"original": "Text", "issues": [], "automatic": []})
    _, payload = state.plan(command(state, "approve"))
    doc = SimpleNamespace(id=uuid4(), content_sha256="a" * 64)
    event = SimpleNamespace(sequence=3, payload=payload)
    rows = [SimpleNamespace(sequence=1, kind="queued", payload=initial, original_blob_sha256=doc.content_sha256),
            SimpleNamespace(sequence=2, kind="analyzed", payload={"original": "Text", "issues": [], "automatic": []}, original_blob_sha256=doc.content_sha256),
            SimpleNamespace(sequence=3, kind="approved", payload=payload, original_blob_sha256=doc.content_sha256)]
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    result, restored = await read_approval(SimpleNamespace(scalar=AsyncMock(return_value=event)), uuid4(), doc, uuid4())
    assert result is event and restored.pages == pages
