"""Fresh case construction preserves legacy stages and existing review authority."""
import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_atomic_audit import TYPED_NAME as AUDIT_NAME
from app.modules.ai.v3.practical_cycle import EXPLICIT_CASE_GUIDE, practical_patch_messages
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.revision_policy import EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_counterexamples import response
from tests.unit.test_v3_practical_review_purpose import typed_allegation

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
async def test_explicit_case_service_changes_authoring_not_review_schema_or_call_inventory(case):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        if name == 'practical_course':
            assert EXPLICIT_CASE_GUIDE in messages[0]['content']
            value = course
        elif name == 'v3_practical_question_review_v14':
            assert EXPLICIT_CASE_GUIDE not in messages[0]['content']
            value = response(packet, course)
        else:
            assert name == AUDIT_NAME
            value = clean_audit(packet, course)
        return view.encode(value)

    options = dict(intent=CourseIntent(), invoke=invoke, journal=Journal(), source_sha256='b' * 64,
        route_fingerprint='c' * 64, review_policy=EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY)
    first = await generate_practical_course(corpus, **options)
    second = await generate_practical_course(corpus, **options)
    assert first.diagnostics == second.diagnostics
    assert first.diagnostics['automated_review_passed']
    assert first.diagnostics['v3_review_policy'] == EXPLICIT_CASE_PRACTICAL_REVIEW_POLICY
    assert calls == ['practical_course', 'v3_practical_question_review_v14', AUDIT_NAME]


def test_same_case_rule_reaches_owned_patch_without_changing_legacy_prompt(case):
    _, packet, course = case
    decision = typed_allegation(packet, 'ANSWER_VALIDITY')
    old = practical_patch_messages(packet, course, decision)
    assert old == practical_patch_messages(packet, course, decision, explicit_cases=False)
    new = practical_patch_messages(packet, course, decision, explicit_cases=True)
    assert new[1] == old[1] and new[0]['content'] == old[0]['content'] + EXPLICIT_CASE_GUIDE
    with pytest.raises(ValueError, match='practical_revision_policy_invalid'):
        practical_patch_messages(packet, course, decision, explicit_cases=True, legacy_source_rule_scope=True)
