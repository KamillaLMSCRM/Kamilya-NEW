import copy
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_source_unit import compile_source_unit, source_unit_request
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from tests.unit.test_v3_simple_course_editor import course, fixture


def setup_unit():
    corpus, _ = fixture()
    doc = corpus.documents[0]
    text = 'PRIMARY_SENTINEL condition.\n\nSUPPORT_SENTINEL parent.\n\nUNSELECTED_SECRET other topic.'
    working, spans = render_text(text, [])
    approved = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approval', text, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approved),))
    packet = build_practical_source_packet(corpus)
    assert len(packet.blocks) == 3
    return corpus, packet, [packet.blocks[0].block_id], [packet.blocks[1].block_id]


def reply():
    value = course(ref='SRC1', content='Connected lesson')
    question = value['lessons'][0]['questions'][0]
    value['lessons'][0]['questions'] = [{**question, 'id': f'q{i}'} for i in range(3)]
    return value


@pytest.mark.asyncio
async def test_selected_unit_managed_prepare_and_producer_schema_without_network():
    corpus, packet, primary, supporting = setup_unit()
    before = copy.deepcopy(corpus)
    messages, fmt, unit = source_unit_request(packet, corpus, {'audience': 'staff'}, primary, supporting)
    body = json.loads(messages[1]['content'])
    assert [block['role'] for block in body['source_blocks']] == ['primary', 'supporting']
    assert 'PRIMARY_SENTINEL' in messages[1]['content'] and 'SUPPORT_SENTINEL' in messages[1]['content']
    assert 'UNSELECTED_SECRET' not in messages[1]['content']
    assert unit.source_fingerprint == packet.fingerprint and len(unit.selection_fingerprint) == 64
    assert body['selection_fingerprint'] == unit.selection_fingerprint
    assert corpus == before
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('source_unit_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
    tenant, user = uuid4(), uuid4()
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=tenant, user_id=user, job_id=str(uuid4()), credential_revision='synthetic',
        model='gpt-6-luna', reasoning_effort='high')

    async def checkpoint():
        return True

    try:
        cap = await client.prepare(messages, max_output_tokens=8192, ownership_checkpoint=checkpoint, response_format=fmt)
        client.discard(cap)
    finally:
        client.close()
    decoded = PracticalModelView(packet).decode(reply())
    result = compile_source_unit(decoded, packet, primary, supporting)
    assert len(result['lessons']) == 1 and len(result['lessons'][0]['questions']) == 3
    assert result['lessons'][0]['questions'][0]['source_refs'] == primary


@pytest.mark.parametrize('fault', ['empty', 'foreign', 'duplicate', 'overlap', 'blank'])
def test_selection_rejects_invalid_references(fault):
    corpus, packet, primary, supporting = setup_unit()
    if fault == 'empty':
        primary = []
    elif fault == 'foreign':
        primary = ['foreign']
    elif fault == 'duplicate':
        primary *= 2
    elif fault == 'overlap':
        supporting = primary[:]
    else:
        primary = ['']
    with pytest.raises(ValueError):
        source_unit_request(packet, corpus, {}, primary, supporting)


@pytest.mark.parametrize('fault', ['foreign_ref', 'unselected_ref', 'two_questions', 'five_questions', 'two_lessons'])
def test_compile_rejects_foreign_or_out_of_scope_course(fault):
    _, packet, primary, supporting = setup_unit()
    value = PracticalModelView(packet).decode(reply())
    questions = value['lessons'][0]['questions']
    if fault == 'foreign_ref':
        questions[0]['source_refs'] = ['foreign']
    elif fault == 'unselected_ref':
        questions[0]['source_refs'] = [packet.blocks[2].block_id]
    elif fault == 'two_questions':
        questions.pop()
    elif fault == 'five_questions':
        questions.extend([{**copy.deepcopy(questions[0]), 'id': f'extra{i}'} for i in range(2)])
    else:
        second = copy.deepcopy(value['lessons'][0])
        second['id'] = 'second'
        for q in second['questions']:
            q['id'] += '-second'
        value['lessons'].append(second)
    with pytest.raises(ValueError):
        compile_source_unit(value, packet, primary, supporting)


def test_unapproved_source_is_rejected():
    corpus, packet, primary, supporting = setup_unit()
    altered = replace(corpus, documents=(replace(corpus.documents[0], source_text='tampered'),))
    with pytest.raises(ValueError):
        source_unit_request(packet, altered, {}, primary, supporting)


def test_decision_context_is_scoped_to_selected_raw_spans():
    corpus, _, _, _ = setup_unit()
    doc = corpus.documents[0]
    text = doc.source_text
    first, last = text.index('PRIMARY_SENTINEL'), text.index('UNSELECTED_SECRET')
    decisions = (
        {'item_id': 'one', 'decision': 'keep', 'quote': 'PRIMARY_SENTINEL',
         'reason': 'selected reason', 'start': first, 'end': first + len('PRIMARY_SENTINEL')},
        {'item_id': 'two', 'decision': 'keep', 'quote': 'UNSELECTED_SECRET',
         'reason': 'unselected reason', 'start': last, 'end': last + len('UNSELECTED_SECRET')},
    )
    approved = replace(doc.editorial_document, decision_context=decisions)
    corpus = replace(corpus, documents=(replace(doc, editorial_document=approved),))
    packet = build_practical_source_packet(corpus)
    messages, _, _ = source_unit_request(packet, corpus, {}, [packet.blocks[0].block_id], [])
    assert 'selected reason' in messages[1]['content']
    assert 'unselected reason' not in messages[1]['content'] and 'UNSELECTED_SECRET' not in messages[1]['content']


def test_partial_selection_fails_closed_on_unscoped_reference_context():
    corpus, _, _, _ = setup_unit()
    doc = corpus.documents[0]
    source = doc.source_text
    first = source.index('PRIMARY_SENTINEL')
    second = source.index('SUPPORT_SENTINEL')
    decision = SourceReferenceDecision(tenant_id=corpus.tenant_id, document_id=doc.doc_id,
        source_revision=doc.source_revision, converted_text_sha256=hashlib.sha256(source.encode()).hexdigest(),
        reference_start=first, reference_end=first + len('PRIMARY_SENTINEL'), reference_exact='PRIMARY_SENTINEL',
        target_start=second, target_end=second + len('SUPPORT_SENTINEL'), target_exact='SUPPORT_SENTINEL', authority='owner_chat')
    packet = build_practical_source_packet(corpus, (decision,))
    with pytest.raises(ValueError, match='simple_unit_reference_context_unscoped'):
        source_unit_request(packet, corpus, {}, [packet.blocks[0].block_id], [packet.blocks[1].block_id])


def corpus_for(text):
    corpus, _ = fixture()
    doc = corpus.documents[0]
    working, spans = render_text(text, [])
    approved = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approval', text, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    return replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approved),))


def reference(corpus, anchor, target):
    doc = corpus.documents[0]
    source = doc.source_text
    start, end = source.index(anchor), source.index(target)
    return SourceReferenceDecision(tenant_id=corpus.tenant_id, document_id=doc.doc_id,
        source_revision=doc.source_revision, converted_text_sha256=hashlib.sha256(source.encode()).hexdigest(),
        reference_start=start, reference_end=start + len(anchor), reference_exact=anchor,
        target_start=end, target_end=end + len(target), target_exact=target, authority='owner_chat')


def test_table_row_includes_exact_header_as_support():
    corpus = corpus_for('Intro.\n\n| Category | Rule |\n| --- | --- |\n| A | First |\n| B | Second |\n')
    packet = build_practical_source_packet(corpus)
    header = next(b for b in packet.blocks if 'Category' in b.text)
    row = next(b for b in packet.blocks if '| B |' in b.text)
    messages, _, unit = source_unit_request(packet, corpus, {}, [row.block_id], [])
    assert unit.primary_refs == (row.block_id,) and unit.supporting_refs == (header.block_id,)
    blocks = json.loads(messages[1]['content'])['source_blocks']
    assert [(b['text'], b['role']) for b in blocks] == [(header.text, 'supporting'), (row.text, 'primary')]


def test_table_row_includes_secondary_literal_header():
    corpus = corpus_for('|  |  |\n| --- | --- |\n| **Category** | **Rule** |\n| A | First |\n')
    packet = build_practical_source_packet(corpus)
    messages, _, unit = source_unit_request(packet, corpus, {}, [packet.blocks[-1].block_id], [])
    assert unit.supporting_refs == tuple(b.block_id for b in packet.blocks[:-1])
    assert [row['role'] for row in json.loads(messages[1]['content'])['source_blocks']] == [
        'supporting', 'supporting', 'primary']


def test_unselected_reference_is_not_disclosed_or_added():
    corpus, _, _, _ = setup_unit()
    decision = reference(corpus, 'UNSELECTED_SECRET', 'SUPPORT_SENTINEL')
    packet = build_practical_source_packet(corpus, (decision,))
    messages, _, unit = source_unit_request(packet, corpus, {}, [packet.blocks[0].block_id], [],
                                             reference_decisions=(decision,))
    body = json.loads(messages[1]['content'])
    assert unit.supporting_refs == () and body['reference_context'] == []
    assert 'UNSELECTED_SECRET' not in messages[1]['content']


def test_reference_selection_expands_cross_block_target_and_transitive_decision():
    text = 'SELECT_ANCHOR.\n\nTARGET_A.\n\nTARGET_B THEN_ANCHOR.\n\nFINAL_TARGET.\n\nOTHER_ANCHOR.\n\nOTHER_TARGET.'
    corpus = corpus_for(text)
    first = reference(corpus, 'SELECT_ANCHOR', 'TARGET_A.\n\nTARGET_B')
    second = reference(corpus, 'THEN_ANCHOR', 'FINAL_TARGET')
    unrelated = reference(corpus, 'OTHER_ANCHOR', 'OTHER_TARGET')
    decisions = (first, second, unrelated)
    packet = build_practical_source_packet(corpus, decisions)
    messages, fmt, unit = source_unit_request(packet, corpus, {}, [packet.blocks[0].block_id], [],
                                               reference_decisions=decisions)
    body = json.loads(messages[1]['content'])
    assert unit.supporting_refs == tuple(b.block_id for b in packet.blocks[1:4])
    assert len(body['reference_context']) == 2 and 'OTHER_TARGET' not in messages[1]['content']
    assert fmt['json_schema']['schema']['properties']['lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum'] == ['SRC1', 'SRC2', 'SRC3', 'SRC4']
    result = PracticalModelView(packet).decode(reply())
    result['lessons'][0]['questions'][0]['source_refs'] = [unit.supporting_refs[-1]]
    assert compile_source_unit(result, packet, unit.primary_refs, unit.supporting_refs)


@pytest.mark.parametrize('fault', ['foreign_tenant', 'foreign_document', 'stale_revision', 'stale_hash', 'changed_span', 'missing_decision'])
def test_reference_packet_requires_exact_authorized_decisions(fault):
    corpus, _, _, _ = setup_unit()
    decision = reference(corpus, 'PRIMARY_SENTINEL', 'SUPPORT_SENTINEL')
    packet = build_practical_source_packet(corpus, (decision,))
    changes = {'foreign_tenant': {'tenant_id': 'foreign'}, 'foreign_document': {'document_id': 'foreign'},
               'stale_revision': {'source_revision': 'other'}, 'stale_hash': {'converted_text_sha256': '0' * 64},
               'changed_span': {'target_exact': 'not the source'}}
    supplied = () if fault == 'missing_decision' else (replace(decision, **changes[fault]),)
    with pytest.raises(ValueError):
        source_unit_request(packet, corpus, {}, [packet.blocks[0].block_id], [], reference_decisions=supplied)


def test_replaced_source_quote_never_reenters_selected_context():
    corpus, _ = fixture()
    doc = corpus.documents[0]
    original = 'OLD_PRIVATE_WORD and retained condition'
    working, spans = render_text(original, [{'id': 'replace-id', 'start': 0, 'end': 16,
                                             'before': 'OLD_PRIVATE_WORD', 'after': 'CURRENT_WORD'}])
    decisions = ({'item_id': 'replace-id', 'decision': 'replace', 'quote': 'OLD_PRIVATE_WORD',
                  'reason': 'replacement interpretation', 'start': 0, 'end': 16},)
    approved = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approval', original, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {}, decision_context=decisions)
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approved),))
    packet = build_practical_source_packet(corpus)
    messages, _, _ = source_unit_request(packet, corpus, {}, [packet.blocks[0].block_id], [])
    assert 'CURRENT_WORD' in messages[1]['content'] and 'replacement interpretation' in messages[1]['content']
    assert 'OLD_PRIVATE_WORD' not in messages[1]['content']
