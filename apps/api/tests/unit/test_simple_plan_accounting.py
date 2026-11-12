import copy

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V10_POLICY, SIMPLE_COURSE_REVIEW_V11_POLICY
from app.modules.ai.v3.simple_course_service import simple_stage_allowed
from app.modules.ai.v3.simple_plan_accounting import (
    accounting_request,
    apply_accounting,
)
from app.modules.ai.v3.simple_semantic_source_plan import build_semantic_slices, semantic_plan_format
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus


def fixture():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    fmt = semantic_plan_format(packet, corpus)
    ids = [s['id'] for s in build_semantic_slices(packet, corpus) if s['text'].strip()]
    plan = {'source_fingerprint': packet.fingerprint,
        'slices_fingerprint': fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0],
        'title': 'Course', 'units': [{'id': 'one', 'title': 'Practical task',
            'primary_slices': ids[:-1], 'supporting_slices': []}], 'non_teaching': []}
    return corpus, packet, plan, ids


@pytest.mark.parametrize('role', ['primary', 'supporting', 'non_teaching'])
def test_only_missing_slice_is_added_without_mutating_plan(role):
    corpus, packet, plan, ids = fixture()
    before = copy.deepcopy(plan)
    messages, fmt = accounting_request(plan, packet, corpus)
    assert ids[-1] in messages[1]['content']
    value = {'source_fingerprint': packet.fingerprint, 'plan_fingerprint': _digest(plan),
        'assignments': [{'slice_id': ids[-1], 'role': role, 'unit_id': '' if role == 'non_teaching' else 'one',
            'reason': 'Model classification against the supplied source.'}], 'new_units': []}
    result, receipt = apply_accounting(value, plan, packet, corpus)
    assert plan == before and result['units'][0]['primary_slices'][:len(ids)-1] == ids[:-1]
    assert receipt['semantic_approval'] is False and receipt['original_plan'] == before
    assert receipt['assignment_proposal'] == value


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'foreign_slice', 'foreign_unit', 'source', 'plan', 'blank'])
def test_bad_assignment_cannot_discard_or_reclassify_source(fault):
    corpus, packet, plan, ids = fixture()
    value = {'source_fingerprint': packet.fingerprint, 'plan_fingerprint': _digest(plan),
        'assignments': [{'slice_id': ids[-1], 'role': 'primary', 'unit_id': 'one', 'reason': 'Source rule'}],
        'new_units': []}
    if fault == 'missing':
        value['assignments'] = []
    elif fault == 'duplicate':
        value['assignments'] *= 2
    elif fault == 'foreign_slice':
        value['assignments'][0]['slice_id'] = ids[0]
    elif fault == 'foreign_unit':
        value['assignments'][0]['unit_id'] = 'foreign'
    elif fault in {'source', 'plan'}:
        value[fault + '_fingerprint'] = '0' * 64
    else:
        value['assignments'][0]['reason'] = ' '
    with pytest.raises(ValueError):
        apply_accounting(value, plan, packet, corpus)


def test_missing_teaching_can_form_new_unit_with_owned_supporting_context():
    corpus, packet, plan, ids = fixture()
    value = {'source_fingerprint': packet.fingerprint, 'plan_fingerprint': _digest(plan),
        'assignments': [], 'new_units': [{'id': 'two', 'title': 'Additional practical task',
            'primary_slices': [ids[-1]], 'supporting_slices': [ids[0]]}]}
    result, _ = apply_accounting(value, plan, packet, corpus)
    assert result['units'][0] == plan['units'][0]
    assert result['units'][1] == value['new_units'][0]


def test_stage_admission_requires_v11_exact_source_plan_and_contract():
    corpus, packet, plan, ids = fixture()
    _, fmt = accounting_request(plan, packet, corpus)
    group = 'practical:simple:plan-accounting:v11:' + packet.fingerprint + ':unit=' + _digest(plan) + ':output=32768'
    assert simple_stage_allowed('repair', group, fmt, policy=SIMPLE_COURSE_REVIEW_V11_POLICY, validator=lambda v: v)
    assert not simple_stage_allowed('repair', group, fmt, policy=SIMPLE_COURSE_REVIEW_V10_POLICY, validator=lambda v: v)
    assert not simple_stage_allowed('review', group, fmt, policy=SIMPLE_COURSE_REVIEW_V11_POLICY, validator=lambda v: v)
    bad = copy.deepcopy(fmt)
    bad['json_schema']['schema']['properties']['plan_fingerprint']['enum'] = ['0' * 64]
    assert not simple_stage_allowed('repair', group, bad, policy=SIMPLE_COURSE_REVIEW_V11_POLICY, validator=lambda v: v)
