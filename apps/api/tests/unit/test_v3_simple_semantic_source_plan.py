import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_semantic_source_plan import (
    build_semantic_slices,
    compile_semantic_plan,
    is_semantic_plan_format,
    matches_semantic_plan,
    semantic_plan_request,
    semantic_unit_request,
)
from app.modules.ai.v3.simple_source_unit import compile_source_unit
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course
from tests.unit.test_v3_simple_source_unit import corpus_for, reference


def fixture():
    corpus = corpus_for('First condition<br>Second action.\nNext branch.\n\nOther context.')
    return corpus, build_practical_source_packet(corpus)


def make_plan(packet, corpus):
    slices = [s for s in build_semantic_slices(packet, corpus) if s['text'].strip()]
    _, fmt = semantic_plan_request(packet, corpus, {})
    fp = fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0]
    ids = [s['id'] for s in slices]
    return {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': fp, 'title': 'Course',
            'units': [{'id': 'a', 'title': 'Work', 'primary_slices': ids[:2], 'supporting_slices': []},
                      {'id': 'b', 'title': 'Related', 'primary_slices': [ids[0]], 'supporting_slices': [ids[1]]}],
            'non_teaching': [{'slice_ids': ids[2:], 'reason': 'Context'}]}, fmt


def test_catalog_exact_reconstruction_ranges_and_shared_slice_plan():
    corpus, packet = fixture()
    before = copy.deepcopy(corpus)
    slices = build_semantic_slices(packet, corpus)
    for block in packet.blocks:
        parts = [row for row in slices if row['source_ref'] == block.block_id]
        assert ''.join(row['text'] for row in parts) == block.text
        assert all(corpus.documents[0].source_text[row['start']:row['end']] == row['text'] for row in parts)
    assert any(row['text'].endswith('<br>') for row in slices)
    plan, fmt = make_plan(packet, corpus)
    assert is_semantic_plan_format(fmt) and matches_semantic_plan(plan, fmt)
    assert compile_semantic_plan(plan, packet, corpus) == plan and corpus == before
    payload = json.loads(semantic_plan_request(packet, corpus, {})[0][1]['content'])
    assert 'source_blocks' not in payload and payload['source_slices'][0]['source_ref'] == 'SRC1'


@pytest.mark.parametrize('fault', ['foreign', 'duplicate', 'missing', 'stale_source', 'stale_slices', 'empty_reason'])
def test_invalid_plan_is_rejected(fault):
    corpus, packet = fixture()
    plan, fmt = make_plan(packet, corpus)
    if fault == 'foreign':
        plan['units'][0]['primary_slices'][0] = 'S999'
    elif fault == 'duplicate':
        plan['units'][0]['supporting_slices'] = [plan['units'][0]['primary_slices'][0]]
    elif fault == 'missing':
        plan['non_teaching'][0]['slice_ids'].pop()
    elif fault == 'stale_source':
        plan['source_fingerprint'] = '0' * 64
    elif fault == 'stale_slices':
        plan['slices_fingerprint'] = '0' * 64
    else:
        plan['non_teaching'][0]['reason'] = ' '
    assert not matches_semantic_plan(plan, fmt)
    with pytest.raises(ValueError):
        compile_semantic_plan(plan, packet, corpus)


def test_unit_primary_excerpts_and_confirmed_reference_closure():
    corpus = corpus_for('ANCHOR refers to procedure.\n\nTARGET applies condition.')
    decision = reference(corpus, 'ANCHOR', 'TARGET')
    packet = build_practical_source_packet(corpus, (decision,))
    slices = build_semantic_slices(packet, corpus)
    _, fmt = semantic_plan_request(packet, corpus, {})
    plan = {'source_fingerprint': packet.fingerprint,
            'slices_fingerprint': fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0],
            'title': 'Course', 'units': [{'id': 'a', 'title': 'Work', 'primary_slices': [slices[0]['id']],
                                         'supporting_slices': []}],
            'non_teaching': [{'slice_ids': [s['id'] for s in slices[1:] if s['text'].strip()], 'reason': 'Context'}]}
    messages, _, meta = semantic_unit_request(packet, corpus, {}, plan, 'a', (decision,))
    payload = json.loads(messages[1]['content'])
    assert payload['primary_slices'][0]['text'] == slices[0]['text']
    assert payload['primary_slices'][0]['source_ref'] == 'SRC1'
    assert packet.blocks[1].block_id in meta['supporting_refs']
    assert len(meta['selection_fingerprint']) == 64 and meta['slices'][0] == slices[0]
    course = PracticalModelView(packet).decode(unit_course('SRC1', 'Authored lesson'))
    compiled = compile_source_unit(course, packet, meta['primary_refs'], meta['supporting_refs'])
    assert compiled['lessons'][0]['content'] == 'Authored lesson'


def test_visual_observation_is_not_split():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    slices = build_semantic_slices(packet, corpus)
    observation = next(row for row in slices if 'Visual OCR sentinel' in row['text'])
    assert 'Visual description sentinel' in observation['text']
    assert {origin['origin'] for origin in observation['origins']} == {'visual_ocr', 'visual_description'}
