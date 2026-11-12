import copy
import hashlib

import pytest

from app.modules.ai.v3 import simple_plan_formatting
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.simple_plan_formatting import complete_formatting_plan
from app.modules.ai.v3.simple_semantic_source_plan import build_semantic_slices, semantic_plan_format
from tests.unit.test_v3_simple_source_unit import corpus_for


@pytest.fixture(autouse=True)
def prepared_text_origins(monkeypatch):
    # corpus_for has no source preparation; model the verified document-body origin.
    def catalog(packet, corpus):
        rows = build_semantic_slices(packet, corpus)
        for row in rows:
            for origin in row['origins']:
                if origin['origin'] == 'unclassified_text':
                    origin['origin'] = 'document_body'
        return rows
    monkeypatch.setattr(simple_plan_formatting, 'build_semantic_slices', catalog)


def make_case(text='Work.\n<br>\nOther.'):
    corpus = corpus_for(text)
    packet = build_practical_source_packet(corpus)
    slices = [row for row in build_semantic_slices(packet, corpus) if row['text'].strip()]
    props = semantic_plan_format(packet, corpus)['json_schema']['schema']['properties']
    plan = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': props['slices_fingerprint']['enum'][0],
            'title': 'Course', 'units': [{'id': 'unit', 'title': 'Work',
              'primary_slices': [slices[0]['id']], 'supporting_slices': []}],
            'non_teaching': [{'slice_ids': [row['id'] for row in slices[1:]], 'reason': 'Context'}]}
    return packet, corpus, slices, plan


@pytest.mark.parametrize('markup', ['<br>', '<br/>', '<br />', '<BR />'])
def test_unassigned_break_is_completed_without_mutation(markup):
    packet, corpus, slices, plan = make_case('Work.\n' + markup + '\nOther.')
    formatting = next(row for row in slices if row['text'] == markup)
    plan['non_teaching'][0]['slice_ids'].remove(formatting['id'])
    original = copy.deepcopy(plan)
    result, receipt = complete_formatting_plan(plan, packet, corpus)
    assert plan == original and receipt['original_plan'] == original
    assert result['units'] == original['units'] and result['non_teaching'][:-1] == original['non_teaching']
    assert result['non_teaching'][-1]['slice_ids'] == [formatting['id']]
    assert receipt['auto_excluded'] == [{'id': formatting['id'], 'text': formatting['text'],
        'start': formatting['start'], 'end': formatting['end'],
        'text_sha256': hashlib.sha256(formatting['text'].encode('utf-8')).hexdigest()}]
    assert receipt['source_fingerprint'] == packet.fingerprint
    assert receipt['model_plan_fingerprint'] == _digest(original)
    assert receipt['normalized_plan_fingerprint'] == _digest(result) and receipt['semantic_approval'] is False
    again, second = complete_formatting_plan(result, packet, corpus)
    assert again == result and second['auto_excluded'] == []


def test_complete_plan_and_already_assigned_break_are_unchanged():
    packet, corpus, slices, plan = make_case()
    break_id = next(row['id'] for row in slices if row['text'] == '<br>')
    plan['non_teaching'][0]['slice_ids'].remove(break_id)
    plan['units'][0]['supporting_slices'].append(break_id)
    result, receipt = complete_formatting_plan(plan, packet, corpus)
    assert result == plan and receipt['auto_excluded'] == []


@pytest.mark.parametrize('origin', [
    {'origin': 'visual_ocr'}, {'origin': 'visual_description'}, {'origin': 'unclassified_text'},
    {'origin': 'scanned_document_text', 'asset_id': 'asset'},
    {'origin': 'document_body', 'asset_id': 'asset'}, {},
])
def test_visual_asset_or_unverified_origin_is_not_excluded(monkeypatch, origin):
    packet, corpus, slices, plan = make_case()
    break_id = next(row['id'] for row in slices if row['text'] == '<br>')
    plan['non_teaching'][0]['slice_ids'].remove(break_id)
    original_catalog = simple_plan_formatting.build_semantic_slices
    def catalog(p, c):
        rows = original_catalog(p, c)
        next(row for row in rows if row['id'] == break_id)['origins'] = [origin]
        return rows
    monkeypatch.setattr(simple_plan_formatting, 'build_semantic_slices', catalog)
    with pytest.raises(ValueError, match='semantic_plan_invalid'):
        complete_formatting_plan(plan, packet, corpus)


@pytest.mark.parametrize('meaningful', ['Action.', '123', '# Heading', 'source-asset:asset-abc', '<hr>'])
def test_missing_meaningful_slice_is_never_excluded(meaningful):
    packet, corpus, slices, plan = make_case('Work.\n\n' + meaningful)
    plan['non_teaching'][0]['slice_ids'].remove(slices[-1]['id'])
    if not plan['non_teaching'][0]['slice_ids']:
        plan['non_teaching'] = []
    with pytest.raises(ValueError, match='semantic_plan_invalid'):
        complete_formatting_plan(plan, packet, corpus)


@pytest.mark.parametrize('fault', ['foreign', 'source', 'catalog', 'duplicate', 'missing_meaningful'])
def test_unrelated_invalidity_still_fails_when_break_missing(fault):
    packet, corpus, slices, plan = make_case()
    break_id = next(row['id'] for row in slices if row['text'] == '<br>')
    plan['non_teaching'][0]['slice_ids'].remove(break_id)
    if fault == 'foreign':
        plan['units'][0]['supporting_slices'].append('S999')
    elif fault == 'source':
        plan['source_fingerprint'] = '0' * 64
    elif fault == 'catalog':
        plan['slices_fingerprint'] = '0' * 64
    elif fault == 'duplicate':
        plan['units'][0]['supporting_slices'].append(plan['units'][0]['primary_slices'][0])
    else:
        plan['non_teaching'] = []
    with pytest.raises(ValueError, match='semantic_plan_invalid'):
        complete_formatting_plan(plan, packet, corpus)
