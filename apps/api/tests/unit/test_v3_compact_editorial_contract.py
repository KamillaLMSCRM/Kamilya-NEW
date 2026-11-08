import copy

import pytest

from app.modules.ai.v3.practical_compact_editorial_contract import (
    compact_editorial_review_format,
    compact_editorial_verification_format,
    compile_compact_editorial_review,
    compile_compact_editorial_verification,
    is_compact_editorial_review_format,
    is_compact_editorial_verification_format,
    matches_compact_editorial_review,
)
from app.modules.ai.v3.practical_contract import _digest
from tests.unit.test_v3_rule_editorial_contract import case


def response(packet, course, reading):
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
        'reading_fingerprint': reading['verified_reading_fingerprint'], 'summary': 'Reviewed',
        'findings': [], 'source_notes': [], 'narrative_sources': {'l1': [packet.blocks[0].block_id]},
        'source_rule_checks': [{'rule_id': f'R{i}', 'status': 'SUPPORTED',
            'lesson_ids': ['l1'],
            'lesson_quotes': [{'lesson_id': 'l1', 'quote': 'credit for personal use'}],
            'reason': 'Model compared the teaching and rule.', 'correction': '', 'severity': 'material'} for i in (1, 2)]}


def test_bound_review_and_literal_positive_prose():
    packet, course, reading = case()
    value = response(packet, course, reading)
    fmt = compact_editorial_review_format(packet, course, reading)
    assert is_compact_editorial_review_format(fmt) and matches_compact_editorial_review(value, fmt)
    stale = copy.deepcopy(fmt)
    stale['json_schema']['name'] = 'v3_practical_compact_editorial_review_v1'
    assert not is_compact_editorial_review_format(stale)
    checks = compile_compact_editorial_review(value, packet, course, reading)['source_rule_checks']
    assert all(row['verified'] and row['lesson_ids'] == ['l1'] for row in checks)
    from app.modules.ai.v3.practical_model_view import PracticalModelView
    view = PracticalModelView(packet)
    assert matches_compact_editorial_review(view.encode(value), view.schema(fmt))
    assert compile_compact_editorial_review(view.decode(view.encode(value)), packet, course, reading)


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'foreign_rule', 'wrong_source', 'wrong_reading', 'wrong_course', 'foreign_refs'])
def test_wrong_identity_fails_closed(fault):
    packet, course, reading = case()
    value = response(packet, course, reading)
    if fault == 'missing':
        value['source_rule_checks'].pop()
    elif fault == 'duplicate':
        value['source_rule_checks'][1]['rule_id'] = 'R1'
    elif fault == 'foreign_rule':
        value['source_rule_checks'][0]['rule_id'] = 'R3'
    elif fault == 'wrong_source':
        value['source_fingerprint'] = 'a' * 64
    elif fault == 'wrong_reading':
        value['reading_fingerprint'] = 'a' * 64
    elif fault == 'wrong_course':
        value['course_fingerprint'] = 'a' * 64
    else:
        value['narrative_sources']['l1'] = ['foreign']
    with pytest.raises(ValueError):
        compile_compact_editorial_review(value, packet, course, reading)


def test_empty_supported_and_disputed_reading_are_technical_holds():
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][0]['lesson_quotes'] = []
    value['source_rule_checks'][1].update(status='SOURCE_READING_DISPUTED', correction='Check the source.')
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert all(not row['verified'] for row in out['source_rule_checks'])
    assert all(row['domain'] == 'content' and row['rule_check_unverified'] for row in out['review']['findings'])


@pytest.mark.parametrize('kind', ['question_only', 'foreign_lesson'])
def test_bad_positive_evidence_is_a_row_hold_without_losing_siblings(kind):
    packet, course, reading = case()
    value = response(packet, course, reading)
    quote = value['source_rule_checks'][0]['lesson_quotes'][0]
    if kind == 'question_only':
        quote['quote'] = 'manager checks records'
    else:
        quote['lesson_id'] = 'foreign'
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert not out['source_rule_checks'][0]['verified'] and out['source_rule_checks'][1]['verified']
    assert ('lesson_quote_invalid' if kind == 'question_only' else 'lesson_id_invalid') in out['source_rule_checks'][0]['verification_errors']
    assert out['review']['findings'][0]['target']['id'] != 'foreign'


def test_negative_missing_quote_requires_an_explicit_owned_target():
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][0].update(status='INCOMPLETE', lesson_quotes=[], correction='Teach the condition.')
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert out['source_rule_checks'][0]['verified']
    assert out['review']['findings'][0]['target'] == {'kind': 'lesson', 'id': 'l1'}
    value['source_rule_checks'][0]['lesson_ids'] = []
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert not out['source_rule_checks'][0]['verified']
    assert 'lesson_target_missing' in out['source_rule_checks'][0]['verification_errors']
    assert out['review']['findings'][0]['rule_check_unverified']


def test_negative_without_quote_targets_actual_second_lesson():
    packet, course, reading = case()
    second = copy.deepcopy(course['lessons'][0])
    second.update(id='l2', title='Second', content='Other lesson prose.')
    second['questions'][0]['id'] = 'q2'
    course['lessons'].append(second)
    value = response(packet, course, reading)
    value['course_fingerprint'] = _digest(course)
    value['narrative_sources']['l2'] = [packet.blocks[0].block_id]
    value['source_rule_checks'][0].update(status='INCOMPLETE', lesson_ids=['l2'], lesson_quotes=[],
                                         correction='Teach the missing action.')
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert out['source_rule_checks'][0]['verified']
    assert out['review']['findings'][0]['target'] == {'kind': 'lesson', 'id': 'l2'}


def test_positive_quote_must_match_listed_target():
    packet, course, reading = case()
    second = copy.deepcopy(course['lessons'][0])
    second.update(id='l2', title='Second')
    second['questions'][0]['id'] = 'q2'
    course['lessons'].append(second)
    value = response(packet, course, reading)
    value['course_fingerprint'] = _digest(course)
    value['narrative_sources']['l2'] = [packet.blocks[0].block_id]
    value['source_rule_checks'][0]['lesson_quotes'][0]['lesson_id'] = 'l2'
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert not out['source_rule_checks'][0]['verified']
    assert 'lesson_quote_target_mismatch' in out['source_rule_checks'][0]['verification_errors']
    assert 'lesson_quote_missing_for_target' in out['source_rule_checks'][0]['verification_errors']


def test_foreign_negative_target_is_never_an_edit_target():
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][0].update(status='INCOMPLETE', lesson_ids=['foreign'], lesson_quotes=[],
                                         correction='Add the missing action.')
    out = compile_compact_editorial_review(value, packet, course, reading)
    assert 'lesson_id_invalid' in out['source_rule_checks'][0]['verification_errors']
    assert out['review']['findings'][0]['target'] == {'kind': 'course', 'id': 'course'}
    assert out['review']['findings'][0]['rule_check_unverified']


def test_contradiction_blocks_old_resolution_and_strict_literal_closure():
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][0].update(status='CONTRADICTED', correction='Correct the condition.')
    finding = compile_compact_editorial_review(value, packet, course, reading)['review']['findings'][0]
    value['resolutions'] = [{'issue_id': finding['issue_id'], 'disposition': 'FIXED', 'reason': 'Rechecked',
        'source_refs': [packet.blocks[0].block_id], 'source_quote': 'credit for personal use',
        'course_quote': 'credit for personal use', 'source_question': ''}]
    fmt = compact_editorial_verification_format(packet, course, reading, [finding])
    assert is_compact_editorial_verification_format(fmt)
    out = compile_compact_editorial_verification(value, packet, course, reading, [finding])
    assert not out['resolutions'][0]['verified'] and 'current_rule_check_open' in out['resolutions'][0]['verification_errors']
    value['source_rule_checks'][0].update(status='SUPPORTED', correction='')
    value['resolutions'][0]['course_quote'] = 'manager checks records'  # question-only text
    out = compile_compact_editorial_verification(value, packet, course, reading, [finding])
    assert 'course_quote_invalid' in out['resolutions'][0]['verification_errors']
    value['resolutions'][0]['course_quote'] = 'credit for personal use'
    assert compile_compact_editorial_verification(value, packet, course, reading, [finding])['resolutions'][0]['verified']


def test_outside_subset_cannot_close_and_source_ambiguity_needs_question():
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][1].update(status='INCOMPLETE', correction='Add the condition.')
    finding = compile_compact_editorial_review(value, packet, course, reading)['review']['findings'][0]
    value['source_rule_checks'] = value['source_rule_checks'][:1]
    value['resolutions'] = [{'issue_id': finding['issue_id'], 'disposition': 'FIXED', 'reason': 'Reviewed',
        'source_refs': [packet.blocks[0].block_id], 'source_quote': 'credit for personal use',
        'course_quote': 'credit for personal use', 'source_question': ''}]
    out = compile_compact_editorial_verification(value, packet, course, reading, [finding], rule_ids=['R1'])
    assert 'current_rule_not_checked_in_subset' in out['resolutions'][0]['verification_errors']
    source = {**copy.deepcopy(finding), 'issue_id': 'source-issue', 'domain': 'source',
              'target': {'kind': 'source', 'id': packet.blocks[0].block_id}}
    source.pop('source_rule_id')
    value['resolutions'][0].update(issue_id='source-issue', disposition='SOURCE_AMBIGUITY', source_question='')
    assert not compile_compact_editorial_verification(value, packet, course, reading, [source], rule_ids=['R1'])['resolutions'][0]['verified']
    value['resolutions'][0]['source_question'] = 'Which condition applies?'
    out = compile_compact_editorial_verification(value, packet, course, reading, [source], rule_ids=['R1'])
    assert out['resolutions'][0]['verified'] and out['resolutions'][0]['source_question']


def test_bad_resolution_source_quote_does_not_discard_valid_sibling():
    packet, course, reading = case()
    value = response(packet, course, reading)
    for row in value['source_rule_checks']:
        row.update(status='CONTRADICTED', correction='Fix the rule.')
    findings = compile_compact_editorial_review(value, packet, course, reading)['review']['findings']
    for row in value['source_rule_checks']:
        row.update(status='SUPPORTED', correction='')
    value['resolutions'] = [{'issue_id': f['issue_id'], 'disposition': 'FIXED', 'reason': 'Reviewed',
        'source_refs': [packet.blocks[0].block_id], 'source_quote': 'credit for personal use',
        'course_quote': 'credit for personal use', 'source_question': ''} for f in findings]
    value['resolutions'][1]['source_quote'] = 'not present in source'
    rows = compile_compact_editorial_verification(value, packet, course, reading, findings)['resolutions']
    assert rows[0]['verified'] and not rows[1]['verified']
    assert 'source_quote_invalid' in rows[1]['verification_errors']

@pytest.mark.parametrize('severity,expected', [('advisory', True), ('material', False)])
def test_not_material_requires_current_negative_to_be_advisory(severity, expected):
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][0].update(status='INCOMPLETE', correction='Check the action.')
    finding = compile_compact_editorial_review(value, packet, course, reading)['review']['findings'][0]
    value['source_rule_checks'][0]['severity'] = severity
    value['resolutions'] = [{'issue_id': finding['issue_id'], 'disposition': 'NOT_MATERIAL',
        'reason': 'Current omission assessed', 'source_refs': [packet.blocks[0].block_id],
        'source_quote': 'credit for personal use', 'course_quote': '', 'source_question': ''}]
    out = compile_compact_editorial_verification(value, packet, course, reading, [finding])
    assert out['resolutions'][0]['verified'] is expected
    assert out['source_rule_checks'][0]['verified']
    if not expected:
        assert 'current_rule_check_open' in out['resolutions'][0]['verification_errors']


@pytest.mark.parametrize('status,severity,invalid,expected', [
    ('INCOMPLETE', 'material', False, True),
    ('CONTRADICTED', 'material', False, True),
    ('SUPPORTED', 'material', False, False),
    ('INCOMPLETE', 'advisory', False, False),
    ('SOURCE_READING_DISPUTED', 'material', False, False),
    ('INCOMPLETE', 'material', True, False),
])
def test_needs_revision_requires_verified_current_material_negative(status, severity, invalid, expected):
    packet, course, reading = case()
    value = response(packet, course, reading)
    value['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach the action.')
    finding = compile_compact_editorial_review(value, packet, course, reading)['review']['findings'][0]
    card = value['source_rule_checks'][0]
    card.update(status=status, severity=severity, correction='' if status == 'SUPPORTED' else 'Check the action.')
    if invalid:
        card['lesson_quotes'] = [{'lesson_id': 'l1', 'quote': 'not in prose'}]
    value['resolutions'] = [{'issue_id': finding['issue_id'], 'disposition': 'NEEDS_REVISION',
        'reason': 'Action needed', 'source_refs': [packet.blocks[0].block_id],
        'source_quote': 'credit for personal use', 'course_quote': '', 'source_question': ''}]
    out = compile_compact_editorial_verification(value, packet, course, reading, [finding])
    assert out['resolutions'][0]['verified'] is expected
    assert out['resolutions'][0]['disposition'] == 'NEEDS_REVISION'
    if not expected:
        assert 'current_rule_check_open' in out['resolutions'][0]['verification_errors']
