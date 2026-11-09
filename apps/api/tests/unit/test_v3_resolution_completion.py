import copy

import pytest

from app.modules.ai.v3.practical_editorial_verification import (
    compile_editorial_verification,
    editorial_verification_format,
    matches_editorial_verification,
    matches_editorial_verification_shape,
)
from app.modules.ai.v3.practical_resolution_completion import complete_editorial_resolutions
from app.modules.ai.v3.response_contracts import matches_transport_contract
from tests.unit.test_v3_editorial_verification import sample

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def partial_case(case):
    _, packet, course = case
    findings, full = sample(packet, course)
    partial = copy.deepcopy(full)
    partial['resolutions'].pop()
    return packet, course, findings, full, partial, editorial_verification_format(packet, course, findings)


def test_partial_known_inventory_is_transport_only_and_cannot_pass_semantic_compiler(case):
    packet, course, findings, _, partial, fmt = partial_case(case)
    assert matches_editorial_verification_shape(partial, fmt)
    assert matches_transport_contract(partial, fmt)
    assert not matches_editorial_verification(partial, fmt)
    with pytest.raises(ValueError, match='editorial_verification_response_invalid'):
        compile_editorial_verification(partial, packet, course, findings)


@pytest.mark.parametrize('fault', ['duplicate', 'foreign', 'fingerprint', 'extra', 'disposition'])
def test_transport_still_rejects_invalid_owned_shape(case, fault):
    _, _, _, _, partial, fmt = partial_case(case)
    if fault == 'duplicate':
        partial['resolutions'].append(copy.deepcopy(partial['resolutions'][0]))
    elif fault == 'foreign':
        partial['resolutions'][0]['issue_id'] = 'foreign'
    elif fault == 'fingerprint':
        partial['course_fingerprint'] = 'foreign'
    elif fault == 'extra':
        partial['ignored'] = True
    else:
        partial['resolutions'][0]['disposition'] = 'ACCEPT'
    assert not matches_transport_contract(partial, fmt)


@pytest.mark.asyncio
async def test_one_addressed_model_completion_preserves_every_existing_decision_and_finding(case):
    packet, course, findings, full, partial, fmt = partial_case(case)
    before = copy.deepcopy(partial)
    messages = [{'role': 'system', 'content': 'Existing joint editor'}, {'role': 'user', 'content': 'Current owned source/course'}]
    seen = []

    async def complete(group, request, missing_format, validate):
        missing = missing_format['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum']
        assert missing == [findings[1]['issue_id']]
        assert request[:2] == messages
        assert 'MISSING_RESOLUTION_IDS_JSON' in request[-1]['content']
        value = {**copy.deepcopy(full), 'resolutions': [copy.deepcopy(full['resolutions'][1])]}
        value['findings'][0]['problem'] = 'A new current material issue from completion'
        seen.append(group)
        validate(value)
        return value

    merged, audit = await complete_editorial_resolutions(partial, fmt, messages, complete)
    assert len(seen) == 1 and 'verify:v34:complete-resolutions:' in seen[0]
    assert partial == before
    assert merged['resolutions'][0] == partial['resolutions'][0]
    assert merged['findings'][0] == partial['findings'][0]
    assert len(merged['findings']) == 2
    assert audit['requested_issue_ids'] == [findings[1]['issue_id']]
    assert audit['retained_issue_ids'] == [findings[0]['issue_id']]
    assert matches_editorial_verification(merged, fmt)
    result = compile_editorial_verification(merged, packet, course, findings)
    assert len(result['review']['findings']) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['missing_again', 'rewrite_existing', 'timeout'])
async def test_completion_never_retries_or_overwrites_a_completed_decision(case, fault):
    _, _, _, full, partial, fmt = partial_case(case)
    seen = []

    async def complete(group, request, missing_format, validate):
        seen.append(group)
        if fault == 'timeout':
            raise TimeoutError('provider outcome unknown')
        value = {**copy.deepcopy(full), 'resolutions': [] if fault == 'missing_again' else copy.deepcopy(full['resolutions'])}
        validate(value)
        return value

    with pytest.raises((ValueError, TimeoutError)):
        await complete_editorial_resolutions(partial, fmt, [], complete)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['joint', 'no_validator', 'legacy', 'proof'])
async def test_partial_checkpoint_is_reserved_for_joint_completion_not_legacy_or_proof(case, mode):
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_partitioned_extraction import Journal

    _, _, _, _, partial, fmt = partial_case(case)
    group = 'practical:editorial:verify:v34:joint:' + 'a' * 64 + ':output=32768'
    if mode == 'legacy':
        group = group.replace(':v34:', ':v33:')
    if mode == 'proof':
        group = group.replace(':joint:', ':proof:')

    async def invoke():
        return copy.deepcopy(partial)

    args = dict(journal=Journal(), stage='review', group_id=group, source_sha256='a' * 64,
        route_fingerprint='b' * 64, messages=[{'role': 'user', 'content': 'Current source/course'}],
        response_format=fmt, invoke=invoke,
        response_validator=None if mode == 'no_validator' else lambda value: matches_editorial_verification_shape(value, fmt))
    if mode == 'joint':
        assert await stage_once(**args) == partial
        assert not matches_editorial_verification(partial, fmt)
    else:
        with pytest.raises(ValueError, match='v3_stage_response_shape_invalid'):
            await stage_once(**args)
