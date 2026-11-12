import base64
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaError
from app.modules.ai.v3 import retained_author_replay as replay
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V6_POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.simple_semantic_source_plan import (
    compile_semantic_plan,
    matches_semantic_plan,
    semantic_plan_request,
)
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_managed_luna_client import setup  # noqa: F401 -- pytest fixture
from tests.unit.test_v3_simple_semantic_source_plan import fixture, make_plan


def context_only_plan():
    corpus, packet = fixture()
    plan, fmt = make_plan(packet, corpus)
    context = plan['non_teaching'][0]['slice_ids'].pop()
    if not plan['non_teaching'][0]['slice_ids']:
        plan['non_teaching'] = []
    plan['units'][0]['supporting_slices'].append(context)
    return corpus, packet, plan, fmt


def test_supporting_only_slice_is_accounted():
    corpus, packet, plan, fmt = context_only_plan()
    assert matches_semantic_plan(plan, fmt)
    assert compile_semantic_plan(plan, packet, corpus) == plan


@pytest.mark.parametrize('fault', ['missing', 'foreign', 'stale', 'primary_excluded'])
def test_supporting_accounting_remains_fail_closed(fault):
    corpus, packet, plan, fmt = context_only_plan()
    plan = copy.deepcopy(plan)
    if fault == 'missing':
        plan['units'][0]['supporting_slices'] = []
    elif fault == 'foreign':
        plan['units'][0]['supporting_slices'] = ['S999999']
    elif fault == 'stale':
        plan['slices_fingerprint'] = '0' * 64
    else:
        plan['non_teaching'].append({'slice_ids': [plan['units'][0]['primary_slices'][0]], 'reason': 'Conflicting'})
    assert not matches_semantic_plan(plan, fmt)
    with pytest.raises(ValueError):
        compile_semantic_plan(plan, packet, corpus)


def test_typed_transport_does_not_approve_incomplete_legacy_plan():
    from app.modules.ai.v3.response_contracts import matches_response_contract

    corpus, packet, plan, fmt = context_only_plan()
    plan['units'][0]['supporting_slices'] = []
    # The shared wire format describes owned structure, not teaching completeness.
    # Legacy consumers remain strict; only V9 may complete verified formatting.
    assert matches_response_contract(plan, fmt)
    assert not matches_semantic_plan(plan, fmt)
    with pytest.raises(ValueError, match='semantic_plan_invalid'):
        compile_semantic_plan(plan, packet, corpus)
    for version in (6, 9):
        stage = {'stage': 'review', 'group_id': f'practical:simple:plan:v{version}:' + 'a' * 64 + ':output=32768'}
        assert not replay.retained_phase_allowed(stage, 'stage_finalize')


@pytest.mark.asyncio
@pytest.mark.parametrize('version', [6, 9])
@pytest.mark.parametrize('fault', [None, 'missing_plan', 'group', 'stage', 'tenant', 'user', 'job',
    'source', 'route', 'request', 'phase', 'body', 'wire', 'format_echo', 'incomplete', 'status'])
async def test_semantic_plan_replay_is_bound_and_never_sends(setup, fault, version):  # noqa: F811 -- pytest fixture
    client, tenant, user, _, requests = setup
    corpus, packet, value, fmt = context_only_plan()
    messages, actual_format = semantic_plan_request(packet, corpus, {})
    assert actual_format == fmt
    body = {'model': client.model, 'structured_output_policy': 'typed-json-object-v1',
        'response_format_sha256': '0' * 64 if fault == 'format_echo' else response_contract_hash(fmt),
        'choices': [{'message': {'content': json.dumps(value)}}],
        'usage': {'prompt_tokens': 8, 'completion_tokens': 2}}
    raw = json.dumps(body).encode()
    checkpoint = AsyncMock(return_value=True)
    capability = await client.prepare(messages, max_output_tokens=32768,
                                      ownership_checkpoint=checkpoint, response_format=fmt)
    plan = {'schema': 'v3-stage-checkpoint-v1', 'tenant_id': str(tenant), 'job_id': 'job',
        'stage': 'review', 'group_id': f'practical:simple:plan:v{version}:' + packet.fingerprint + ':output=32768',
        'source_sha256': 'b' * 64, 'route_fingerprint': client.cache_fingerprint(),
        'request_sha256': _digest([messages, fmt])}
    receipt = {'policy': 'managed-response-quarantine-v1', 'accepted': False, 'complete_http_response': True,
        'status': 200, 'phase': 'structured_shape', 'stage_sha256': _digest(plan),
        'route_fingerprint': client.cache_fingerprint(),
        'wire_request_sha256': hashlib.sha256(client._prepared[capability]).hexdigest(),
        'raw_base64': base64.b64encode(raw).decode(), 'byte_count': len(raw),
        'body_sha256': hashlib.sha256(raw).hexdigest()}
    changes = {'group': ('group_id', 'practical:simple:author-unit:v6:' + packet.fingerprint + ':output=32768'),
        'stage': ('stage', 'lesson'), 'tenant': ('tenant_id', str(uuid4())), 'job': ('job_id', 'other'),
        'source': ('group_id', f'practical:simple:plan:v{version}:' + '0' * 64 + ':output=32768'),
        'route': ('route_fingerprint', 'c' * 64), 'request': ('request_sha256', 'c' * 64)}
    if fault in changes:
        key, changed = changes[fault]
        plan[key] = changed
        receipt['stage_sha256'] = _digest(plan)
    if fault == 'phase':
        receipt['phase'] = 'stage_finalize'
    if fault == 'body':
        receipt['body_sha256'] = '0' * 64
    if fault == 'wire':
        receipt['wire_request_sha256'] = '0' * 64
    if fault == 'incomplete':
        receipt['complete_http_response'] = False
    if fault == 'status':
        receipt['status'] = 500
    options = {'receipt': receipt, 'tenant_id': tenant, 'user_id': uuid4() if fault == 'user' else user,
        'job_id': 'job', 'stage_id': receipt['stage_sha256'], 'ownership_checkpoint': checkpoint,
        'stage_plan': None if fault == 'missing_plan' else plan}
    if fault is None:
        result = await client.replay_completed(capability, **options)
        assert result.content == value
    else:
        with pytest.raises(ManagedLunaError):
            await client.replay_completed(capability, **options)
    with pytest.raises(ManagedLunaError):
        await client.replay_completed(capability, **options)
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize('version', [6, 9])
@pytest.mark.parametrize('fault', [None, 'policy', 'cross_policy', 'stage', 'phase', 'claim', 'body', 'owner', 'result'])
async def test_owned_semantic_candidate_requires_exact_policy_and_receipt(monkeypatch, fault, version):
    tenant, actor, job_id = str(uuid4()), uuid4(), str(uuid4())
    plan = {'schema': 'v3-stage-checkpoint-v1', 'tenant_id': tenant, 'job_id': job_id,
            'stage': 'review', 'group_id': f'practical:simple:plan:v{version}:' + 'f' * 64 + ':output=32768',
            'route_fingerprint': 'a' * 64}
    if fault == 'stage':
        plan['stage'] = 'lesson'
    digest = _digest(plan)
    entry = {'claim_key': 'v3-stage-claim:' + digest, 'result_key': 'v3-stage-result:' + digest, 'token': 'b' * 32}
    raw = b'synthetic'
    receipt = {'policy': replay.POLICY, 'accepted': False, 'complete_http_response': True, 'status': 200,
        'phase': 'stage_finalize' if fault == 'phase' else 'structured_shape', 'stage_sha256': digest,
        'route_fingerprint': 'a' * 64, 'wire_request_sha256': 'c' * 64,
        'raw_base64': base64.b64encode(raw).decode(), 'body_sha256': hashlib.sha256(raw).hexdigest(),
        'byte_count': len(raw)}
    reference = {k: v for k, v in receipt.items() if k != 'raw_base64'} | {'checkpoint_key': replay.private_key(digest)}
    expected = SIMPLE_COURSE_REVIEW_V6_POLICY if version == 6 else SIMPLE_COURSE_REVIEW_V9_POLICY
    other = SIMPLE_COURSE_REVIEW_V9_POLICY if version == 6 else SIMPLE_COURSE_REVIEW_V6_POLICY
    job = SimpleNamespace(id=job_id, tenant_id=tenant, user_id=actor, course_id=None,
        params={'source_analysis': {'v3_review_policy': 'wrong' if fault == 'policy' else other if fault == 'cross_policy' else expected}},
        result={'v3_pending_stages': {'policy': 'v3-pending-stages-v1', 'entries': {digest: entry}},
                replay.KEY: {'policy': replay.POLICY, 'entries': {digest: reference}}})
    marker = {'identity': digest, 'claim_token': 'wrong' if fault == 'claim' else entry['token']}
    if fault == 'body':
        receipt['raw_base64'] = base64.b64encode(b'changed').decode()
    if fault == 'owner':
        job.user_id = None

    class Journal:
        def __init__(self, tenant_id, user_id, job_id, sessions):
            self.tenant_id, self.job_id, self.repository = tenant_id, job_id, self

        def _owned_key(self, key):
            return key

        async def load_plan(self, *_args, **_kwargs):
            return SimpleNamespace(plan_payload=plan, source_job_id=job_id, plan_revision='v1', lessons=('lesson',))

        async def read_owned_value_in_session(self, _db, key, _plan):
            return (marker if key == entry['claim_key'] else
                    ({'already_saved': True} if fault == 'result' else None) if key == entry['result_key'] else receipt)

    monkeypatch.setattr(replay, 'PendingStageJournal', Journal)
    candidate = await replay.owned_candidate(object(), job)
    assert (candidate is not None) is (fault is None)
