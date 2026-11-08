import copy

import pytest

from app.modules.ai.v3.practical_compact_editorial_contract import compile_compact_editorial_review
from app.modules.ai.v3.practical_compact_editorial_cycle import review_editorial_candidate
from app.modules.ai.v3.practical_editorial_proof_correction import correct_resolution_proofs
from app.modules.ai.v3.practical_editorial_verification import compile_editorial_verification
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_compact_editorial_contract import case as compact_case
from tests.unit.test_v3_compact_editorial_contract import response
from tests.unit.test_v3_editorial_verification import sample

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('old,new', [('FIXED', 'ALREADY_COVERED'), ('ALREADY_COVERED', 'FIXED')])
async def test_resolution_positive_equivalence_preserves_original_and_raw(case, old, new):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0].update(disposition=old, course_quote='invalid quote')
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    sibling = copy.deepcopy(compiled['resolutions'][1])
    async def call(_name, _group, _messages, _fmt, validate):
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0].update(disposition=new, course_quote=course['lessons'][0]['content'])
        validate(value)
        return value
    out = await correct_resolution_proofs(packet, course, prior, compiled, 'source', PracticalModelView(packet), call)
    assert out['resolutions'][0]['verified'] and out['resolutions'][0]['disposition'] == old
    assert out['resolutions'][1] == sibling
    assert out['raw_parts'][-1]['response']['resolutions'][0]['disposition'] == new


@pytest.mark.asyncio
async def test_equivalent_positive_does_not_validate_bad_literal(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0]['course_quote'] = 'bad quote'
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    async def call(_name, _group, _messages, _fmt, validate):
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0]['disposition'] = 'ALREADY_COVERED'
        validate(value)
        return value
    out = await correct_resolution_proofs(packet, course, prior, compiled, 'source', PracticalModelView(packet), call)
    assert not out['resolutions'][0]['verified']
    assert 'course_quote_invalid' in out['resolutions'][0]['verification_errors']


@pytest.mark.asyncio
@pytest.mark.parametrize('new', ['NOT_MATERIAL', 'NEEDS_REVISION', 'UNRESOLVED', 'SOURCE_AMBIGUITY'])
async def test_positive_to_distinct_verdict_is_rejected(case, new):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0]['course_quote'] = 'bad quote'
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    async def call(_name, _group, _messages, _fmt, _validate):
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0].update(disposition=new, source_question='What is the source rule?' if new == 'SOURCE_AMBIGUITY' else '')
        return value
    with pytest.raises(ValueError, match='disposition_changed'):
        await correct_resolution_proofs(packet, course, prior, compiled, 'source', PracticalModelView(packet), call)


@pytest.mark.asyncio
async def test_source_question_cannot_change_during_proof_repair(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0].update(disposition='SOURCE_AMBIGUITY', source_quote='bad',
                                 course_quote='', source_question='Which rule applies?')
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    async def call(_name, _group, _messages, _fmt, _validate):
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0].update(source_quote=packet.blocks[0].text, source_question='A different question?')
        return value
    with pytest.raises(ValueError, match='source_question_changed'):
        await correct_resolution_proofs(packet, course, prior, compiled, 'source', PracticalModelView(packet), call)


@pytest.mark.asyncio
async def test_rule_card_proof_correction_accepts_equivalent_positive_only():
    packet, course, reading = compact_case()
    raw = response(packet, course, reading)
    raw['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach this.')
    prior = compile_compact_editorial_review(raw, packet, course, reading)['review']['findings'][0]
    async def call(_name, group, messages, fmt, validate):
        value = response(packet, course, reading)
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        correction = 'PRIOR_RULE_CHECKS_UNVERIFIED_JSON' in messages[1]['content']
        if prose:
            if correction:
                value['source_rule_checks'] = value['source_rule_checks'][:1]
            else:
                value['source_rule_checks'][0]['lesson_quotes'] = []
            value['resolutions'] = [{'issue_id': prior['issue_id'],
                'disposition': 'ALREADY_COVERED' if correction else 'FIXED', 'reason': 'Current prose',
                'source_refs': [packet.blocks[0].block_id], 'source_quote': packet.blocks[0].text,
                'course_quote': course['lessons'][0]['content'], 'source_question': ''}]
        else:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
        validate(value)
        return value
    out = await review_editorial_candidate(packet, reading, course, 'source', PracticalModelView(packet), call,
        'Review', max_rules=128, prior=[prior], assessment_system='Assess', verification_guide='Verify')
    row = out['resolutions'][0]
    assert row['verified'] and row['disposition'] == 'FIXED'
    assert out['raw_parts'][0]['evidence_correction']['resolutions'][0]['disposition'] == 'ALREADY_COVERED'


@pytest.mark.asyncio
async def test_rule_card_proof_correction_cannot_replace_source_question():
    packet, course, reading = compact_case()
    raw = response(packet, course, reading)
    raw['source_rule_checks'][0].update(status='INCOMPLETE', correction='Teach this.')
    prior = compile_compact_editorial_review(raw, packet, course, reading)['review']['findings'][0]
    async def call(_name, _group, messages, fmt, validate):
        value = response(packet, course, reading)
        prose = fmt['json_schema']['name'].startswith('v3_practical_compact')
        correction = 'PRIOR_RULE_CHECKS_UNVERIFIED_JSON' in messages[1]['content']
        if prose:
            if correction:
                value['source_rule_checks'] = value['source_rule_checks'][:1]
            else:
                value['source_rule_checks'][0]['lesson_quotes'] = []
            value['resolutions'] = [{'issue_id': prior['issue_id'], 'disposition': 'SOURCE_AMBIGUITY',
                'reason': 'The source needs clarification.', 'source_refs': [packet.blocks[0].block_id],
                'source_quote': packet.blocks[0].text, 'course_quote': '',
                'source_question': 'Different source question?' if correction else 'Original source question?'}]
        else:
            value.pop('reading_fingerprint')
            value.pop('source_rule_checks')
        validate(value)
        return value
    out = await review_editorial_candidate(packet, reading, course, 'source', PracticalModelView(packet), call,
        'Review', max_rules=128, prior=[prior], assessment_system='Assess', verification_guide='Verify')
    row = out['resolutions'][0]
    assert not row['verified'] and row['source_question'] == 'Original source question?'
    assert out['raw_parts'][0]['evidence_correction']['resolutions'][0]['source_question'] == 'Different source question?'
    assert prior['issue_id'] in out['raw_parts'][0]['unverified_resolution_changes']
