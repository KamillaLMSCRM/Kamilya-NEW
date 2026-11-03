import copy
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_scope import scoped_course_view
from app.modules.ai.v3.practical_source_audit import (
    is_source_audit_format,
    matches_source_audit,
    source_audit_format,
    source_audit_messages,
    validate_source_audit,
)
from tests.unit.test_v3_practical_review import example


@pytest.fixture
def audit():
    packet, course, _review, ref = example.__wrapped__()
    value = {'source_fingerprint': packet.fingerprint, 'source_units_fingerprint': audit_units(packet).fingerprint,
             'source_review': 'Reviewed source.',
             'source_notes': [{'note': 'A nonblocking ambiguity', 'source_refs': [ref]}],
             'source_checks': [{'unit_id': 'U1', 'source_refs': [ref], 'status': 'TAUGHT', 'lesson_ids': ['lesson'], 'reason': 'Covered'}],
             'findings': [{'scope': 'lesson', 'target_id': 'lesson', 'problem': 'Condition lost',
                           'source_refs': [ref], 'expected_rule': 'Both actions', 'correction': 'Restore both'}],
             'narrative_sources': {'lesson': [ref]}}
    return packet, course, value, ref


def test_closed_schema_and_no_semantic_approval(audit):
    packet, course, value, _ = audit
    fmt = source_audit_format(packet, course)
    original = copy.deepcopy(value)
    assert is_source_audit_format(fmt) and matches_source_audit(value, fmt)
    checked = validate_source_audit(value, packet, course)
    checked['findings'][0]['problem'] = 'changed'
    assert value == original and value['findings']
    forged = copy.deepcopy(fmt)
    forged['json_schema']['schema']['additionalProperties'] = True
    assert not is_source_audit_format(forged)


@pytest.mark.parametrize('defect', ['foreign_ref', 'duplicate_ref', 'foreign_target', 'wrong_scope',
                                    'blank_review', 'blank_note', 'blank_finding', 'missing_lesson', 'fingerprint'])
def test_invalid_source_evidence_or_inventory_rejected(audit, defect):
    packet, course, value, ref = audit
    if defect == 'foreign_ref':
        value['findings'][0]['source_refs'] = ['foreign']
    elif defect == 'duplicate_ref':
        value['narrative_sources']['lesson'] = [ref, ref]
    elif defect == 'foreign_target':
        value['findings'][0]['target_id'] = 'foreign'
    elif defect == 'wrong_scope':
        value['findings'][0]['scope'] = 'question'
    elif defect == 'blank_review':
        value['source_review'] = ' '
    elif defect == 'blank_note':
        value['source_notes'][0]['note'] = ''
    elif defect == 'blank_finding':
        value['findings'][0]['correction'] = ' '
    elif defect == 'missing_lesson':
        value['narrative_sources'] = {}
    else:
        value['source_fingerprint'] = '0' * 64
    assert not matches_source_audit(value, source_audit_format(packet, course))
    with pytest.raises(ValueError, match='practical_source_audit_response_invalid'):
        validate_source_audit(value, packet, course)


def test_messages_include_only_keyed_answer_and_explanation_and_alias_round_trip(audit):
    packet, course, value, ref = audit
    view = PracticalModelView(packet)
    messages = source_audit_messages(packet, course, view)
    content = messages[1]['content']
    lessons = json.loads(content.split('LESSON_PROSE_JSON\n', 1)[1])
    lesson = scoped_course_view(packet, course)['lessons'][0]
    assert lessons == [{'id': 'lesson', 'title': lesson['title'], 'content': lesson['content'],
                        'answer_explanations': [{'question_id': q['id'], 'prompt': q['prompt'],
                            'correct_answer_text': q['choices'][q['correct_index']], 'explanation': q['explanation']}
                            for q in lesson['questions']]}]
    assert 'SOURCE_BLOCK SRC1' in content and ref not in content
    assert 'correct_index' not in content and 'choices' not in content
    unit_json = content.split('SOURCE_AUDIT_UNITS_JSON\n', 1)[1].split('\n\nLESSON_PROSE_JSON', 1)[0]
    assert json.loads(unit_json) == [{'unit_id': 'U1', 'source_refs': ['SRC1']}]
    assert all('source_refs' not in q for lesson_row in lessons for q in lesson_row['answer_explanations'])
    for q in lesson['questions']:
        for index, choice in enumerate(q['choices']):
            if index != q['correct_index']:
                assert choice not in json.dumps(lessons, ensure_ascii=False)
    encoded = view.encode(value)
    assert encoded['narrative_sources']['lesson'] == ['SRC1'] and view.decode(encoded) == value


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'foreign', 'blank_reason', 'no_lesson',
                                    'foreign_lesson', 'missing_finding', 'uncertain_finding', 'wrong_ref',
                                    'wrong_unit', 'wrong_units_fingerprint'])
def test_source_check_inventory_and_findings(audit, defect):
    packet, course, value, ref = audit
    row = value['source_checks'][0]
    if defect == 'missing':
        value['source_checks'] = []
    elif defect == 'duplicate':
        value['source_checks'].append(copy.deepcopy(row))
    elif defect == 'foreign':
        row['source_refs'] = ['foreign']
    elif defect == 'blank_reason':
        row['reason'] = '  '
    elif defect == 'no_lesson':
        row['lesson_ids'] = []
    elif defect == 'foreign_lesson':
        row['lesson_ids'] = ['foreign']
    elif defect == 'wrong_ref':
        row['source_refs'] = [ref, ref]
    elif defect == 'wrong_unit':
        row['unit_id'] = 'U2'
    elif defect == 'wrong_units_fingerprint':
        value['source_units_fingerprint'] = '0' * 64
    else:
        row['status'] = 'MISSING' if defect == 'missing_finding' else 'UNCERTAIN'
    assert not matches_source_audit(value, source_audit_format(packet, course))


@pytest.mark.parametrize(('status', 'scope'), [('MISSING', 'coverage'), ('UNCERTAIN', 'source')])
def test_source_check_requires_bound_finding(audit, status, scope):
    packet, course, value, ref = audit
    value['source_checks'][0].update(status=status, lesson_ids=[], reason='Specific issue')
    value['findings'] = [{'scope': scope, 'target_id': ref, 'source_refs': [ref],
                          'problem': 'Procedure omitted', 'expected_rule': 'Perform procedure',
                          'correction': 'Teach procedure'}]
    assert matches_source_audit(value, source_audit_format(packet, course))
    view = PracticalModelView(packet)
    assert view.decode(view.encode(value)) == value
    value['findings'][0]['source_refs'] = []
    assert not matches_source_audit(value, source_audit_format(packet, course))


def test_large_inventory_passes_actual_runner_schema_checker():
    from app.modules.ai.v3.practical_source_audit import _format
    sources = [f'SRC{i}' for i in range(1, 101)]
    lessons = [f'lesson{i}' for i in range(1, 101)]
    questions = [f'q{i}' for i in range(1, 101)]
    fmt = _format(sources, 'a' * 64, lessons, questions, [f'U{i}' for i in range(1, 101)], 'b' * 64)
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('source_audit_test_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(fmt) == fmt['json_schema']['schema']
    assert '$ref' not in json.dumps(fmt)


def test_question_finding_is_bound_to_actual_course_inventory(audit):
    packet, course, value, ref = audit
    qid = course['lessons'][0]['questions'][0]['id']
    value['findings'][0].update(scope='question', target_id=qid)
    assert matches_source_audit(value, source_audit_format(packet, course))
    assert validate_source_audit(value, packet, course) == value
    for target in ['foreign', 'lesson', ref]:
        value['findings'][0]['target_id'] = target
        assert not matches_source_audit(value, source_audit_format(packet, course))
    value['findings'][0]['target_id'] = qid
    altered = copy.deepcopy(course)
    altered['lessons'][0]['questions'][0]['id'] = 'new-question'
    with pytest.raises(ValueError, match='practical_source_audit_response_invalid'):
        validate_source_audit(value, packet, altered)


def test_ambiguous_question_identity_is_rejected(audit):
    packet, course, _, _ = audit
    course['lessons'][0]['questions'][0]['id'] = course['lessons'][0]['id']
    with pytest.raises(ValueError, match='practical_course_invalid'):
        source_audit_format(packet, course)


def test_actual_group_membership_is_bound_even_when_union_matches():
    from tests.unit.test_v3_practical_audit_units import packet_for
    packet = packet_for('# 1. First\n1. Parent\n1) Child\n2) Other child\n'
                        '# 2. Second\n2. Other\n')
    grouping = audit_units(packet)
    assert len(grouping.groups) >= 2 and any(len(refs) > 1 for _, refs in grouping.groups)
    ref = packet.blocks[0].block_id
    course = {'title': 'Course', 'lessons': [{'id': 'lesson', 'title': 'Lesson', 'content': 'Text',
        'questions': [{'id': 'q', 'prompt': 'Question?', 'choices': ['A', 'B', 'C'],
                       'correct_index': 0, 'explanation': 'Reason', 'source_refs': [ref]}]}]}
    value = {'source_fingerprint': packet.fingerprint, 'source_units_fingerprint': grouping.fingerprint,
             'source_review': 'Reviewed', 'source_notes': [], 'narrative_sources': {'lesson': [ref]},
             'findings': [], 'source_checks': [
                 {'unit_id': name, 'source_refs': list(refs), 'status': 'TAUGHT',
                  'lesson_ids': ['lesson'], 'reason': 'Covered'} for name, refs in grouping.groups]}
    fmt = source_audit_format(packet, course)
    assert validate_source_audit(value, packet, course) == value
    rows = value['source_checks']
    rows[0]['source_refs'][0], rows[1]['source_refs'][0] = rows[1]['source_refs'][0], rows[0]['source_refs'][0]
    assert matches_source_audit(value, fmt)  # Shape and union cannot prove group membership.
    with pytest.raises(ValueError, match='practical_source_audit_response_invalid'):
        validate_source_audit(value, packet, course)
    rows[0]['source_refs'][0], rows[1]['source_refs'][0] = rows[1]['source_refs'][0], rows[0]['source_refs'][0]
    row = next(row for row in rows if len(row['source_refs']) > 1)
    target = row['source_refs'][-1]
    row.update(status='MISSING', lesson_ids=[], reason='Part omitted')
    value['findings'] = [{'scope': 'coverage', 'target_id': target, 'source_refs': [target],
                          'problem': 'Missing procedure', 'expected_rule': 'Perform it', 'correction': 'Teach it'}]
    assert validate_source_audit(value, packet, course) == value
    row['source_refs'].reverse()
    assert matches_source_audit(value, fmt)
    with pytest.raises(ValueError, match='practical_source_audit_response_invalid'):
        validate_source_audit(value, packet, course)
