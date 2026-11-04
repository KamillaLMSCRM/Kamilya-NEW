"""A recognized unclassified hold may be stopped, never retried or refunded."""
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import job_service
from app.modules.ai.v3.pending_stage_transactions import has_pending
from tests.unit.test_v3_abandon_unknown import fixture_job


def unclassified_job():
    job = fixture_job(uuid4())
    job.status = 'interrupted'
    job.errors = ['generation_stage_outcome_unknown']
    job.result['v3_pending_stages'] = None
    job.params['source_analysis'] = {'generation_engine': 'evidence_v3', 'analysis_mode': 'direct_source',
                                    'v3_review_policy': 'v3-practical-source-review-v19'}
    return job


@pytest.mark.parametrize('drift', ['running', 'error', 'engine', 'mode', 'policy', 'intent', 'course', 'missing_key'])
def test_only_recognized_interrupted_null_hold_is_available(drift):
    job = unclassified_job()
    assert job_service.can_abandon_unknown(job)
    if drift == 'running':
        job.status = 'running'
    elif drift == 'error':
        job.errors = []
    elif drift == 'engine':
        job.params['source_analysis']['generation_engine'] = 'legacy'
    elif drift == 'mode':
        job.params['source_analysis']['analysis_mode'] = 'legacy'
    elif drift == 'policy':
        job.params['source_analysis']['v3_review_policy'] = 'caller-defined'
    elif drift == 'intent':
        job.result['v3_final_save_intent'] = None
    elif drift == 'course':
        job.course_id = uuid4()
    else:
        del job.result['v3_pending_stages']
    assert not job_service.can_abandon_unknown(job)


@pytest.mark.asyncio
async def test_null_abandon_retains_fence_and_reservation_without_refund_or_resumption(monkeypatch):
    job, db, tenant = unclassified_job(), AsyncMock(), uuid4()
    original = deepcopy((job.result, job.params))
    monkeypatch.setattr(job_service, '_lock_tenant_row', AsyncMock())
    monkeypatch.setattr(job_service, 'get_ai_job', AsyncMock(return_value=job))
    assert await job_service.abandon_unknown_generation(db, job_id=job.id, tenant_id=tenant,
                                                       user_id=uuid4()) == 'not_found'
    db.commit.assert_not_awaited()
    assert await job_service.abandon_unknown_generation(db, job_id=job.id, tenant_id=tenant,
                                                       user_id=job.user_id) == 'abandoned'
    assert has_pending(job.result) and job.result == original[0]
    assert {k: v for k, v in job.params.items() if k != 'generation_abandonment'} == original[1]
    assert job.params['generation_abandonment']['cost'] == 'unknown'
    assert not job_service.is_resumable_generation_job(job)
    assert await job_service.release_generation_reservation_once(db, job_id=job.id, tenant_id=tenant) is False
    assert await job_service.abandon_unknown_generation(db, job_id=job.id, tenant_id=tenant,
                                                       user_id=job.user_id) == 'abandoned'
    db.commit.assert_awaited_once()
