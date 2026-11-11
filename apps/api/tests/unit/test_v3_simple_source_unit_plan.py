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
from app.modules.ai.v3.simple_source_unit_plan import (
    _plan_format,
    compile_source_unit_plan,
    decode_source_unit_plan,
    encode_source_unit_plan,
    is_source_unit_plan_format,
    matches_source_unit_plan,
    source_unit_plan_request,
)
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from tests.unit.test_v3_simple_source_unit import setup_unit


def wire_plan(packet):
    return {'source_fingerprint': packet.fingerprint, 'title': 'Course',
            'units': [{'id': 'unit-a', 'title': 'First', 'supporting_refs': ['SRC2']},
                      {'id': 'unit-b', 'title': 'Second', 'supporting_refs': ['SRC1']}],
            'assignments': ['unit-a', 'unit-b', 'CONTEXT: Administrative context']}


@pytest.mark.asyncio
async def test_current_literal_source_real_managed_prepare_and_producer():
    corpus, packet, _, _ = setup_unit()
    before = copy.deepcopy(corpus)
    messages, fmt = source_unit_plan_request(packet, corpus, {'audience': 'staff'})
    payload = json.loads(messages[1]['content'])
    assert [''.join(segment['text'] for segment in block['segments']) for block in payload['source_blocks']] == [block.text for block in packet.blocks]
    assert payload['source_fingerprint'] == packet.fingerprint
    assert 'PRIMARY_SENTINEL' in messages[1]['content'] and 'UNSELECTED_SECRET' in messages[1]['content']
    assert 'old_course' not in messages[1]['content'] and corpus == before
    assert is_source_unit_plan_format(fmt) and matches_source_unit_plan(wire_plan(packet), fmt)
    assignment_schema = fmt['json_schema']['schema']['properties']['assignments']
    assert assignment_schema['minItems'] == assignment_schema['maxItems'] == 3
    assert payload['assignment_source_order'] == ['SRC1', 'SRC2', 'SRC3']
    assert [block['assignment_index'] for block in payload['source_blocks']] == [0, 1, 2]
    assert fmt['json_schema']['name'] == 'simple_source_unit_plan_v2'
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('unit_plan_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=uuid4(), user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic',
        model='gpt-6-luna', reasoning_effort='high')

    async def checkpoint():
        return True

    try:
        cap = await client.prepare(messages, max_output_tokens=8192, ownership_checkpoint=checkpoint, response_format=fmt)
        client.discard(cap)
    finally:
        client.close()
    original = wire_plan(packet)
    canonical = decode_source_unit_plan(original, PracticalModelView(packet))
    compiled = compile_source_unit_plan(canonical, packet)
    assert compiled['units'][0]['primary_refs'] == [packet.blocks[0].block_id]
    assert compiled['units'][0]['supporting_refs'] == [packet.blocks[1].block_id]
    assert compiled['non_teaching'][0]['source_refs'] == [packet.blocks[2].block_id]
    assert encode_source_unit_plan(compiled, PracticalModelView(packet)) == original
    assert original == wire_plan(packet)


@pytest.mark.asyncio
async def test_thousand_source_schema_real_prepare_and_producer():
    corpus, _, _, _ = setup_unit()
    doc = corpus.documents[0]
    text = ''.join(f'Original source paragraph {i}.\n\n' for i in range(1000))
    working, spans = render_text(text, [])
    approval = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approval', text, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approval),))
    packet = build_practical_source_packet(corpus)
    assert len(packet.blocks) == 1000
    messages, fmt = source_unit_plan_request(packet, corpus, {})
    assert len(json.dumps(fmt, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()) <= 65536
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=uuid4(), user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic',
        model='gpt-6-luna', reasoning_effort='high')

    async def checkpoint():
        return True

    try:
        cap = await client.prepare(messages, max_output_tokens=8192, ownership_checkpoint=checkpoint, response_format=fmt)
        client.discard(cap)
    finally:
        client.close()
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('large_unit_plan_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


def test_229_source_schema_fits_existing_producer():
    fmt = _plan_format([f'SRC{i}' for i in range(1, 230)], 'a' * 64)
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('current_unit_plan_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


@pytest.mark.parametrize('fault', ['missing', 'extra_assignment', 'unknown_unit', 'invalid_assignment',
                                   'foreign_support', 'duplicate_unit', 'stale_fingerprint',
                                   'empty_reason', 'primaryless', 'reserved_unit'])
def test_plan_rejects_invalid_custody_and_coverage(fault):
    corpus, packet, _, _ = setup_unit()
    _, fmt = source_unit_plan_request(packet, corpus, {})
    value = wire_plan(packet)
    if fault == 'missing':
        value['assignments'].pop()
    elif fault == 'extra_assignment':
        value['assignments'].append('CONTEXT: other')
    elif fault == 'unknown_unit':
        value['assignments'][0] = 'foreign'
    elif fault == 'invalid_assignment':
        value['assignments'][0] = ''
    elif fault == 'foreign_support':
        value['units'][0]['supporting_refs'] = ['SRC999']
    elif fault == 'duplicate_unit':
        value['units'][1]['id'] = value['units'][0]['id']
    elif fault == 'stale_fingerprint':
        value['source_fingerprint'] = '0' * 64
    elif fault == 'empty_reason':
        value['assignments'][2] = 'CONTEXT:  '
    elif fault == 'reserved_unit':
        value['units'][0]['id'] = 'CONTEXT: bad'
    else:
        value['assignments'][0] = 'CONTEXT: context'
    assert not matches_source_unit_plan(value, fmt)
    with pytest.raises(ValueError):
        decoded = decode_source_unit_plan(value, PracticalModelView(packet))
        compile_source_unit_plan(decoded, packet)


def test_redundant_owned_support_is_normalized_without_changing_source_set():
    corpus, packet, _, _ = setup_unit()
    _, fmt = source_unit_plan_request(packet, corpus, {})
    raw = wire_plan(packet)
    raw['units'][0]['supporting_refs'] = ['SRC1', 'SRC2', 'SRC2', 'SRC1']
    before = copy.deepcopy(raw)
    assert matches_source_unit_plan(raw, fmt)
    view = PracticalModelView(packet)
    canonical = compile_source_unit_plan(decode_source_unit_plan(raw, view), packet)
    selected = canonical['units'][0]['primary_refs'] + canonical['units'][0]['supporting_refs']
    assert selected == [packet.blocks[0].block_id, packet.blocks[1].block_id]
    assert raw == before
    wire = encode_source_unit_plan(canonical, view)
    assert wire['units'][0]['supporting_refs'] == ['SRC2']
    invalid = copy.deepcopy(canonical)
    invalid['units'][0]['supporting_refs'].append(invalid['units'][0]['primary_refs'][0])
    with pytest.raises(ValueError):
        encode_source_unit_plan(invalid, view)


def test_unapproved_source_is_rejected_before_request():
    corpus, packet, _, _ = setup_unit()
    altered = replace(corpus, documents=(replace(corpus.documents[0], source_text='tampered'),))
    with pytest.raises(ValueError):
        source_unit_plan_request(packet, altered, {})


def test_structure_metadata_is_owned_literal_navigation_and_source_unchanged():
    corpus, _, _, _ = setup_unit()
    doc = corpus.documents[0]
    text = '# 1. Operations\n\n| Category | Action |\n|---|---|\n| Desk | Record |\n| Service | Review |\n\n# 2. Other\nProceed.'
    working, spans = render_text(text, [])
    approval = ApprovedEditorialDocument(doc.doc_id, doc.source_revision, 'approval', text, working,
        hashlib.sha256(working.encode()).hexdigest(), tuple(spans), {})
    corpus = replace(corpus, documents=(replace(doc, source_text=working, editorial_document=approval),))
    packet = build_practical_source_packet(corpus)
    before = copy.deepcopy(corpus)
    messages, _ = source_unit_plan_request(packet, corpus, {})
    payload = json.loads(messages[1]['content'])
    aliases = PracticalModelView(packet).canonical_to_alias
    assert [''.join(segment['text'] for segment in row['segments']) for row in payload['source_blocks']] == [block.text for block in packet.blocks if block.block_id in aliases]
    structure = payload['source_structure']
    assert {row['source_ref'] for row in structure} == set(aliases.values())
    assert all(row['document_id'] == doc.doc_id for row in structure)
    header = next(row for row in structure if row['kind'] == 'table_header')
    rows = [row for row in structure if row['kind'] == 'table_row']
    assert [row['table_topic'] for row in rows] == ['Desk', 'Service']
    assert all(row['table_header_refs'] == [header['source_ref']] for row in rows)
    assert all(row['section_label'] == 'Раздел 1' for row in rows)
    assert 'Record' not in json.dumps(structure) and corpus == before
    assert 'actual target procedures and conditions' in messages[0]['content']
    assert 'Human-confirmed decisions govern ambiguous references' in messages[0]['content']
