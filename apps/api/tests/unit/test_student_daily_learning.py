from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, Uuid, and_, create_engine, select

from app.models.registry import load_all_models

load_all_models()


class Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows


class Scalar:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


@pytest.mark.asyncio
async def test_student_dashboard_includes_cycle_deadline_and_native_resume_in_bounded_reads():
    from app.modules.student.service import get_student_dashboard

    tenant_id, user_id = uuid4(), uuid4()
    native_course_id, scorm_course_id = uuid4(), uuid4()
    native_enrollment_id, scorm_enrollment_id = uuid4(), uuid4()
    due_at = datetime(2026, 10, 15, tzinfo=UTC)
    last_accessed = datetime(2026, 9, 28, tzinfo=UTC)
    lesson_id = uuid4()

    native_course = SimpleNamespace(
        id=native_course_id,
        tenant_id=tenant_id,
        title="Native",
        description="",
        status="published",
        delivery_type="native",
        thumbnail_url=None,
    )
    scorm_course = SimpleNamespace(
        id=scorm_course_id,
        tenant_id=tenant_id,
        title="SCORM",
        description="",
        status="published",
        delivery_type="scorm",
        thumbnail_url=None,
    )
    native_enrollment = SimpleNamespace(
        id=native_enrollment_id,
        course_id=native_course_id,
        user_id=user_id,
        tenant_id=tenant_id,
        status="in_progress",
        source="learning_path",
        enrolled_at=datetime(2026, 9, 1, tzinfo=UTC),
        recurring_assignment_id=None,
        learning_path_assignment_id=uuid4(),
        previous_enrollment_id=None,
    )
    scorm_enrollment = SimpleNamespace(
        id=scorm_enrollment_id,
        course_id=scorm_course_id,
        user_id=user_id,
        tenant_id=tenant_id,
        status="in_progress",
        source="manual",
        enrolled_at=datetime(2026, 9, 2, tzinfo=UTC),
        recurring_assignment_id=None,
        learning_path_assignment_id=None,
        previous_enrollment_id=None,
    )

    class DB:
        def __init__(self):
            self.statements = []
            self.results = [
                Rows([(native_enrollment, native_course, due_at), (scorm_enrollment, scorm_course, None)]),
                Rows([]),  # lesson totals
                Rows([]),  # completed lessons
                Rows([(native_enrollment_id, lesson_id, False, last_accessed)]),  # one batched resume query
                Scalar(0),
            ]

        async def execute(self, statement):
            self.statements.append(statement)
            return self.results.pop(0)

    db = DB()
    result = await get_student_dashboard(db, user_id, tenant_id)

    assert len(db.statements) == 5
    assert result["enrolled_courses"][0]["assignment_due_at"] == due_at
    assert result["enrolled_courses"][0]["assignment_source"] == "learning_path"
    assert result["enrolled_courses"][0]["resume_href"] == f"/courses/{native_course_id}?lessonId={lesson_id}"
    assert result["enrolled_courses"][1]["resume_href"] == f"/courses/{scorm_course_id}"
    assert "enrollment_access_policies.due_at" in str(db.statements[0])
    resume_sql = str(db.statements[3])
    assert "progress.tenant_id" in resume_sql
    assert "progress.user_id" in resume_sql
    assert "enrollments.tenant_id" in resume_sql
    assert "enrollments.user_id" in resume_sql


@pytest.mark.asyncio
async def test_fully_completed_lessons_do_not_hide_unfinished_quiz_enrollment():
    from app.modules.student.service import get_student_dashboard

    tenant_id, user_id, course_id, enrollment_id = uuid4(), uuid4(), uuid4(), uuid4()
    course = SimpleNamespace(
        id=course_id,
        tenant_id=tenant_id,
        title="Required quiz",
        description="",
        status="published",
        delivery_type="native",
        thumbnail_url=None,
    )
    enrollment = SimpleNamespace(
        id=enrollment_id,
        course_id=course_id,
        user_id=user_id,
        tenant_id=tenant_id,
        status="in_progress",
        source="manual",
        enrolled_at=datetime(2026, 9, 1, tzinfo=UTC),
        recurring_assignment_id=None,
        learning_path_assignment_id=None,
        previous_enrollment_id=None,
    )

    class DB:
        def __init__(self):
            self.results = [
                Rows([(enrollment, course, None)]),
                Rows([SimpleNamespace(course_id=course_id, total=2)]),
                Rows([SimpleNamespace(course_id=course_id, enrollment_id=None, completed=2)]),
                Rows([]),
                Scalar(0),
            ]

        async def execute(self, _statement):
            return self.results.pop(0)

    result = await get_student_dashboard(DB(), user_id, tenant_id)
    assignment = result["enrolled_courses"][0]
    assert assignment["progress_percent"] == 100
    assert assignment["enrollment_status"] == "in_progress"
    assert assignment["resume_href"] == f"/courses/{course_id}"


@pytest.mark.asyncio
async def test_same_course_current_occurrences_resume_from_their_own_progress_scope():
    from app.modules.student.service import get_student_dashboard

    tenant_id, user_id, course_id = uuid4(), uuid4(), uuid4()
    enrollment_ids = (uuid4(), uuid4())
    lesson_ids = (uuid4(), uuid4())
    course = SimpleNamespace(
        id=course_id,
        tenant_id=tenant_id,
        title="Repeated course",
        description="",
        status="published",
        delivery_type="native",
        thumbnail_url=None,
    )
    enrollments = [
        SimpleNamespace(
            id=enrollment_id,
            course_id=course_id,
            user_id=user_id,
            tenant_id=tenant_id,
            status="in_progress",
            source="learning_path",
            enrolled_at=datetime(2026, 9, day, tzinfo=UTC),
            recurring_assignment_id=None,
            learning_path_assignment_id=uuid4(),
            previous_enrollment_id=None,
        )
        for enrollment_id, day in zip(enrollment_ids, (1, 2), strict=True)
    ]

    class DB:
        def __init__(self):
            self.statements = []
            urgent_due_at = datetime(2026, 9, 15, tzinfo=UTC)
            self.results = [
                Rows([(enrollments[1], course, None), (enrollments[0], course, urgent_due_at)]),
                Rows([SimpleNamespace(course_id=course_id, total=2)]),
                Rows([
                    SimpleNamespace(course_id=course_id, enrollment_id=enrollment_ids[0], completed=1),
                    SimpleNamespace(course_id=course_id, enrollment_id=enrollment_ids[1], completed=1),
                ]),
                Rows([
                    (enrollment_ids[1], lesson_ids[1], False, datetime(2026, 9, 11, tzinfo=UTC)),
                ]),
                Scalar(0),
            ]

        async def execute(self, statement):
            self.statements.append(statement)
            return self.results.pop(0)

    db = DB()
    result = await get_student_dashboard(db, user_id, tenant_id)
    current, previous = result["enrolled_courses"]
    assert current["enrollment_id"] == enrollment_ids[1]
    assert current["can_resume"] is True
    assert current["resume_href"] == f"/courses/{course_id}?lessonId={lesson_ids[1]}"
    assert previous["enrollment_id"] == enrollment_ids[0]
    assert previous["can_resume"] is False
    assert previous["assignment_due_at"] == datetime(2026, 9, 15, tzinfo=UTC)
    assert previous["resume_href"] is None
    assert "CASE" in str(db.statements[0])
    assert "enrollments.enrolled_at DESC" in str(db.statements[0])
    assert "enrollments.id DESC" in str(db.statements[0])
    resume_sql = str(db.statements[3])
    assert resume_sql.count("enrollments.id =") == 1
    assert resume_sql.count("progress.enrollment_id =") == 1
    assert enrollment_ids[1] in db.statements[3].compile().params.values()


def test_resume_join_predicate_does_not_cross_match_progress_between_occurrences():
    from app.modules.student.service import _resume_progress_scope

    tenant_id = UUID("10000000-0000-4000-8000-000000000001")
    user_id = UUID("10000000-0000-4000-8000-000000000002")
    course_id = UUID("10000000-0000-4000-8000-000000000003")
    first_enrollment = UUID("20000000-0000-4000-8000-000000000001")
    second_enrollment = UUID("20000000-0000-4000-8000-000000000002")
    first_lesson = UUID("30000000-0000-4000-8000-000000000001")
    second_lesson = UUID("30000000-0000-4000-8000-000000000002")
    metadata = MetaData()
    enrollment_rows = Table(
        "enrollment_rows",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("course_id", Uuid(as_uuid=True), nullable=False),
        Column("tenant_id", Uuid(as_uuid=True), nullable=False),
        Column("user_id", Uuid(as_uuid=True), nullable=False),
    )
    lesson_rows = Table(
        "lesson_rows",
        metadata,
        Column("course_id", Uuid(as_uuid=True), nullable=False),
        Column("lesson_id", Uuid(as_uuid=True), nullable=False),
    )
    progress_rows = Table(
        "progress_rows",
        metadata,
        Column("enrollment_id", Uuid(as_uuid=True), nullable=True),
        Column("lesson_id", Uuid(as_uuid=True), nullable=False),
    )
    scope = _resume_progress_scope(
        [
            (first_enrollment, course_id, first_enrollment),
            (second_enrollment, course_id, second_enrollment),
        ],
        enrollment_id_column=enrollment_rows.c.id,
        course_id_column=lesson_rows.c.course_id,
        progress_enrollment_id_column=progress_rows.c.enrollment_id,
    )
    join = enrollment_rows.join(
        lesson_rows,
        and_(
            enrollment_rows.c.course_id == lesson_rows.c.course_id,
            enrollment_rows.c.tenant_id == tenant_id,
            enrollment_rows.c.user_id == user_id,
        ),
    ).outerjoin(
        progress_rows,
        and_(progress_rows.c.lesson_id == lesson_rows.c.lesson_id, scope),
    )
    query = select(enrollment_rows.c.id, lesson_rows.c.lesson_id, progress_rows.c.enrollment_id).select_from(join)

    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            enrollment_rows.insert(),
            [
                {"id": first_enrollment, "course_id": course_id, "tenant_id": tenant_id, "user_id": user_id},
                {"id": second_enrollment, "course_id": course_id, "tenant_id": tenant_id, "user_id": user_id},
            ],
        )
        connection.execute(
            lesson_rows.insert(),
            [
                {"course_id": course_id, "lesson_id": first_lesson},
                {"course_id": course_id, "lesson_id": second_lesson},
            ],
        )
        connection.execute(
            progress_rows.insert(),
            [
                {"enrollment_id": first_enrollment, "lesson_id": first_lesson},
                {"enrollment_id": second_enrollment, "lesson_id": second_lesson},
            ],
        )
        actual = connection.execute(query).all()

    expected = [
        (first_enrollment, first_lesson, first_enrollment),
        (first_enrollment, second_lesson, None),
        (second_enrollment, first_lesson, None),
        (second_enrollment, second_lesson, second_enrollment),
    ]
    def sort_key(row):
        return str(row[0]), str(row[1])

    assert sorted(actual, key=sort_key) == sorted(expected, key=sort_key)


@pytest.mark.asyncio
async def test_empty_student_dashboard_uses_only_enrollment_and_certificate_reads():
    from app.modules.student.service import get_student_dashboard

    class DB:
        def __init__(self):
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            return Rows([]) if self.calls == 1 else Scalar(0)

    db = DB()
    result = await get_student_dashboard(db, uuid4(), uuid4())
    assert db.calls == 2
    assert result["enrolled_courses"] == []
    assert result["completed_courses"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("matches", [True, False, None])
async def test_exact_assignment_read_does_not_resume_against_another_occurrence(matches):
    from app.modules.student.service import get_student_dashboard

    tenant, user, course_id, requested = (uuid4() for _ in range(4))
    enrollment = SimpleNamespace(
        id=requested, source="manual", status="in_progress", enrolled_at=datetime(2026, 9, 1, tzinfo=UTC),
        recurring_assignment_id=None, learning_path_assignment_id=None, previous_enrollment_id=uuid4(),
    )
    course = SimpleNamespace(
        id=course_id, title="Exact read", description="", status="published", delivery_type="native", thumbnail_url=None,
    )

    class DB:
        def __init__(self):
            self.lookups = []
            self.rows = [Rows([(enrollment, course, None)]), Rows([]), Rows([])]
            if matches:
                self.rows.append(Rows([]))  # only the matching occurrence can look up a resume lesson
            self.rows.append(Scalar(0))

        async def execute(self, statement):
            if not self.lookups:
                assert requested in statement.compile().params.values()
            return self.rows.pop(0)

        async def scalar(self, statement):
            self.lookups.append(statement)
            params = statement.compile().params.values()
            assert tenant in params and user in params and course_id in params
            return None if matches is None else SimpleNamespace(id=requested if matches else uuid4())

    db = DB()
    result = await get_student_dashboard(db, user, tenant, enrollment_id=requested)
    assert len(db.lookups) == 1
    assert len(result["enrolled_courses"]) == 1
    assignment = result["enrolled_courses"][0]
    assert assignment["enrollment_id"] == requested
    assert assignment["can_resume"] is bool(matches)
    assert assignment["resume_href"] == (f"/courses/{course_id}" if matches else None)
