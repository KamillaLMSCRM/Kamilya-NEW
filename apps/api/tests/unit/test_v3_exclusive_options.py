"""Versioned construction guidance, not a deterministic semantic judge."""
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3 import practical_lesson_cycle, practical_service
from app.modules.ai.v3.practical_cycle import EXCLUSIVE_OPTIONS_GUIDE, practical_patch_messages
from app.modules.ai.v3.practical_patch import practical_patch_format
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.revision_policy import (
    EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY,
    OWNED_AUDIT_PRACTICAL_REVIEW_POLICY,
)

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('exclusive', [False, True])
async def test_author_construction_only_changes_new_policy(case, exclusive):
    _, packet, _ = case
    captured = []

    async def first_stage(stage, group, messages, fmt, validate):
        captured.append((stage, group, messages, fmt))
        raise RuntimeError('captured_before_inference')

    flags = dict(adjudicate=True, standalone=True, typed_findings=True, counterexamples=True,
                 explicit_cases=True, question_batch=True, strict_audit_owners=True)
    with pytest.raises(RuntimeError, match='captured_before_inference'):
        await practical_lesson_cycle.run_lesson_practical_cycle(
            packet, {}, first_stage, **flags, exclusive_options=exclusive)
    assert len(captured) == 1
    assert captured[0][:2] == ('lesson', 'practical:author:v1')
    assert (EXCLUSIVE_OPTIONS_GUIDE in captured[0][2][0]['content']) is exclusive


def test_patch_preserves_target_projection_and_legacy_bytes(case):
    _, packet, course = case
    decision = PracticalReviewDecision(False, False, (), ('q1',), False, ())
    legacy = practical_patch_messages(packet, course, decision, explicit_cases=True)
    fresh = practical_patch_messages(packet, course, decision, explicit_cases=True, exclusive_options=True)
    assert fresh[0]['content'] == legacy[0]['content'] + EXCLUSIVE_OPTIONS_GUIDE
    assert fresh[1] == legacy[1]
    assert '"id": "q1"' in fresh[1]['content']
    # Peers remain visible as context; only the owned question is writable.
    schema = practical_patch_format(packet, course, decision)['json_schema']['schema']
    assert set(schema['properties']['question_updates']['properties']) == {'q1'}
    with pytest.raises(ValueError, match='practical_revision_policy_invalid'):
        practical_patch_messages(packet, course, decision, exclusive_options=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('policy,exclusive', [
    (OWNED_AUDIT_PRACTICAL_REVIEW_POLICY, False),
    (EXCLUSIVE_OPTIONS_PRACTICAL_REVIEW_POLICY, True),
])
async def test_service_selects_only_fresh_construction_flag(case, monkeypatch, policy, exclusive):
    corpus, _, _ = case
    cycle = AsyncMock(return_value=object())
    monkeypatch.setattr(practical_lesson_cycle, 'run_lesson_practical_cycle', cycle)
    sentinel = object()
    monkeypatch.setattr(practical_service, 'practical_artifacts', lambda *args: sentinel)
    invoke = AsyncMock(side_effect=AssertionError('no inference expected'))
    result = await practical_service.generate_practical_course(
        corpus, intent=CourseIntent(audience='Staff'), invoke=invoke,
        source_sha256='1' * 64, journal=None, route_fingerprint='2' * 64,
        review_policy=policy)
    assert result is sentinel
    assert cycle.await_count == 1
    assert cycle.call_args.kwargs.get('exclusive_options', False) is exclusive
    assert cycle.call_args.kwargs['strict_audit_owners'] is True
    invoke.assert_not_awaited()
