"""The practical wrapper must retain the exact author group and wire on replay."""
import base64
import hashlib
import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_contract import _course_format
from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY
from app.modules.ai.v3.revision_policy import EDITORIAL_PRACTICAL_REVIEW_POLICY, FOCUSED_EDITORIAL_REVIEW_POLICY
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_direct_luna_owned_stage import setup


@pytest.mark.asyncio
@pytest.mark.parametrize('focused', [False, True])
async def test_practical_wrapper_replays_retained_author_without_post(monkeypatch, focused):
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.v3 import practical_editorial_cycle, practical_service
    from app.modules.ai.v3.owned_stage_inspection import StageInspection
    from app.modules.ai.v3.response_contracts import response_contract_hash

    fake, journal, _, _, _ = setup()
    client = ManagedLunaClient(base_url='http://10.77.77.2:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1', model='gpt-6-luna')
    source = 'Synthetic source.'
    document = DirectSourceDocument('doc', 'Title', 'source.md', 'general',
        'document:' + hashlib.sha256(source.encode()).hexdigest(), (), source_text=source)
    corpus = DirectSourceCorpus(journal.tenant_id, (document,), len(source), 0)
    messages = [{'role': 'user', 'content': 'Synthetic source only.'}]
    group = 'practical:focused:author:v36:' + 'f' * 64 if focused else 'practical:author:editorial:v31'
    cap_limit = 32768 if focused else 16384
    expected_group = group + ':output=' + str(cap_limit)
    policy = FOCUSED_EDITORIAL_REVIEW_POLICY if focused else EDITORIAL_PRACTICAL_REVIEW_POLICY
    if focused:
        journal.review_policy_bound = True
        journal.expected_review_policy = policy
    fmt = _course_format(['SRC1'])
    response = {'title': 'Course', 'lessons': [{'id': 'l1', 'title': 'Lesson', 'content': 'Text',
        'questions': [{'id': 'q1', 'prompt': 'Question?', 'choices': ['A', 'B', 'C'],
                       'correct_index': 0, 'explanation': 'Explanation', 'source_refs': ['SRC1']}]}]}
    raw = json.dumps({'model': 'gpt-6-luna', 'structured_output_policy': 'typed-json-object-v1',
        'response_format_sha256': response_contract_hash(fmt),
        'choices': [{'message': {'content': json.dumps(response)}}],
        'usage': {'prompt_tokens': 7, 'completion_tokens': 2}}).encode()
    candidate_holder = {}

    async def inspect(**options):
        plan = options['plan']
        assert plan['group_id'] == expected_group
        cap = await client.prepare(messages, max_output_tokens=cap_limit,
            ownership_checkpoint=AsyncMock(return_value=True), response_format=fmt)
        wire_hash = hashlib.sha256(client._prepared[cap]).hexdigest()
        client.discard(cap)
        digest = _digest(plan)
        receipt = {'policy': 'managed-response-quarantine-v1', 'accepted': False, 'complete_http_response': True,
            'status': 200, 'phase': 'stage_finalize' if focused else 'structured_shape', 'stage_sha256': digest,
            'route_fingerprint': client.cache_fingerprint(), 'wire_request_sha256': wire_hash,
            'raw_base64': base64.b64encode(raw).decode(), 'byte_count': len(raw), 'body_sha256': hashlib.sha256(raw).hexdigest()}
        candidate = {'stage': digest, 'body_sha256': receipt['body_sha256'], 'pending_sha256': 'b' * 64,
            'marker': {'identity': digest, 'claim_token': 'c' * 32}, 'receipt': receipt}
        candidate_holder['value'] = candidate
        fake.job.params[AUTHORIZATION_KEY] = {'policy': AUTHORIZATION_POLICY, 'stage': digest,
            'body_sha256': candidate['body_sha256'], 'pending_sha256': candidate['pending_sha256'], 'delivery_id': 'delivery'}
        return StageInspection('replay_completed', candidate)

    async def candidate_read(*_args):
        return candidate_holder['value']

    async def finalize(**kwargs):
        assert kwargs['plan']['group_id'] == expected_group
        stored = json.loads(json.dumps(kwargs['value'], allow_nan=False))
        assert stored == kwargs['value']
        return kwargs['validate'](stored)

    async def editorial(_packet, _corpus, _intent, _decisions, stage, **_kwargs):
        return await stage('lesson', group, messages, fmt, lambda _: None)

    monkeypatch.setattr('app.modules.ai.v3.direct_luna_owned_stage.inspect_owned_stage', inspect)
    monkeypatch.setattr('app.modules.ai.v3.retained_author_replay.owned_candidate', candidate_read)
    monkeypatch.setattr('app.modules.ai.v3.pending_stage_transactions.finalize_pending', finalize)
    if focused:
        monkeypatch.setattr('app.modules.ai.v3.practical_focused_cycle.run_focused_cycle', editorial)
    else:
        monkeypatch.setattr(practical_editorial_cycle, 'run_editorial_cycle', editorial)
    monkeypatch.setattr(practical_service, 'practical_artifacts', lambda result, *_args, **_kwargs: result)
    forbidden = AsyncMock(side_effect=AssertionError('unexpected inference'))
    monkeypatch.setattr(client, 'invoke', forbidden)
    token = delivery_id.set('delivery')
    try:
        result = await practical_service.generate_practical_course(corpus, intent=CourseIntent(audience='Staff'),
            invoke=forbidden, source_sha256='a' * 64, journal=journal, route_fingerprint=client.cache_fingerprint(),
            direct_client=client, direct_max_output_tokens=cap_limit, review_policy=policy)
        assert result == response
        forbidden.assert_not_awaited()
    finally:
        delivery_id.reset(token)
        client.close()
