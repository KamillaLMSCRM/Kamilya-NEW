"""Fresh evidence policy wiring; no provider, database, or network calls."""
import copy

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.revision_policy import (
    CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY,
    DOMAIN_PRACTICAL_REVIEW_POLICY,
    EDITORIAL_PRACTICAL_REVIEW_POLICY,
    MATERIALITY_PRACTICAL_REVIEW_POLICY,
    SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
    SOURCE_CORE_PRACTICAL_REVIEW_POLICY,
    SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY,
    is_practical_policy,
    read_review_policy,
    stamp_policy,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def test_fresh_policy_is_closed_and_preserves_saved_materiality_policy():
    assert stamp_policy({}, practical=True)['v3_review_policy'] == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    assert CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v26'
    for policy in (MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY, SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY, SOURCE_CORE_PRACTICAL_REVIEW_POLICY, EDITORIAL_PRACTICAL_REVIEW_POLICY):
        assert is_practical_policy(policy)
        assert read_review_policy({'v3_review_policy': policy}) == policy
    assert SOURCE_CORE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v30'
    assert EDITORIAL_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v31'
    assert not is_practical_policy('v3-practical-source-review-v33')
    with pytest.raises(ValueError, match='v3_review_policy_invalid'):
        read_review_policy({'v3_review_policy': 'v3-practical-source-review-v33'})


@pytest.mark.asyncio
@pytest.mark.parametrize('policy,expected', [(None, True), (SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY, True), (DOMAIN_PRACTICAL_REVIEW_POLICY, True), (CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, True),
                                           (MATERIALITY_PRACTICAL_REVIEW_POLICY, False)])
async def test_ordinary_service_dispatch_selects_owned_evidence_only_for_fresh_policy(case, monkeypatch, policy, expected):
    corpus, _packet, _course = case
    import app.modules.ai.v3.practical_lesson_cycle as cycle

    class SelectedError(Exception):
        pass

    async def observe(*args, **kwargs):
        assert kwargs.get('claim_evidence', False) is expected
        assert kwargs.get('review_domains', False) is (policy in (None, DOMAIN_PRACTICAL_REVIEW_POLICY, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY))
        assert kwargs.get('source_scope_complete', False) is (policy in (None, SOURCE_SCOPE_PRACTICAL_REVIEW_POLICY))
        assert kwargs['materiality_review'] is True
        assert kwargs['question_batch'] is True
        assert kwargs['strict_audit_owners'] is True
        raise SelectedError

    async def no_model(*args, **kwargs):
        raise AssertionError('dispatcher_should_not_invoke_provider')

    monkeypatch.setattr(cycle, 'run_lesson_practical_cycle', observe)
    options = {} if policy is None else {'review_policy': policy}
    with pytest.raises(SelectedError):
        await generate_practical_course(corpus, intent=CourseIntent(), invoke=no_model, source_sha256='a' * 64, journal=None, route_fingerprint='route', **options)


@pytest.mark.asyncio
async def test_fresh_ordinary_service_retains_evidence_and_cold_replays_without_provider(case):
    from app.modules.ai.v3.practical_atomic_audit import EXPLANATION_AUDIT_NAME, SOURCE_SCOPE_COMPLETE_GUIDE
    from app.modules.ai.v3.practical_audit_units import audit_units
    from app.modules.ai.v3.practical_contract import _digest
    from app.modules.ai.v3.practical_curriculum import CURRICULUM_BANK_NAME, CURRICULUM_NAME, validate_curriculum
    from app.modules.ai.v3.practical_model_view import PracticalModelView
    from app.modules.ai.v3.practical_question_context import NAME
    from tests.unit.test_v3_partitioned_extraction import Journal
    from tests.unit.test_v3_practical_bank_cycle import bank_value
    from tests.unit.test_v3_practical_claim_evidence import response
    from tests.unit.test_v3_question_context_cycle import context_value

    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []
    refs = [b.block_id for b in packet.blocks if b.text.strip()]
    plan = validate_curriculum({'source_fingerprint': packet.fingerprint,
        'sections': [{'title': 'Practical decisions', 'source_units': [key for key, _ in audit_units(packet).groups],
            'depends_on_units': [], 'goals': [{'id': 'local', 'decision': 'Apply the source procedure',
                'essential_case_conditions': [], 'source_refs': refs}]}],
        'non_teaching_units': [], 'source_uncertainties': []}, packet)

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        assert (SOURCE_SCOPE_COMPLETE_GUIDE in messages[0]['content']) is (name == EXPLANATION_AUDIT_NAME)
        if name == CURRICULUM_NAME:
            assert 'STANDALONE_QUESTIONS_JSON' not in messages[1]['content']
            value = plan
        elif name == 'practical_course':
            value = course
        elif name == NAME:
            value = context_value(fmt)
        elif name == CURRICULUM_BANK_NAME:
            value = bank_value(packet, course)
            value.update(curriculum_fingerprint=_digest(plan), goal_checks=[{
                'goal_id': 'G1', 'status': 'COVERED', 'source_refs': refs,
                'question_ids': [course['lessons'][0]['questions'][0]['id']],
                'assessment_lesson_id': '', 'reason': 'Representative procedure assessed.'}])
        elif name == EXPLANATION_AUDIT_NAME:
            value = response(packet, course)
        else:
            raise AssertionError('Unexpected stage in accepted fresh course')
        return view.encode(value)

    journal = Journal()
    options = dict(intent=CourseIntent(), source_sha256='a' * 64, route_fingerprint='b' * 64)
    artifacts = await generate_practical_course(corpus, invoke=invoke, journal=journal, **options)
    assert artifacts.diagnostics['v3_review_policy'] == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    assert artifacts.diagnostics['automated_review_passed'] is True
    assert artifacts.diagnostics['practical_course'] == course
    assert calls.count('practical_course') == 1
    assert calls.count(EXPLANATION_AUDIT_NAME) == 1
    assert calls[0] == CURRICULUM_NAME
    assert artifacts.diagnostics['practical_curriculum_plan'] == plan
    assert len(calls) == 5
    cold = Journal()
    cold.plans, cold.values = copy.deepcopy(journal.plans), copy.deepcopy(journal.values)

    async def no_provider(*args):
        raise AssertionError('Cold recovery dispatched another model request')

    recovered = await generate_practical_course(corpus, invoke=no_provider, journal=cold, **options)
    assert recovered.diagnostics == artifacts.diagnostics

