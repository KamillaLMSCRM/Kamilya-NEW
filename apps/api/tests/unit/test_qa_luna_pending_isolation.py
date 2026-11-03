from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.qa_luna_pending_policy import POLICY, admission_marker, check_worker_marker


def settings(environment="render-development", enabled=True):
    return SimpleNamespace(AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=enabled, AI_QA_LUNA_DEV_ENABLED=True,
                           DEPLOYMENT_ENVIRONMENT=environment)


def test_admission_is_default_off_and_foreign_untouched():
    assert admission_marker(settings=SimpleNamespace(), tenant_id=QA_TENANT, user_id=uuid4(), course_id=None, source_first=False) is None
    assert admission_marker(settings=settings(), tenant_id=uuid4(), user_id=uuid4(), course_id=None, source_first=False) is None


@pytest.mark.parametrize("change", [{"course_id": uuid4()}, {"source_first": True}, {"user_id": None}])
def test_admission_rejects_existing_course_or_wrong_authority(change):
    values = dict(settings=settings(), tenant_id=QA_TENANT, user_id=uuid4(), course_id=None, source_first=False)
    with pytest.raises(ValueError):
        admission_marker(**(values | change))


def test_fresh_admission_and_worker_must_match_marker_and_flag():
    user = uuid4()
    assert admission_marker(settings=settings(), tenant_id=QA_TENANT, user_id=user, course_id=None, source_first=False) == POLICY
    assert check_worker_marker(settings=settings("render-development-worker"), tenant_id=QA_TENANT, user_id=user,
                               stored=POLICY, dispatched=POLICY, course_id=None)
    for stored, dispatched, cfg in [(POLICY, POLICY, settings("render-development-worker", False)),
                                     (POLICY, None, settings("render-development-worker")),
                                     (None, POLICY, settings("render-development-worker"))]:
        with pytest.raises(ValueError):
            check_worker_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user,
                                stored=stored, dispatched=dispatched, course_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('practical', [False, True])
async def test_managed_factory_configuration_is_bound_before_generation(monkeypatch, practical):
    from contextlib import nullcontext

    from app.core import config
    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import direct_luna_responses_factory, pipeline
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3 import owned_route_binding, owned_source_context, pending_stage_transactions, service
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, MANAGED_POLICY
    from app.modules.ai.v3.revision_policy import POLICY as REVISION
    from app.modules.ai.v3.revision_policy import PRACTICAL_REVIEW_POLICY, REVIEW_POLICY

    cfg = settings('render-development-worker')
    cfg.AI_MANAGED_LUNA_QA_DEV_ENABLED, cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = True, False
    monkeypatch.setattr(config, 'get_settings', lambda: cfg)
    user = uuid4()
    review = PRACTICAL_REVIEW_POLICY if practical else REVIEW_POLICY
    analysis = {KEY: MANAGED_POLICY, 'v3_revision_policy': REVISION, 'v3_review_policy': review}
    locked = SimpleNamespace(params={'source_analysis': analysis}, course_id=None, result={})
    monkeypatch.setattr(pending_stage_transactions, '_locked_job', AsyncMock(return_value=locked))
    monkeypatch.setattr(pipeline, '_load_owned_revision_policy', AsyncMock(return_value=REVISION))
    monkeypatch.setattr(pipeline, '_load_owned_generation_analysis', AsyncMock(return_value=analysis))
    monkeypatch.setattr(pipeline, '_load_owned_reference_decisions', AsyncMock(return_value=()))
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(pipeline, 'async_session_factory', Session)
    corpus = SimpleNamespace(tenant_id=str(QA_TENANT), document_ids=['doc'])
    context = SimpleNamespace(corpus=corpus, verify_locked=AsyncMock(return_value=True))
    monkeypatch.setattr(owned_source_context, 'load_owned_source_context', AsyncMock(return_value=context))
    async def create(**kwargs):
        profile = kwargs.get('profile') == 'luna6'
        return ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=kwargs['tenant_id'], user_id=kwargs['user_id'], job_id=kwargs['job_id'],
            credential_revision='r1', model='gpt-6-luna' if profile else 'gpt-5.6-luna',
            reasoning_effort='high' if profile else kwargs.get('reasoning_effort', 'low'),
            deadline_seconds=300 if profile else kwargs.get('deadline_seconds', 60))
    factory = AsyncMock(side_effect=create)
    monkeypatch.setattr(direct_luna_responses_factory, 'create_managed_qa_client', factory)
    bound = {}
    async def bind(*, journal, user_id, client):
        bound['client'], bound['fingerprint'] = client, client.cache_fingerprint()
        bound['deadline'] = client.generation_deadline_seconds
        return bound['fingerprint']
    monkeypatch.setattr(owned_route_binding, 'bind_owned_route', AsyncMock(side_effect=bind))
    monkeypatch.setattr(runtime, 'resolve_runtime_settings', AsyncMock(return_value=SimpleNamespace(number=lambda _n: 0.2)))
    monkeypatch.setattr(runtime, 'runtime_settings_scope', lambda _value: nullcontext())
    async def stop(*_args, **kwargs):
        assert kwargs['direct_client'] is bound['client']
        assert kwargs['route_fingerprint'] == bound['fingerprint'] == bound['client'].cache_fingerprint()
        raise RuntimeError('stopped_before_generation')
    monkeypatch.setattr(service, 'generate_v3_course_from_corpus', AsyncMock(side_effect=stop))
    state = SimpleNamespace(job_id='job', source_analysis=analysis)
    with pytest.raises(RuntimeError, match='stopped_before_generation'):
        await pipeline._run_v3_generation(state, corpus, tenant_id=QA_TENANT, user_id=user,
            target_audience='', guidance=None, goals=None, max_total_lessons=None)
    kwargs = factory.await_args.kwargs
    assert kwargs.get('profile') == ('luna6' if practical else None)
    assert bound['deadline'] == (300.0 if practical else 60.0)
    assert not check_worker_marker(settings=SimpleNamespace(), tenant_id=QA_TENANT, user_id=user,
                                   stored=None, dispatched=None, course_id=None)


@pytest.mark.asyncio
async def test_worker_selects_pending_journal_only_from_locked_job(monkeypatch):
    from app.core import config
    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import pipeline, qa_luna_dev_route
    from app.modules.ai.v3 import owned_source_context, pending_stage_transactions, service
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal

    user = uuid4()
    monkeypatch.setattr(config, "get_settings", lambda: settings("render-development-worker"))
    monkeypatch.setattr(pipeline, "_load_owned_reference_decisions", AsyncMock(return_value=()))
    monkeypatch.setattr(pipeline, "_load_owned_revision_policy", AsyncMock(return_value=None))
    locked = SimpleNamespace(params={"source_analysis": {"qa_luna_pending_journal_policy": POLICY}}, course_id=None)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", AsyncMock(return_value=locked))
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(pipeline, "async_session_factory", Session)
    corpus = SimpleNamespace(tenant_id=str(QA_TENANT), document_ids=["doc"])
    context = SimpleNamespace(corpus=corpus, verify_locked=AsyncMock(return_value=True))
    monkeypatch.setattr(owned_source_context, "load_owned_source_context", AsyncMock(return_value=context))
    client = SimpleNamespace(cache_fingerprint=lambda: "a" * 64)
    monkeypatch.setattr(qa_luna_dev_route, "qa_luna_dev_client", AsyncMock(return_value=client))
    class Policy:
        def number(self, name): return 0.2
    monkeypatch.setattr(runtime, "resolve_runtime_settings", AsyncMock(return_value=Policy()))
    from contextlib import nullcontext
    monkeypatch.setattr(runtime, "runtime_settings_scope", lambda value: nullcontext())
    generator = AsyncMock(side_effect=RuntimeError("stop after selection"))
    monkeypatch.setattr(service, "generate_v3_course_from_corpus", generator)
    state = SimpleNamespace(job_id="job", source_analysis={"qa_luna_pending_journal_policy": POLICY})
    with pytest.raises(RuntimeError, match="stop after selection"):
        await pipeline._run_v3_generation(state, corpus, tenant_id=QA_TENANT, user_id=user,
                                          target_audience="", guidance=None, goals=None, max_total_lessons=None)
    selected = generator.await_args.kwargs["extraction_journal"]
    assert generator.await_args.kwargs["authenticated_qa_policy"] == POLICY
    assert type(selected) is PendingStageJournal and selected.user_id == user and callable(selected.verify_source)
    assert await selected.verify_source(None, locked, {"synthetic": True}) is True
    locked.params["source_analysis"]["qa_luna_pending_journal_policy"] = "tampered"
    assert await selected.verify_source(None, locked, {"synthetic": True}) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("stored,dispatched", [(POLICY, None), (None, POLICY), (None, "invalid"), ("invalid", None)])
async def test_job_source_identity_rejects_route_marker_tampering(monkeypatch, stored, dispatched):
    from app.core import db as db_module
    from app.modules.ai import job_service, pipeline
    from app.modules.ai.v3.qa_luna_pending_policy import KEY

    tenant, user, document = QA_TENANT, uuid4(), uuid4()
    analysis = {"generation_engine": "evidence_v3"}
    if stored is not None:
        analysis[KEY] = stored
    job = SimpleNamespace(user_id=user, status="running", params={"documents": [str(document)],
        "source_analysis": analysis}, result={})
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def execute(self, *args, **kwargs): pass
    monkeypatch.setattr(db_module, "async_session_factory", Session)
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    with pytest.raises(pipeline.GenerationJobOwnerMismatchError):
        await pipeline._check_generation_source_job("job", tenant, [str(document)], user, "evidence_v3", dispatched)


@pytest.mark.asyncio
async def test_v2_legacy_fallback_is_available_without_pending_state(monkeypatch):
    from contextlib import nullcontext

    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import pipeline, qa_luna_dev_route

    class Policy:
        def number(self, _name): return 0.2
    monkeypatch.setattr(runtime, "resolve_runtime_settings", AsyncMock(return_value=Policy()))
    monkeypatch.setattr(runtime, "runtime_settings_scope", lambda _value: nullcontext())
    monkeypatch.setattr(qa_luna_dev_route, "qa_luna_dev_client", AsyncMock(return_value=None))
    fallback = AsyncMock(side_effect=RuntimeError("legacy fallback reached"))
    monkeypatch.setattr(pipeline.ResilientLLMClient, "from_settings_async", fallback)
    with pytest.raises(RuntimeError, match="legacy fallback reached"):
        await pipeline._run_evidence_v2_generation(SimpleNamespace(), SimpleNamespace(), tenant_id=uuid4(),
            target_audience="", guidance=None, goals=None, max_total_lessons=None)
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_v3_provider_unavailable_never_falls_back(monkeypatch):
    from contextlib import nullcontext

    from app.core import config
    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import pipeline, qa_luna_dev_route
    from app.modules.ai.v3 import owned_source_context, pending_stage_transactions
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError

    user = uuid4()
    monkeypatch.setattr(config, "get_settings", lambda: settings("render-development-worker"))
    monkeypatch.setattr(pipeline, "_load_owned_reference_decisions", AsyncMock(return_value=()))
    monkeypatch.setattr(pipeline, "_load_owned_revision_policy", AsyncMock(return_value=None))
    locked = SimpleNamespace(params={"source_analysis": {"qa_luna_pending_journal_policy": POLICY}}, course_id=None)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", AsyncMock(return_value=locked))
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(pipeline, "async_session_factory", Session)
    corpus = SimpleNamespace(tenant_id=str(QA_TENANT), document_ids=["doc"])
    monkeypatch.setattr(owned_source_context, "load_owned_source_context", AsyncMock(return_value=
        SimpleNamespace(corpus=corpus, verify_locked=AsyncMock(return_value=True))))
    monkeypatch.setattr(qa_luna_dev_route, "qa_luna_dev_client", AsyncMock(return_value=None))
    class Policy:
        def number(self, _name): return 0.2
    monkeypatch.setattr(runtime, "resolve_runtime_settings", AsyncMock(return_value=Policy()))
    monkeypatch.setattr(runtime, "runtime_settings_scope", lambda _value: nullcontext())
    fallback = AsyncMock(side_effect=AssertionError("fallback forbidden"))
    monkeypatch.setattr(pipeline.ResilientLLMClient, "from_settings_async", fallback)
    state = SimpleNamespace(job_id="job", source_analysis={"qa_luna_pending_journal_policy": POLICY})
    with pytest.raises(ExtractionOutcomeUnknownError, match="qa_luna_pending_provider_unavailable"):
        await pipeline._run_v3_generation(state, corpus, tenant_id=QA_TENANT, user_id=user,
            target_audience="", guidance=None, goals=None, max_total_lessons=None)
    fallback.assert_not_awaited()


def test_direct_admission_is_server_scoped_and_flag_off_never_downgrades():
    from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY
    cfg = settings()
    cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    user = uuid4()
    assert admission_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user, course_id=None, source_first=False) == DIRECT_POLICY
    assert admission_marker(settings=cfg, tenant_id=uuid4(), user_id=user, course_id=None, source_first=False) is None
    cfg.DEPLOYMENT_ENVIRONMENT = "production"
    with pytest.raises(ValueError):
        admission_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user, course_id=None, source_first=False)
    cfg.DEPLOYMENT_ENVIRONMENT = "render-development-worker"
    assert check_worker_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user, stored=DIRECT_POLICY, dispatched=DIRECT_POLICY, course_id=None)
    cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = False
    with pytest.raises(ValueError):
        check_worker_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user, stored=DIRECT_POLICY, dispatched=DIRECT_POLICY, course_id=None)


def test_direct_factory_protects_secret_and_binds_rotation():
    from pydantic import SecretStr

    from app.modules.ai.direct_luna_responses_factory import create_direct_qa_responses_client
    cfg = settings("render-development-worker")
    cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    cfg.AI_DIRECT_LUNA_QA_API_KEY = SecretStr("synthetic-secret")
    cfg.AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION = "r1"
    user = uuid4()
    first = create_direct_qa_responses_client(settings=cfg, tenant_id=QA_TENANT, user_id=user, job_id="job")
    fingerprint = first.cache_fingerprint()
    assert "synthetic-secret" not in repr(first) and "synthetic-secret" not in fingerprint
    cfg.AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION = "r2"
    second = create_direct_qa_responses_client(settings=cfg, tenant_id=QA_TENANT, user_id=user, job_id="job")
    assert second.cache_fingerprint() != fingerprint
    cfg.AI_DIRECT_LUNA_QA_API_KEY = SecretStr("")
    with pytest.raises(ValueError):
        create_direct_qa_responses_client(settings=cfg, tenant_id=QA_TENANT, user_id=user, job_id="job")
    first.close()
    second.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_version", ["v2", "v3"])
async def test_worker_direct_marker_uses_direct_client_without_legacy_fallback(monkeypatch, policy_version):
    from pydantic import SecretStr

    from app.core import config
    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import pipeline, qa_luna_dev_route
    from app.modules.ai.v3 import owned_route_binding, owned_source_context, pending_stage_transactions, service
    from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, DIRECT_POLICY_V2

    marker = DIRECT_POLICY_V2 if policy_version == "v2" else DIRECT_POLICY

    cfg = settings("render-development-worker")
    cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    cfg.AI_DIRECT_LUNA_QA_API_KEY = SecretStr("synthetic-secret")
    cfg.AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION = "r1"
    user = uuid4()
    monkeypatch.setattr(config, "get_settings", lambda: cfg)
    monkeypatch.setattr(pipeline, "_load_owned_reference_decisions", AsyncMock(return_value=()))
    monkeypatch.setattr(pipeline, "_load_owned_revision_policy", AsyncMock(return_value=None))
    locked = SimpleNamespace(params={"source_analysis": {"qa_luna_pending_journal_policy": marker}}, course_id=None)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", AsyncMock(return_value=locked))
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(pipeline, "async_session_factory", Session)
    corpus = SimpleNamespace(tenant_id=str(QA_TENANT), document_ids=["doc"])
    context = SimpleNamespace(corpus=corpus, verify_locked=AsyncMock(return_value=True))
    monkeypatch.setattr(owned_source_context, "load_owned_source_context", AsyncMock(return_value=context))
    async def bind_route(*, journal, user_id, client):
        assert journal.user_id == user_id == user
        fingerprint = client.cache_fingerprint()
        locked.result = {owned_route_binding.KEY: {"policy": owned_route_binding.POLICY, "fingerprint": fingerprint}}
        return fingerprint
    binding = AsyncMock(side_effect=bind_route)
    monkeypatch.setattr(owned_route_binding, "bind_owned_route", binding)
    legacy = AsyncMock(side_effect=AssertionError("legacy fallback forbidden"))
    monkeypatch.setattr(qa_luna_dev_route, "qa_luna_dev_client", legacy)
    class Policy:
        def number(self, _name): return 0.2
    monkeypatch.setattr(runtime, "resolve_runtime_settings", AsyncMock(return_value=Policy()))
    from contextlib import nullcontext
    monkeypatch.setattr(runtime, "runtime_settings_scope", lambda _value: nullcontext())
    async def stop_after_selection(*_args, **kwargs):
        assert await kwargs["extraction_journal"].verify_source(None, locked, {"synthetic": True}) is True
        raise RuntimeError("stop after selection")
    generator = AsyncMock(side_effect=stop_after_selection)
    monkeypatch.setattr(service, "generate_v3_course_from_corpus", generator)
    state = SimpleNamespace(job_id="job", source_analysis={"qa_luna_pending_journal_policy": marker})
    with pytest.raises(RuntimeError, match="stop after selection"):
        await pipeline._run_v3_generation(state, corpus, tenant_id=QA_TENANT, user_id=user,
                                          target_audience="", guidance=None, goals=None, max_total_lessons=None)
    client = generator.await_args.kwargs["direct_client"]
    assert generator.await_args.kwargs["authenticated_qa_policy"] == marker
    assert generator.await_args.kwargs["owned_source_context"] is context
    assert client is generator.await_args.kwargs["generation_client"] and client._closed
    selected = generator.await_args.kwargs["extraction_journal"]
    assert await selected.verify_source(None, locked, {"synthetic": True}) is (policy_version == "v2")
    legacy.assert_not_awaited()
    assert binding.await_count == (1 if policy_version == "v3" else 0)
    generator.reset_mock()
    locked.params["source_analysis"]["qa_luna_pending_journal_policy"] = POLICY
    assert await selected.verify_source(None, locked, {"synthetic": True}) is False
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    with pytest.raises(ExtractionOutcomeUnknownError, match="route_unverified"):
        await pipeline._run_v3_generation(state, corpus, tenant_id=QA_TENANT, user_id=user,
                                          target_audience="", guidance=None, goals=None, max_total_lessons=None)
    generator.assert_not_awaited()


def test_previous_direct_policy_is_not_reinterpreted_by_new_worker():
    from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, DIRECT_POLICY_V1, DIRECT_POLICY_V2

    cfg = settings()
    cfg.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    cfg.DEPLOYMENT_ENVIRONMENT = "render-development-worker"
    user = uuid4()
    assert DIRECT_POLICY != DIRECT_POLICY_V1
    assert check_worker_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user,
                               stored=DIRECT_POLICY_V2, dispatched=DIRECT_POLICY_V2, course_id=None)
    for stored, dispatched in ((DIRECT_POLICY_V1, DIRECT_POLICY_V1),
                               (DIRECT_POLICY_V1, DIRECT_POLICY), (DIRECT_POLICY, DIRECT_POLICY_V1),
                               (DIRECT_POLICY_V2, DIRECT_POLICY), (DIRECT_POLICY, DIRECT_POLICY_V2)):
        with pytest.raises(ValueError, match="qa_luna_pending_worker_unavailable"):
            check_worker_marker(settings=cfg, tenant_id=QA_TENANT, user_id=user,
                                stored=stored, dispatched=dispatched, course_id=None)
