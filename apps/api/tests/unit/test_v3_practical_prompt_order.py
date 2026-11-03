"""Prompt identity survives JSONB-style object reordering; list order remains significant."""
import copy
from types import SimpleNamespace

import pytest

from app.modules.ai.v3.practical_cycle import practical_patch_messages, run_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_patch import practical_patch_format
from app.modules.ai.v3.practical_review import (
    PracticalReviewDecision,
    practical_review_format,
    practical_review_messages,
)
from app.modules.ai.v3.practical_source_audit import source_audit_format, source_audit_messages
from app.modules.ai.v3.stage_checkpoint import stage_plan
from tests.unit.test_v3_practical_cycle import case


def reverse_objects(value):
    if isinstance(value, dict):
        return {key: reverse_objects(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reverse_objects(item) for item in value]
    if isinstance(value, tuple):
        return tuple(reverse_objects(item) for item in value)
    return value


def identity(messages, fmt, stage, group):
    journal = SimpleNamespace(tenant_id='tenant-1', job_id='job')
    return stage_plan(journal, stage=stage, group_id=group, source_sha256='a' * 64,
                      route_fingerprint='b' * 64, messages=messages, response_format=fmt)['request_sha256']


@pytest.mark.asyncio
async def test_warm_and_cold_prompt_and_stage_identity_are_object_order_independent():
    corpus, packet, course = case.__wrapped__()
    view = PracticalModelView(packet)
    original = copy.deepcopy(course)
    cold = reverse_objects(course)
    intent = {'purpose': 'Learning', 'audience': 'Staff', 'nested': {'b': 2, 'a': 1}}
    captured = []

    async def stop(*args):
        captured.append((args[2], args[3]))
        raise RuntimeError('stop_before_model')

    for value in (intent, reverse_objects(intent)):
        with pytest.raises(RuntimeError, match='stop_before_model'):
            await run_practical_cycle(packet, value, stop)
    assert captured[0] == captured[1]
    assert identity(*captured[0], 'lesson', 'author') == identity(*captured[1], 'lesson', 'author')
    previous = ({'issue_id': 'issue-a', 'scope': 'lesson', 'id': 'l1', 'evidence': {'b': 2, 'a': 1}},)
    decision = PracticalReviewDecision(False, False, ('l1',), (), False, previous)
    reversed_decision = PracticalReviewDecision(False, False, ('l1',), (), False, reverse_objects(previous))
    pairs = [
        (practical_review_messages(packet, course, previous, model_view=view),
         practical_review_messages(packet, cold, reverse_objects(previous), model_view=view),
         practical_review_format(packet, course, previous), 'review'),
        (source_audit_messages(packet, course, model_view=view), source_audit_messages(packet, cold, model_view=view),
         source_audit_format(packet, course), 'review'),
        (practical_patch_messages(packet, course, decision, model_view=view),
         practical_patch_messages(packet, cold, reversed_decision, model_view=view),
         practical_patch_format(packet, course, decision), 'repair'),
    ]
    for warm, reordered, fmt, stage in pairs:
        assert warm == reordered
        assert identity(warm, view.schema(fmt), stage, 'same-group') == identity(reordered, view.schema(fmt), stage, 'same-group')
        assert all(block.text in warm[1]['content'] for block in packet.blocks if block.text.strip())
    assert course == original and cold['lessons'][0]['id'] == course['lessons'][0]['id']
