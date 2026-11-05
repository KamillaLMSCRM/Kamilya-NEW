"""P31 server admission and native ownership boundaries; fake sessions only."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import pipeline, router
from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.job_service import AIJobAdmissionLimitReachedError
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_cycle import PracticalCycleResult
from app.modules.ai.v3.practical_editorial_contract import editorial_review_format, editorial_revision_format
from app.modules.ai.v3.practical_review import PracticalReviewDecision
from app.modules.ai.v3.practical_service import generate_practical_course, practical_artifacts
from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_PENDING_KEY
from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from app.modules.ai.v3.revision_policy import (
    CANONICAL_EDITORIAL_REVIEW_POLICY,
    EDITORIAL_ORDINARY_KEY,
    EDITORIAL_ORDINARY_MARKER,
    EDITORIAL_PRACTICAL_REVIEW_POLICY,
    EDITORIAL_QA_KEY,
    EDITORIAL_QA_MARKER,
    SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY,
    editorial_qa_worker_valid,
    is_practical_policy,
    read_review_policy,
    stamp_policy,
)
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_ai_router_admission import _lenient_db
from tests.unit.test_direct_luna_owned_stage import options, setup
from tests.unit.test_v3_native_final_source import install_fake_writer, native_fixture

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
FLAGS = ('AI_QA_LUNA_DEV_ENABLED', 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED',
         'AI_DIRECT_LUNA_QA_DEV_ENABLED', 'AI_MANAGED_LUNA_QA_DEV_ENABLED')


def settings(environment):
    return SimpleNamespace(DEPLOYMENT_ENVIRONMENT=environment, **{name: False for name in FLAGS})


def test_closed_policy_and_worker_route_fences():
    assert stamp_policy({}, practical=True)['v3_review_policy'] == SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY
    assert is_practical_policy(EDITORIAL_PRACTICAL_REVIEW_POLICY)
    assert read_review_policy({'v3_review_policy': EDITORIAL_PRACTICAL_REVIEW_POLICY}) == EDITORIAL_PRACTICAL_REVIEW_POLICY
    with pytest.raises(ValueError):
        read_review_policy({'v3_review_policy': 'v3-practical-source-review-v33'})
    base = {'settings': settings('vm-development-worker'), 'tenant_id': QA_TENANT, 'user_id': uuid4(),
            'course_id': None, 'stored': EDITORIAL_QA_MARKER, 'dispatched': EDITORIAL_QA_MARKER}
    assert editorial_qa_worker_valid(**base)
    for delta in ({'tenant_id': uuid4()}, {'user_id': None}, {'course_id': uuid4()},
                  {'stored': 'forged'}, {'dispatched': None}, {'settings': settings('production')}):
        assert not editorial_qa_worker_valid(**(base | delta))
    for name in FLAGS:
        altered = settings('vm-development-worker')
        setattr(altered, name, True)
        assert not editorial_qa_worker_valid(**(base | {'settings': altered}))


def test_editorial_closed_formats_registered(case):
    _, packet, course = case
    for fmt, kind in ((editorial_review_format(packet, course), 'practical_editorial_review'),
                      (editorial_revision_format(packet, course), 'practical_editorial_revision')):
        assert response_contract(fmt) == kind
        assert not matches_response_contract({}, fmt)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['review', 'revision'])
@pytest.mark.parametrize('drift', ['none', 'stage', 'group', 'digest'])
async def test_direct_owned_editorial_plan_is_exact(case, monkeypatch, kind, drift):
    _, packet, course = case
    fmt = editorial_review_format(packet, course) if kind == 'review' else editorial_revision_format(packet, course)
    fake, journal, client, plan, validate = setup()
    args = options(journal, client, plan, validate)
    args['response_format'] = fmt
    plan.update(stage='review' if kind == 'review' else 'repair',
        group_id='practical:editorial:' + kind + ':v31:test', request_sha256=_digest([args['messages'], fmt]))
    if drift == 'stage':
        plan['stage'] = 'lesson'
    elif drift == 'group':
        plan['group_id'] = 'practical:other:v31:test'
    elif drift == 'digest':
        plan['request_sha256'] = 'a' * 64
    class PreparedError(Exception):
        pass
    prepare = AsyncMock(side_effect=PreparedError)
    monkeypatch.setattr(client, 'prepare', prepare)
    if drift == 'none':
        with pytest.raises(PreparedError):
            await run_direct_owned_stage(**args)
        prepare.assert_awaited_once()
    else:
        with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
            await run_direct_owned_stage(**args)
        prepare.assert_not_awaited()


def test_editorial_artifact_always_requires_human_review(case):
    corpus, packet, course = case
    decision = PracticalReviewDecision(True, False, (), (), False, ())
    review = {'source_notes': [], 'narrative_sources': {lesson['id']: [packet.blocks[0].block_id]
                                                        for lesson in course['lessons']}}
    result = PracticalCycleResult(course, review, decision, (), 'draft', editorial_review=True)
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64)
    assert artifacts.diagnostics['v3_review_policy'] == EDITORIAL_PRACTICAL_REVIEW_POLICY
    assert artifacts.diagnostics['draft_review']['human_review_required'] is True
    assert artifacts.diagnostics['draft_review']['generation_status'] == 'draft_prepared'


@pytest.mark.asyncio
async def test_editorial_dispatch_progress_accepts_whole_course_repair(case, monkeypatch):
    import app.modules.ai.v3.practical_editorial_cycle as cycle
    import app.modules.ai.v3.practical_service as service

    corpus, _, _ = case
    observed = []
    sentinel = object()
    async def fake_cycle(packet, received_corpus, intent, reference_decisions, stage, *, canonical_json):
        assert received_corpus is corpus
        assert canonical_json is True
        for name, group in [('lesson', 'practical:author:editorial:v31'),
                            ('review', 'practical:editorial:review:v31:x'),
                            ('repair', 'practical:editorial:revision:v31:x'),
                            ('review', 'practical:review:editorial-answer:v31:x')]:
            await stage(name, group, [], {}, lambda _value: None)
        return sentinel
    async def invoke(_messages, _fmt):
        return {'course': {}}
    async def report(*args):
        observed.append(args)
    monkeypatch.setattr(cycle, 'run_editorial_cycle', fake_cycle)
    monkeypatch.setattr(service, 'practical_artifacts', lambda result, *_args, **_kwargs: result)
    actual = await generate_practical_course(corpus, intent=CourseIntent(), invoke=invoke,
        source_sha256='a' * 64, journal=None, route_fingerprint='b' * 64,
        review_policy=CANONICAL_EDITORIAL_REVIEW_POLICY, progress_callback=report)
    assert actual is sentinel and [row[1:3] for row in observed] == [(1, 4), (2, 4), (3, 4), (4, 4)]


@pytest.mark.asyncio
@pytest.mark.parametrize('tenant,environment,destination,expected', [
    (QA_TENANT, 'render-development', None, CANONICAL_EDITORIAL_REVIEW_POLICY),
    (QA_TENANT, 'production', None, SEPARATED_DOMAINS_PRACTICAL_REVIEW_POLICY),
    (uuid4(), 'render-development', None, CANONICAL_EDITORIAL_REVIEW_POLICY),
])
async def test_ordinary_admission_stamps_only_server_selected_qa(monkeypatch, tenant, environment, destination, expected):
    request = AIGenerateRequest(documents=[uuid4()], course_id=destination)
    analysis = SimpleNamespace(status='compatible', score=1.0, requires_decision=False, clusters=[])
    monkeypatch.setattr('app.modules.ai.source_analysis.analyze_document_set', AsyncMock(return_value=analysis))
    monkeypatch.setattr(router, '_compatibility_response', lambda _value: SimpleNamespace(
        model_dump=lambda **_kwargs: {'v3_review_policy': 'forged',
                                     EDITORIAL_ORDINARY_KEY: 'forged', EDITORIAL_QA_KEY: 'forged'}))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_chunk_totals', AsyncMock(return_value={}))
    monkeypatch.setattr('app.modules.ai.source_analysis.document_script_languages', AsyncMock(return_value={}))
    monkeypatch.setattr('app.modules.ai.v3.qa_luna_pending_policy.admission_marker', lambda **_kwargs: None)
    cfg = settings(environment)
    cfg.AI_MULTI_DOC_MAX_TOTAL_CHUNKS = 1000
    cfg.AI_MAX_ACTIVE_JOBS_PER_TENANT = 2
    cfg.AI_WORKER_CONCURRENCY = 1
    cfg.AI_ESTIMATED_JOB_SECONDS = 60
    monkeypatch.setattr(router, 'get_settings', lambda: cfg)
    monkeypatch.setattr('app.core.demo_limits.check_ai_generation_quota', AsyncMock())
    monkeypatch.setattr('app.core.demo_limits.release_ai_generation_quota', AsyncMock())
    monkeypatch.setattr(router, 'resolve_tenant_ai_active_limit', AsyncMock(return_value=2))
    submit = AsyncMock(side_effect=AIJobAdmissionLimitReachedError(tenant_id=tenant, active_count=2, active_limit=2))
    monkeypatch.setattr(router, 'submit_ai_job', submit)
    with pytest.raises(HTTPException):
        await router.generate_course(request, db=_lenient_db(), user=SimpleNamespace(id=uuid4(), tenant_id=tenant))
    stored = submit.await_args.kwargs['params']['source_analysis']
    assert stored['v3_review_policy'] == expected
    assert stored.get(EDITORIAL_QA_KEY) == (EDITORIAL_QA_MARKER if tenant == QA_TENANT and expected == CANONICAL_EDITORIAL_REVIEW_POLICY else None)
    assert stored.get(EDITORIAL_ORDINARY_KEY) == (EDITORIAL_ORDINARY_MARKER if tenant != QA_TENANT and expected == CANONICAL_EDITORIAL_REVIEW_POLICY else None)


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['none', 'stored', 'dispatched', 'environment', 'flag', 'managed_marker'])
async def test_final_atomic_save_checks_exact_editorial_qa_marker(monkeypatch, drift):
    state, job, document = native_fixture(EDITORIAL_PRACTICAL_REVIEW_POLICY)
    monkeypatch.setattr('app.modules.ai.qa_luna_dev_route.QA_TENANT', job.tenant_id)
    cfg = settings('vm-development-worker')
    monkeypatch.setattr('app.core.config.get_settings', lambda: cfg)
    state.source_analysis[EDITORIAL_QA_KEY] = EDITORIAL_QA_MARKER
    job.params['source_analysis'][EDITORIAL_QA_KEY] = EDITORIAL_QA_MARKER
    if drift == 'stored':
        job.params['source_analysis'][EDITORIAL_QA_KEY] = 'forged'
    elif drift == 'dispatched':
        state.source_analysis[EDITORIAL_QA_KEY] = 'forged'
    elif drift == 'environment':
        cfg.DEPLOYMENT_ENVIRONMENT = 'production'
    elif drift == 'flag':
        cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    elif drift == 'managed_marker':
        state.source_analysis[QA_PENDING_KEY] = MANAGED_POLICY
        job.params['source_analysis'][QA_PENDING_KEY] = MANAGED_POLICY
    added = install_fake_writer(monkeypatch, job, document)
    if drift == 'none':
        await pipeline._save_generation_to_db(state, job.tenant_id, job.user_id)
        assert added and job.course_id is not None
    else:
        with pytest.raises((ValueError, DeliveryOwnershipLostError, ExtractionOutcomeUnknownError)):
            await pipeline._save_generation_to_db(state, job.tenant_id, job.user_id)
        assert not added and job.course_id is None
