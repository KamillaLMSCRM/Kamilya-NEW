"""Native final checks through the ordinary writer; fake DB, no RLS evidence."""
import hashlib
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.ai import pipeline
from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError
from app.modules.ai.v3.native_profile_binding import KEY as PROFILE_KEY
from app.modules.ai.v3.native_profile_binding import POLICY_ID
from app.modules.ai.v3.owned_source_context import OwnedSourceContext
from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY
from app.modules.ai.v3.revision_policy import (
    OWNED_AUDIT_PRACTICAL_REVIEW_POLICY,
    POLICY,
    QUESTION_BANK_PRACTICAL_REVIEW_POLICY,
)
from app.modules.courses.models import Course
from tests.unit.test_v3_final_save_readback import fixture


def native_fixture(review_policy=OWNED_AUDIT_PRACTICAL_REVIEW_POLICY):
    data = fixture()
    state, job, document = data['state'], data['job'], data['documents'][0]
    analysis = {'generation_engine': 'evidence_v3', 'analysis_mode': 'direct_source',
                'v3_revision_policy': POLICY, 'v3_review_policy': review_policy}
    state.source_analysis = dict(analysis)
    state.structure = state.content = state.assessment = None
    state.course_id = None
    job.status, job.course_id = 'running', None
    job.params = {'documents': list(state.source_document_ids), 'source_analysis': dict(analysis)}
    profile = {'policy': POLICY_ID, 'fingerprint': 'a' * 64}
    job.result = {PROFILE_KEY: dict(profile)}
    journal = SimpleNamespace(expected_native_profile=dict(profile), expected_revision_policy=POLICY,
                              expected_review_policy=review_policy)
    context = OwnedSourceContext(data['source_corpus'], journal, job.tenant_id, job.user_id, str(job.id),
                                 tuple(state.source_document_ids))
    plan = {'schema': 'v3-stage-checkpoint-v1', 'tenant_id': str(job.tenant_id), 'job_id': str(job.id),
            'source_sha256': hashlib.sha256(b'source').hexdigest()}
    journal.expected_revision_plan = dict(plan)
    state.native_practical_final = (context, plan, profile)
    return state, job, document


def install_fake_writer(monkeypatch, job, document, *, lost_ack=False):
    added = []
    class Session:
        def __init__(self):
            self.calls = 0
            self.committed = False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None
        async def execute(self, *_args, **_kwargs):
            return None
        async def scalar(self, *_args, **_kwargs):
            self.calls += 1
            return job if self.calls == 1 else document
        def add(self, row):
            added.append(row)
        async def flush(self):
            return None
        async def commit(self):
            self.committed = True
            if lost_ack:
                raise TimeoutError('commit acknowledgement lost')
    async def lock(_session, _job_id, _tenant, **_kwargs):
        if job.status != 'running':
            raise DeliveryOwnershipLostError('generation_delivery_ownership_lost')
    monkeypatch.setattr(pipeline, 'async_session_factory', Session)
    monkeypatch.setattr(pipeline, 'lock_owned_delivery', lock)
    return added


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['document', 'profile', 'owner', 'tenant', 'selection', 'revision', 'review', 'pending', 'plan', 'guard', 'qa_marker'])
async def test_native_final_drift_rejected_before_course_mutation(monkeypatch, drift):
    state, job, document = native_fixture()
    added = install_fake_writer(monkeypatch, job, document)
    tenant, actor = job.tenant_id, job.user_id
    if drift == 'document':
        document.content_sha256 = 'c' * 64
    elif drift == 'profile':
        job.result[PROFILE_KEY]['fingerprint'] = 'c' * 64
    elif drift == 'owner':
        job.user_id = uuid4()
    elif drift == 'tenant':
        job.tenant_id = uuid4()
    elif drift == 'selection':
        job.params['documents'] = [str(uuid4())]
    elif drift == 'revision':
        job.params['source_analysis']['v3_revision_policy'] = 'other'
    elif drift == 'review':
        job.params['source_analysis']['v3_review_policy'] = 'other'
    elif drift == 'pending':
        job.result['v3_pending_stages'] = None
    elif drift == 'plan':
        state.native_practical_final[1]['source_sha256'] = 'b' * 64
    elif drift == 'qa_marker':
        state.source_analysis['qa_luna_pending_journal_policy'] = 'unknown-nonowned-marker'
    else:
        state.native_practical_final = None
    with pytest.raises((ValueError, pipeline.DirectSourceError)):
        await pipeline._save_generation_to_db(state, tenant, actor)
    assert added == [] and job.course_id is None


@pytest.mark.asyncio
async def test_native_final_cannot_skip_guard_when_destination_changes():
    state, job, _document = native_fixture()
    state.course_id = str(uuid4())
    with pytest.raises(ValueError, match='v3_native_final_source_unverified'):
        await pipeline._verify_native_practical_final_source(None, job, state, job.tenant_id, job.user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['legacy', 'qa'])
async def test_existing_legacy_and_qa_paths_do_not_require_native_guard(scope):
    state, job, _document = native_fixture()
    state.native_practical_final = None
    if scope == 'legacy':
        state.source_analysis['v3_review_policy'] = 'v3-batched-decision-review-v5'
        job.params['source_analysis']['v3_review_policy'] = 'v3-batched-decision-review-v5'
    else:
        state.source_analysis['qa_luna_pending_journal_policy'] = MANAGED_POLICY
        job.params['source_analysis']['qa_luna_pending_journal_policy'] = MANAGED_POLICY
    await pipeline._verify_native_practical_final_source(None, job, state, job.tenant_id, job.user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('lost_ack', [False, True])
@pytest.mark.parametrize('review_policy', [QUESTION_BANK_PRACTICAL_REVIEW_POLICY, OWNED_AUDIT_PRACTICAL_REVIEW_POLICY])
async def test_native_final_uses_original_plan_and_ordinary_atomic_save(monkeypatch, lost_ack, review_policy):
    state, job, document = native_fixture(review_policy)
    original_plan = deepcopy(state.native_practical_final[1])
    calls = []
    original = OwnedSourceContext.verify_locked
    async def verify(context, session, checked_job, plan):
        calls.append(deepcopy(plan))
        return await original(context, session, checked_job, plan)
    monkeypatch.setattr(OwnedSourceContext, 'verify_locked', verify)
    added = install_fake_writer(monkeypatch, job, document, lost_ack=lost_ack)
    if lost_ack:
        with pytest.raises(TimeoutError):
            await pipeline._save_generation_to_db(state, job.tenant_id, job.user_id)
    else:
        await pipeline._save_generation_to_db(state, job.tenant_id, job.user_id)
    assert calls == [original_plan]
    assert len([item for item in added if isinstance(item, Course)]) == 1
    assert job.course_id is not None and job.status == 'completed'
    with pytest.raises(DeliveryOwnershipLostError):
        await pipeline._save_generation_to_db(state, job.tenant_id, job.user_id)
    assert len([item for item in added if isinstance(item, Course)]) == 1
