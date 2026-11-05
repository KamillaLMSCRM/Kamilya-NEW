import hashlib

import pytest

from app.modules.ai.v3.practical_atomic_audit import SOURCE_SCOPE_COMPLETE_GUIDE, atomic_audit_messages
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.revision_policy import (
    DOMAIN_PRACTICAL_REVIEW_POLICY,
    SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
    SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY,
    is_practical_policy,
    read_review_policy,
    stamp_policy,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
FLAGS = {'typed_findings': True, 'strict_owners': True, 'materiality_review': True, 'claim_evidence': True}


def test_exact_pilot_guide_and_legacy_request_identity(case):
    _, packet, course = case
    assert hashlib.sha256(SOURCE_SCOPE_COMPLETE_GUIDE.encode('utf-8')).hexdigest() == '06a92bb8d5550aa1e8b79ae1b21b4660c0875e1d98a33d1fbebec6cf35644270'
    before = atomic_audit_messages(packet, course, **FLAGS)
    assert before == atomic_audit_messages(packet, course, **FLAGS, source_scope_complete=False)
    new = atomic_audit_messages(packet, course, **FLAGS, source_scope_complete=True)
    assert new[0]['content'] == before[0]['content'] + SOURCE_SCOPE_COMPLETE_GUIDE
    assert new[1] == before[1]


@pytest.mark.parametrize('flags', [
    {'source_scope_complete': True},
    {'source_scope_complete': 'yes'},
    {'typed_findings': True, 'strict_owners': True, 'claim_evidence': True, 'source_scope_complete': True},
])
def test_audit_scope_flag_requires_owned_materiality(case, flags):
    _, packet, course = case
    with pytest.raises(ValueError, match='practical_atomic_audit_format_invalid'):
        atomic_audit_messages(packet, course, **flags)


@pytest.mark.asyncio
@pytest.mark.parametrize('flags', [{'source_scope_complete': True}, {'source_scope_complete': 'yes'},
                                   {'claim_evidence': True, 'source_scope_complete': True}])
async def test_scope_flag_rejected_before_cycle_dispatch(case, flags):
    _, packet, _ = case
    async def forbidden(*args):
        raise AssertionError('invalid policy dispatched a call')
    with pytest.raises(ValueError, match='practical_revision_policy_invalid'):
        await run_lesson_practical_cycle(packet, {}, forbidden, **flags)


def test_fresh_stamp_and_legacy_27_are_recognized():
    assert stamp_policy({}, practical=True)['v3_review_policy'] == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    for policy in (DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY):
        assert is_practical_policy(policy)
        assert read_review_policy({'v3_review_policy': policy}) == policy
