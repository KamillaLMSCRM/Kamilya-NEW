from copy import deepcopy
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
)
from app.modules.source_preparation.domain import PreparedSource, digest


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
                                        "result": {"manifest": package.model_dump()}}),
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
                                        "result": {"manifest": data}}), event(4, "failed", {"code": "no_learning"})]
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
