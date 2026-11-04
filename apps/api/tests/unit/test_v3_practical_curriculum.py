import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_curriculum import (
    CURRICULUM_REVIEW_GUIDE,
    compile_curriculum_findings,
    curriculum_bank_format,
    curriculum_bank_messages,
    curriculum_context,
    curriculum_format,
    curriculum_messages,
    is_curriculum_bank_format,
    is_curriculum_format,
    matches_curriculum,
    matches_curriculum_bank,
    validate_curriculum,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_practical_bank_cycle import bank_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def plan_value(packet):
    groups = audit_units(packet).groups
    refs = [b.block_id for b in packet.blocks if b.text.strip()]
    goals = [{'id': 'same-model-id', 'decision': 'Decide the required action.',
              'essential_case_conditions': ['The source rule applies.'], 'source_refs': refs} for _ in range(2)]
    return {'source_fingerprint': packet.fingerprint,
            'sections': [{'title': 'Practice', 'source_units': [key for key, _ in groups],
                          'depends_on_units': [], 'goals': goals}],
            'non_teaching_units': [], 'source_uncertainties': []}


def bank_response(packet, course, plan):
    result = bank_value(packet, course)
    result['curriculum_fingerprint'] = _digest(plan)
    result['goal_checks'] = [{'goal_id': goal['id'], 'status': 'COVERED',
        'source_refs': goal['source_refs'], 'question_ids': ['q1'], 'assessment_lesson_id': '', 'reason': 'Checked.'}
        for section in plan['sections'] for goal in section['goals']]
    return result


def test_source_only_plan_normalizes_ids_and_binds_units(case):
    _, packet, _ = case
    raw = plan_value(packet)
    fmt = curriculum_format(packet)
    assert is_curriculum_format(fmt) and matches_curriculum(raw, fmt)
    plan = validate_curriculum(raw, packet)
    assert [g['id'] for g in plan['sections'][0]['goals']] == ['G1', 'G2']
    assert raw['sections'][0]['goals'][0]['id'] == 'same-model-id'
    assert validate_curriculum(plan, packet) == plan
    wire = PracticalModelView(packet)
    assert is_curriculum_format(wire.schema(fmt)) and matches_curriculum(wire.encode(raw), wire.schema(fmt))
    assert wire.decode(wire.encode(plan)) == plan
    assert 'STANDALONE_QUESTIONS_JSON' not in curriculum_messages(packet)[1]['content']


@pytest.mark.parametrize('mutation', ['foreign_ref', 'missing_unit', 'blank_goal'])
def test_invalid_plan_never_authorizes_context(case, mutation):
    _, packet, _ = case
    raw = plan_value(packet)
    if mutation == 'foreign_ref':
        raw['sections'][0]['goals'][0]['source_refs'] = ['foreign']
    elif mutation == 'missing_unit':
        raw['sections'][0]['source_units'] = []
    else:
        raw['sections'][0]['goals'][0]['decision'] = ' '
    with pytest.raises(ValueError):
        validate_curriculum(raw, packet)


def test_bank_is_blind_closed_and_compiles_only_owned_allegations(case):
    _, packet, course = case
    plan = validate_curriculum(plan_value(packet), packet)
    fmt = curriculum_bank_format(packet, course, plan)
    assert is_curriculum_bank_format(fmt)
    wire = PracticalModelView(packet)
    assert is_curriculum_bank_format(wire.schema(fmt))
    messages = curriculum_bank_messages(packet, course, plan, model_view=wire)
    body = messages[1]['content'].split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
    questions = json.loads(body)
    assert all(set(q) == {'lesson_id', 'id', 'prompt', 'choices'} for q in questions)
    assert course['lessons'][0]['content'] not in messages[1]['content']
    assert 'correct_index' not in messages[1]['content'] and 'explanation' not in messages[1]['content']
    assert CURRICULUM_REVIEW_GUIDE in messages[0]['content']
    assert _digest(CURRICULUM_REVIEW_GUIDE) == 'bff498b544206f1dd9cbd8b6078925444aa2c06d9e6117557f5f2dd4579d6f07'
    assert curriculum_context(packet, plan, wire) in messages[1]['content']
    value = bank_response(packet, course, plan)
    value['goal_checks'][0].update(status='MISSING', question_ids=[], assessment_lesson_id='l1')
    value['goal_checks'][1].update(status='MISSING', question_ids=[], assessment_lesson_id='')
    assert matches_curriculum_bank(value, fmt)
    assert matches_curriculum_bank(wire.encode(value), wire.schema(fmt))
    findings, unresolved = compile_curriculum_findings(value, packet, course, plan)
    assert len(findings) == 1 and findings[0]['scope'] == 'assessment' and findings[0]['target_id'] == 'l1'
    assert unresolved == ('G2',)
    # Goal findings are proposals, not a decision or edit authority.
    assert findings[0]['expected_rule'] == plan['sections'][0]['goals'][0]['decision']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'foreign_goal', 'foreign_question', 'foreign_source', 'foreign_lesson', 'stale_plan'])
def test_goal_inventory_and_plan_custody_fail_closed(case, mutation):
    _, packet, course = case
    plan = validate_curriculum(plan_value(packet), packet)
    value = bank_response(packet, course, plan)
    if mutation == 'missing':
        value['goal_checks'].pop()
    elif mutation == 'duplicate':
        value['goal_checks'][1]['goal_id'] = 'G1'
    elif mutation == 'foreign_goal':
        value['goal_checks'][0]['goal_id'] = 'G999'
    elif mutation == 'foreign_question':
        value['goal_checks'][0]['question_ids'] = ['q-foreign']
    elif mutation == 'foreign_source':
        value['goal_checks'][0]['source_refs'] = ['foreign']
    elif mutation == 'foreign_lesson':
        value['goal_checks'][0]['assessment_lesson_id'] = 'l-foreign'
    else:
        plan = copy.deepcopy(plan)
        plan['sections'][0]['goals'][0]['decision'] += ' changed'
    assert not matches_curriculum_bank(value, curriculum_bank_format(packet, course, plan))
    with pytest.raises(ValueError):
        compile_curriculum_findings(value, packet, course, plan)


def test_large_aliased_formats_fit_shipped_runner():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet

    source = ''.join(f'Operational paragraph {i}.\n\n' for i in range(1000))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
                  'correct_index': 0, 'explanation': 'A.', 'source_refs': [packet.blocks[i].block_id]}
                 for i in range(3)]
    course = {'title': 'Course', 'lessons': [{'id': f'l{i}', 'title': 'Lesson', 'content': 'Rule.',
                                              'questions': questions[i:i + 4]} for i in range(0, 3, 4)]}
    plan = plan_value(packet)
    plan['sections'][0]['goals'] = [copy.deepcopy(plan['sections'][0]['goals'][i % 2]) for i in range(100)]
    plan = validate_curriculum(plan, packet)
    view = PracticalModelView(packet)
    fmt = view.schema(curriculum_bank_format(packet, course, plan))
    spec = importlib.util.spec_from_file_location('curriculum_runner',
        Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(view.schema(curriculum_format(packet)))
    assert runner._checked_structured_format(fmt)


def test_micro_scale_deduplicates_inventory_and_rejects_foreign_source():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.practical_contract import build_practical_source_packet
    from app.modules.ai.v3.practical_review import practical_review_format
    from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract

    source = ''.join(f'Operational paragraph {i}.\n\n' for i in range(276))
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
                  'correct_index': 0, 'explanation': 'A.', 'source_refs': [packet.blocks[i].block_id]}
                 for i in range(80)]
    course = {'title': 'Course', 'lessons': [{'id': f'l{i}', 'title': 'Lesson', 'content': 'Rule.',
        'questions': questions[i:i + 4]} for i in range(0, 80, 4)]}
    plan = validate_curriculum(plan_value(packet), packet)
    view = PracticalModelView(packet)
    fmt = view.schema(curriculum_bank_format(packet, course, plan))
    base = view.schema(practical_review_format(packet, course, concise=True, strict_targets=True,
        standalone=True, typed_findings=True, counterexamples=True, question_batch=True))
    assert 'enum' in base['json_schema']['schema']['properties']['question_sources']['properties']['l0']['items']
    assert fmt['json_schema']['schema']['properties']['question_sources']['properties']['l0']['items'] == {'type': 'string'}
    spec = importlib.util.spec_from_file_location('curriculum_micro_runner',
        Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert len(json.dumps(fmt, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) < runner.MAX_SCHEMA_BYTES
    assert runner._checked_structured_format(fmt)
    assert response_contract(fmt) == 'practical_curriculum_bank'
    value = bank_response(packet, course, plan)
    wire = view.encode(value)
    assert matches_response_contract(wire, fmt)
    wire['question_sources']['l0'] = ['foreign']
    assert not matches_response_contract(wire, fmt)
    bad = copy.deepcopy(fmt)
    bad['json_schema']['schema']['properties']['source_notes']['items']['properties']['source_refs']['items']['enum'].append('foreign')
    assert not is_curriculum_bank_format(bad)
