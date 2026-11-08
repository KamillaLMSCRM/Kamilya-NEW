"""Physical prose/quiz separation and lossless current-revision issue routing."""

import copy
import json

import pytest

from app.modules.ai.v3.practical_compact_editorial_contract import compile_compact_editorial_review
from app.modules.ai.v3.practical_compact_editorial_cycle import review_editorial_candidate
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_compact_editorial_contract import case, response
from tests.unit.test_v3_editorial_contract import review_value


@pytest.mark.asyncio
async def test_quiz_facts_are_physically_absent_from_prose_check_and_cannot_replace_coverage():
    packet, course, reading = case()
    course['lessons'][0]['questions'][0].update(prompt='QA_ONLY_PROMPT', explanation='QA_ONLY_EXPLANATION')
    calls = []

    async def call(name, group, messages, fmt, validate):
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        calls.append(prose)
        value = response(packet, course, reading)
        if prose:
            assert 'QA_ONLY_PROMPT' not in messages[1]['content']
            assert 'QA_ONLY_EXPLANATION' not in messages[1]['content']
            assert course['lessons'][0]['content'] in messages[1]['content']
            value['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach the missing action.')
        else:
            assert 'QA_ONLY_PROMPT' in messages[1]['content'] and 'correct_index' in messages[1]['content']
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
            value['narrative_sources'] = {'l1': [packet.blocks[-1].block_id]}
        validate(value)
        return value

    result = await review_editorial_candidate(packet, reading, course, 'Full original source', PracticalModelView(packet),
        call, 'Review prose', max_rules=128, assessment_system='Review tests', verification_guide='Verify current')
    assert calls == [True, False]
    assert result['source_rule_checks'][0]['status'] == 'INCOMPLETE'
    assert any(row.get('source_rule_id') == 'R1' for row in result['review']['findings'])
    assert result['review']['narrative_sources']['l1'] == [packet.blocks[0].block_id]


@pytest.mark.asyncio
async def test_each_domain_gets_its_prior_issues_and_bad_proof_is_corrected_without_losing_sibling():
    packet, course, reading = case()
    bad = response(packet, course, reading)
    bad['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach the action.')
    content_issue = compile_compact_editorial_review(bad, packet, course, reading)['review']['findings'][0]
    assessment_issue = compile_editorial_review(review_value(packet, course), packet, course)['findings'][0]
    assignments = []

    async def call(name, group, messages, fmt, validate):
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        proof = ':proof:' in group
        prior = json.loads(messages[1]['content'].split('\nPRIOR_MATERIAL_FINDINGS_JSON\n')[1].split('\n', 1)[0])
        assignments.append({row['issue_id'] for row in prior})
        expected = content_issue if prose or proof else assessment_issue
        assert assignments[-1] == {expected['issue_id']}
        value = response(packet, course, reading)
        if not prose:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
        value['resolutions'] = [{'issue_id': expected['issue_id'], 'disposition': 'FIXED', 'reason': 'Current evidence',
            'source_refs': [packet.blocks[0].block_id],
            'source_quote': 'not in the source' if prose else packet.blocks[0].text,
            'course_quote': course['lessons'][0]['content'] if prose or proof else course['lessons'][0]['questions'][0]['prompt'],
            'source_question': ''}]
        validate(value)
        return value

    result = await review_editorial_candidate(packet, reading, course, 'Full original source', PracticalModelView(packet),
        call, 'Review prose', max_rules=128, prior=copy.deepcopy([content_issue, assessment_issue]),
        assessment_system='Review tests', verification_guide='Verify current')
    resolutions = {row['issue_id']: row for row in result['resolutions']}
    assert resolutions[content_issue['issue_id']]['verified']
    assert resolutions[assessment_issue['issue_id']]['verified']
    assert len(resolutions) == 2
    assert len(assignments) == 3


@pytest.mark.asyncio
async def test_prose_proof_correction_cannot_authorize_edits_to_unseen_questions():
    packet, course, reading = case()
    calls = []

    async def call(name, group, messages, fmt, validate):
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        correction = 'PRIOR_RULE_CHECKS_UNVERIFIED_JSON' in messages[1]['content']
        calls.append((prose, correction))
        value = response(packet, course, reading)
        if prose and not correction:
            value['source_rule_checks'][0]['lesson_quotes'] = []
        elif prose:
            value['source_rule_checks'] = value['source_rule_checks'][:1]
            value['findings'] = review_value(packet, course)['findings']
        else:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
        validate(value)
        return value

    result = await review_editorial_candidate(packet, reading, course, 'Full original source', PracticalModelView(packet),
        call, 'Review prose', max_rules=128, assessment_system='Review tests', verification_guide='Verify current')
    assert calls == [(True, False), (True, True), (False, False)]
    question_issue = next(row for row in result['review']['findings'] if row['target']['kind'] == 'question')
    assert question_issue['rule_check_unverified']
    assert question_issue['out_of_scope_review'] == 'PROSE_ONLY_STAGE'


def test_review_instruction_has_no_decoding_replacement_characters():
    import inspect

    from app.modules.ai.v3 import practical_compact_editorial_cycle
    assert '\ufffd' not in inspect.getsource(practical_compact_editorial_cycle)


@pytest.mark.asyncio
async def test_evidence_correction_cannot_erase_unverified_negative_allegation():
    packet, course, reading = case()
    calls = []

    async def call(name, group, messages, fmt, validate):
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        correction = 'PRIOR_RULE_CHECKS_UNVERIFIED_JSON' in messages[1]['content']
        calls.append((prose, correction))
        value = response(packet, course, reading)
        if prose and not correction:
            value['source_rule_checks'][0].update(
                status='INCOMPLETE', reason='A material action is absent.', correction='Teach the action.',
                lesson_quotes=[{'lesson_id': 'l1', 'quote': 'not in the lesson'}])
        elif prose:
            value['source_rule_checks'] = value['source_rule_checks'][:1]
            # A corrected technical quote cannot silently adjudicate away the
            # earlier model's substantive allegation.
            value['source_rule_checks'][0].update(status='SUPPORTED', correction='')
        else:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
        validate(value)
        return value

    result = await review_editorial_candidate(packet, reading, course, 'Full original source', PracticalModelView(packet),
        call, 'Review prose', max_rules=128, assessment_system='Review tests', verification_guide='Verify current')
    assert calls == [(True, False), (True, True), (False, False)]
    assert result['raw_parts'][0]['response']['source_rule_checks'][0]['status'] == 'INCOMPLETE'
    assert result['raw_parts'][0]['evidence_correction']['source_rule_checks'][0]['status'] == 'SUPPORTED'
    sibling = next(row for row in result['source_rule_checks'] if row['rule_id'] == 'R2')
    assert sibling['status'] == 'SUPPORTED' and sibling['verified']
    hold = next((row for row in result['review']['findings']
                 if row.get('source_rule_id') == 'R1' and row.get('rule_check_unverified')), None)
    assert hold is not None and 'material action is absent' in hold['basis']

@pytest.mark.asyncio
@pytest.mark.parametrize('new_disposition', ['NEEDS_REVISION', 'FIXED', 'NOT_MATERIAL'])
async def test_card_proof_repair_cannot_change_unresolved_verdict(new_disposition):
    packet, course, reading = case()
    original = response(packet, course, reading)
    original['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach the missing action.')
    prior = compile_compact_editorial_review(original, packet, course, reading)['review']['findings'][0]
    calls = []

    async def call(name, group, messages, fmt, validate):
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        correction = 'PRIOR_RULE_CHECKS_UNVERIFIED_JSON' in messages[1]['content']
        calls.append((prose, correction))
        value = response(packet, course, reading)
        if prose:
            value['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach the missing action.',
                lesson_quotes=[{'lesson_id': 'l1', 'quote': 'not in the lesson'}] if not correction else [])
            if correction:
                value['source_rule_checks'] = value['source_rule_checks'][:1]
            value['resolutions'] = [{'issue_id': prior['issue_id'],
                'disposition': new_disposition if correction else 'UNRESOLVED', 'reason': 'Needs further review',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': 'credit for personal use',
                'course_quote': '', 'source_question': ''}]
        else:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
        validate(value)
        return value

    result = await review_editorial_candidate(packet, reading, course, 'Full original source', PracticalModelView(packet),
        call, 'Review prose', max_rules=128, prior=[prior], assessment_system='Review tests', verification_guide='Verify')
    assert calls == [(True, False), (True, True), (False, False)]
    row = next(row for row in result['resolutions'] if row['issue_id'] == prior['issue_id'])
    assert row['disposition'] == 'UNRESOLVED'
    assert result['raw_parts'][0]['response']['resolutions'][0]['disposition'] == 'UNRESOLVED'
    assert result['raw_parts'][0]['evidence_correction']['resolutions'][0]['disposition'] == new_disposition
    assert any(f.get('source_rule_id') == 'R1' for f in result['review']['findings'])
