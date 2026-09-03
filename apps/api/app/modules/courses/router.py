from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.document import Document
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.courses.access import AUTHORING_ROLES, require_course_access
from app.modules.courses.publication_service import (
    activate_course_assignments,
    refresh_course_assignments,
)
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.courses.schemas import (
    CourseCompletionResponse,
    CourseCreate,
    CoursePreviewLesson,
    CoursePreviewModule,
    CoursePreviewResponse,
    CoursePreviewSourceDocument,
    CourseResponse,
    CourseReviewer,
    CourseReviewRequest,
    CourseUpdate,
)
from app.modules.enrollments.schemas import AssignmentAccessWindowResponse

router = APIRouter(
    prefix="/courses",
    tags=["courses"],
    dependencies=[Depends(require_tenant_user())],
)


async def _hydrate_reviewer(db: AsyncSession, course: Course) -> CourseReviewer | None:
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
    status: str | None = Query(None, description="Filter by status: draft, published, archived"),
    q: str | None = Query(None, description="Search in title and description"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Course).where(Course.tenant_id == user.tenant_id)
    if user.role == "student":
        query = query.join(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.user_id == user.id)
            & (Enrollment.tenant_id == user.tenant_id),
        ).where(Course.status == "published")
        assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
        if assignment_enrollment_id is not None:
            query = query.where(Enrollment.id == assignment_enrollment_id)
    elif user.role not in AUTHORING_ROLES:
        raise HTTPException(status_code=403, detail="Course authoring role required")
    if status:
        query = query.where(Course.status == status)
    elif user.role in AUTHORING_ROLES:
        query = query.where(Course.status != "archived")
    if q:
        search = f"%{q}%"
        query = query.where((Course.title.ilike(search)) | (Course.description.ilike(search)))
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
    user: User = Depends(require_role("superadmin", "methodologist")),
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
        db,
        user.tenant_id,
        "create",
        "course",
        resource_id=str(course.id),
        user_id=user.id,
        details={"title": course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = None
    return course


@router.get("/{course_id}/access-window", response_model=AssignmentAccessWindowResponse | None)
async def get_course_access_window(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return only timer state for the exact enrollment bound to a link JWT."""
    from app.modules.enrollments.access_service import get_assignment_access_window

    return await get_assignment_access_window(
        db,
        user_id=user.id,
        tenant_id=user.tenant_id,
        course_id=course_id,
        enrollment_id=getattr(user, "assignment_access_enrollment_id", None),
    )


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    course = await require_course_access(db, course_id, user)
    course.reviewer = await _hydrate_reviewer(db, course)
    return course


@router.get("/{course_id}/preview", response_model=CoursePreviewResponse)
async def get_course_preview(
    course_id: UUID,
    max_chars: int = Query(240, ge=80, le=2000, description="Max chars of lesson content to include inline"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    """Lightweight course structure for the AI-generation review step.

    Returns modules → lessons → quiz headers (without questions/answers).
    Designed so the methodologist can sanity-check what the AI produced
    without needing to open every lesson in the editor.
    """
    from app.modules.lessons.models import Module
    from app.modules.quizzes.models import Question, Quiz

    course = (
        await db.execute(
            select(Course)
            .where(Course.id == course_id, Course.tenant_id == user.tenant_id)
            .options(selectinload(Course.modules).selectinload(Module.lessons))
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
            (await db.execute(select(Quiz).where(Quiz.lesson_id.in_(lesson_ids), Quiz.tenant_id == user.tenant_id)))
            .scalars()
            .all()
        )
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

    source_documents: list[CoursePreviewSourceDocument] = []
    source_ids: list[UUID] = []
    for value in cast(list[object] | None, course.source_document_ids) or []:
        try:
            source_ids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if source_ids:
        source_rows = (
            (
                await db.execute(
                    select(Document).where(
                        Document.tenant_id == user.tenant_id,
                        Document.id.in_(source_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        source_by_id = {document.id: document for document in source_rows}
        source_documents = [
            CoursePreviewSourceDocument(
                id=document_id,
                title=source_by_id[document_id].title,
                filename=source_by_id[document_id].filename,
            )
            for document_id in source_ids
            if document_id in source_by_id
        ]

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
            lessons_out.append(
                CoursePreviewLesson(
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
                    source_document_ids=list(l.source_document_ids or []),
                    source_references=list(l.source_references or []),
                    source_validation_status=l.source_validation_status,
                )
            )
            total_lessons += 1
            if quiz:
                total_quizzes += 1
        preview_modules.append(
            CoursePreviewModule(
                id=m.id,
                title=m.title,
                description=m.description,
                order_index=m.order_index,
                lessons=lessons_out,
            )
        )

    return CoursePreviewResponse(
        id=course.id,
        title=course.title,
        description=course.description,
        status=course.status,
        modules_count=len(preview_modules),
        lessons_count=total_lessons,
        quizzes_count=total_quizzes,
        source_strategy=course.source_strategy,
        source_combination_goal=course.source_combination_goal,
        source_documents=source_documents,
        source_analysis=course.source_analysis or {},
        modules=preview_modules,
    )


@router.post("/{course_id}/review", response_model=CourseResponse)
async def review_course(
    course_id: UUID,
    req: CourseReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    """Mark a course as approved or needs_changes (methodologist sign-off).

    Sets review_status, reviewed_by (current user), reviewed_at (now),
    and review_comment. Designed for the AI-generation review step where
    the methodologist validates the AI's output before it goes to staff.
    """
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if req.review_status == "approved":
        from app.modules.courses.blueprint_service import (
            BlueprintContentConflictError,
            assert_blueprint_ready_for_approval,
        )

        try:
            assert_blueprint_ready_for_approval(course)
        except BlueprintContentConflictError as error:
            blueprint_marker = (course.source_analysis or {}).get("blueprint") or {}
            blueprint_id = str(blueprint_marker.get("id") or "")
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "blueprint_adaptation_incomplete",
                    "message": error.message,
                    "adaptation_url": f"/courses/templates/{blueprint_id}?course_id={course.id}",
                },
            ) from error

    course.review_status = req.review_status
    course.reviewed_by = user.id
    course.reviewed_at = datetime.now(UTC)
    course.review_comment = req.comment
    if req.review_status == "approved":
        from sqlalchemy import update

        from app.modules.lessons.models import Lesson, Module

        module_ids = select(Module.id).where(
            Module.course_id == course.id,
            Module.tenant_id == user.tenant_id,
        )
        await db.execute(
            update(Lesson)
            .where(
                Lesson.tenant_id == user.tenant_id,
                Lesson.module_id.in_(module_ids),
                Lesson.source_validation_status == "needs_review",
            )
            .values(source_validation_status="verified")
        )
    await db.flush()
    await db.refresh(course)
    await log_action(
        db,
        user.tenant_id,
        "review",
        "course",
        resource_id=str(course.id),
        user_id=user.id,
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
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    # A mutable edit invalidates all approval artifacts.  Reviewers must never
    # approve a snapshot that no longer matches the course being published.
    from app.modules.course_approval.service import supersede_course_approvals
    await supersede_course_approvals(db, course_id=course.id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.flush()
    await db.refresh(course)
    await log_action(
        db,
        user.tenant_id,
        "update",
        "course",
        resource_id=str(course.id),
        user_id=user.id,
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
    user: User = Depends(require_role("superadmin", "methodologist")),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    from app.modules.course_approval.models import WorkflowIdempotencyKey
    publish_fingerprint = canonical_json_sha256({"course_id": str(course_id)}) if idempotency_key else None
    if idempotency_key:
        if len(idempotency_key) > 200:
            raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
        prior = await db.scalar(select(WorkflowIdempotencyKey).where(
            WorkflowIdempotencyKey.tenant_id == user.tenant_id,
            WorkflowIdempotencyKey.key == idempotency_key,
            WorkflowIdempotencyKey.operation == "course.publish",
        ))
        if prior is not None:
            if prior.request_fingerprint != publish_fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            existing = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
            if existing is None:
                raise HTTPException(status_code=404, detail="Course not found")
            existing.reviewer = await _hydrate_reviewer(db, existing)
            return existing
    # Serialize publication against course edits and approval decisions.  The
    # lock must be acquired before reading the approved revision or rebuilding
    # the live snapshot, otherwise a concurrent edit can bypass the hash gate.
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id).with_for_update())
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.status == "published":
        raise HTTPException(status_code=409, detail="Course is already published")
    # Optional immutable approval gate.  Existing courses default to off;
    # enabled courses publish only the latest approved frozen snapshot.
    from app.modules.course_approval.models import CourseApprovalPolicy, CourseApprovalRevision
    approval_policy = await db.scalar(
        select(CourseApprovalPolicy).where(
            CourseApprovalPolicy.course_id == course.id,
            CourseApprovalPolicy.tenant_id == user.tenant_id,
        )
    )
    approved_revision = None
    if approval_policy is not None and approval_policy.requires_approval:
        approved_revision = await db.scalar(
            select(CourseApprovalRevision)
            .where(
                CourseApprovalRevision.course_id == course.id,
                CourseApprovalRevision.tenant_id == user.tenant_id,
            )
            .order_by(CourseApprovalRevision.revision_number.desc())
            .limit(1)
            .with_for_update()
        )
        if approved_revision is None:
            raise HTTPException(status_code=409, detail={"code": "approval_required"})
        if approved_revision.state != "approved":
            code = "approval_pending" if approved_revision.state == "pending" else "approval_changes_requested" if approved_revision.state == "changes_requested" else "approval_superseded"
            raise HTTPException(status_code=409, detail={"code": code})
        from app.modules.courses.release_service import build_course_release_snapshot
        current_snapshot = await build_course_release_snapshot(db, course, version=approved_revision.revision_number)
        if canonical_json_sha256(current_snapshot) != approved_revision.snapshot_sha256:
            raise HTTPException(status_code=409, detail={"code": "approval_revision_mismatch"})
    blueprint_marker = (course.source_analysis or {}).get("blueprint") or {}
    if blueprint_marker:
        from app.modules.courses.blueprint_service import (
            BlueprintContentConflictError,
            assert_blueprint_ready_for_approval,
        )

        try:
            assert_blueprint_ready_for_approval(course)
        except BlueprintContentConflictError as error:
            blueprint_id = str(blueprint_marker.get("id") or "")
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "blueprint_adaptation_incomplete",
                    "message": error.message,
                    "adaptation_url": f"/courses/templates/{blueprint_id}?course_id={course.id}",
                },
            ) from error
    if (course.ai_generated or blueprint_marker) and course.review_status != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "course_review_required",
                "message": "Перед публикацией курс должен быть проверен и одобрен методологом",
            },
        )
    from app.modules.lessons.models import Lesson, Module
    from app.modules.quizzes.models import Quiz

    stale_quiz = await db.scalar(
        select(Quiz.id)
        .join(Lesson, Lesson.id == Quiz.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .where(
            Module.course_id == course.id,
            Quiz.tenant_id == user.tenant_id,
            Quiz.review_status == "needs_review",
        )
        .limit(1)
    )
    if stale_quiz:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "quiz_review_required",
                "message": "Перед публикацией проверьте тесты, отмеченные после изменения урока.",
            },
        )
    if course.source_instruction_id is not None and not course.ai_generated:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "instruction_course_incomplete",
                "message": ("Генерация курса по должностной инструкции ещё не завершена"),
            },
        )
    from app.modules.courses.release_service import create_course_release, create_course_release_from_snapshot

    release = (
        await create_course_release_from_snapshot(db, course, approved_revision.snapshot, published_by=user.id)
        if approved_revision is not None
        else await create_course_release(db, course, published_by=user.id)
    )
    course.status = "published"
    course.published_at = release.published_at or datetime.now(UTC)
    if approved_revision is not None:
        approved_revision.state = "published"
        approved_revision.published_release_id = release.id
    await db.flush()
    await activate_course_assignments(db, course)
    await db.refresh(course)
    await log_action(
        db,
        user.tenant_id,
        "publish",
        "course",
        resource_id=str(course.id),
        user_id=user.id,
        details={
            "content_release_id": str(release.id),
            "content_release_version": release.version,
            "snapshot_sha256": release.snapshot_sha256,
            "approval_revision_id": str(approved_revision.id) if approved_revision is not None else None,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)
    if idempotency_key:
        db.add(WorkflowIdempotencyKey(
            tenant_id=user.tenant_id,
            key=idempotency_key,
            operation="course.publish",
            request_fingerprint=publish_fingerprint,
            response={"course_id": str(course.id), "release_id": str(release.id)},
        ))
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            prior = await db.scalar(select(WorkflowIdempotencyKey).where(
                WorkflowIdempotencyKey.tenant_id == user.tenant_id,
                WorkflowIdempotencyKey.key == idempotency_key,
                WorkflowIdempotencyKey.operation == "course.publish",
            ))
            if prior is None or prior.request_fingerprint != publish_fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict") from None
    return course


@router.post("/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    from app.modules.course_approval.models import WorkflowIdempotencyKey
    unpublish_fingerprint = canonical_json_sha256({"course_id": str(course_id)}) if idempotency_key else None
    if idempotency_key:
        prior = await db.scalar(select(WorkflowIdempotencyKey).where(WorkflowIdempotencyKey.tenant_id == user.tenant_id, WorkflowIdempotencyKey.key == idempotency_key, WorkflowIdempotencyKey.operation == "course.unpublish"))
        if prior is not None:
            if prior.request_fingerprint != unpublish_fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            existing = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
            if existing is None:
                raise HTTPException(status_code=404, detail="Course not found")
            existing.reviewer = await _hydrate_reviewer(db, existing)
            return existing
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "draft"
    course.published_at = None
    await db.flush()
    await refresh_course_assignments(db, course)
    await db.refresh(course)
    await log_action(
        db,
        user.tenant_id,
        "unpublish",
        "course",
        resource_id=str(course.id),
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)
    if idempotency_key:
        db.add(WorkflowIdempotencyKey(tenant_id=user.tenant_id, key=idempotency_key, operation="course.unpublish", request_fingerprint=unpublish_fingerprint, response={"course_id": str(course.id)}))
        await db.commit()
    return course


@router.post("/{course_id}/duplicate", response_model=CourseResponse, status_code=201)
async def duplicate_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    from app.core.trial_limits import assert_can_create_courses

    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
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
        db,
        user.tenant_id,
        "duplicate",
        "course",
        resource_id=str(new_course.id),
        user_id=user.id,
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
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.current_release_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Published course evidence cannot be deleted; archive the course instead",
        )
    await log_action(
        db,
        user.tenant_id,
        "delete",
        "course",
        resource_id=str(course.id),
        user_id=user.id,
        details={"title": course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.delete(course)
    await db.commit()


@router.post("/{course_id}/archive", response_model=CourseResponse)
async def archive_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    user: User = Depends(require_role("superadmin", "methodologist")),  # noqa: B008
) -> CourseResponse:
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.status == "archived":
        return CourseResponse.model_validate(course)

    previous_status = course.status
    course.status = "archived"  # type: ignore[assignment]
    await db.flush()
    await db.refresh(course)
    response = CourseResponse.model_validate(course)
    await log_action(
        db,
        UUID(str(user.tenant_id)),
        "archive",
        "course",
        resource_id=str(course.id),
        user_id=UUID(str(user.id)),
        details={
            "title": course.title,
            "previous_status": previous_status,
            "content_release_id": str(course.current_release_id) if course.current_release_id else None,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return response


async def _complete_course_for_user(db: AsyncSession, course_id: UUID, user: User) -> dict:
    from app.models.enrollment import Enrollment
    from app.models.progress import Progress
    from app.modules.audit.service import log_action
    from app.modules.certificates.service import issue_certificate
    from app.modules.courses.release_models import ContentRelease
    from app.modules.enrollments.access_service import (
        AssignmentWindowExpiredError,
        assignment_window_error,
        require_active_enrollment_window,
        require_assignment_enrollment_read_access,
    )
    from app.modules.enrollments.context import current_enrollment
    from app.modules.lessons.models import Lesson, Module
    from app.modules.quizzes.models import Question, Quiz, QuizAttempt

    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    user_id = UUID(str(user.id))
    tenant_id = UUID(str(user.tenant_id))
    try:
        await require_active_enrollment_window(
            db,
            user_id=user_id,
            tenant_id=tenant_id,
            course_id=course_id,
            enrollment_id=assignment_enrollment_id,
        )
    except AssignmentWindowExpiredError as exc:
        if assignment_enrollment_id is None or exc.code != "assignment_enrollment_not_active":
            raise assignment_window_error(exc) from exc
        try:
            # Completion is idempotent. A credential-bound learner may read
            # back the same completed enrollment; revoked, cancelled and
            # cross-tenant credentials still fail closed in this read guard.
            await require_assignment_enrollment_read_access(
                db,
                user_id=user_id,
                tenant_id=tenant_id,
                course_id=course_id,
                enrollment_id=assignment_enrollment_id,
            )
        except AssignmentWindowExpiredError as read_exc:
            raise assignment_window_error(read_exc) from read_exc
    enrollment = await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course_id)
    if assignment_enrollment_id is None and (
        enrollment is None or enrollment.status == "completed"
    ):
        # A historical completion for the same course must not win over the
        # active assignment-scoped enrollment for the current path cycle.
        enrollment = await db.scalar(
            select(Enrollment)
            .where(
                Enrollment.tenant_id == tenant_id,
                Enrollment.user_id == user_id,
                Enrollment.course_id == course_id,
                Enrollment.status != "completed",
                Enrollment.learning_path_assignment_id.is_not(None),
            )
            .order_by(Enrollment.enrolled_at.desc())
            .limit(1)
        ) or enrollment

    course_result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = course_result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    total_lessons = (
        await db.scalar(
            select(func.count(Lesson.id))
            .join(Module, Lesson.module_id == Module.id)
            .where(
                Module.course_id == course_id,
                Module.tenant_id == user.tenant_id,
                Lesson.tenant_id == user.tenant_id,
            )
        )
        or 0
    )
    if total_lessons == 0:
        raise HTTPException(status_code=400, detail="Course has no lessons")

    completed_lessons = (
        await db.scalar(
            select(func.count(func.distinct(Progress.lesson_id)))
            .join(Lesson, Progress.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .where(
                Module.course_id == course_id,
                Progress.user_id == user.id,
                Progress.tenant_id == user.tenant_id,
                Progress.completed.is_(True),
                Progress.enrollment_id
                == (
                    enrollment.id
                    if enrollment
                    and (
                        enrollment.recurring_assignment_id
                        or getattr(enrollment, "learning_path_assignment_id", None)
                    )
                    else None
                ),
            )
        )
        or 0
    )
    if completed_lessons < total_lessons:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "lessons_incomplete",
                "completed_lessons": completed_lessons,
                "total_lessons": total_lessons,
            },
        )

    total_quizzes = (
        await db.scalar(
            select(func.count(func.distinct(Quiz.id)))
            .join(Lesson, Quiz.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .join(Question, Question.quiz_id == Quiz.id)
            .where(
                Module.course_id == course_id,
                Module.tenant_id == user.tenant_id,
                Quiz.tenant_id == user.tenant_id,
            )
        )
        or 0
    )
    passed_quizzes = (
        await db.scalar(
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
                QuizAttempt.passed.is_(True),
                QuizAttempt.enrollment_id == (enrollment.id if enrollment else None),
            )
        )
        or 0
    )
    if passed_quizzes < total_quizzes:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "quizzes_incomplete",
                "passed_quizzes": passed_quizzes,
                "total_quizzes": total_quizzes,
            },
        )

    release_id = enrollment.content_release_id if enrollment else None
    if release_id is None:
        release_id = course.current_release_id
    if release_id is None:
        raise HTTPException(
            status_code=400,
            detail="Course must have an immutable ContentRelease before completion",
        )

    release = await db.scalar(
        select(ContentRelease).where(
            ContentRelease.id == release_id,
            ContentRelease.course_id == course.id,
            ContentRelease.tenant_id == user.tenant_id,
        )
    )
    if release is None:
        raise HTTPException(
            status_code=409,
            detail="Course completion release evidence is unavailable",
        )

    if not enrollment:
        enrollment = Enrollment(
            course_id=course_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
            content_release_id=release_id,
            status="enrolled",
            source="manual",
        )
        db.add(enrollment)
        await db.flush()
    elif enrollment.content_release_id is None:
        # Bind legacy enrollments to the immutable release used for this
        # completion before creating its evidence record.
        enrollment.content_release_id = release_id

    was_already_completed = enrollment.status == "completed"
    if not was_already_completed:
        enrollment.status = "completed"
        enrollment.completed_at = datetime.now(UTC)
        # A completed required step can unlock the next course in one or more
        # assigned learning programs. Keep this in the same transaction as the
        # completion so learners never observe a completed step without the
        # newly available course enrollment.
        from app.modules.certificates.service import issue_learning_path_certificate
        from app.modules.learning_paths.service import (
            sync_learning_path_enrollments_after_course_completion,
        )

        completed_program_assignments = await sync_learning_path_enrollments_after_course_completion(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            return_completed_assignments=True,
        )
        if isinstance(completed_program_assignments, int):
            completed_program_assignments = []
        for program_assignment in completed_program_assignments:
            await issue_learning_path_certificate(
                db,
                tenant_id=user.tenant_id,
                user=user,
                learning_path_assignment_id=program_assignment.id,
            )

    cert = await issue_certificate(
        db=db,
        user_id=user.id,
        course_id=course_id,
        tenant_id=user.tenant_id,
        enrollment_id=enrollment.id,
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

    from app.modules.training_evidence.workflow import record_course_completion

    evidence_event = await record_course_completion(
        db,
        user=user,
        course=course,
        enrollment=enrollment,
        certificate=cert,
    )

    if enrollment.recurring_assignment_id:
        from app.modules.learning_cycles.models import RecurringLearningAssignment

        occurrence = await db.scalar(
            select(RecurringLearningAssignment).where(
                RecurringLearningAssignment.id == enrollment.recurring_assignment_id,
                RecurringLearningAssignment.tenant_id == user.tenant_id,
            )
        )
        if occurrence is not None:
            occurrence.status = "completed"

    await db.commit()
    return {
        "status": "already_completed" if was_already_completed else "completed",
        "course_id": str(course_id),
        "certificate_number": cert_number,
        "certificate_id": cert_id,
        "training_evidence_event_id": evidence_event.id,
    }


@router.post("/{course_id}/complete", response_model=CourseCompletionResponse)
async def complete_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    return await _complete_course_for_user(db, course_id, user)
