from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import router
from app.modules.ai.job_service import AIJobAdmissionLimitReachedError
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, MANAGED_POLICY
from app.modules.ai.v3.revision_policy import (
    COHERENT_EDITORIAL_REVIEW_POLICY,
    EDITORIAL_QA_KEY,
    EDITORIAL_QA_MARKER,
    REVIEW_POLICY,
    SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
    practical_qa_admission,
    source_core_qa_admission,
)
from tests.unit.test_ai_router_admission import _lenient_db

FLAGS = ('AI_QA_LUNA_DEV_ENABLED', 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED',
         'AI_DIRECT_LUNA_QA_DEV_ENABLED', 'AI_MANAGED_LUNA_QA_DEV_ENABLED')


def native_settings():
    return SimpleNamespace(DEPLOYMENT_ENVIRONMENT='render-development', **{key: False for key in FLAGS})


def test_server_admission_is_strict_and_managed_marker_remains_supported():
    cfg = native_settings()
    args = {'settings': cfg, 'marker': None, 'tenant_id': QA_TENANT, 'course_id': None}
    assert practical_qa_admission(**args)
    assert practical_qa_admission(**(args | {'marker': MANAGED_POLICY}))
    assert source_core_qa_admission(**args, user_id=uuid4())
    assert not source_core_qa_admission(**args, user_id=None)
    assert not source_core_qa_admission(**(args | {'tenant_id': uuid4()}), user_id=uuid4())
    assert not source_core_qa_admission(**(args | {'marker': MANAGED_POLICY}), user_id=uuid4())
    assert not source_core_qa_admission(**(args | {'course_id': uuid4()}), user_id=uuid4())
    for changed in ({'tenant_id': uuid4()}, {'course_id': uuid4()}, {'marker': DIRECT_POLICY}):
        assert not practical_qa_admission(**(args | changed))
    cfg.DEPLOYMENT_ENVIRONMENT = 'production'
    assert not practical_qa_admission(**args)
    cfg.DEPLOYMENT_ENVIRONMENT = 'render-development'
    for flag in FLAGS:
        for invalid in (True, 'false', None, 0):
            altered = native_settings()
            setattr(altered, flag, invalid)
            assert not practical_qa_admission(**(args | {'settings': altered}))
            assert not source_core_qa_admission(**(args | {'settings': altered}), user_id=uuid4())
        missing = native_settings()
        delattr(missing, flag)
        assert not practical_qa_admission(**(args | {'settings': missing}))


@pytest.mark.asyncio
@pytest.mark.parametrize('tenant_kind,environment', [
    ('qa', 'render-development'), ('normal', 'render-development'), ('normal', 'production'),
])
async def test_native_parent_rejected_before_quota_and_dispatch(monkeypatch, tenant_kind, environment):
    user = SimpleNamespace(id=uuid4(), tenant_id=QA_TENANT if tenant_kind == 'qa' else uuid4())
    request = AIGenerateRequest(documents=[uuid4()], completed_extraction_parent_job_id=uuid4())
    analysis = SimpleNamespace(status='compatible', score=1.0, requires_decision=False, clusters=[])
    monkeypatch.setattr('app.modules.ai.source_analysis.analyze_document_set', AsyncMock(return_value=analysis))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_chunk_totals', AsyncMock(return_value={}))
    monkeypatch.setattr('app.modules.ai.v3.qa_luna_pending_policy.admission_marker', lambda **_kwargs: None)
    settings = native_settings()
    settings.DEPLOYMENT_ENVIRONMENT = environment
    settings.AI_MULTI_DOC_MAX_TOTAL_CHUNKS = 1000
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    quota, submit, reuse = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr('app.core.demo_limits.check_ai_generation_quota', quota)
    monkeypatch.setattr(router, 'submit_ai_job', submit)
    monkeypatch.setattr('app.modules.ai.v3.completed_extraction_reuse.validate_parent_admission', reuse)
    with pytest.raises(HTTPException) as error:
        await router.generate_course(request, db=_lenient_db(), user=user)
    assert error.value.status_code == 422
    assert error.value.detail == 'completed_extraction_reuse_not_supported_for_practical_policy'
    quota.assert_not_awaited()
    submit.assert_not_awaited()
    reuse.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('tenant_kind,environment', [
    ('qa', 'render-development'), ('normal', 'render-development'), ('normal', 'production'),
])
@pytest.mark.parametrize('destination', ['fresh', 'existing', 'reuse_new'])
async def test_native_admission_binds_policy_to_actual_destination(monkeypatch, tenant_kind, environment, destination):
    tenant = QA_TENANT if tenant_kind == 'qa' else uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant)
    course = uuid4() if destination == 'existing' else None
    request = AIGenerateRequest(documents=[uuid4()], course_id=course,
                                reuse_reason='other' if destination == 'reuse_new' else None)
    analysis = SimpleNamespace(status='compatible', score=1.0, requires_decision=False, clusters=[])
    monkeypatch.setattr('app.modules.ai.source_analysis.analyze_document_set', AsyncMock(return_value=analysis))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_chunk_totals', AsyncMock(return_value={}))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_script_languages', AsyncMock(return_value={}))
    monkeypatch.setattr('app.modules.ai.v3.qa_luna_pending_policy.admission_marker', lambda **_kwargs: None)
    settings = native_settings()
    settings.DEPLOYMENT_ENVIRONMENT = environment
    settings.AI_MULTI_DOC_MAX_TOTAL_CHUNKS = 1000
    settings.AI_MAX_ACTIVE_JOBS_PER_TENANT = 2
    settings.AI_WORKER_CONCURRENCY = 1
    settings.AI_ESTIMATED_JOB_SECONDS = 60
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    monkeypatch.setattr('app.core.demo_limits.check_ai_generation_quota', AsyncMock())
    monkeypatch.setattr('app.core.demo_limits.release_ai_generation_quota', AsyncMock())
    monkeypatch.setattr(router, 'resolve_tenant_ai_active_limit', AsyncMock(return_value=2))
    submit = AsyncMock(side_effect=AIJobAdmissionLimitReachedError(tenant_id=tenant, active_count=2, active_limit=2))
    monkeypatch.setattr(router, 'submit_ai_job', submit)
    with pytest.raises(HTTPException) as error:
        await router.generate_course(request, db=_lenient_db(), user=user)
    assert error.value.status_code == 429
    expected = (REVIEW_POLICY if destination == 'existing' else
                COHERENT_EDITORIAL_REVIEW_POLICY if tenant_kind == 'normal' or environment == 'render-development'
                else SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY)
    assert submit.await_args.kwargs['params']['source_analysis']['v3_review_policy'] == expected
    marker = submit.await_args.kwargs['params']['source_analysis'].get(EDITORIAL_QA_KEY)
    assert marker == (EDITORIAL_QA_MARKER if tenant_kind == 'qa' and expected == COHERENT_EDITORIAL_REVIEW_POLICY else None)
    assert submit.await_args.kwargs['course_id'] == (course if destination == 'existing' else None)
