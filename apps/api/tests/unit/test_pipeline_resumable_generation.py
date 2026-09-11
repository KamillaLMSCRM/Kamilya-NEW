from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.generation_checkpoint import (
    AIGenerationCheckpointError,
    GenerationCheckpointSnapshot,
    GenerationPlan,
)
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


class _MemoryCheckpoints:
    def __init__(self):
        self.plan: GenerationPlan | None = None
        self.snapshots: list[GenerationCheckpointSnapshot] = []

    async def load_plan(self, session, *, tenant_id, generation_key):
        if self.plan is None:
            raise AIGenerationCheckpointError("generation_plan_not_found")
        return self.plan

    async def create_plan(self, session, *, generation_key, plan_revision, source_job_id, plan_payload, lessons, **kwargs):
        if self.plan is None:
            self.plan = GenerationPlan(
                generation_key=generation_key,
                plan_revision=plan_revision,
                source_job_id=source_job_id,
                plan_payload=plan_payload,
                lessons=tuple(lessons),
            )
            self.snapshots = [
                GenerationCheckpointSnapshot(
                    module_key=item.module_key,
                    lesson_key=item.lesson_key,
                    module_order=item.module_order,
                    lesson_order=item.lesson_order,
                    content_payload=None,
                    review_payload=None,
                    assessment_payload=None,
                )
                for item in lessons
            ]
        return self.plan

    async def load_checkpoints(self, session, **kwargs):
        return tuple(self.snapshots)

    def _index(self, module_key, lesson_key):
        return next(
            index
            for index, item in enumerate(self.snapshots)
            if (item.module_key, item.lesson_key) == (module_key, lesson_key)
        )

    async def checkpoint_content(self, session, *, module_key, lesson_key, content_payload, **kwargs):
        index = self._index(module_key, lesson_key)
        self.snapshots[index] = replace(
            self.snapshots[index], content_payload=content_payload,
        )

    async def checkpoint_assessment(self, session, *, module_key, lesson_key, assessment_payload, **kwargs):
        index = self._index(module_key, lesson_key)
        self.snapshots[index] = replace(
            self.snapshots[index], assessment_payload=assessment_payload,
        )

    async def checkpoint_review(self, session, *, module_key, lesson_key, review_payload, **kwargs):
        index = self._index(module_key, lesson_key)
        self.snapshots[index] = replace(
            self.snapshots[index], review_payload=review_payload,
        )

    async def claim_item(self, session, **kwargs):
        return SimpleNamespace(**kwargs)

    async def release_leases(self, session, **kwargs):
        return None

    async def assert_complete(self, session, **kwargs):
        assert len(self.snapshots) == 25
        assert all(item.content_payload is not None for item in self.snapshots)
        assert all(item.review_payload is not None for item in self.snapshots)
        assert all(item.assessment_payload is not None for item in self.snapshots)


@pytest.mark.asyncio
async def test_pipeline_resumes_15_of_25_without_repeating_completed_lessons(monkeypatch):
    from app.modules.ai import pipeline
    from app.modules.ai.direct_source import DirectSourceCorpus

    tenant_id = uuid4()
    document_id = str(uuid4())
    structure = CourseStructure(
        title="Synthetic catalog",
        modules=[
            Module(
                title=f"Module {module_index + 1}",
                lessons=[
                    Lesson(
                        title=f"Lesson {module_index * 5 + lesson_index + 1}",
                        source_doc_ids=[document_id],
                    )
                    for lesson_index in range(5)
                ],
            )
            for module_index in range(5)
        ],
    )
    checkpoints = _MemoryCheckpoints()
    architect_calls = 0
    writer_provider_calls: list[str] = []
    reviewer_provider_calls: list[str] = []
    assessment_provider_calls: list[str] = []

    async def load_corpus(*args, **kwargs):
        return DirectSourceCorpus(
            tenant_id=str(tenant_id), documents=(), total_chars=1000, total_chunks=100,
        )

    async def architect(*args, **kwargs):
        nonlocal architect_calls
        architect_calls += 1
        return structure

    async def writer(*args, completed_lessons=None, before_lesson_generate=None, on_lesson_complete=None, on_progress=None, **kwargs):
        restored = completed_lessons or {}
        modules: list[ModuleContent] = []
        available = 0
        for module_index, module in enumerate(structure.modules):
            lessons: list[LessonContent] = []
            for lesson_index, planned in enumerate(module.lessons):
                key = (module_index, lesson_index)
                content = restored.get(key)
                if content is None:
                    await before_lesson_generate(module_index, lesson_index)
                    writer_provider_calls.append(planned.title)
                    content = LessonContent(title=planned.title, content=f"Content {planned.title}")
                    await on_lesson_complete(module_index, lesson_index, content)
                    if len(writer_provider_calls) == 15:
                        raise SoftTimeLimitExceeded()
                lessons.append(content)
                available += 1
                if on_progress:
                    await on_progress(f"Completed lesson {available}/25: {planned.title}")
            modules.append(ModuleContent(title=module.title, lessons=lessons))
        return CourseContent(title=structure.title, modules=modules)

    async def assessments(*, course_content, completed_assessments=None, before_assessment_generate=None, on_assessment_complete=None, on_progress=None, **kwargs):
        restored = completed_assessments or {}
        result: list[LessonAssessment] = []
        for module_index, module in enumerate(course_content.modules):
            for lesson_index, lesson in enumerate(module.lessons):
                item = restored.get((module_index, lesson_index))
                if item is None:
                    await before_assessment_generate(module_index, lesson_index)
                    assessment_provider_calls.append(lesson.title)
                    item = LessonAssessment(lesson_title=lesson.title)
                    await on_assessment_complete(module_index, lesson_index, item)
                result.append(item)
                if on_progress:
                    await on_progress(f"Assessment: {lesson.title}")
        return CourseAssessment(assessments=result)

    class LLMFactory:
        @classmethod
        async def from_settings_async(cls, **kwargs):
            return object()

    class Reviewer:
        def __init__(self, llm_client):
            pass

        async def review_lesson(self, **kwargs):
            reviewer_provider_calls.append(kwargs["lesson_meta"]["title"])
            return {"quality_score": 10.0, "issues": []}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline, "load_direct_source_corpus", load_corpus)
    monkeypatch.setattr(pipeline, "run_direct_architect", architect)
    monkeypatch.setattr(pipeline, "write_direct_course", writer)
    monkeypatch.setattr(pipeline, "generate_course_assessment", assessments)
    monkeypatch.setattr(pipeline, "ResilientLLMClient", LLMFactory)
    monkeypatch.setattr(pipeline, "ReviewerAgent", Reviewer)
    monkeypatch.setattr(pipeline, "_update_job_db", noop)
    monkeypatch.setattr(pipeline, "_check_cancelled_async", noop)

    kwargs = {
        "job_id": str(uuid4()),
        "documents": [document_id],
        "tenant_id": tenant_id,
        "source_analysis": {"analysis_mode": "direct_source"},
        "num_modules": 5,
        "lessons_per_module": 5,
        "max_total_lessons": 25,
        "generation_checkpoint_repository": checkpoints,
    }
    first = await pipeline.run_generation_pipeline(**kwargs)
    assert first.status == "interrupted"
    assert len(writer_provider_calls) == 15
    assert reviewer_provider_calls == []
    assert assessment_provider_calls == []
    assert sum(item.content_payload is not None for item in checkpoints.snapshots) == 15

    second = await pipeline.run_generation_pipeline(**kwargs)
    assert second.status == "completed"
    assert architect_calls == 1
    assert writer_provider_calls == [f"Lesson {index}" for index in range(1, 26)]
    assert reviewer_provider_calls == [f"Lesson {index}" for index in range(1, 26)]
    assert assessment_provider_calls == [f"Lesson {index}" for index in range(1, 26)]
    assert [item.title for module in second.content.modules for item in module.lessons] == [
        f"Lesson {index}" for index in range(1, 26)
    ]

    third = await pipeline.run_generation_pipeline(**kwargs)
    assert third.status == "completed"
    assert architect_calls == 1
    assert len(writer_provider_calls) == 25
    assert len(reviewer_provider_calls) == 25
    assert len(assessment_provider_calls) == 25
