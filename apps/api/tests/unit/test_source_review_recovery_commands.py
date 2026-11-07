from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.source_editorial_review.domain import ReviewCommand, ReviewConflictError, text_hash
from app.modules.source_editorial_review.service import (
    _command_digest,
    apply_command,
    continuation_pending,
    read_state,
    requires_retry_acknowledgement,
    retry_blocked_unknown_visual,
    review_view,
)
from app.modules.source_preparation.domain import PreparedSource, digest
from app.modules.source_preparation.preparation import _VISUAL_REVIEW_POLICY

SHA = "a" * 64


def row(sequence, kind, payload, actor, **kwargs):
    return SimpleNamespace(id=kwargs.get("id", uuid4()), sequence=sequence, kind=kind, payload=payload,
        original_blob_sha256=SHA, actor_id=actor, request_id=kwargs.get("request_id"),
        command_sha256=kwargs.get("command_sha256"), created_at=datetime.now(UTC))


def request(revision, action="start", **kwargs):
    return ReviewCommand(expected_revision=revision, request_id=uuid4(), action=action, **kwargs)


def package():
    block = "block-" + "1" * 24
    return PreparedSource.model_validate({"original_blob_sha256": SHA,
        "blocks": [{"id": block, "text": "Learning", "kind": "text"}],
        "parts": [{"id": "part-" + digest(SHA + block + block)[:24], "title": "Learning",
                   "role": "learning", "reason": "Relevant", "first_block": block, "last_block": block}]})


@pytest.mark.parametrize("value", ["true", "false", 0, 1])
def test_acknowledgement_requires_strict_boolean(value):
    with pytest.raises(ValidationError):
        request(1, acknowledge_outcome_and_cost_unknown=value)
    with pytest.raises(ValidationError):
        request(1, action="approve", acknowledge_outcome_and_cost_unknown=True)


@pytest.mark.parametrize("value", [False, None])
def test_acknowledgement_field_is_for_start_only_even_when_false_or_null(value):
    with pytest.raises(ValidationError):
        request(1, action="approve", acknowledge_outcome_and_cost_unknown=value)


@pytest.mark.parametrize("failure", [
    {"code": "source_review_timeout", "phase": "editor_request"},
    {"code": "source_review_provider_outcome_unknown", "phase": "independent_review_request"},
])
@pytest.mark.asyncio
async def test_unknown_retry_requires_explicit_ack_and_records_exact_failure(monkeypatch, failure):
    actor = uuid4()
    rows = [row(1, "queued", {}, actor), row(2, "running", {}, actor), row(3, "failed", failure, actor)]
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=SHA)
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    assert requires_retry_acknowledgement(rows)
    for ack in (None, False):
        with pytest.raises(ReviewConflictError, match="retry_ack_required"):
            await apply_command(db, doc, actor, request(3, acknowledge_outcome_and_cost_unknown=ack))
    with pytest.raises(ReviewConflictError, match="retry_ack_required"):
        await apply_command(db, doc, actor, request(3, action="select_parts", selected_part_ids=["part-" + "1" * 24],
            preparation_sha256=SHA))
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        await apply_command(db, doc, actor, request(2, acknowledge_outcome_and_cost_unknown=True))
    cmd = request(3, acknowledge_outcome_and_cost_unknown=True)
    _, _, saved, dispatch = await apply_command(db, doc, actor, cmd)
    assert dispatch and saved.payload["acknowledged_unknown"] == {
        "failure_event_id": str(rows[-1].id), "request_id": str(cmd.request_id), "actor_id": str(actor)}
    assert rows[-1].payload == failure
    rows.append(saved)
    _, _, receipt, dispatch = await apply_command(db, doc, actor, cmd)
    assert receipt is saved and dispatch and db.add.call_count == 1
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        await apply_command(db, doc, actor, request(3, acknowledge_outcome_and_cost_unknown=True))
    assert db.add.call_count == 1
    assert _command_digest(cmd) != _command_digest(cmd.model_copy(update={"acknowledge_outcome_and_cost_unknown": False}))


def test_legacy_digest_and_failure_classification():
    actor = uuid4()
    cmd = request(0)
    old = (f'{{"expected_revision":0,"request_id":"{cmd.request_id}","action":"start",'
           '"item_id":null,"decision":null,"replacement":null,"reason":null,"quote":null}')
    assert _command_digest(cmd) == text_hash(old)
    assert not requires_retry_acknowledgement([row(1, "failed", {"code": "source_review_timeout"}, actor)])
    assert not requires_retry_acknowledgement([row(1, "failed", {"code": "source_review_timeout", "phase": "editor_response"}, actor)])


def test_review_view_exposes_incomplete_and_previous_failed_usage():
    actor = uuid4()
    previous = {"failure_event_id": str(uuid4()), "usage": [], "usage_complete": False}
    rows = [row(1, "analyzed", {"policy": "v1", "original": "text", "issues": [], "automatic": [],
                                  "usage_complete": False, "previous_failed_usage": previous}, actor)]
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=SHA,
                          title="Synthetic", version=1, filename="source.txt")
    analysis = review_view(doc, rows, read_state(rows, SHA))["analysis"]
    assert analysis["usage_complete"] is False and analysis["previous_failed_usage"] == previous


@pytest.mark.parametrize("kind", ["running", "analysis_block"])
@pytest.mark.asyncio
async def test_interrupted_worker_is_held_without_appending_event(monkeypatch, kind):
    actor = uuid4()
    rows = [row(1, "queued", {}, actor), row(2, kind, {}, actor)]
    rows[-1].created_at = datetime.now(UTC) - timedelta(hours=1)
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=SHA,
                          title="Synthetic", version=1, filename="source.txt")
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    view = review_view(doc, rows, read_state(rows, SHA))
    assert view["error"] == "source_review_interrupted_outcome_unknown"
    for cmd in (request(2), request(2, action="select_parts", selected_part_ids=["part-" + "1" * 24],
                                   preparation_sha256=SHA)):
        with pytest.raises(ReviewConflictError, match="interrupted_outcome_unknown"):
            await apply_command(db, doc, actor, cmd)
    db.add.assert_not_called()


@pytest.mark.parametrize("failure", [
    {"code": "source_review_provider_outcome_unknown", "phase": "source_extraction"},
    {"code": "source_review_timeout", "phase": "source_extraction", "unknown_visual_outcome": True},
])
@pytest.mark.asyncio
async def test_visual_unknown_is_held_even_if_acknowledged(monkeypatch, failure):
    actor = uuid4()
    rows = [row(1, "queued", {}, actor), row(2, "running", {}, actor), row(3, "failed", failure, actor)]
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=SHA)
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    assert retry_blocked_unknown_visual(rows) and requires_retry_acknowledgement(rows)
    with pytest.raises(ReviewConflictError, match="visual_outcome_unknown"):
        await apply_command(db, doc, actor, request(3, acknowledge_outcome_and_cost_unknown=True))
    db.add.assert_not_called()


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.asyncio
async def test_latest_continuation_redispatches_exact_existing_event(monkeypatch, bound):
    actor = uuid4()
    parent = row(1, "queued", {}, actor)
    rows = [parent, row(2, "running", {"queued_event_id": str(parent.id)}, actor)]
    if bound:
        p = package()
        rows.append(row(3, "analysis_block", {"claim_id": str(rows[1].id),
            "key": "source-preparation-v1:manifest:" + SHA,
            "result": {"manifest": p.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}}, actor))
    payload = {"continuation_from": str(rows[1].id)}
    if bound:
        payload["preparation"] = p.binding([p.parts[0].id])
    queued = row(len(rows) + 1, "queued", payload, actor)
    rows.append(queued)
    assert continuation_pending(rows, SHA)
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=rows))
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=SHA)
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        await apply_command(db, doc, actor, request(queued.sequence - 1))
    _, _, receipt, dispatch = await apply_command(db, doc, actor, request(queued.sequence))
    assert dispatch and receipt is queued
    db.add.assert_not_called()
    _, _, other_receipt, other_dispatch = await apply_command(db, doc, uuid4(), request(queued.sequence))
    assert other_dispatch and other_receipt is queued and other_receipt.actor_id == actor
    db.add.assert_not_called()
    wrong = list(rows)
    wrong[-1] = row(queued.sequence, "queued", {**payload, "continuation_from": str(uuid4())}, actor)
    assert not continuation_pending(wrong, SHA)
    wrong[-1] = row(queued.sequence, "queued", {**payload, "pages": {"first_page": 1, "last_page": 2}}, actor)
    assert not continuation_pending(wrong, SHA)
    if bound:
        wrong[-1] = row(queued.sequence, "queued", {**payload, "preparation": {**payload["preparation"], "sha256": "b" * 64}}, actor)
        assert not continuation_pending(wrong, SHA)
