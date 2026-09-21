"""Idempotent data guarantees for the public demo sandbox."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.courses.release_service import create_course_release
from app.modules.enrollments.service import enroll_users
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice

_DEMO_FIXTURE_VERSION = 1
_DEMO_LESSONS = (
    {
        "title": "Как устроен учебный маршрут",
        "content": (
            "# Как устроен учебный маршрут\n\n"
            "Курс состоит из коротких уроков и проверок знаний. Прогресс сохраняется, "
            "поэтому к обучению можно вернуться позже. После завершения методист видит "
            "результат в журнале обучения."
        ),
        "question": "Что сохраняет Kamilya во время прохождения курса?",
        "choices": ("Прогресс обучения", "Пароль сотрудника", "Личные переписки"),
        "correct_index": 0,
        "explanation": "Платформа сохраняет учебный прогресс и результаты, а не личные переписки или пароль.",
    },
    {
        "title": "Как подтверждается результат",
        "content": (
            "# Как подтверждается результат\n\n"
            "Обучающийся проходит назначенные материалы и обязательные тесты. "
            "Завершение курса фиксируется один раз и связывается с опубликованной "
            "версией содержания."
        ),
        "question": "С чем связывается зафиксированное завершение курса?",
        "choices": (
            "С опубликованной версией курса",
            "С любым черновиком курса",
            "Только с названием организации",
        ),
        "correct_index": 0,
        "explanation": "Результат относится к конкретной опубликованной версии курса.",
    },
)


async def _create_demo_course(db: AsyncSession, *, tenant_id: UUID) -> Course:
    """Create the deterministic provider-free course used only by the demo tenant."""
    published_at = datetime.now(UTC)
    course = Course(
        tenant_id=tenant_id,
        title="Знакомство с Kamilya",
        description="Короткий учебный пример прохождения курса и проверки знаний.",
        status="published",
        delivery_type="native",
        created_by=None,
        ai_generated=False,
        source_document_ids=[],
        source_strategy="single_topic",
        source_analysis={"demo_fixture": {"version": _DEMO_FIXTURE_VERSION}},
        review_status="approved",
        reviewed_by=None,
        reviewed_at=published_at,
        published_at=published_at,
    )
    db.add(course)
    await db.flush()

    module = Module(
        tenant_id=tenant_id,
        course_id=course.id,
        title="Учебный пример",
        description="Два шага, которые показывают путь обучающегося.",
        order_index=0,
        ai_generated=False,
    )
    db.add(module)
    await db.flush()

    for lesson_index, fixture in enumerate(_DEMO_LESSONS):
        lesson = Lesson(
            tenant_id=tenant_id,
            module_id=module.id,
            title=fixture["title"],
            content_type="text",
            content=fixture["content"],
            duration_seconds=180,
            order_index=lesson_index,
            ai_generated=False,
            source_document_ids=[],
            source_references=[],
            source_validation_status="not_applicable",
            published_at=published_at,
        )
        db.add(lesson)
        await db.flush()

        quiz = Quiz(
            tenant_id=tenant_id,
            lesson_id=lesson.id,
            title=f"{fixture['title']}: проверка",
            pass_score=80,
            attempt_limit=3,
            deferral_days=7,
            review_status="approved",
        )
        db.add(quiz)
        await db.flush()

        question = Question(
            quiz_id=quiz.id,
            text=fixture["question"],
            type="single_choice",
            points=1,
            explanation=fixture["explanation"],
            order_index=0,
        )
        db.add(question)
        await db.flush()
        for choice_index, choice in enumerate(fixture["choices"]):
            db.add(
                QuizChoice(
                    question_id=question.id,
                    text=choice,
                    is_correct=choice_index == fixture["correct_index"],
                    order_index=choice_index,
                )
            )

    await db.flush()
    await create_course_release(db, course, published_by=None)
    return course


async def ensure_demo_student_course(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    student_id: UUID,
) -> UUID | None:
    """Ensure the canonical demo learner can open a published course.

    Public demo data is long-lived and may be cleaned independently from the
    fixed demo identities. Locking the learner serializes concurrent logins,
    while the normal enrollment service creates release evidence and enforces
    the same tenant/status checks as a methodologist assignment.

    If several published courses exist, prefer the one already used by the
    most demo enrollments. This keeps the public learner on the established
    scenario without coupling the contract to a translated course title or a
    deployment-specific UUID.
    """
    is_demo_tenant = await db.scalar(
        select(Tenant.is_demo).where(Tenant.id == tenant_id)
    )
    if is_demo_tenant is not True:
        return None

    locked_student_id = await db.scalar(
        select(User.id)
        .where(
            User.id == student_id,
            User.tenant_id == tenant_id,
            User.role == "student",
            User.is_active.is_(True),
            User.status == "active",
        )
        .with_for_update()
    )
    if locked_student_id is None:
        return None

    existing_course_id = await db.scalar(
        select(Course.id)
        .join(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.tenant_id == tenant_id),
        )
        .where(
            Course.tenant_id == tenant_id,
            Course.status == "published",
            Enrollment.user_id == student_id,
        )
        .limit(1)
    )
    if existing_course_id is not None:
        return existing_course_id

    course = await db.scalar(
        select(Course)
        .outerjoin(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.tenant_id == tenant_id),
        )
        .where(
            Course.tenant_id == tenant_id,
            Course.status == "published",
        )
        .group_by(Course.id)
        .order_by(
            func.count(Enrollment.id).desc(),
            Course.created_at.asc(),
            Course.id.asc(),
        )
        .limit(1)
    )
    if course is None:
        course = await _create_demo_course(db, tenant_id=tenant_id)

    created = await enroll_users(db, course.id, tenant_id, [student_id])
    if created:
        return course.id

    # A concurrent or historical assignment may have become visible after
    # the initial check. Confirm the postcondition rather than returning a
    # successful login with an empty learner dashboard.
    return await db.scalar(
        select(Course.id)
        .join(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.tenant_id == tenant_id),
        )
        .where(
            Course.tenant_id == tenant_id,
            Course.status == "published",
            Enrollment.user_id == student_id,
        )
        .limit(1)
    )
