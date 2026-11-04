"""Offline regression for initial and resumed final-save delivery ownership."""
import asyncio
import socket
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.delivery_ownership import delivery_id, lock_owned_delivery, matches_generation_delivery
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.final_save_contract import INTENT_KEY, make_intent, resolve_intent
from app.modules.ai.v3.final_save_owned_checkpoint import checkpoint_final_output
from app.modules.ai.v3.final_save_readback import verify_snapshot
from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
from tests.unit.test_v3_final_save_owned_checkpoint import setup


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(httpx, 'Client', deny)
    monkeypatch.setattr(httpx, 'AsyncClient', deny)


def initial_fixture(monkeypatch):
    data, journal, context = setup(monkeypatch)
    old = data['intent']
    intent = make_intent(tenant_id=old['tenant_id'], user_id=old['user_id'], job_id=old['job_id'],
                         delivery_id=old['job_id'], route_policy=old['route_policy'],
                         route_fingerprint=old['route_fingerprint'], documents=old['documents'],
                         output_digest=old['output_digest'])
    data['intent'] = intent
    del journal.job.result['delivery_task_id']

    # Keep the fixture's transaction mutex, while exercising the production
    # ownership check through the same session and delivery context.
    async def real_lock(session):
        await journal.lock.acquire()
        # The shared fake opens before the mutex; refresh its rollback snapshot
        # after acquisition to model the row observed under the owner lock.
        session.snapshot = (deepcopy(journal.plans), deepcopy(journal.values), deepcopy(journal.job.result))
        await lock_owned_delivery(session, journal.job_id, journal.tenant_id, require_running=True)
    journal._lock_delivery = real_lock
    return data, journal, context


@pytest.mark.asyncio
@pytest.mark.parametrize('resumed', [False, True])
async def test_owned_checkpoint_and_readback_accept_exact_initial_or_resumed_delivery(monkeypatch, resumed):
    data, journal, context = initial_fixture(monkeypatch)
    intent = data['intent']
    if resumed:
        old = intent
        intent = make_intent(tenant_id=old['tenant_id'], user_id=old['user_id'], job_id=old['job_id'],
                             delivery_id='resumed-delivery', route_policy=old['route_policy'],
                             route_fingerprint=old['route_fingerprint'], documents=old['documents'],
                             output_digest=old['output_digest'])
        data['intent'] = intent
        journal.job.result.update(delivery_task_id='resumed-delivery', resume_count=1)
    token = delivery_id.set(intent['delivery_id'])
    try:
        await checkpoint_final_output(journal=journal, context=context, state=data['state'], intent=intent)
        saved = deepcopy(journal.job.result)
        assert saved[INTENT_KEY] == intent and PENDING_KEY in saved
        await checkpoint_final_output(journal=journal, context=context, state=data['state'], intent=intent)
        assert journal.job.result == saved
    finally:
        delivery_id.reset(token)
    data['job'].result = resolve_intent(saved, intent, course_id=str(data['course'].id),
                                        output_digest=intent['output_digest'])
    data['job'].status = 'completed'
    data['job'].course_id = data['course'].id
    data['job'].params['progress_detail'] = {'current': 1, 'total': 1, 'estimated_remaining_seconds': 0}
    assert verify_snapshot(**data)


@pytest.mark.parametrize('result,current,expected', [
    (None, 'job', True), ({}, 'job', True), ({'resume_count': 0}, 'job', True),
    ({'delivery_task_id': 'new', 'resume_count': 1}, 'new', True),
    ({'delivery_task_id': 'new', 'resume_count': 1}, 'job', False),
    ({'resume_count': 1}, 'job', False), ({}, 'other', False),
    ({'resume_count': False}, 'job', False), ({'resume_count': '0'}, 'job', False),
    ({'resume_count': -1}, 'job', False), ({'delivery_task_id': ''}, 'job', False),
    ({'delivery_task_id': 7}, 'job', False), ([], 'job', False), ({}, '', False),
])
def test_delivery_identity_rejects_stale_and_malformed_states(result, current, expected):
    assert matches_generation_delivery('job', result, current) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['stale', 'resumed_missing', 'actor', 'route', 'source', 'pending'])
async def test_initial_checkpoint_fails_closed_on_owner_and_fence_drift(monkeypatch, drift):
    data, journal, context = initial_fixture(monkeypatch)
    intent = data['intent']
    current = intent['delivery_id']
    if drift == 'stale':
        journal.job.result.update(delivery_task_id='new-delivery', resume_count=1)
    elif drift == 'resumed_missing':
        journal.job.result['resume_count'] = 1
    elif drift == 'actor':
        journal.job.user_id = uuid4()
    elif drift == 'route':
        journal.job.result['v3_owned_route_binding']['fingerprint'] = 'f' * 64
    elif drift == 'source':
        context.selection = (str(uuid4()),)
    else:
        journal.job.result[PENDING_KEY] = None
    original = deepcopy(journal.job.result)
    token = delivery_id.set(current)
    try:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await checkpoint_final_output(journal=journal, context=context, state=data['state'], intent=intent)
    finally:
        delivery_id.reset(token)
    assert journal.job.result == original and not journal.values


@pytest.mark.asyncio
async def test_replaced_delivery_cannot_checkpoint_after_waiting_for_owner_lock(monkeypatch):
    data, journal, context = initial_fixture(monkeypatch)
    intent = data['intent']
    await journal.lock.acquire()
    token = delivery_id.set(intent['delivery_id'])
    try:
        pending = asyncio.create_task(checkpoint_final_output(
            journal=journal, context=context, state=data['state'], intent=intent))
        await asyncio.sleep(0)
        journal.job.result.update(delivery_task_id='replacement', resume_count=1)
        journal.lock.release()
        with pytest.raises(ExtractionOutcomeUnknownError):
            await pending
    finally:
        delivery_id.reset(token)
    assert journal.job.result['delivery_task_id'] == 'replacement'
    assert not journal.values and INTENT_KEY not in journal.job.result


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['delivery', 'count', 'actor', 'tenant', 'pending', 'source'])
async def test_initial_readback_fails_closed_on_drift(monkeypatch, drift):
    data, journal, context = initial_fixture(monkeypatch)
    intent = data['intent']
    token = delivery_id.set(intent['delivery_id'])
    try:
        await checkpoint_final_output(journal=journal, context=context, state=data['state'], intent=intent)
    finally:
        delivery_id.reset(token)
    data['job'].result = resolve_intent(journal.job.result, intent, course_id=str(data['course'].id),
                                        output_digest=intent['output_digest'])
    data['job'].status = 'completed'
    data['job'].course_id = data['course'].id
    data['job'].params['progress_detail'] = {'current': 1, 'total': 1, 'estimated_remaining_seconds': 0}
    assert verify_snapshot(**data)
    if drift == 'delivery':
        data['job'].result.update(delivery_task_id='replacement', resume_count=1)
    elif drift == 'count':
        data['job'].result['resume_count'] = True
    elif drift == 'actor':
        data['job'].user_id = uuid4()
    elif drift == 'tenant':
        data['job'].tenant_id = uuid4()
    elif drift == 'pending':
        data['job'].result[PENDING_KEY] = None
    else:
        data['documents'][0].content_sha256 = 'f' * 64
    assert not verify_snapshot(**data)
