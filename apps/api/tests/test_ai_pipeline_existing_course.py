"""Regression coverage for generating into a pre-created source course."""

from uuid import uuid4

import pytest

from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.pipeline import GenerationState, _save_generation_to_db
from app.modules.ai.writer_schema import CourseContent
from app.modules.courses.models import Course
from app.modules.lessons.models import Module  # noqa: F401 - registers ORM relationship


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
