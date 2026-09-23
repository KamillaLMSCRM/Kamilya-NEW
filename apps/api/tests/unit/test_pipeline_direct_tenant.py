from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import pipeline
from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


@pytest.mark.asyncio
async def test_course_generation_rejects_retired_engine_before_source_or_provider_calls(monkeypatch):
    """Only evidence_v2 may execute, including direct/internal invocations."""
    tenant_id = uuid4()
    load_corpus = AsyncMock(side_effect=AssertionError("source loader called"))
    create_llm = AsyncMock(side_effect=AssertionError("provider called"))
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock())
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", load_corpus)
    monkeypatch.setattr(
        pipeline.ResilientLLMClient,
        "from_settings_async",
        create_llm,
    )
    monkeypatch.setattr(
        pipeline,
        "_release_generation_reservation",
        AsyncMock(return_value=True),
    )

    state = await pipeline.run_generation_pipeline(
        str(uuid4()),
        documents=[str(uuid4())],
        tenant_id=tenant_id,
        source_analysis={"analysis_mode": "direct_source"},
    )

    assert state.status == "failed"
    assert state.errors == ["generation_engine_retired"]
    load_corpus.assert_not_awaited()
    create_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_evidence_v2_job_uses_single_generation_and_save(monkeypatch):
    from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
    from app.modules.ai.direct_source import DirectSourceCorpus
    from app.modules.ai.evidence_engine.application import GenerationArtifacts

    tenant_id, user_id, doc_id = uuid4(), uuid4(), str(uuid4())
    corpus = DirectSourceCorpus(
        tenant_id=str(tenant_id),
        documents=(),
        total_chars=100,
        total_chunks=1,
    )
    structure = CourseStructure(
        title="Evidence V2",
        modules=[Module(title="Module", lessons=[Lesson(title="Lesson", source_doc_ids=[doc_id])])],
    )
    content = CourseContent(
        title="Evidence V2",
        modules=[ModuleContent(title="Module", lessons=[LessonContent(title="Lesson", content="Grounded")])],
    )
    artifacts = GenerationArtifacts(
        structure=structure,
        content=content,
        assessment=CourseAssessment(assessments=[LessonAssessment("Lesson")]),
        diagnostics={"engine": "evidence_v2", "lesson_count": 1, "question_count": 0},
    )
    generated = SimpleNamespace(result=SimpleNamespace(), corpus=corpus)
    generate = AsyncMock(return_value=generated)
    from unittest.mock import Mock

    convert = Mock(return_value=artifacts)
    save = AsyncMock()

    async def save_success(state, *_args):
        state.status = "completed"

    save.side_effect = save_success
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock())
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=corpus))
    monkeypatch.setattr(pipeline, "generate_evidence_course", generate)
    monkeypatch.setattr(pipeline, "to_generation_artifacts", convert)
    generation_factory = AsyncMock(return_value=object())
    monkeypatch.setattr(
        pipeline.ResilientLLMClient,
        "from_settings_async",
        generation_factory,
    )
    monkeypatch.setattr(pipeline.ResilientEmbeddingsClient, "from_settings_async", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, "_save_generation_to_db", save)

    state = await pipeline.run_generation_pipeline(
        str(uuid4()),
        documents=[doc_id],
        tenant_id=tenant_id,
        user_id=user_id,
        guidance="Train the employee",
        max_total_lessons=2,
        source_analysis={
            "analysis_mode": "direct_source",
            "generation_engine": "evidence_v2",
        },
    )

    assert state.status == "completed"
    assert state.structure is structure
    assert state.content is content
    assert state.assessment is artifacts.assessment
    assert state.source_analysis["evidence_v2"] == artifacts.diagnostics
    generate.assert_awaited_once()
    assert generate.await_args.kwargs["max_lessons"] == 2
    generation_factory.assert_awaited_once_with(tenant_id=tenant_id, temperature=0.2)
    save.assert_awaited_once_with(state, tenant_id, user_id)


@pytest.mark.asyncio
async def test_new_evidence_v2_save_failure_refunds_reserved_generation(monkeypatch):
    from app.modules.ai.assessment_schema import CourseAssessment
    from app.modules.ai.direct_source import DirectSourceCorpus
    from app.modules.ai.evidence_engine.application import GenerationArtifacts

    tenant_id, user_id, doc_id = uuid4(), uuid4(), str(uuid4())
    corpus = DirectSourceCorpus(
        tenant_id=str(tenant_id), documents=(), total_chars=100, total_chunks=1
    )
    artifacts = GenerationArtifacts(
        structure=CourseStructure(title="Candidate"),
        content=CourseContent(title="Candidate"),
        assessment=CourseAssessment(),
        diagnostics={"engine": "evidence_v2"},
    )

    async def failed_save(state, *_args):
        state.course_id = str(uuid4())
        raise RuntimeError("synthetic post-flush failure")

    release = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock())
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=corpus))
    monkeypatch.setattr(
        pipeline,
        "generate_evidence_course",
        AsyncMock(return_value=SimpleNamespace(result=SimpleNamespace(), corpus=corpus)),
    )
    monkeypatch.setattr(pipeline, "to_generation_artifacts", lambda _value: artifacts)
    monkeypatch.setattr(
        pipeline.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        pipeline.ResilientEmbeddingsClient,
        "from_settings_async",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(pipeline, "_save_generation_to_db", AsyncMock(side_effect=failed_save))
    monkeypatch.setattr(pipeline, "_release_generation_reservation", release)

    state = await pipeline.run_generation_pipeline(
        str(uuid4()),
        documents=[doc_id],
        tenant_id=tenant_id,
        user_id=user_id,
        source_analysis={
            "analysis_mode": "direct_source",
            "generation_engine": "evidence_v2",
        },
    )

    assert state.status == "failed"
    release.assert_awaited_once_with(state.job_id, tenant_id)


@pytest.mark.asyncio
async def test_failure_status_write_cannot_skip_reserved_generation_cleanup(monkeypatch):
    tenant_id = uuid4()
    update = AsyncMock(side_effect=RuntimeError("synthetic status write failure"))
    release = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline, "_update_job_db", update)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", release)

    state = await pipeline.run_generation_pipeline(
        str(uuid4()),
        documents=[],
        tenant_id=tenant_id,
        source_analysis={
            "analysis_mode": "direct_source",
            "generation_engine": "evidence_v2",
        },
    )

    assert state.status == "failed"
    release.assert_awaited_once_with(state.job_id, tenant_id)


@pytest.mark.asyncio
async def test_new_course_cancellation_releases_reservation_once(monkeypatch):
    import asyncio

    tenant_id, doc_id = uuid4(), str(uuid4())
    release = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock())
    monkeypatch.setattr(
        pipeline,
        "load_direct_source_corpus",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    monkeypatch.setattr(pipeline, "_release_generation_reservation", release)

    state = await pipeline.run_generation_pipeline(
        str(uuid4()),
        documents=[doc_id],
        tenant_id=tenant_id,
        source_analysis={
            "analysis_mode": "direct_source",
            "generation_engine": "evidence_v2",
        },
    )

    assert state.status == "cancelled"
    release.assert_awaited_once_with(state.job_id, tenant_id)


def test_completed_progress_counts_only_persisted_lessons() -> None:
    content = CourseContent(
        title="Synthetic",
        modules=[
            ModuleContent(title="One", lessons=[
                LessonContent(title="A", content="a", objectives=["a"]),
                LessonContent(title="B", content="b", objectives=["b"]),
            ]),
            ModuleContent(title="Two", lessons=[
                LessonContent(title="C", content="c", objectives=["c"]),
            ]),
        ],
    )

    assert pipeline._completed_progress_detail(content) == {
        "current": 3,
        "total": 3,
        "estimated_remaining_seconds": 0,
    }
