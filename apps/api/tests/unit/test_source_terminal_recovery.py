"""Terminal custody permits a continuation; unknown calls never become retries."""
import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.source_editorial_review.continuation import lineage, valid_continuation
from app.modules.source_editorial_review.domain import ReviewCommand, ReviewConflictError
from app.modules.source_editorial_review.recovery import recoverable_turn
from app.modules.source_editorial_review.request_custody import POLICY
from app.modules.source_preparation.domain import PreparedSource, digest
from tests.unit.test_source_review_custody import row


def fixture():
    actor, blob = uuid4(), 'a' * 64
    block = 'block-' + 'b' * 24
    package = PreparedSource.model_validate({'original_blob_sha256': blob,
        'blocks': [{'id': block, 'text': 'Rules', 'kind': 'text'}],
        'parts': [{'id': 'part-' + digest(blob + block + block)[:24], 'title': 'Rules',
                   'role': 'learning', 'reason': 'Training', 'first_block': block, 'last_block': block}]})
    binding = package.binding([package.parts[0].id])
    queued = row('queued', 1, actor, blob, {'preparation': binding})
    claim = row('running', 2, actor, blob, {'queued_event_id': str(queued.id)})
    base = POLICY + ':' + 'c' * 64 + ':initial'
    def checkpoint(seq, key, result):
        return row('analysis_block', seq, actor, blob, {'claim_id': str(claim.id), 'key': key, 'result': result})
    rows = [queued, claim,
        checkpoint(3, base + ':intent', {'identity': 'c' * 64, 'attempt': 'initial', 'state': 'started'}),
        checkpoint(4, base + ':completed', {'identity': 'c' * 64, 'attempt': 'initial', 'status': 'ok', 'usage': None, 'value': {'saved': True}}),
        checkpoint(5, 'source-review-v2:turn-usage:' + str(claim.id), {'usage': [], 'usage_complete': False})]
    for entry in rows:
        entry.created_at = datetime.now(UTC) - timedelta(minutes=21)
    return rows, actor, blob


@pytest.mark.parametrize('case', ['live', 'other_actor', 'wrong_blob', 'unknown_intent',
    'corrupt_identity', 'missing_value', 'orphan_completion', 'visual', 'not_terminal_turn', 'invalid_turn'])
def test_recovery_rejects_unproved_or_live_claims(case):
    rows, actor, blob = fixture()
    interrupted = True
    if case == 'live':
        interrupted = False
    if case == 'other_actor':
        actor = uuid4()
    if case == 'wrong_blob':
        blob = 'd' * 64
    if case == 'unknown_intent':
        rows.pop(3)
    if case == 'orphan_completion':
        rows.pop(2)
    if case == 'corrupt_identity':
        rows[3].payload['result']['identity'] = 'd' * 64
    if case == 'missing_value':
        rows[3].payload['result'].pop('value')
    if case == 'visual':
        rows[0].payload['preparation']['manifest']['assets'].append({'unverified': True})
    if case == 'not_terminal_turn':
        rows[-1].payload['key'] = 'some_other_checkpoint'
    if case == 'invalid_turn':
        rows[-1].payload.pop('result')
    assert recoverable_turn(rows, blob, actor, interrupted=interrupted) is None


@pytest.mark.asyncio
async def test_ordinary_resume_preserves_lineage_selection_receipts_and_idempotency(monkeypatch):
    from app.modules.source_editorial_review import service
    rows, actor, blob = fixture()
    original = copy.deepcopy(rows)
    assert recoverable_turn(rows, blob, actor, interrupted=True) == (rows[1], rows[0])
    monkeypatch.setattr(service, 'history', AsyncMock(side_effect=lambda *_: rows))
    monkeypatch.setattr(service, 'verified_preparation_binding', lambda *_: True)
    monkeypatch.setattr('app.modules.source_editorial_review.continuation.verified_preparation_binding', lambda *_: True)
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=blob, filename='rules.txt', title='Rules', version=1)
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    state = service.read_state(rows, blob)
    view = service.review_view(doc, rows, state, actor_id=actor)
    assert view['status'] == 'interrupted' and view['continuation_pending']
    assert view['error'] != 'source_review_interrupted_outcome_unknown'
    stale = ReviewCommand(expected_revision=4, request_id=uuid4(), action='start')
    with pytest.raises(ReviewConflictError, match='revision_conflict'):
        await service.apply_command(db, doc, actor, stale)
    command = ReviewCommand(expected_revision=5, request_id=uuid4(), action='start')
    updated, state, event, dispatch = await service.apply_command(db, doc, actor, command)
    assert dispatch and event.kind == 'queued' and event.sequence == 6
    assert event.payload['preparation'] == rows[0].payload['preparation']
    assert event.payload['recovered_terminal_checkpoint'] == str(rows[-1].id)
    assert valid_continuation(updated, event, blob)
    assert lineage(updated, event)[-1].id == rows[0].id
    assert [r.payload for r in rows] == [r.payload for r in original]
    rows.append(event)
    again = await service.apply_command(db, doc, actor, command)
    assert again[2] is event and db.add.call_count == 1


@pytest.mark.asyncio
async def test_unknown_request_stays_held_in_view_and_command(monkeypatch):
    from app.modules.source_editorial_review import service
    rows, actor, blob = fixture()
    rows.pop(3)
    for number, entry in enumerate(rows, 1):
        entry.sequence = number
    monkeypatch.setattr(service, 'history', AsyncMock(return_value=rows))
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256=blob, filename='rules.txt', title='Rules', version=1)
    state = service.read_state(rows, blob)
    view = service.review_view(doc, rows, state, actor_id=actor)
    assert not view['continuation_pending'] and view['error'] == 'source_review_interrupted_outcome_unknown'
    with pytest.raises(ReviewConflictError, match='interrupted_outcome_unknown'):
        await service.apply_command(SimpleNamespace(), doc, actor, ReviewCommand(
            expected_revision=4, request_id=uuid4(), action='start'))
