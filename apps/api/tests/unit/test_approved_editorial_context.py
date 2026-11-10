"""Approved keep decisions must reach generation without becoming source rewrites."""
import dataclasses

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_editorial_cycle import _context
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text, text_hash


def fixture():
    text = 'Funds are issued only to the named recipient.\n\nEmployee advance: the client signs the receipt.'
    quote = 'the client signs the receipt.'
    start = text.index(quote)
    decision = {'item_id': 'issue-recipient', 'decision': 'keep', 'quote': quote,
                'start': start, 'end': start + len(quote),
                'reason': 'For this employee advance, apply the general named-recipient rule; the recipient is the employee.'}
    _, spans = render_text(text, [])
    approved = ApprovedEditorialDocument('doc', 'document:' + 'a' * 64, 'approval', text, text,
        text_hash(text), tuple(spans), {}, decision_context=(decision,))
    doc = DirectSourceDocument('doc', 'Source', 'source.docx', 'general', approved.source_revision, (),
                               source_text=text, editorial_document=approved)
    corpus = DirectSourceCorpus('tenant', (doc,), len(text), 0)
    return approved, corpus, decision


def test_approved_keep_reason_reaches_model_as_scoped_editorial_context():
    approved, corpus, decision = fixture()
    packet = build_practical_source_packet(corpus)
    message = _context(packet, corpus, PracticalModelView(packet), canonical_json=True)
    assert approved.valid(document_id='doc', source_revision=approved.source_revision)
    assert 'APPROVED_EDITORIAL_DECISIONS_JSON' in message
    assert decision['reason'] in message and decision['quote'] in message
    assert 'approval' in message and approved.working_sha256 in message
    assert approved.working_text == approved.recognized_text
    assert 'not a company reply' in message


@pytest.mark.parametrize('fault', ['foreign_quote', 'foreign_span', 'invalid_decision', 'blank_reason'])
def test_editorial_context_cannot_outlive_its_bound_original(fault):
    approved, _, decision = fixture()
    row = dict(decision)
    if fault == 'foreign_quote':
        row['quote'] = 'Different source.'
    elif fault == 'foreign_span':
        row['start'] += 1
    elif fault == 'invalid_decision':
        row['decision'] = 'automatic_approval'
    else:
        row['reason'] = ' '
    changed = dataclasses.replace(approved, decision_context=(row,))
    assert not changed.valid(document_id='doc', source_revision=approved.source_revision)


@pytest.mark.asyncio
@pytest.mark.parametrize('anchored', [True, False])
async def test_owned_approval_reader_preserves_the_recorded_decision(monkeypatch, anchored):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.modules.source_editorial_review import service
    approved, _, decision = fixture()
    if not anchored:
        decision.update(start=None, end=None, quote='')
    tenant, document, approval = uuid4(), uuid4(), uuid4()
    row = SimpleNamespace(document_id=document, id=approval, sequence=8, original_blob_sha256='a' * 64,
        payload={'working': approved.working_text, 'working_sha256': approved.working_sha256,
                 'spans': list(approved.spans)})
    state = SimpleNamespace(original=approved.recognized_text, fidelity={}, preparation=None,
        decisions={decision['item_id']: dict(decision, before=decision['quote'])})
    monkeypatch.setattr(service, 'owned_document', AsyncMock(return_value=SimpleNamespace(id=document)))
    monkeypatch.setattr(service, 'read_approval', AsyncMock(return_value=(row, state)))
    result = await service.resolve_pins(None, tenant, [str(document)], [service.snapshot_identity(row)])
    assert result[str(document)].decision_context == (decision,)
    assert result[str(document)].approval_id == str(approval)
    assert result[str(document)].valid(document_id=str(document), source_revision=approved.source_revision)
