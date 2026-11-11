"""P31 managed QA admission and owned final fence; fake sessions, no provider."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import pipeline, router
from app.modules.ai.delivery_ownership import delivery_id
from app.modules.ai.job_service import AIJobAdmissionLimitReachedError
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_editorial_contract import editorial_review_format
from app.modules.ai.v3.qa_luna_pending_policy import KEY, MANAGED_POLICY, admission_marker
from app.modules.ai.v3.revision_policy import (
    CANONICAL_EDITORIAL_REVIEW_POLICY,
    EDITORIAL_MANAGED_QA_MARKER,
    EDITORIAL_PRACTICAL_REVIEW_POLICY,
    EDITORIAL_QA_KEY,
    SIMPLE_COURSE_REVIEW_POLICY,
    editorial_qa_admission_marker,
    editorial_qa_worker_valid,
)
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_ai_router_admission import _lenient_db
from tests.unit.test_direct_luna_owned_stage import options, setup
from tests.unit.test_managed_luna_owned_route import managed
from tests.unit.test_v3_final_source_save_fence import owned

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def config(environment):
    return SimpleNamespace(DEPLOYMENT_ENVIRONMENT=environment, AI_QA_LUNA_DEV_ENABLED=True,
        AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=True, AI_MANAGED_LUNA_QA_DEV_ENABLED=True,
        AI_DIRECT_LUNA_QA_DEV_ENABLED=False, AI_MULTI_DOC_MAX_TOTAL_CHUNKS=1000,
        AI_MAX_ACTIVE_JOBS_PER_TENANT=2, AI_WORKER_CONCURRENCY=1, AI_ESTIMATED_JOB_SECONDS=60)


def test_managed_p31_selector_and_worker_fences():
    user = uuid4()
    api = config('render-development')
    marker = admission_marker(settings=api, tenant_id=QA_TENANT, user_id=user, course_id=None, source_first=False)
    assert marker == MANAGED_POLICY
    assert editorial_qa_admission_marker(settings=api, marker=marker, tenant_id=QA_TENANT, user_id=user,
                                         course_id=None) == EDITORIAL_MANAGED_QA_MARKER
    for change in ({'tenant_id': uuid4()}, {'user_id': None}, {'course_id': uuid4()}, {'marker': 'forged'}):
        args = {'settings': api, 'marker': marker, 'tenant_id': QA_TENANT, 'user_id': user, 'course_id': None}
        assert editorial_qa_admission_marker(**(args | change)) is None
    worker = config('vm-development-worker')
    args = {'settings': worker, 'tenant_id': QA_TENANT, 'user_id': user, 'course_id': None,
            'stored': EDITORIAL_MANAGED_QA_MARKER, 'dispatched': EDITORIAL_MANAGED_QA_MARKER,
            'qa_stored': MANAGED_POLICY, 'qa_dispatched': MANAGED_POLICY}
    assert editorial_qa_worker_valid(**args)
    for change in ({'stored': 'forged'}, {'dispatched': 'forged'}, {'qa_stored': 'forged'},
                   {'qa_dispatched': None}, {'tenant_id': uuid4()}, {'user_id': None}, {'course_id': uuid4()},
                   {'settings': config('production')}):
        assert not editorial_qa_worker_valid(**(args | change))
    for field, invalid in [('AI_QA_LUNA_DEV_ENABLED', False), ('AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED', False),
                           ('AI_MANAGED_LUNA_QA_DEV_ENABLED', False), ('AI_DIRECT_LUNA_QA_DEV_ENABLED', True)]:
        changed = config('vm-development-worker')
        setattr(changed, field, invalid)
        assert not editorial_qa_worker_valid(**(args | {'settings': changed}))


@pytest.mark.asyncio
async def test_real_managed_admission_stamps_canonical_editorial_policy_server_side(monkeypatch):
    settings = config('render-development')
    user = SimpleNamespace(id=uuid4(), tenant_id=QA_TENANT)
    analysis = SimpleNamespace(status='compatible', score=1.0, requires_decision=False, clusters=[])
    monkeypatch.setattr('app.modules.ai.source_analysis.analyze_document_set', AsyncMock(return_value=analysis))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_chunk_totals', AsyncMock(return_value={}))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_script_languages', AsyncMock(return_value={}))
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    monkeypatch.setattr('app.core.demo_limits.check_ai_generation_quota', AsyncMock())
    monkeypatch.setattr('app.core.demo_limits.release_ai_generation_quota', AsyncMock())
    monkeypatch.setattr(router, 'resolve_tenant_ai_active_limit', AsyncMock(return_value=2))
    submit = AsyncMock(side_effect=AIJobAdmissionLimitReachedError(tenant_id=QA_TENANT, active_count=2, active_limit=2))
    monkeypatch.setattr(router, 'submit_ai_job', submit)
    with pytest.raises(HTTPException) as error:
        await router.generate_course(AIGenerateRequest(documents=[uuid4()]), db=_lenient_db(), user=user)
    assert error.value.status_code == 429
    stored = submit.await_args.kwargs['params']['source_analysis']
    assert stored[KEY] == MANAGED_POLICY
    assert stored['v3_review_policy'] == SIMPLE_COURSE_REVIEW_POLICY
    assert stored[EDITORIAL_QA_KEY] == EDITORIAL_MANAGED_QA_MARKER


@pytest.mark.asyncio
async def test_managed_p31_owned_review_reaches_local_preparation(case, monkeypatch):
    _, packet, course = case
    _, journal, _, plan, validate = setup()
    client = managed(journal.tenant_id, journal.user_id, journal.job_id)
    args = options(journal, client, plan, validate)
    fmt = editorial_review_format(packet, course)
    args['response_format'] = fmt
    plan.update(stage='review', group_id='practical:editorial:review:v31:owned',
                request_sha256=_digest([args['messages'], fmt]))
    class PreparedError(Exception):
        pass
    prepare = AsyncMock(side_effect=PreparedError)
    monkeypatch.setattr(client, 'prepare', prepare)
    with pytest.raises(PreparedError):
        await run_direct_owned_stage(**args)
    prepare.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['none', 'stored_editorial', 'state_editorial', 'stored_transport',
                                   'state_transport', 'policy', 'source', 'actor', 'route', 'flag'])
async def test_managed_final_uses_owned_source_and_both_markers(monkeypatch, drift):
    state, job, user = owned()
    cfg = config('vm-development-worker')
    monkeypatch.setattr('app.core.config.get_settings', lambda: cfg)
    state.source_analysis.update({KEY: MANAGED_POLICY, EDITORIAL_QA_KEY: EDITORIAL_MANAGED_QA_MARKER,
                                  'v3_review_policy': CANONICAL_EDITORIAL_REVIEW_POLICY})
    job.params['source_analysis'].update({KEY: MANAGED_POLICY, EDITORIAL_QA_KEY: EDITORIAL_MANAGED_QA_MARKER,
                                          'v3_review_policy': CANONICAL_EDITORIAL_REVIEW_POLICY})
    job.course_id = None
    verify = AsyncMock(return_value=drift != 'source')
    monkeypatch.setattr(state.owned_v3_source_context, 'verify_locked', verify)
    if drift == 'stored_editorial':
        job.params['source_analysis'][EDITORIAL_QA_KEY] = 'forged'
    elif drift == 'state_editorial':
        state.source_analysis[EDITORIAL_QA_KEY] = 'forged'
    elif drift == 'stored_transport':
        job.params['source_analysis'][KEY] = 'forged'
    elif drift == 'state_transport':
        state.source_analysis[KEY] = 'forged'
    elif drift == 'policy':
        job.params['source_analysis']['v3_review_policy'] = EDITORIAL_PRACTICAL_REVIEW_POLICY
    elif drift == 'actor':
        state.owned_v3_source_context.user_id = uuid4()
    elif drift == 'route':
        job.result['v3_owned_route_binding']['fingerprint'] = 'b' * 64
    elif drift == 'flag':
        cfg.AI_MANAGED_LUNA_QA_DEV_ENABLED = False
    token = delivery_id.set('delivery')
    try:
        if drift == 'none':
            await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
            await pipeline._verify_native_practical_final_source(object(), job, state, QA_TENANT, user)
            verify.assert_awaited_once()
        else:
            with pytest.raises(ExtractionOutcomeUnknownError, match='v3_final_source_unverified'):
                await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)
