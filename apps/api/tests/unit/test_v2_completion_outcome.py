"""Completion contract with real persistence code and an in-memory session boundary."""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from app.core import db
from app.models.ai_job import AIJob
from app.modules.ai import pipeline
from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson as SavedLesson
from app.modules.quizzes.models import Question, Quiz


def _artifacts(question_count=0):
    titles = ["Equipment", "Procedure"]
    question = MCQQuestion(
        "How is Alpha powered?",
        [MCQOption("Solar", True), MCQOption("Diesel", False), MCQOption("Mains", False)],
    )
    return GenerationArtifacts(
        structure=CourseStructure("Synthetic", modules=[Module("Module", lessons=[Lesson(t) for t in titles])]),
        content=CourseContent("Synthetic", modules=[ModuleContent("Module", [
            LessonContent(t, content="Alpha uses solar power.") for t in titles
        ])]),
        assessment=CourseAssessment([
            LessonAssessment(titles[0], mcq=[question] if question_count else []),
            LessonAssessment(titles[1]),
        ]),
        diagnostics={
            "engine": "evidence_v2", "question_count": question_count,
            "assessment_review": {
                "accepted": question_count, "reasons": ["unsupported_answer"],
                "coverage": {"requires_review": False},
            },
        },
    )


class MemorySession:
    def __init__(self, job):
        self.job = job
        self.rows = []
        self.commits = []
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, statement, *_args):
        self.statements.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: self.job)

    async def scalar(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        if entity is AIJob:
            return self.job
        assert entity is Course
        return next(row for row in self.rows if isinstance(row, Course))

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        self.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits.append((self.job.status, self.job.course_id, self.job.errors, self.job.result))


@pytest.fixture
def harness(monkeypatch):
    import asyncpg

    # Any missed database mock fails before attempting a socket connection.
    monkeypatch.setattr(asyncpg, "connect", AsyncMock(side_effect=AssertionError("DB forbidden")))
    tenant_id, user_id = uuid4(), uuid4()
    job = SimpleNamespace(
        id=str(uuid4()), tenant_id=tenant_id, user_id=user_id, course_id=None,
        status="running", stage="ingestion", progress=5, message="", errors=None,
        completed_at=None, updated_at=datetime.now(UTC),
        params={"documents": [str(uuid4())], "generation_reservation_required": True},
        result={"delivery_task_id": "delivery-1", "resume_count": 0},
    )
    session = MemorySession(job)
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: session)
    monkeypatch.setattr(db, "async_session_factory", lambda: session)
    corpus = DirectSourceCorpus(str(tenant_id), (), 10, 1)
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=corpus))
    generate = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(pipeline, "generate_evidence_course", generate)
    artifacts = _artifacts()
    convert = Mock(return_value=artifacts)
    monkeypatch.setattr(pipeline, "to_generation_artifacts", convert)
    monkeypatch.setattr(pipeline.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline.ResilientEmbeddingsClient, "from_settings_async", AsyncMock(return_value=object()))
    release = AsyncMock()
    monkeypatch.setattr(pipeline, "_release_generation_reservation", release)
    return SimpleNamespace(job=job, session=session, generate=generate, convert=convert,
                           artifacts=artifacts, release=release)


async def _run(harness, *, user=True, course_id=None):
    return await pipeline.run_generation_pipeline(
        harness.job.id, harness.job.params["documents"], tenant_id=harness.job.tenant_id,
        user_id=harness.job.user_id if user else None, course_id=course_id,
        source_analysis={"analysis_mode": "direct_source", "generation_engine": "evidence_v2"},
    )


@pytest.mark.asyncio
async def test_zero_questions_commits_review_required_draft_and_course_link(harness):
    state = await _run(harness)
    job = harness.job

    assert state.status == job.status == "interrupted"
    assert state.stage == job.stage == "interrupted"
    assert state.errors == job.errors == ["assessment_no_valid_questions"]
    assert "Уроки сохранены" in job.message and "Проверьте" in job.message
    assert state.progress == job.progress == 100
    assert job.completed_at is None and job.updated_at is not None
    assert UUID(state.course_id) == job.course_id
    assert harness.session.commits[-1][:3] == ("interrupted", job.course_id, state.errors)
    courses = [row for row in harness.session.rows if isinstance(row, Course)]
    assert len(courses) == 1 and courses[0].status == "draft"
    assert len([row for row in harness.session.rows if isinstance(row, SavedLesson)]) == 2
    assert not any(isinstance(row, Quiz | Question) for row in harness.session.rows)
    assert job.result["counts"] == {"modules": 1, "lessons": 2, "quizzes": 0, "questions": 0}
    assert job.result["course_id"] == state.course_id
    assert job.result["delivery_task_id"] == "delivery-1"
    assert job.params["progress_detail"] == {"current": 2, "total": 2, "estimated_remaining_seconds": 0}
    assert job.params["generation_reservation_required"] is True
    harness.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_substantive_topic_preserves_draft_instead_of_reporting_success(harness):
    artifacts = _artifacts(1)
    artifacts.diagnostics["assessment_review"]["coverage"] = {
        "requires_review": True, "missing_fact_ids": ["topic-b"],
    }
    harness.convert.return_value = artifacts
    state = await _run(harness)
    assert state.status == harness.job.status == "interrupted"
    assert state.errors == ["assessment_coverage_incomplete"]
    assert state.course_id
    assert harness.job.result["counts"]["questions"] == 1
    harness.generate.reset_mock()
    resumed = await _run(harness, course_id=state.course_id)
    assert resumed.errors == ["assessment_coverage_incomplete"]
    harness.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind, value", [
    ("missing", None),
    ("null", None),
    ("list", []),
    ("non_bool", "false"),
])
async def test_missing_or_malformed_coverage_fails_closed_and_preserves_review_draft(harness, kind, value):
    artifacts = _artifacts(1)
    review = artifacts.diagnostics["assessment_review"]
    if kind == "missing":
        review.pop("coverage")
    elif kind == "non_bool":
        review["coverage"] = {"requires_review": value}
    else:
        review["coverage"] = value
    harness.convert.return_value = artifacts

    state = await _run(harness)

    assert state.status == harness.job.status == "interrupted"
    assert state.errors == harness.job.errors == ["assessment_coverage_incomplete"]
    assert state.course_id and harness.job.result["counts"]["questions"] == 1
    assert next(row for row in harness.session.rows if isinstance(row, Course)).status == "draft"
    harness.generate.reset_mock()
    resumed = await _run(harness, course_id=state.course_id)
    assert resumed.errors == ["assessment_coverage_incomplete"]
    harness.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_quiz_is_success_without_per_lesson_quota_and_keeps_review_metadata(harness):
    artifacts = _artifacts(1)
    artifacts.content.omitted_lesson_titles = ["Unavailable topic"]
    artifacts.content.source_warnings = ["Source section could not be realized"]
    harness.convert.return_value = artifacts

    state = await _run(harness)
    job = harness.job

    assert state.status == job.status == "completed"
    assert state.errors == job.errors == []
    assert job.completed_at is not None
    assert job.result["counts"] == {"modules": 1, "lessons": 2, "quizzes": 1, "questions": 1}
    assert len([row for row in harness.session.rows if isinstance(row, Quiz)]) == 1
    assert len([row for row in harness.session.rows if isinstance(row, Question)]) == 1
    assert job.result["assessment_review"] == artifacts.diagnostics["assessment_review"]
    assert job.result["omitted_lessons"] == [{
        "title": "Unavailable topic", "reasons": ["lesson_omitted"],
    }]
    assert job.result["omitted_assessments"] == [{
        "title": "Procedure", "reasons": ["assessment_no_valid_questions"],
    }]
    assert job.result["course_id"] == state.course_id
    assert job.result["delivery_task_id"] == "delivery-1"
    assert "Source section could not be realized" in job.result["source_warnings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("question_count, expected_status", [(0, "interrupted"), (1, "completed")])
async def test_no_user_branch_records_same_outcome_and_preserves_link(harness, question_count, expected_status):
    harness.convert.return_value = _artifacts(question_count)
    course_id = uuid4()
    harness.job.course_id = course_id

    state = await _run(harness, user=False, course_id=str(course_id))

    assert state.status == harness.job.status == expected_status
    assert state.stage == harness.job.stage == expected_status
    assert state.course_id == str(harness.job.course_id) == str(course_id)
    assert harness.job.result["counts"] == {
        "modules": 1, "lessons": 2, "quizzes": question_count, "questions": question_count,
    }
    assert harness.job.result["course_id"] == str(course_id)
    assert harness.job.result["delivery_task_id"] == "delivery-1"
    assert harness.job.params["progress_detail"]["current"] == 2
    assert harness.job.errors == (["assessment_no_valid_questions"] if not question_count else [])
    assert state.progress == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("forward_course_id", [False, True])
async def test_retry_or_resume_retains_saved_draft_without_generation_or_overwrite(harness, forward_course_id):
    first = await _run(harness)
    course = next(row for row in harness.session.rows if isinstance(row, Course))
    course.title = "Methodologist's saved edits"
    rows_before = list(harness.session.rows)
    # Resume clears terminal errors but retains result, params and course_id.
    harness.job.status = "running"
    harness.job.stage = "queued"
    harness.job.errors = None
    harness.job.result = {**harness.job.result, "resume_count": 1, "delivery_task_id": "delivery-2"}
    harness.generate.reset_mock()

    resumed = await _run(harness, course_id=first.course_id if forward_course_id else None)

    assert resumed.status == harness.job.status == "interrupted"
    assert resumed.stage == harness.job.stage == "interrupted"
    assert resumed.course_id == first.course_id == str(harness.job.course_id)
    assert resumed.errors == harness.job.errors == ["assessment_no_valid_questions"]
    assert harness.session.rows == rows_before
    assert course.title == "Methodologist's saved edits"
    assert harness.job.result["resume_count"] == 1
    assert harness.job.result["delivery_task_id"] == "delivery-2"
    assert harness.job.result["counts"]["lessons"] == 2
    harness.generate.assert_not_awaited()
    harness.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_save_cannot_duplicate_or_replace_review_draft(harness):
    first = await _run(harness)
    rows_before = list(harness.session.rows)
    # A stale delivery may already have cleared progress in its saving callback.
    harness.job.params.pop("progress_detail")
    late = pipeline.GenerationState(
        job_id=harness.job.id, structure=harness.artifacts.structure,
        content=harness.artifacts.content, assessment=harness.artifacts.assessment,
        source_analysis={"generation_engine": "evidence_v2"},
    )

    await pipeline._save_generation_to_db(late, harness.job.tenant_id, harness.job.user_id)

    assert late.course_id == first.course_id
    assert late.status == "interrupted"
    assert harness.session.rows == rows_before
    assert harness.job.params["progress_detail"]["current"] == 2


@pytest.mark.asyncio
async def test_legacy_zero_question_persistence_is_unchanged(harness):
    state = pipeline.GenerationState(
        job_id=harness.job.id, structure=harness.artifacts.structure,
        content=harness.artifacts.content, assessment=harness.artifacts.assessment,
        source_analysis={"analysis_mode": "direct_source"},
    )

    await pipeline._save_generation_to_db(state, harness.job.tenant_id, harness.job.user_id)

    assert state.status == harness.job.status == "completed"
    assert harness.job.completed_at is not None
    assert "completion" not in harness.job.params
    assert harness.job.result == {"delivery_task_id": "delivery-1", "resume_count": 0}
    assert harness.job.errors is None


@pytest.mark.asyncio
async def test_cancelled_job_never_generates_or_saves(harness):
    harness.job.status = "cancelled"

    state = await _run(harness)

    assert state.status == harness.job.status == "cancelled"
    assert harness.session.rows == []
    harness.generate.assert_not_awaited()
    harness.release.assert_awaited_once_with(harness.job.id, harness.job.tenant_id)


@pytest.mark.asyncio
async def test_cancel_wins_at_save_boundary_even_after_review_draft_exists(harness):
    first = await _run(harness)
    rows_before = list(harness.session.rows)
    harness.job.status = "cancelled"
    late = pipeline.GenerationState(
        job_id=harness.job.id, source_analysis={"generation_engine": "evidence_v2"},
    )

    with pytest.raises(asyncio.CancelledError):
        await pipeline._save_generation_to_db(late, harness.job.tenant_id, harness.job.user_id)

    assert harness.job.status == "cancelled"
    assert str(harness.job.course_id) == first.course_id
    assert harness.session.rows == rows_before


@pytest.mark.asyncio
async def test_failed_course_commit_does_not_return_a_saved_link_and_releases_reservation(harness):
    commit = harness.session.commit

    async def reject_course_commit():
        if harness.job.course_id is not None:
            # Emulate rollback of the job fields in the failed transaction.
            harness.job.course_id = None
            raise RuntimeError("synthetic commit failure")
        await commit()

    harness.session.commit = reject_course_commit

    state = await _run(harness)

    assert state.status == "failed"
    assert state.course_id is None
    harness.release.assert_awaited_once_with(harness.job.id, harness.job.tenant_id)


@pytest.mark.asyncio
async def test_existing_job_api_exposes_interruption_errors_saved_course_and_lesson_progress(harness):
    from app.modules.ai.router import _job_response

    state = await _run(harness)
    harness.job.created_at = datetime.now(UTC)
    harness.job.started_at = None

    response = await _job_response(harness.session, harness.job, queue_metadata={})

    assert response.status == "interrupted"
    assert response.stage == "interrupted"
    assert response.course_id == UUID(state.course_id)
    assert response.errors == ["assessment_no_valid_questions"]
    assert response.message == state.message
    assert response.progress_current == response.progress_total == 2


@pytest.mark.asyncio
async def test_no_user_completion_cannot_override_concurrent_cancellation(harness, monkeypatch):
    from app.modules.ai import job_service

    update = job_service.update_ai_job

    async def cancel_before_terminal_update(*args, **kwargs):
        if kwargs.get("status") == "interrupted":
            harness.job.status = "cancelled"
        return await update(*args, **kwargs)

    monkeypatch.setattr(job_service, "update_ai_job", cancel_before_terminal_update)

    state = await _run(harness, user=False)

    assert state.status == harness.job.status == "cancelled"
    assert "counts" not in harness.job.result
    assert "completion" not in harness.job.params
