"""Regression coverage for generating into a pre-created source course."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.pipeline import (
    GENERATION_FAILURE_CODE,
    GENERATION_FAILURE_MESSAGE,
    GenerationState,
    _save_generation_to_db,
    run_generation_pipeline,
)
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson
from app.modules.lessons.models import Module as CourseModule
from app.modules.quizzes.models import Question, Quiz, QuizChoice


def test_course_model_registers_instruction_source_table() -> None:
    assert "documents" in Course.metadata.tables


class FakeSession:
    def __init__(self, course: Course, job=None):
        self.course = course
        self.job = job or SimpleNamespace(
            id="active-job",
            tenant_id=course.tenant_id,
            status="running",
        )
        self.added = []
        self.executed = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scalar(self, statement):
        if "FROM ai_jobs" in str(statement):
            return self.job
        return self.course

    async def execute(self, statement, params=None):
        self.executed.append((statement, params))
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_quality_filtered_empty_quiz_preserves_lesson_and_named_warning(monkeypatch):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    course = Course(id=uuid4(), tenant_id=tenant_id, title="Draft", status="draft", created_by=uuid4())
    session = FakeSession(course)
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)
    title = "Synthetic safety procedure"
    state = GenerationState(
        job_id="synthetic-empty-quiz", course_id=str(course.id),
        structure=CourseStructure(title="Course", modules=[StructureModule(
            title="Module", lessons=[StructureLesson(title=title)])]),
        content=CourseContent(title="Course", modules=[ModuleContent(
            title="Module", lessons=[LessonContent(title=title, content="Verified lesson content.")])]),
        assessment=CourseAssessment(assessments=[LessonAssessment(
            lesson_title=title, quality_policy_version="assessment-drop-only-v1",
            omission_reason="no_valid_questions")]),
    )
    await _save_generation_to_db(state, tenant_id, course.created_by)
    assert session.committed
    assert len([v for v in session.added if isinstance(v, Lesson)]) == 1
    assert not any(isinstance(v, Quiz | Question | QuizChoice) for v in session.added)
    assert title in course.description and "без теста" in course.description
    assert title in session.job.message and "без теста" in session.job.message
    assert course.status == "draft"


@pytest.mark.asyncio
async def test_generation_updates_existing_course_without_duplicate_insert(monkeypatch):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    course = Course(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Placeholder",
        description="",
        status="draft",
        created_by=uuid4(),
        ai_generated=False,
    )
    session = FakeSession(course)
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)

    state = GenerationState(
        job_id="job-1",
        course_id=str(course.id),
        structure=CourseStructure(title="Generated title", description="Generated description"),
        content=CourseContent(title="Generated title"),
    )

    await _save_generation_to_db(state, tenant_id, course.created_by)

    assert session.added == []
    assert session.committed is True
    assert course.title == "Generated title"
    assert course.description == "Generated description"
    assert course.ai_generated is True
    assert session.job.status == "completed"
    assert session.job.stage == "completed"
    assert session.job.progress == 100
    assert session.job.course_id == course.id
    assert session.job.completed_at == session.job.updated_at
    # set_current_tenant + delete old module structure
    assert len(session.executed) == 2


@pytest.mark.asyncio
async def test_new_course_persists_reuse_reason_in_source_provenance(monkeypatch):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    placeholder = Course(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Unused",
        description="",
        status="draft",
        created_by=uuid4(),
    )
    session = FakeSession(placeholder)
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)

    state = GenerationState(
        job_id="job-reuse",
        structure=CourseStructure(title="Different audience course"),
        content=CourseContent(title="Different audience course"),
        source_analysis={"status": "compatible"},
        reuse_reason="different_audience",
    )

    await _save_generation_to_db(state, tenant_id, placeholder.created_by)

    created = next(value for value in session.added if isinstance(value, Course))
    assert created.source_analysis == {
        "status": "compatible",
        "reuse_reason": "different_audience",
    }
    assert created.status == "draft"
    assert created.id != placeholder.id
    assert state.course_id == str(created.id)
    assert session.job.status == "completed"
    assert session.job.course_id == created.id


@pytest.mark.asyncio
async def test_new_course_id_is_not_exposed_before_transaction_commit(monkeypatch):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    placeholder = Course(
        id=uuid4(), tenant_id=tenant_id, title="Unused", status="draft", created_by=uuid4()
    )
    session = FakeSession(placeholder)

    async def fail_commit():
        raise RuntimeError("synthetic commit failure")

    session.commit = fail_commit
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)
    state = GenerationState(
        job_id="commit-failure",
        structure=CourseStructure(title="Candidate"),
        content=CourseContent(title="Candidate"),
    )

    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await _save_generation_to_db(state, tenant_id, placeholder.created_by)

    assert state.course_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("source_text,explicit_status,expected_source_status", [
    ("Source facts", "verified", "verified"),
    ("Rate: [UNREADABLE_PERCENTAGE_VALUE]", "verified", "needs_review"),
    ("Deterministic source-only fallback", "needs_review", "needs_review"),
])
async def test_generated_single_answer_questions_are_saved_as_mcq(
    monkeypatch, source_text, explicit_status, expected_source_status
):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    course = Course(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Placeholder",
        description="",
        status="draft",
        created_by=uuid4(),
        ai_generated=False,
    )
    session = FakeSession(course)
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)

    lesson_title = "Single-answer lesson"
    state = GenerationState(
        job_id="job-2",
        course_id=str(course.id),
        structure=CourseStructure(
            title="Generated title",
            modules=[StructureModule(title="Module", lessons=[StructureLesson(title=lesson_title)])],
        ),
        content=CourseContent(
            title="Generated title",
            modules=[ModuleContent(title="Module", lessons=[LessonContent(
                title=lesson_title,
                content="Body",
                source_chunks=[source_text],
                source_validation_status=explicit_status,
            )])],
        ),
        assessment=CourseAssessment(
            assessments=[
                LessonAssessment(
                    lesson_title=lesson_title,
                    mcq=[
                        MCQQuestion(
                            question="Which answer is correct?",
                            options=[
                                MCQOption(text="Correct", is_correct=True),
                                MCQOption(text="Incorrect", is_correct=False),
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    await _save_generation_to_db(state, tenant_id, course.created_by)

    modules = [value for value in session.added if isinstance(value, CourseModule)]
    lessons = [value for value in session.added if isinstance(value, Lesson)]
    quizzes = [value for value in session.added if isinstance(value, Quiz)]
    questions = [value for value in session.added if isinstance(value, Question)]
    choices = [value for value in session.added if isinstance(value, QuizChoice)]

    assert len(modules) == 1
    assert modules[0].tenant_id == tenant_id
    assert len(lessons) == 1
    assert lessons[0].tenant_id == tenant_id
    assert lessons[0].source_validation_status == expected_source_status
    assert len(quizzes) == 1
    assert quizzes[0].tenant_id == tenant_id
    assert [question.type for question in questions] == ["MCQ"]
    assert [choice.text for choice in choices] == ["Correct", "Incorrect"]
    assert [choice.is_correct for choice in choices] == [True, False]
    assert session.committed is True


@pytest.mark.asyncio
async def test_generated_mcq_correct_answers_are_balanced_across_persisted_positions(monkeypatch):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    course = Course(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Placeholder",
        description="",
        status="draft",
        created_by=uuid4(),
        ai_generated=False,
    )
    session = FakeSession(course)
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)

    lesson_title = "Balanced answers"
    questions = [
        MCQQuestion(
            question=f"Question {index + 1}?",
            options=[
                MCQOption(text=f"Correct {index + 1}", is_correct=True),
                MCQOption(text=f"Wrong A {index + 1}", is_correct=False),
                MCQOption(text=f"Wrong B {index + 1}", is_correct=False),
                MCQOption(text=f"Wrong C {index + 1}", is_correct=False),
            ],
        )
        for index in range(4)
    ]
    state = GenerationState(
        job_id="job-balanced",
        course_id=str(course.id),
        structure=CourseStructure(
            title="Generated title",
            modules=[StructureModule(title="Module", lessons=[StructureLesson(title=lesson_title)])],
        ),
        content=CourseContent(
            title="Generated title",
            modules=[ModuleContent(title="Module", lessons=[LessonContent(title=lesson_title, content="Body")])],
        ),
        assessment=CourseAssessment(
            assessments=[LessonAssessment(lesson_title=lesson_title, mcq=questions)]
        ),
    )

    await _save_generation_to_db(state, tenant_id, course.created_by)

    choices = [value for value in session.added if isinstance(value, QuizChoice)]
    persisted_questions = [choices[index : index + 4] for index in range(0, len(choices), 4)]
    assert [
        next(choice.order_index for choice in question_choices if choice.is_correct)
        for question_choices in persisted_questions
    ] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_cancelled_generation_does_not_persist_a_new_course(monkeypatch):
    from app.modules.ai import pipeline

    tenant_id = uuid4()
    placeholder = Course(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Unused",
        description="",
        status="draft",
        created_by=uuid4(),
    )
    session = FakeSession(
        placeholder,
        SimpleNamespace(
            id="cancelled-job",
            tenant_id=tenant_id,
            status="cancelled",
        )
    )
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)
    state = GenerationState(
        job_id="cancelled-job",
        structure=CourseStructure(title="Must not be saved"),
        content=CourseContent(title="Must not be saved"),
    )

    with pytest.raises(__import__("asyncio").CancelledError):
        await _save_generation_to_db(state, tenant_id, uuid4())

    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_pipeline_persists_only_bounded_failure_diagnostics(monkeypatch):
    from app.modules.ai import pipeline

    updates = []

    async def fail_then_capture(job_id, tenant_id=None, **kwargs):
        if not updates:
            updates.append(kwargs)
            raise RuntimeError("secret provider endpoint and tenant content")
        updates.append(kwargs)

    monkeypatch.setattr(pipeline, "_update_job_db", fail_then_capture)
    monkeypatch.setattr(
        pipeline,
        "_release_generation_reservation",
        AsyncMock(return_value=True),
    )

    state = await run_generation_pipeline(
        "failed-job",
        documents=[],
        tenant_id=uuid4(),
        source_analysis={
            "analysis_mode": "direct_source",
            "generation_engine": "evidence_v2",
        },
    )

    assert state.status == "failed"
    assert state.message == GENERATION_FAILURE_MESSAGE
    assert state.errors == [GENERATION_FAILURE_CODE]
    assert "secret" not in state.message
    assert updates[-1]["message"] == GENERATION_FAILURE_MESSAGE
    assert updates[-1]["errors"] == [GENERATION_FAILURE_CODE]
