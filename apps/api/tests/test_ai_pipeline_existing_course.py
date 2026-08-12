"""Regression coverage for generating into a pre-created source course."""

from uuid import uuid4

import pytest

from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.pipeline import GenerationState, _save_generation_to_db
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.modules.courses.models import Course
from app.modules.lessons.models import Module as CourseModule  # noqa: F401 - registers ORM relationship
from app.modules.quizzes.models import Question


def test_course_model_registers_instruction_source_table() -> None:
    assert "documents" in Course.metadata.tables


class FakeSession:
    def __init__(self, course: Course):
        self.course = course
        self.added = []
        self.executed = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scalar(self, statement):
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


@pytest.mark.asyncio
async def test_generated_single_answer_questions_are_saved_as_mcq(monkeypatch):
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
            modules=[ModuleContent(title="Module", lessons=[LessonContent(title=lesson_title, content="Body")])],
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

    questions = [value for value in session.added if isinstance(value, Question)]
    assert [question.type for question in questions] == ["MCQ"]
