from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest

from app.models.document import Document
from app.modules.courses.models import Course
from app.modules.courses.release_service import build_course_release_snapshot, canonical_json_sha256
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.scorm.models import ScormPackage

TENANT = UUID("00000000-0000-0000-0000-000000000001")
COURSE = UUID("00000000-0000-0000-0000-000000000002")
MODULE = UUID("00000000-0000-0000-0000-000000000003")
LESSON = UUID("00000000-0000-0000-0000-000000000004")
BLOCK = UUID("00000000-0000-0000-0000-000000000005")
QUIZ = UUID("00000000-0000-0000-0000-000000000006")
QUESTION = UUID("00000000-0000-0000-0000-000000000007")
CHOICE = UUID("00000000-0000-0000-0000-000000000008")
DOCUMENT = UUID("00000000-0000-0000-0000-000000000009")
SCORM = UUID("00000000-0000-0000-0000-00000000000a")


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _SnapshotDB:
    """SQL-aware fake: routes each SELECT by its primary ORM entity."""

    def __init__(self, rows, *, force_refresh: bool):
        self.rows = rows
        self.force_refresh = force_refresh
        self.options: list[bool] = []

    async def execute(self, statement):
        option = statement.get_execution_options().get("populate_existing", False)
        self.options.append(option)
        entity = statement.column_descriptions[0].get("entity")
        values = self.rows.get(entity, [])
        return _ScalarRows(values)


def _fixtures():
    course = Course(
        id=COURSE,
        tenant_id=TENANT,
        title="Course",
        description="Description",
        status="draft",
        delivery_type="native",
        source_document_ids=[str(DOCUMENT)],
        source_strategy="single_topic",
        source_analysis={},
        review_status="pending",
    )
    module = Module(id=MODULE, tenant_id=TENANT, course_id=COURSE, title="Module", description="", order_index=0)
    lesson = Lesson(
        id=LESSON,
        tenant_id=TENANT,
        module_id=MODULE,
        title="Lesson",
        content_type="text",
        content="Lesson content",
        order_index=0,
        source_document_ids=[str(DOCUMENT)],
        source_references=[],
        source_validation_status="verified",
    )
    block = ContentBlock(id=BLOCK, lesson_id=LESSON, block_type="text", content="Block", order_index=0)
    quiz = Quiz(
        id=QUIZ, lesson_id=LESSON, tenant_id=TENANT, title="Quiz", pass_score=80, attempt_limit=3, deferral_days=7
    )
    question = Question(id=QUESTION, quiz_id=QUIZ, text="Question", type="single_choice", points=1, order_index=0)
    choice = QuizChoice(id=CHOICE, question_id=QUESTION, text="Choice", is_correct=True, order_index=0)
    document = Document(
        id=DOCUMENT,
        tenant_id=TENANT,
        uploaded_by=TENANT,
        title="Source",
        filename="source.pdf",
        content_type="application/pdf",
        size=10,
        s3_key="source",
        source_family_id=DOCUMENT,
        version=1,
        content_sha256="a" * 64,
        category="general",
    )
    package = ScormPackage(
        id=SCORM,
        tenant_id=TENANT,
        course_id=COURSE,
        version="scorm_1_2",
        title="Package",
        entrypoint="index.html",
        storage_key="package.zip",
        manifest_json={"sha256": "b" * 64},
    )
    return course, {
        Module: [module],
        Lesson: [lesson],
        ContentBlock: [block],
        Quiz: [quiz],
        Question: [question],
        QuizChoice: [choice],
        Document: [document],
        ScormPackage: [package],
    }


@pytest.mark.asyncio
async def test_default_false_is_preserved_and_true_forwards_to_every_child_select():
    course, rows = _fixtures()
    default_db = _SnapshotDB(rows, force_refresh=False)
    forced_db = _SnapshotDB(rows, force_refresh=True)
    default_snapshot = await build_course_release_snapshot(default_db, course, version=1)
    forced_snapshot = await build_course_release_snapshot(forced_db, course, version=1, populate_existing=True)
    assert default_snapshot == forced_snapshot
    assert default_db.options and all(option is False for option in default_db.options)
    assert forced_db.options and all(option is True for option in forced_db.options)
    assert len(forced_db.options) == 8
    assert set(forced_db.rows) == {Module, Lesson, ContentBlock, Quiz, Question, QuizChoice, Document, ScormPackage}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity,attribute,value",
    [
        (Lesson, "content", "Changed lesson"),
        (Module, "title", "Changed module"),
        (ContentBlock, "content", "Changed block"),
        (Quiz, "title", "Changed quiz"),
        (Question, "text", "Changed question"),
        (QuizChoice, "text", "Changed choice"),
        (Document, "title", "Changed document"),
        (ScormPackage, "entrypoint", "changed.html"),
    ],
)
async def test_forced_refresh_snapshot_hash_changes_for_each_non_target_child(entity, attribute, value):
    course, rows = _fixtures()
    stale_db = _SnapshotDB(rows, force_refresh=False)
    stale = await build_course_release_snapshot(stale_db, course, version=1)
    fresh_rows = deepcopy(rows)
    setattr(fresh_rows[entity][0], attribute, value)
    fresh_db = _SnapshotDB(fresh_rows, force_refresh=True)
    fresh = await build_course_release_snapshot(fresh_db, course, version=1, populate_existing=True)
    assert canonical_json_sha256(fresh) != canonical_json_sha256(stale)
    assert all(option is True for option in fresh_db.options)
