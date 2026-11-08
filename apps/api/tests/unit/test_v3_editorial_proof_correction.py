import copy

import pytest

from app.modules.ai.v3.practical_editorial_proof_correction import correct_resolution_proofs
from app.modules.ai.v3.practical_editorial_verification import compile_editorial_verification
from app.modules.ai.v3.practical_model_view import PracticalModelView
from tests.unit.test_v3_editorial_verification import sample

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
async def test_repairs_only_bad_quote_and_retains_semantic_hold_and_extras(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0]['course_quote'] = 'invented quote'
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    compiled['resolutions'][0]['verification_errors'].append('current_rule_check_open')
    before = copy.deepcopy(compiled)
    calls = []

    async def call(name, group, messages, fmt, validator):
        calls.append((name, group))
        assert 'CURRENT_TEACHING_PROSE_JSON' in messages[1]['content']
        assert 'CURRENT_ASSESSMENT_TARGETS_JSON\n[]' in messages[1]['content']
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0]['course_quote'] = course['lessons'][0]['content']
        value['findings'][0]['problem'] = 'Proof-only extra'
        validator(value)
        return value

    out = await correct_resolution_proofs(packet, course, prior, compiled, 'SOURCE', PracticalModelView(packet), call)
    assert len(calls) == 1 and ':proof:' in calls[0][1]
    assert compiled == before and out['resolutions'][1] == before['resolutions'][1]
    assert out['resolutions'][0]['verification_errors'] == ['current_rule_check_open']
    assert not out['resolutions'][0]['verified']
    assert out['review'] == before['review']
    assert out['raw_parts'][-1]['unverified_proof_scope_extras']['findings'][0]['problem'] == 'Proof-only extra'


@pytest.mark.asyncio
async def test_valid_correction_closes_custody_without_editing_course(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0]['source_quote'] = 'bad quote'
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    before_course = copy.deepcopy(course)

    async def call(name, group, messages, fmt, validator):
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0]['source_quote'] = packet.blocks[0].text
        return value

    out = await correct_resolution_proofs(packet, course, prior, compiled, 'SOURCE', PracticalModelView(packet), call)
    assert out['resolutions'][0]['verified'] and course == before_course


@pytest.mark.asyncio
async def test_changed_disposition_rejected_and_unknown_never_retried(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0]['course_quote'] = 'bad quote'
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])
    calls = []

    async def changed(name, group, messages, fmt, validator):
        calls.append(group)
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0].update(disposition='NOT_MATERIAL', course_quote='')
        return value

    with pytest.raises(ValueError, match='disposition_changed'):
        await correct_resolution_proofs(packet, course, prior, compiled, 'SOURCE', PracticalModelView(packet), changed)
    assert len(calls) == 1

    async def unknown(name, group, messages, fmt, validator):
        calls.append(group)
        raise TimeoutError('unknown')

    with pytest.raises(TimeoutError):
        await correct_resolution_proofs(packet, course, prior, compiled, 'SOURCE', PracticalModelView(packet), unknown)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_missing_source_question_alone_is_not_repaired(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0].update(disposition='SOURCE_AMBIGUITY', source_question='')
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])

    async def forbidden(*args):
        raise AssertionError('must not call model')

    out = await correct_resolution_proofs(packet, course, prior, compiled, 'SOURCE', PracticalModelView(packet), forbidden)
    assert 'source_question_missing' in out['resolutions'][0]['verification_errors'] and not out['raw_parts']


@pytest.mark.asyncio
async def test_source_question_cannot_be_replaced_during_other_proof_correction(case):
    _, packet, course = case
    prior, raw = sample(packet, course)
    raw['resolutions'][0].update(disposition='SOURCE_AMBIGUITY', source_question='', source_quote='bad')
    compiled = compile_editorial_verification(raw, packet, course, prior)
    compiled.update(raw_parts=[], source_rule_checks=[])

    async def fabricate(name, group, messages, fmt, validator):
        value = copy.deepcopy(raw)
        value['resolutions'] = value['resolutions'][:1]
        value['resolutions'][0].update(source_quote=packet.blocks[0].text, source_question='Invented question?')
        return value

    with pytest.raises(ValueError, match='source_question_changed'):
        await correct_resolution_proofs(packet, course, prior, compiled, 'SOURCE', PracticalModelView(packet), fabricate)
