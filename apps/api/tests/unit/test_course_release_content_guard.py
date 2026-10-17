from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from app.models.document import Document
from app.modules.courses.models import Course
from app.modules.courses.release_service import (
    CourseContentRequiredError,
    create_course_release,
    create_course_release_from_snapshot,
)
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.scorm.models import ScormPackage

TENANT = UUID("00000000-0000-0000-0000-000000000001")
COURSE = UUID("00000000-0000-0000-0000-000000000002")
PUBLISHER = UUID("00000000-0000-0000-0000-000000000003")


def _course(*, delivery_type: str = "native") -> Course:
    return Course(
        id=COURSE,
        tenant_id=TENANT,
        title="Guarded publication",
        description="",
        status="draft",
        delivery_type=delivery_type,
        source_document_ids=[],
        source_strategy="single_topic",
        source_analysis={},
        review_status="approved",
    )


def _snapshot(*, delivery_type: str = "native", lessons: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "release_version": 7,
        "course": {"id": str(COURSE), "delivery_type": delivery_type},
        "modules": [] if lessons is None else [{"id": "module-1", "lessons": lessons}],
        "scorm_packages": [],
    }


class _ReleaseDB:
    def __init__(self, course: Course, *, rows: dict[type, list[object]] | None = None) -> None:
        self.course = course
        self.rows = rows or {}
        self.scalar_values: list[object | None] = [course, None]
        self.add = Mock()
        self.flush = AsyncMock()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return _ScalarRows(self.rows.get(entity, []))


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(),
        _snapshot(lessons=[]),
        _snapshot(
            lessons=[
                {
                    "content": "\u00a0\t\n",
                    "content_blocks": [{"content": "   ", "metadata": {}}],
                    "quizzes": [{"questions": []}],
                }
            ]
        ),
        _snapshot(
            lessons=[
                {
                    "content": "",
                    "content_blocks": [
                        {
                            "block_type": "video",
                            "content": None,
                            "metadata": {"style": "plain", "language": "ru"},
                        }
                    ],
                    "quizzes": [],
                }
            ]
        ),
        _snapshot(
            lessons=[
                {
                    "content": "",
                    "content_blocks": [{"block_type": "video", "content": None, "metadata": "{}"}],
                    "quizzes": [],
                }
            ]
        ),
        _snapshot(
            lessons=[
                {
                    "content": "",
                    "content_blocks": [
                        {
                            "block_type": "callout",
                            "content": None,
                            "metadata": {"url": "/media/not-a-media-block.mp4"},
                        }
                    ],
                    "quizzes": [],
                }
            ]
        ),
    ],
    ids=[
        "zero-modules",
        "empty-module",
        "all-empty-lesson-bodies",
        "decorative-metadata-only",
        "empty-json-metadata",
        "unsupported-block-type-url",
    ],
)
async def test_required_native_release_rejects_empty_snapshot_before_any_write(snapshot: dict) -> None:
    course = _course()
    db = _ReleaseDB(course)

    with pytest.raises(CourseContentRequiredError):
        await create_course_release_from_snapshot(
            db,
            course,
            snapshot,
            published_by=PUBLISHER,
            require_usable_content=True,
        )

    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    assert course.current_release_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lesson",
    [
        {"content": "Learner text", "content_blocks": [], "quizzes": []},
        {
            "content": None,
            "content_blocks": [{"block_type": "video", "content": None, "metadata": {"url": "/media/lesson.mp4"}}],
            "quizzes": [],
        },
        {
            "content": None,
            "content_blocks": [
                {
                    "block_type": "audio",
                    "content": None,
                    "metadata": '{"asset_url":"/media/lesson.mp3","language":"ru"}',
                }
            ],
            "quizzes": [],
        },
        {
            "content": "",
            "content_blocks": [],
            "quizzes": [{"questions": [{"text": "What is the safe action?"}]}],
        },
    ],
    ids=["text", "media-dict", "media-json-string", "quiz-only"],
)
async def test_required_native_release_accepts_a_usable_lesson_without_mutating_approved_snapshot(lesson: dict) -> None:
    course = _course()
    db = _ReleaseDB(course)
    approved_snapshot = _snapshot(lessons=[lesson])
    original = deepcopy(approved_snapshot)

    release = await create_course_release_from_snapshot(
        db,
        course,
        approved_snapshot,
        published_by=PUBLISHER,
        require_usable_content=True,
    )

    assert approved_snapshot == original
    assert release.snapshot is not approved_snapshot
    assert release.snapshot["release_version"] == 1
    db.add.assert_called_once_with(release)
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_legacy_release_creation_keeps_empty_native_snapshot_compatibility_by_default() -> None:
    course = _course()
    db = _ReleaseDB(course)

    release = await create_course_release_from_snapshot(
        db,
        course,
        _snapshot(),
        published_by=PUBLISHER,
    )

    db.add.assert_called_once_with(release)
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_live_release_builder_rejects_its_exact_empty_native_snapshot_before_write() -> None:
    course = _course()
    rows = {
        Module: [],
        Lesson: [],
        ContentBlock: [],
        Quiz: [],
        Question: [],
        QuizChoice: [],
        Document: [],
        ScormPackage: [],
    }
    db = _ReleaseDB(course, rows=rows)

    with pytest.raises(CourseContentRequiredError):
        await create_course_release(
            db,
            course,
            published_by=PUBLISHER,
            require_usable_content=True,
        )

    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    assert course.current_release_id is None


@pytest.mark.asyncio
async def test_live_release_builder_keeps_legacy_empty_snapshot_compatibility_by_default() -> None:
    course = _course()
    db = _ReleaseDB(course, rows={Module: [], ScormPackage: []})

    release = await create_course_release(
        db,
        course,
        published_by=PUBLISHER,
    )

    assert release.snapshot["modules"] == []
    db.add.assert_called_once_with(release)
    assert db.flush.await_count == 2


@pytest.mark.asyncio
async def test_scorm_release_is_unchanged_by_native_content_guard() -> None:
    course = _course(delivery_type="scorm")
    db = _ReleaseDB(course)

    release = await create_course_release_from_snapshot(
        db,
        course,
        _snapshot(delivery_type="scorm"),
        published_by=PUBLISHER,
        require_usable_content=True,
    )

    db.add.assert_called_once_with(release)


@pytest.mark.asyncio
async def test_persisted_native_delivery_type_cannot_be_bypassed_by_snapshot_mismatch() -> None:
    course = _course(delivery_type="native")
    db = _ReleaseDB(course)

    with pytest.raises(CourseContentRequiredError):
        await create_course_release_from_snapshot(
            db,
            course,
            _snapshot(delivery_type="scorm"),
            published_by=PUBLISHER,
            require_usable_content=True,
        )

    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    assert course.current_release_id is None
