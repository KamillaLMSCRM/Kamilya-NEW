from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.models.courses import Course
from app.modules.courses.schemas import (
    CourseCreate,
    CourseUpdate,
    CourseResponse,
    CoursePreviewResponse,
    CoursePreviewModule,
    CoursePreviewLesson,
    CourseReviewRequest,
    CourseReviewer,
    CoursePreviewRequest,
)
from app.modules.audit.service import log_action

router = APIRouter(
    prefix="/courses",
    tags=["courses"],
    dependencies=[Depends(require_tenant_user())],
)


async def _hydrate_reviewer(db: AsyncSession, course: Course) -> Optional[CourseReviewer]:
    """Resolve the reviewer user record into a small embed (best-effort).
    Returns None if there is no reviewer on this course."""
    if not course.reviewed_by:
        return None
    user = await db.get(User, course.reviewed_by)
    if not user:
        return None
    return CourseReviewer.model_validate(user)


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    status: Optional[str] = Query(None, description="Filter by status: draft, published, archived"),
    q: Optional[str] = Query(None, description="Search in title and description"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Course).where(Course.tenant_id == user.tenant_id)
    if status:
        query = query.where(Course.status == status)
    if q:
        search = f"%{q}%"
        query = query.where(
            (Course.title.ilike(search)) | (Course.description.ilike(search))
        )
    query = query.order_by(Course.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    courses = result.scalars().all()
    # Hydrate reviewer info on each course
    out = []
    for c in courses:
        c.reviewer = await _hydrate_reviewer(db, c)
        out.append(c)
    return out


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(
    req: CourseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    from app.core.trial_limits import assert_can_create_courses

    await assert_can_create_courses(db, user.tenant_id)
    course = Course(
        tenant_id=user.tenant_id,
        title=req.title,
        description=req.description,
        status=req.status,
        created_by=user.id,
    )
    db.add(course)
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "create", "course",
        resource_id=str(course.id), user_id=user.id,
        details={"title": course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = None
    return course


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.reviewer = await _hydrate_reviewer(db, course)
    return course


@router.get("/{course_id}/preview", response_model=CoursePreviewResponse)
async def get_course_preview(
    course_id: UUID,
    max_chars: int = Query(240, ge=80, le=2000, description="Max chars of lesson content to include inline"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lightweight course structure for the AI-generation review step.

    Returns modules → lessons → quiz headers (without questions/answers).
    Designed so the methodologist can sanity-check what the AI produced
    without needing to open every lesson in the editor.
    """
    from app.modules.lessons.models import Module, Lesson
    from app.modules.quizzes.models import Quiz, Question

    course = (
        await db.execute(
            select(Course)
            .where(Course.id == course_id, Course.tenant_id == user.tenant_id)
            .options(
                selectinload(Course.modules)
                .selectinload(Module.lessons)
            )
        )
    ).scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Resolve quiz headers per lesson in a single query.
    lesson_ids: list[UUID] = []
    for m in course.modules:
        for l in m.lessons:
            lesson_ids.append(l.id)
    quiz_by_lesson: dict[UUID, Quiz] = {}
    quiz_q_counts: dict[UUID, int] = {}
    if lesson_ids:
        quizzes_rows = (
            await db.execute(
                select(Quiz).where(Quiz.lesson_id.in_(lesson_ids), Quiz.tenant_id == user.tenant_id)
            )
        ).scalars().all()
        for q in quizzes_rows:
            quiz_by_lesson[q.lesson_id] = q
        counts_rows = (
            await db.execute(
                select(Question.quiz_id, func.count(Question.id))
                .where(Question.quiz_id.in_([q.id for q in quizzes_rows]))
                .group_by(Question.quiz_id)
            )
        ).all()
        for qid, cnt in counts_rows:
            quiz_q_counts[qid] = int(cnt)

    # Build response — content preview is the first N chars of plain text.
    preview_modules: list[CoursePreviewModule] = []
    total_lessons = 0
    total_quizzes = 0
    for m in sorted(course.modules, key=lambda x: (x.order_index, x.title)):
        lessons_out: list[CoursePreviewLesson] = []
        for l in sorted(m.lessons, key=lambda x: (x.order_index, x.title)):
            quiz = quiz_by_lesson.get(l.id)
            preview_text = (l.content or "").strip()
            if len(preview_text) > max_chars:
                preview_text = preview_text[:max_chars].rstrip() + "…"
            lessons_out.append(CoursePreviewLesson(
                id=l.id,
                title=l.title,
                content_type=l.content_type,
                content_preview=preview_text,
                duration_seconds=l.duration_seconds,
                order_index=l.order_index,
                has_quiz=quiz is not None,
                quiz_id=quiz.id if quiz else None,
                quiz_title=quiz.title if quiz else None,
                quiz_question_count=quiz_q_counts.get(quiz.id, 0) if quiz else 0,
            ))
            total_lessons += 1
            if quiz:
                total_quizzes += 1
        preview_modules.append(CoursePreviewModule(
            id=m.id,
            title=m.title,
            description=m.description,
            order_index=m.order_index,
            lessons=lessons_out,
        ))

    return CoursePreviewResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        status=course.status,
        modules_count=len(preview_modules),
        lessons_count=total_lessons,
        quizzes_count=total_quizzes,
        modules=preview_modules,
    )


@router.post("/{course_id}/review", response_model=CourseResponse)
async def review_course(
    course_id: UUID,
    req: CourseReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Mark a course as approved or needs_changes (methodologist sign-off).

    Sets review_status, reviewed_by (current user), reviewed_at (now),
    and review_comment. Designed for the AI-generation review step where
    the methodologist validates the AI's output before it goes to staff.
    """
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    course.review_status = req.review_status
    course.reviewed_by = user.id
    course.reviewed_at = datetime.now(timezone.utc)
    course.review_comment = req.comment
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "review", "course",
        resource_id=str(course.id), user_id=user.id,
        details={
            "review_status": req.review_status,
            "has_comment": bool(req.comment and req.comment.strip()),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)
    return course


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: UUID,
    req: CourseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "update", "course",
        resource_id=str(course.id), user_id=user.id,
        details=req.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)
    return course


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "published"
    course.published_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "publish", "course",
        resource_id=str(course.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)
    return course


@router.post("/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "draft"
    course.published_at = None
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "unpublish", "course",
        resource_id=str(course.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)
    return course


@router.post("/{course_id}/duplicate", response_model=CourseResponse, status_code=201)
async def duplicate_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    from app.core.trial_limits import assert_can_create_courses

    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    await assert_can_create_courses(db, user.tenant_id)
    new_course = Course(
        tenant_id=user.tenant_id,
        title=f"{course.title} (копия)",
        description=course.description,
        status="draft",
        created_by=user.id,
    )
    db.add(new_course)
    await db.flush()
    await db.refresh(new_course)
    await log_action(
        db, user.tenant_id, "duplicate", "course",
        resource_id=str(new_course.id), user_id=user.id,
        details={"original_id": str(course.id), "title": new_course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    new_course.reviewer = None
    return new_course


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    await log_action(
        db, user.tenant_id, "delete", "course",
        resource_id=str(course.id), user_id=user.id,
        details={"title": course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.delete(course)
    await db.commit()


async def _complete_course_for_user(db: AsyncSession, course_id: UUID, user: User) -> dict:
    from app.models.enrollment import Enrollment
    from app.models.progress import Progress
    from app.modules.audit.service import log_action
    from app.modules.certificates.service import issue_certificate
    from app.modules.lessons.models import Lesson, Module
    from app.modules.quizzes.models import Quiz, QuizAttempt, Question

    result = await db.execute(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == user.tenant_id,
        )
    )
    enrollment = result.scalar_one_or_none()

    course_result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    if not course_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Course not found")

    total_lessons = await db.scalar(
        select(func.count(Lesson.id))
        .join(Module, Lesson.module_id == Module.id)
        .where(
            Module.course_id == course_id,
            Module.tenant_id == user.tenant_id,
            Lesson.tenant_id == user.tenant_id,
        )
    ) or 0
    if total_lessons == 0:
        raise HTTPException(status_code=400, detail="Course has no lessons")

    completed_lessons = await db.scalar(
        select(func.count(func.distinct(Progress.lesson_id)))
        .join(Lesson, Progress.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .where(
            Module.course_id == course_id,
            Progress.user_id == user.id,
            Progress.tenant_id == user.tenant_id,
            Progress.completed == True,
        )
    ) or 0
    if completed_lessons < total_lessons:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "lessons_incomplete",
                "completed_lessons": completed_lessons,
                "total_lessons": total_lessons,
            },
        )

    total_quizzes = await db.scalar(
        select(func.count(func.distinct(Quiz.id)))
        .join(Lesson, Quiz.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Question, Question.quiz_id == Quiz.id)
        .where(
            Module.course_id == course_id,
            Module.tenant_id == user.tenant_id,
            Quiz.tenant_id == user.tenant_id,
        )
    ) or 0
    passed_quizzes = await db.scalar(
        select(func.count(func.distinct(QuizAttempt.quiz_id)))
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .join(Lesson, Quiz.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Question, Question.quiz_id == Quiz.id)
        .where(
            Module.course_id == course_id,
            Quiz.tenant_id == user.tenant_id,
            QuizAttempt.user_id == user.id,
            QuizAttempt.tenant_id == user.tenant_id,
            QuizAttempt.passed == True,
        )
    ) or 0
    if passed_quizzes < total_quizzes:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "quizzes_incomplete",
                "passed_quizzes": passed_quizzes,
                "total_quizzes": total_quizzes,
            },
        )

    if not enrollment:
        enrollment = Enrollment(
            course_id=course_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
            status="enrolled",
            source="manual",
        )
        db.add(enrollment)
        await db.flush()

    was_already_completed = enrollment.status == "completed"
    if not was_already_completed:
        enrollment.status = "completed"
        enrollment.completed_at = datetime.now(timezone.utc)

    cert = await issue_certificate(
        db=db,
        user_id=user.id,
        course_id=course_id,
        tenant_id=user.tenant_id,
    )
    cert_number = cert.certificate_number
    cert_id = str(cert.id)

    await log_action(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="course.complete",
        resource_type="course",
        resource_id=str(course_id),
        details={"certificate_number": cert_number, "certificate_id": cert_id},
    )

    await db.commit()
    return {
        "status": "already_completed" if was_already_completed else "completed",
        "course_id": str(course_id),
        "certificate_number": cert_number,
        "certificate_id": cert_id,
    }


@router.post("/{course_id}/complete")
async def complete_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _complete_course_for_user(db, course_id, user)
