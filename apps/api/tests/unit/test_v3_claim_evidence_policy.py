"""Fresh evidence policy wiring; no provider, database, or network calls."""
import copy

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.revision_policy import (
    CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY,
    MATERIALITY_PRACTICAL_REVIEW_POLICY,
    is_practical_policy,
    read_review_policy,
    stamp_policy,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def test_fresh_policy_is_closed_and_preserves_saved_materiality_policy():
    assert stamp_policy({}, practical=True)['v3_review_policy'] == CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY
    assert CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY == 'v3-practical-source-review-v26'
    for policy in (MATERIALITY_PRACTICAL_REVIEW_POLICY, CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY):
        assert is_practical_policy(policy)
        assert read_review_policy({'v3_review_policy': policy}) == policy
    assert not is_practical_policy('v3-practical-source-review-v27')


@pytest.mark.asyncio
@pytest.mark.parametrize('policy,expected', [(None, True), (CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY, True),
                                           (MATERIALITY_PRACTICAL_REVIEW_POLICY, False)])
async def test_ordinary_service_dispatch_selects_owned_evidence_only_for_fresh_policy(case, monkeypatch, policy, expected):
    corpus, _packet, _course = case
    import app.modules.ai.v3.practical_lesson_cycle as cycle

    class SelectedError(Exception):
        pass

    async def observe(*args, **kwargs):
        assert kwargs.get('claim_evidence', False) is expected
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
    from app.modules.ai.v3.practical_atomic_audit import CLAIM_EVIDENCE_NAME
    from app.modules.ai.v3.practical_model_view import PracticalModelView
    from app.modules.ai.v3.practical_question_context import NAME
    from app.modules.ai.v3.practical_review import QUESTION_BATCH_NAME
    from tests.unit.test_v3_partitioned_extraction import Journal
    from tests.unit.test_v3_practical_bank_cycle import bank_value
    from tests.unit.test_v3_practical_claim_evidence import response
    from tests.unit.test_v3_question_context_cycle import context_value

    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        if name == 'practical_course':
            value = course
        elif name == NAME:
            value = context_value(fmt)
        elif name == QUESTION_BATCH_NAME:
            value = bank_value(packet, course)
        elif name == CLAIM_EVIDENCE_NAME:
            value = response(packet, course)
        else:
            raise AssertionError('Unexpected stage in accepted fresh course')
        return view.encode(value)

    journal = Journal()
    options = dict(intent=CourseIntent(), source_sha256='a' * 64, route_fingerprint='b' * 64)
    artifacts = await generate_practical_course(corpus, invoke=invoke, journal=journal, **options)
    assert artifacts.diagnostics['v3_review_policy'] == CLAIM_EVIDENCE_PRACTICAL_REVIEW_POLICY
    assert artifacts.diagnostics['automated_review_passed'] is True
    assert artifacts.diagnostics['practical_course'] == course
    assert calls.count('practical_course') == 1
    assert calls.count(CLAIM_EVIDENCE_NAME) == 1
    cold = Journal()
    cold.plans, cold.values = copy.deepcopy(journal.plans), copy.deepcopy(journal.values)

    async def no_provider(*args):
        raise AssertionError('Cold recovery dispatched another model request')

    recovered = await generate_practical_course(corpus, invoke=no_provider, journal=cold, **options)
    assert recovered.diagnostics == artifacts.diagnostics

