import copy

import pytest

from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_editorial_verification import (
    compile_editorial_verification,
    editorial_verification_format,
    is_editorial_verification_format,
    matches_editorial_verification,
)
from tests.unit.test_v3_editorial_contract import review_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def sample(packet, course):
    raw = review_value(packet, course, kind='lesson', target='l1', domain='content')
    second = copy.deepcopy(raw['findings'][0])
    second['problem'] = 'A separate observation.'
    raw['findings'].append(second)
    findings = compile_editorial_review(raw, packet, course)['findings']
    rows = [{'issue_id': finding['issue_id'], 'disposition': 'FIXED', 'reason': 'Reviewed',
             'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
             'course_quote': course['lessons'][0]['content'], 'source_question': ''}
            for finding in findings]
    return findings, {**review_value(packet, course), 'resolutions': rows}


def test_valid_sibling_survives_bad_source_evidence(case):
    _, packet, course = case
    findings, value = sample(packet, course)
    value['resolutions'][1]['source_quote'] = 'not present in the source'
    fmt = editorial_verification_format(packet, course, findings)
    assert is_editorial_verification_format(fmt) and matches_editorial_verification(value, fmt)
    result = compile_editorial_verification(value, packet, course, findings)
    assert result['resolutions'][0]['verified'] is True
    assert result['resolutions'][1]['verified'] is False
    assert 'source_quote_invalid' in result['resolutions'][1]['verification_errors']


@pytest.mark.parametrize('fault', ['fingerprint', 'duplicate', 'missing', 'foreign'])
def test_stale_or_invalid_identity_fails_closed(case, fault):
    _, packet, course = case
    findings, value = sample(packet, course)
    if fault == 'fingerprint':
        value['course_fingerprint'] = 'stale'
    elif fault == 'duplicate':
        value['resolutions'][1]['issue_id'] = value['resolutions'][0]['issue_id']
    elif fault == 'missing':
        value['resolutions'].pop()
    else:
        value['resolutions'][0]['issue_id'] = 'foreign'
    with pytest.raises(ValueError, match='editorial_verification_response_invalid'):
        compile_editorial_verification(value, packet, course, findings)


def test_quiz_text_cannot_prove_lesson_prose(case):
    _, packet, course = case
    findings, value = sample(packet, course)
    value['resolutions'][0]['course_quote'] = course['lessons'][0]['questions'][0]['prompt']
    assert value['resolutions'][0]['course_quote'] not in course['lessons'][0]['content']
    result = compile_editorial_verification(value, packet, course, findings)
    assert 'course_quote_invalid' in result['resolutions'][0]['verification_errors']


@pytest.mark.parametrize('kind,target', [('lesson', 'l1'), ('course', 'course')])
def test_assessment_coverage_needs_quiz_evidence_instead_of_teaching_prose(case, kind, target):
    _, packet, course = case
    raw = review_value(packet, course, kind=kind, target=target, domain='assessment')
    findings = compile_editorial_review(raw, packet, course)['findings']
    _, value = sample(packet, course)
    value['findings'] = []
    value['resolutions'] = value['resolutions'][:1]
    value['resolutions'][0]['issue_id'] = findings[0]['issue_id']
    value['resolutions'][0]['course_quote'] = course['lessons'][0]['content']
    result = compile_editorial_verification(value, packet, course, findings)
    assert 'course_quote_invalid' in result['resolutions'][0]['verification_errors']
    value['resolutions'][0]['course_quote'] = course['lessons'][0]['questions'][0]['prompt']
    assert compile_editorial_verification(value, packet, course, findings)['resolutions'][0]['verified']


def test_ambiguity_retains_question_and_requires_evidence(case):
    _, packet, course = case
    findings, value = sample(packet, course)
    row = value['resolutions'][0]
    row.update(disposition='SOURCE_AMBIGUITY', course_quote='', source_question='Which rule applies?')
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert result['verified'] and result['source_question'] == 'Which rule applies?'
    row['source_question'] = ''
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert not result['verified'] and 'source_question_missing' in result['verification_errors']


def test_question_evidence_and_nonmaterial_do_not_require_lesson_quote(case):
    _, packet, course = case
    raw = review_value(packet, course)
    findings = compile_editorial_review(raw, packet, course)['findings']
    _, value = sample(packet, course)
    value['resolutions'] = value['resolutions'][:1]
    row = value['resolutions'][0]
    row['issue_id'] = findings[0]['issue_id']
    row['course_quote'] = course['lessons'][0]['questions'][0]['explanation']
    assert compile_editorial_verification(value, packet, course, findings)['resolutions'][0]['verified']
    row.update(disposition='NOT_MATERIAL', course_quote='')
    assert compile_editorial_verification(value, packet, course, findings)['resolutions'][0]['verified']
    row['disposition'] = 'UNRESOLVED'
    assert not compile_editorial_verification(value, packet, course, findings)['resolutions'][0]['verified']


@pytest.mark.parametrize('disposition', ['FIXED', 'ALREADY_COVERED'])
def test_source_issue_cannot_be_fixed_by_course(case, disposition):
    _, packet, course = case
    raw = review_value(packet, course, kind='lesson', target='l1', domain='source')
    findings = compile_editorial_review(raw, packet, course)['findings']
    _, value = sample(packet, course)
    value['resolutions'] = value['resolutions'][:1]
    value['resolutions'][0]['issue_id'] = findings[0]['issue_id']
    value['resolutions'][0]['disposition'] = disposition
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert 'source_finding_cannot_be_fixed_by_course' in result['verification_errors']


def test_source_false_positive_dismissal_and_question_custody(case):
    _, packet, course = case
    raw = review_value(packet, course, kind='lesson', target='l1', domain='source')
    findings = compile_editorial_review(raw, packet, course)['findings']
    _, value = sample(packet, course)
    value['resolutions'] = value['resolutions'][:1]
    value['resolutions'][0].update(issue_id=findings[0]['issue_id'], disposition='NOT_MATERIAL',
                                   course_quote='', source_question='Should not be exposed?')
    row = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert row['verified'] and row['source_question'] == ''


@pytest.mark.parametrize('kind,target,domain', [('lesson', 'l1', 'content'), ('question', 'q1', 'assessment')])
def test_needs_revision_confirms_material_issue_without_closing_or_source_question(case, kind, target, domain):
    _, packet, course = case
    findings = compile_editorial_review(review_value(packet, course, kind=kind, target=target, domain=domain), packet, course)['findings']
    _, value = sample(packet, course)
    value['resolutions'] = value['resolutions'][:1]
    value['resolutions'][0].update(issue_id=findings[0]['issue_id'], disposition='NEEDS_REVISION',
                                   course_quote=(course['lessons'][0]['questions'][0]['prompt'] if kind == 'question' else ''),
                                   source_question='Not an owner question')
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert result['verified'] and result['disposition'] == 'NEEDS_REVISION'
    assert result['source_question'] == ''


def test_needs_revision_cannot_authorize_source_change_and_requires_source_evidence(case):
    _, packet, course = case
    findings = compile_editorial_review(review_value(packet, course, kind='lesson', target='l1', domain='source'), packet, course)['findings']
    _, value = sample(packet, course)
    value['resolutions'] = value['resolutions'][:1]
    value['resolutions'][0].update(issue_id=findings[0]['issue_id'], disposition='NEEDS_REVISION', course_quote='')
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert not result['verified']
    findings[0]['domain'] = 'content'
    value['resolutions'][0]['source_quote'] = 'not in source'
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert not result['verified'] and 'source_quote_invalid' in result['verification_errors']


def test_needs_revision_does_not_authorize_foreign_current_target(case):
    _, packet, course = case
    findings, value = sample(packet, course)
    findings[0]['target'] = {'kind': 'lesson', 'id': 'foreign-lesson'}
    value['resolutions'][0].update(disposition='NEEDS_REVISION', course_quote='')
    result = compile_editorial_verification(value, packet, course, findings)['resolutions'][0]
    assert not result['verified'] and 'current_target_invalid' in result['verification_errors']
