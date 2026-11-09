"""Transport and custody checks; actual semantic fidelity needs saved-model controls."""
import copy

import pytest

from app.modules.ai.v3 import practical_source_semantic_cycle as cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_semantics import compile_source_semantics
from tests.unit.test_v3_source_semantics import packet, verification


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
async def test_enumerated_rule_revision_keeps_members_conditions_and_custody(enabled):
    original = 'Include Alpha, Beta and Gamma; Delta only for overseas cases.'
    p = packet(original)
    rule = {'actor': 'operator', 'action': 'include', 'object': 'the listed records',
            'modality': 'must', 'conditions': [{'applies_to': 'Delta', 'expression': 'overseas cases'}],
            'limits': [], 'alternatives': [], 'source_refs': [p.blocks[0].block_id],
            'source_quote': 'Include Alpha, Beta and Gamma'}
    raw = {'source_fingerprint': p.fingerprint, 'sections': [{'section': 'Records', 'rules': [rule]}],
           'uncertainties': []}
    checks = verification(p, compile_source_semantics(raw, p))
    replacement = copy.deepcopy(rule)
    replacement['object'] = 'Alpha, Beta and Gamma; Delta only for overseas cases'
    checks['rule_checks'][0].update(status='REVISE', reason='The summary omitted the operational members.',
                                   replacement=[replacement])
    calls = []

    async def call(_name, _group, messages, fmt, validate):
        calls.append(messages)
        if len(calls) == 1:
            value = raw
        elif len(calls) == 2:
            value = checks
        else:
            fingerprint = fmt['json_schema']['schema']['properties']['verified_reading_fingerprint']['enum'][0]
            value = {'source_fingerprint': p.fingerprint, 'verified_reading_fingerprint': fingerprint,
                     'additional_rules': []}
        validate(value)
        return copy.deepcopy(value)

    result = await cycle.prepare_source_semantics(p, original, PracticalModelView(p), call,
                                                  relation_checks=enabled)
    guide = getattr(cycle, 'SOURCE_ENUMERATION_GUIDE', '')
    assert guide, 'The model roles need the operational enumeration fidelity contract'
    assert len(calls) == 3
    assert all((guide in messages[0]['content']) == enabled for messages in calls)
    assert all(original in messages[1]['content'] for messages in calls)
    corrected = result['interpretations'][0]
    assert corrected['rule']['object'] == replacement['object']
    assert corrected['rule']['conditions'] == rule['conditions']
    assert corrected['rule']['source_refs'] == rule['source_refs']
    assert corrected['custody_valid'] and corrected['status'] == 'REVISE'
    assert result['original_reading']['original'] == raw


def test_author_and_editor_share_the_same_enumeration_fidelity_contract():
    guide = getattr(cycle, 'SOURCE_ENUMERATION_GUIDE', '')
    assert guide and guide in cycle.SOURCE_AUTHORITY_GUIDE
