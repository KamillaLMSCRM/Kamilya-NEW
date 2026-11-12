import base64
import copy
import hashlib
import json
import socket
from uuid import uuid4

import pytest

from app.modules.ai.delivery_ownership import delivery_id
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.managed_rejection_quarantine import KEY, POLICY, private_key, private_plan
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.simple_course_editor_v9 import run_simple_course_editor_v9
from app.modules.ai.v3.simple_semantic_source_plan import build_semantic_slices, semantic_plan_format
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
from tests.unit.test_owned_stage_inspection import setup_journal
from tests.unit.test_v3_simple_source_origin import make_corpus, source_block


class ReachedAuthorError(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['formatting', 'meaningful'])
async def test_retained_v9_plan_continues_without_model_post(monkeypatch, missing):
    corpus = make_corpus([source_block(1, 'Work.\n<br>\nOther.')], [])
    packet = build_practical_source_packet(corpus)
    slices = [row for row in build_semantic_slices(packet, corpus) if row['text'].strip()]
    props = semantic_plan_format(packet, corpus)['json_schema']['schema']['properties']
    value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': props['slices_fingerprint']['enum'][0],
        'title': 'Course', 'units': [{'id': 'unit', 'title': 'Work',
            'primary_slices': [slices[0]['id']], 'supporting_slices': []}],
        'non_teaching': [{'slice_ids': [row['id'] for row in slices[1:]], 'reason': 'Context'}]}
    missing_id = next(row['id'] for row in slices if row['text'] == ('<br>' if missing == 'formatting' else 'Other.'))
    value['non_teaching'][0]['slice_ids'].remove(missing_id)
    if not value['non_teaching'][0]['slice_ids']:
        value['non_teaching'] = []

    fake = setup_journal()
    tenant, actor = uuid4(), uuid4()
    fake.tenant_id = str(tenant)
    fake.job.user_id, fake.job.tenant_id, fake.job.id, fake.job.course_id = actor, tenant, fake.job_id, None
    fake.job.params['source_analysis']['v3_review_policy'] = SIMPLE_COURSE_REVIEW_V9_POLICY

    async def verify(_session, _job, _plan):
        return True

    journal = PendingStageJournal(str(tenant), actor, fake.job_id, fake.sessions, verify_source=verify)
    journal.repository = fake
    journal._lock_delivery = fake._lock_delivery
    journal._owned_key = fake._owned_key
    journal.read_owned_value_in_session = fake.read_owned_value_in_session
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V9_POLICY
    # owned_candidate reconstructs the journal; retain its real method with our fake repository.
    monkeypatch.setattr('app.modules.ai.v3.retained_author_replay.PendingStageJournal', lambda *_: journal)
    monkeypatch.setattr(socket.socket, 'connect', lambda *_a, **_k: pytest.fail('network forbidden'))
    client = ManagedLunaClient(base_url='http://10.77.77.2:18999/v1', api_key='synthetic',
        tenant_id=tenant, user_id=actor, job_id=fake.job_id, credential_revision='r1')
    calls = []
    retained = {}

    async def stage(name, group, messages, fmt, validator):
        calls.append(group)
        if ':author-unit:' in group:
            assert missing == 'formatting'
            assert retained['result_key'] in fake.values
            assert PENDING_KEY not in fake.job.result
            raise ReachedAuthorError
        assert ':plan:v9:' in group and len(calls) == 1
        full_group = group + ':output=32768'
        plan = stage_plan(journal, stage=name, group_id=full_group, source_sha256='b' * 64,
            route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt)
        digest = _digest(plan)
        claim_key, result_key = 'v3-stage-claim:' + digest, 'v3-stage-result:' + digest
        token = 'c' * 32
        marker = {'identity': digest, 'claim_token': token}
        cap = await client.prepare(messages, max_output_tokens=32768, ownership_checkpoint=verify_cap,
                                   response_format=fmt)
        wire = client._prepared[cap]
        wire_hash = hashlib.sha256(wire).hexdigest()
        client.discard(cap)
        raw = json.dumps({'model': client.model, 'structured_output_policy': 'typed-json-object-v1',
            'response_format_sha256': response_contract_hash(fmt),
            'choices': [{'message': {'content': json.dumps(value)}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 2}}).encode()
        decoded, _ = client._decode_response(raw, wire)
        assert decoded.content == value
        receipt = {'policy': POLICY, 'accepted': False, 'complete_http_response': True, 'status': 200,
            'phase': 'structured_shape', 'stage_sha256': digest, 'route_fingerprint': client.cache_fingerprint(),
            'wire_request_sha256': wire_hash, 'raw_base64': base64.b64encode(raw).decode(),
            'byte_count': len(raw), 'body_sha256': hashlib.sha256(raw).hexdigest()}
        fake.plans.update({claim_key: copy.deepcopy(plan), result_key: copy.deepcopy(plan),
                           private_key(digest): private_plan(plan)})
        fake.values.update({claim_key: marker, private_key(digest): receipt})
        fake.job.result[PENDING_KEY] = {'policy': 'v3-pending-stages-v1', 'entries': {
            digest: {'claim_key': claim_key, 'result_key': result_key, 'token': token}}}
        fake.job.result[KEY] = {'policy': POLICY, 'entries': {digest: {
            **{k: v for k, v in receipt.items() if k != 'raw_base64'}, 'checkpoint_key': private_key(digest)}}}
        fake.job.params[AUTHORIZATION_KEY] = {'policy': AUTHORIZATION_POLICY, 'stage': digest,
            'body_sha256': receipt['body_sha256'], 'pending_sha256': _digest(fake.job.result[PENDING_KEY]),
            'delivery_id': 'synthetic-delivery'}
        retained.update(result_key=result_key, digest=digest, raw_plan=copy.deepcopy(value), receipt=receipt)

        async def forbidden():
            pytest.fail('model POST forbidden')

        return await stage_once(journal, stage=name, group_id=full_group, source_sha256='b' * 64,
            route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt,
            invoke=forbidden, direct_client=client, direct_max_output_tokens=32768, response_validator=validator)

    async def verify_cap():
        return True

    context = delivery_id.set('synthetic-delivery')
    try:
        if missing == 'formatting':
            with pytest.raises(ReachedAuthorError):
                await run_simple_course_editor_v9(packet, corpus, {}, stage)
            assert len(calls) == 2
            saved = fake.values[retained['result_key']]
            assert saved['response'] == retained['raw_plan']
            assert saved['response_sha256'] == _digest(retained['raw_plan'])
            assert fake.job.result['v3_retained_author_replay_audit']['body_sha256'] == retained['receipt']['body_sha256']
        else:
            with pytest.raises(ExtractionOutcomeUnknownError):
                await run_simple_course_editor_v9(packet, corpus, {}, stage)
            assert len(calls) == 1 and retained['result_key'] not in fake.values
            assert PENDING_KEY in fake.job.result
    finally:
        delivery_id.reset(context)
        client.close()
