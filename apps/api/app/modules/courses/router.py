from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
    CourseResolveSourceUncertaintyRequest,
    CourseResponse,
    CourseReviewer,
    CourseReviewRequest,
    CourseSourceUncertaintyDefectInfo,
    CourseSourceUncertaintyDetailsResponse,
    CourseUpdate,
    SourceDocumentRevisionInfo,
)
from app.modules.enrollments.schemas import AssignmentAccessWindowResponse

router = APIRouter(
    prefix="/courses",
    tags=["courses"],
    dependencies=[Depends(require_tenant_user())],
)


@router.get("/{course_id}/lessons/{lesson_id}/source-assets/{asset_id}")
async def get_lesson_source_asset(course_id: UUID, lesson_id: UUID, asset_id: str,
                                  db: Annotated[AsyncSession, Depends(get_db)],
                                  user: Annotated[User, Depends(get_current_user)]) -> Response:
    from app.modules.source_preparation.assets import course_asset

    return await course_asset(db, course_id, lesson_id, asset_id, user)


def _preview_source_references(references: list[Any], lesson_source_ids: list[Any],
                               owned_documents: dict[UUID, Any], source_analysis: Any) -> list[Any]:
    """Add response-only names to fresh-v3 spans from the tenant-scoped document map."""
    from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, KEY

    if (not isinstance(source_analysis, dict) or source_analysis.get(KEY) != DIRECT_POLICY
            or source_analysis.get("generation_engine") != "evidence_v3"):
        return references
    allowed = {str(value) for value in lesson_source_ids}
    projected = []
    for reference in references:
        if not isinstance(reference, dict) or reference.get("kind") != "working_text_span_v1":
            projected.append(reference)
            continue
        item = dict(reference)
        item.pop("doc_name", None)
        item.pop("document", None)
        doc_id = item.get("doc_id")
        try:
            document = owned_documents.get(UUID(doc_id)) if isinstance(doc_id, str) and doc_id in allowed else None
        except ValueError:
            document = None
        if document is not None:
            item["doc_name"] = document.filename or document.title
        projected.append(item)
    return projected


async def _hydrate_reviewer(db: AsyncSession, course: Course) -> CourseReviewer | None:
    """Resolve the reviewer user record into a small embed (best-effort).
    Returns None if there is no reviewer on this course."""
    if not course.reviewed_by:
        return None
    user = await db.get(User, course.reviewed_by)
    if not user:
        return None
    return CourseReviewer.model_validate(user)


async def _hydrate_course_authors(db: AsyncSession, courses: Sequence[Course], tenant_id: object) -> None:
    """One tenant-filtered name projection; never expose foreign authors or emails."""
    ids = {course.created_by for course in courses if course.created_by}
    names = {}
    if ids:
        rows = (await db.execute(select(User.id, User.first_name, User.last_name).where(
            User.tenant_id == tenant_id, User.id.in_(ids)))).all()
        names = {row.id: ' '.join(part.strip() for part in (row.first_name, row.last_name)
                                  if isinstance(part, str) and part.strip()) or None for row in rows}
    for course in courses:
        cast(Any, course).author_name = names.get(course.created_by)


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
    await _hydrate_course_authors(db, courses, user.tenant_id)
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
    await _hydrate_course_authors(db, [course], user.tenant_id)
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
    source_by_id: dict[UUID, Any] = {}
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
        source_by_id = {cast(UUID, document.id): document for document in source_rows}
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
                    source_references=_preview_source_references(
                        list(l.source_references or []), list(l.source_document_ids or []),
                        source_by_id, course.source_analysis),
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
    from app.modules.courses.source_uncertainty import is_qa_source_tenant, qa_source_holds_enabled

    qa_source_guard = req.review_status == "approved" and qa_source_holds_enabled(user.tenant_id)
    query = select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    if req.review_status == "approved":
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if req.review_status == "approved":
        from app.modules.courses.source_uncertainty import require_current_draft_review

        await require_current_draft_review(db, course)
        from app.modules.courses.source_uncertainty import (
            require_persisted_source_hold_clear,
            require_source_uncertainty_clear,
        )

        if is_qa_source_tenant(user.tenant_id):
            require_persisted_source_hold_clear(course.source_analysis)
        if qa_source_guard:
            require_source_uncertainty_clear(course.source_analysis)
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


async def _extract_course_source_revisions(
    db: AsyncSession, course: Course, *, for_update: bool = False
) -> tuple[list[str], dict[str, str], list[SourceDocumentRevisionInfo]]:
    """Gathers authoritative source revisions from DB Document records and enforces strict consistency.

    Invariants enforced:
    1. DB Document records of the current tenant are the sole authoritative source of truth for document revisions.
    2. All declared document IDs across:
       - course.source_instruction_id
       - course.source_document_ids
       - lesson source_document_ids (for all lessons in the course)
       - course.source_analysis (source_documents list and any other source document keys)
       MUST exist in the DB for course.tenant_id.
       Any missing document, foreign tenant document, unparseable ID, or missing DB revision
       immediately raises ValueError (fail-closed).
    3. Metadata in course.source_analysis is strictly validated against DB Document records.
       Any conflict between analysis metadata and DB records raises ValueError (fail-closed).
       Analysis metadata NEVER creates, overrides, or acts as a fallback for DB records.
    4. Authoritative revisions are never forged (no fake revisions like 'vNone' or 'v0').
    5. Both GET and POST endpoints construct and verify the identical authoritative mapping.
    """
    from app.models.document import Document
    from app.modules.lessons.models import Lesson, Module

    available_revisions: list[str] = []
    authoritative_doc_revisions: dict[str, str] = {}
    docs_info: list[SourceDocumentRevisionInfo] = []

    # Map of UUID -> source description for clear domain error reporting
    declared_docs: dict[UUID, str] = {}

    # 1. Source instruction ID
    if course.source_instruction_id is not None:
        try:
            inst_uuid = course.source_instruction_id if isinstance(course.source_instruction_id, UUID) else UUID(str(course.source_instruction_id).strip())
            declared_docs[inst_uuid] = "инструкция курса"
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"Идентификатор инструкции курса '{course.source_instruction_id}' имеет неверный формат (ожидался UUID).") from exc

    # 2. Course-level source document IDs
    if getattr(course, "source_document_ids", None):
        raw_course_docs = course.source_document_ids
        if not isinstance(raw_course_docs, list):
            raise ValueError("Поле 'source_document_ids' курса имеет неверный формат (ожидался список).")
        for raw_id in raw_course_docs:
            try:
                doc_uuid = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id).strip())
                if doc_uuid not in declared_docs:
                    declared_docs[doc_uuid] = "документ источника курса"
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"Идентификатор документа курса '{raw_id}' имеет неверный формат (ожидался UUID).") from exc

    # 3. Lesson-level declared source document IDs
    lessons_stmt = (
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course.id, Lesson.tenant_id == course.tenant_id)
    )
    lessons_res = await db.execute(lessons_stmt)
    for lesson in lessons_res.scalars().all():
        lesson_source_ids = getattr(lesson, "source_document_ids", None)
        if lesson_source_ids and isinstance(lesson_source_ids, list):
            for raw_id in lesson_source_ids:
                try:
                    doc_uuid = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id).strip())
                    if doc_uuid not in declared_docs:
                        declared_docs[doc_uuid] = f"документ источника урока '{getattr(lesson, 'title', '')}'"
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValueError(f"Идентификатор документа источника урока '{raw_id}' имеет неверный формат (ожидался UUID).") from exc

    # 4. Source analysis metadata source documents (MUST also be validated against DB!)
    sa: dict[str, Any] = course.source_analysis if isinstance(course.source_analysis, dict) else {}
    sa_source_docs = sa.get("source_documents")
    if sa_source_docs and isinstance(sa_source_docs, list):
        for item in sa_source_docs:
            if isinstance(item, dict) and item.get("id"):
                raw_id = item["id"]
                try:
                    doc_uuid = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id).strip())
                    if doc_uuid not in declared_docs:
                        declared_docs[doc_uuid] = "документ из метаданных анализа"
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValueError(f"Идентификатор документа из анализа курса '{raw_id}' имеет неверный формат (ожидался UUID).") from exc

    # 5. Authoritative verification against Database Document records of the CURRENT TENANT
    if declared_docs:
        docs_stmt = (
            select(Document)
            .where(
                Document.id.in_(list(declared_docs.keys())),
                Document.tenant_id == course.tenant_id,
            )
            .order_by(Document.id)
        )
        if for_update:
            docs_stmt = docs_stmt.with_for_update().execution_options(populate_existing=True)
        docs_res = await db.execute(docs_stmt)
        found_docs: dict[UUID, Document] = {cast(UUID, doc.id): doc for doc in docs_res.scalars().all()}

        # Verify EVERY declared document exists in DB and belongs to the current tenant
        for req_id, doc_label in declared_docs.items():
            if req_id not in found_docs:
                raise ValueError(
                    f"Задекларированный {doc_label} с идентификатором '{req_id}' не найден в базе данных текущего тенанта."
                )

        # Build authoritative revisions solely from confirmed DB Document rows
        for doc_uuid, doc in sorted(found_docs.items(), key=lambda kv: str(kv[0])):
            doc_id_str = str(doc_uuid)
            doc_sha = str(getattr(doc, "content_sha256", None) or "").strip()
            doc_ver = getattr(doc, "version", None)
            doc_idx_rev = getattr(doc, "index_revision", None)

            # Determine canonical revision without inventing fake strings (no 'vNone')
            doc_rev = ""
            if doc_sha:
                doc_rev = doc_sha
            elif doc_ver is not None and str(doc_ver).strip() and str(doc_ver).strip().lower() != "none":
                doc_rev = f"v{doc_ver}"
            elif doc_idx_rev is not None and str(doc_idx_rev).strip() and str(doc_idx_rev).strip().lower() != "none":
                doc_rev = f"rev{doc_idx_rev}"
            elif course.source_instruction_id == doc_uuid and course.source_instruction_version_at:
                doc_rev = course.source_instruction_version_at.isoformat()

            if not doc_rev:
                raise ValueError(
                    f"Для документа источника '{getattr(doc, 'title', '') or doc_uuid}' не определена актуальная ревизия в базе данных."
                )

            authoritative_doc_revisions[doc_id_str] = doc_rev
            available_revisions.append(doc_rev)
            if doc_ver is not None:
                available_revisions.append(f"v{doc_ver}")
            if doc_sha:
                available_revisions.append(doc_sha)

            docs_info.append(
                SourceDocumentRevisionInfo(
                    document_id=doc_id_str,
                    title=str(getattr(doc, "title", "") or "Документ источника"),
                    filename=str(getattr(doc, "filename", "") or "source.pdf"),
                    authoritative_revision=doc_rev,
                )
            )

        # 6. Validate analysis metadata against authoritative DB records (Never overwrite DB revision!)
        if sa_source_docs and isinstance(sa_source_docs, list):
            for item in sa_source_docs:
                if isinstance(item, dict) and item.get("id"):
                    d_id_str = str(item["id"])
                    analysis_rev = str(item.get("revision") or "").strip()
                    if d_id_str not in authoritative_doc_revisions:
                        raise ValueError(
                            f"Документ источника '{d_id_str}' из анализа отсутствует среди задекларированных документов курса в базе данных."
                        )
                    db_rev = authoritative_doc_revisions[d_id_str]
                    doc_obj = found_docs.get(UUID(d_id_str))
                    valid_revs = {db_rev}
                    if doc_obj:
                        if getattr(doc_obj, "content_sha256", None):
                            valid_revs.add(str(doc_obj.content_sha256).strip())
                        if getattr(doc_obj, "version", None) is not None:
                            valid_revs.add(f"v{doc_obj.version}")
                    if analysis_rev and analysis_rev not in valid_revs:
                        raise ValueError(
                            f"Конфликт ревизий для документа '{d_id_str}': ревизия в анализе '{analysis_rev}' "
                            f"не совпадает с актуальной ревизией документа в базе данных '{db_rev}'."
                        )

        # Single document check for general analysis revisions
        sa_rev = str(sa.get("source_revision") or "").strip()
        if sa_rev and len(found_docs) == 1:
            single_doc = next(iter(found_docs.values()))
            single_rev = authoritative_doc_revisions[str(single_doc.id)]
            valid_revs = {single_rev}
            if getattr(single_doc, "content_sha256", None):
                valid_revs.add(str(single_doc.content_sha256).strip())
            if getattr(single_doc, "version", None) is not None:
                valid_revs.add(f"v{single_doc.version}")
            if sa_rev not in valid_revs:
                raise ValueError(
                    f"Конфликт ревизий: ревизия в анализе курса '{sa_rev}' "
                    f"не совпадает с актуальной ревизией документа в базе данных '{single_rev}'."
                )

        if course.source_instruction_version_at:
            available_revisions.append(course.source_instruction_version_at.isoformat())

    elif course.source_instruction_version_at:
        # Verified DB timestamp column on Course (instruction version)
        available_revisions.append(course.source_instruction_version_at.isoformat())

    # When no authoritative documents exist in DB and no verified DB instruction version exists,
    # available_revisions remains empty. Unbacked metadata strings in source_analysis (e.g. source_revision,
    # document_revision, revision) are NEVER accepted as authoritative without matching tenant DB records.
    unique_revisions = list(dict.fromkeys(r for r in available_revisions if r))
    return unique_revisions, authoritative_doc_revisions, docs_info


@router.get("/{course_id}/source-uncertainty", response_model=CourseSourceUncertaintyDetailsResponse)
async def get_course_source_uncertainty_details(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    user: User = Depends(require_role("superadmin", "methodologist")),  # noqa: B008
) -> CourseSourceUncertaintyDetailsResponse:
    """Official methodologist inspection endpoint: delivers current content snapshot hash,
    authoritative source document revisions, and active defect IDs required for resolution."""
    from app.modules.courses.source_uncertainty import (
        SOURCE_UNCERTAINTY_KEY,
        compute_course_content_snapshot_hash,
        get_active_source_defects,
    )

    query = select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    result = await db.execute(query)
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        content_hash = await compute_course_content_snapshot_hash(db, course)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "course_snapshot_build_failed",
                "message": "Не удалось сформировать полный снимок курса для проверки целостности. Пожалуйста, проверьте доступность структуры курса.",
            },
        ) from exc

    try:
        avail_revs, _, docs_info = await _extract_course_source_revisions(db, course)
    except ValueError as val_err:
        raise HTTPException(
            status_code=409,
            detail={"code": "source_uncertainty_resolution_rejected", "message": str(val_err)},
        ) from val_err

    sa: dict[str, Any] = course.source_analysis if isinstance(course.source_analysis, dict) else {}
    has_hold = SOURCE_UNCERTAINTY_KEY in sa
    from app.modules.courses.draft_review import read_draft_review, resolution_is_current

    manifest = read_draft_review(sa)
    if manifest is not None:
        review_current = resolution_is_current(sa, content_hash)
        if not has_hold and not review_current:
            from app.modules.courses.automated_editorial_acceptance import automatic_acceptance_is_current

            review_current = await automatic_acceptance_is_current(db, course=course, content_hash=content_hash)
        has_hold = has_hold or not review_current

    raw_defects = get_active_source_defects(sa)
    active_defects = [
        CourseSourceUncertaintyDefectInfo(**d)
        for d in raw_defects
    ]
    history: list[dict[str, Any]] = list(sa.get("resolutions_history") or [])

    return CourseSourceUncertaintyDetailsResponse(
        course_id=cast(UUID, course.id),
        has_active_hold=has_hold,
        content_snapshot_hash=content_hash,
        available_revisions=avail_revs,
        source_documents=docs_info,
        active_defects=active_defects if has_hold or manifest is None else [],
        resolutions_history=history,
        draft_review=manifest,
    )


@router.post("/{course_id}/resolve-source-uncertainty", response_model=CourseResponse)
async def resolve_course_source_uncertainty(
    course_id: UUID,
    req: CourseResolveSourceUncertaintyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    user: User = Depends(require_role("superadmin", "methodologist")),  # noqa: B008
) -> Course:
    """Authorized methodologist endpoint: clears server-owned source uncertainty hold.

    Validates tenant isolation, records immutable resolution entry with user ID,
    timestamp, and reason into Course.source_analysis, and writes an audit log.
    """
    from app.modules.courses.source_uncertainty import (
        compute_course_content_snapshot_hash,
        resolve_source_uncertainty,
    )

    query = select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id).with_for_update()
    result = await db.execute(query)
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        available_revisions, authoritative_document_revisions, _ = await _extract_course_source_revisions(
            db, course, for_update=True
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=409,
            detail={"code": "source_uncertainty_resolution_rejected", "message": str(val_err)},
        ) from val_err
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "course_snapshot_build_failed",
                "message": "Не удалось сформировать полный снимок курса для проверки целостности. Пожалуйста, проверьте доступность структуры курса.",
            },
        ) from exc

    try:
        actual_hash = await compute_course_content_snapshot_hash(db, course)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "course_snapshot_build_failed",
                "message": "Не удалось сформировать полный снимок курса для проверки целостности. Пожалуйста, проверьте доступность структуры курса.",
            },
        ) from exc

    defect_payload = [d.model_dump() for d in req.defect_resolutions]

    try:
        updated_analysis = resolve_source_uncertainty(
            course.source_analysis,  # type: ignore[arg-type]
            reason=req.reason,
            methodologist_user_id=user.id,
            expected_content_hash=req.expected_content_hash,
            actual_content_hash=actual_hash,
            verified_revision=req.verified_revision,
            available_revisions=available_revisions or None,
            authoritative_document_revisions=authoritative_document_revisions or None,
            verified_revisions=req.verified_revisions or None,
            defect_resolutions=defect_payload,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=409,
            detail={"code": "source_uncertainty_resolution_rejected", "message": str(val_err)},
        ) from val_err

    course.source_analysis = updated_analysis  # type: ignore[assignment]
    await db.flush()
    await db.refresh(course)
    resolution_data = updated_analysis.get("source_uncertainty_resolution", {})
    await log_action(
        db,
        user.tenant_id,  # type: ignore[arg-type]
        "resolve_source_uncertainty",
        "course",
        resource_id=str(course.id),
        user_id=user.id,  # type: ignore[arg-type]
        details={
            "reason": req.reason,
            "resolved_at": resolution_data.get("resolved_at"),
            "content_hash": resolution_data.get("content_hash"),
            "verified_revision": resolution_data.get("verified_revision"),
            "defect_resolutions": resolution_data.get("defect_resolutions"),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    course.reviewer = await _hydrate_reviewer(db, course)  # type: ignore[attr-defined]
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
    from app.modules.courses.draft_review import read_draft_review

    if read_draft_review(course.source_analysis) is not None:
        editable = cast(Any, course)
        editable.review_status = 'pending'
        editable.reviewed_by = None
        editable.reviewed_at = None
        editable.review_comment = None
    # A mutable edit invalidates all approval artifacts.  Reviewers must never
    # approve a snapshot that no longer matches the course being published.
    from app.modules.course_approval.service import supersede_course_approvals
    await supersede_course_approvals(db, course_id=course.id, tenant_id=user.tenant_id, actor_id=user.id)  # type: ignore[arg-type]
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
    # FastAPI injects a string at runtime; direct unit calls receive the
    # ``Header`` marker object unless they provide a value explicitly.
    if not isinstance(idempotency_key, str):
        idempotency_key = None
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
            existing.reviewer = await _hydrate_reviewer(db, existing)  # type: ignore[attr-defined]
            return CourseResponse.model_validate(existing)
    # Serialize publication against course edits and approval decisions.  The
    # lock must be acquired before reading the approved revision or rebuilding
    # the live snapshot, otherwise a concurrent edit can bypass the hash gate.
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id).with_for_update())
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    from app.modules.courses.source_uncertainty import (
        is_qa_source_tenant,
        qa_source_holds_enabled,
        require_current_draft_review,
        require_persisted_source_hold_clear,
        require_source_uncertainty_clear,
    )

    await require_current_draft_review(db, course)

    if is_qa_source_tenant(user.tenant_id):
        require_persisted_source_hold_clear(course.source_analysis)
    qa_source_guard = qa_source_holds_enabled(user.tenant_id)
    if qa_source_guard:
        require_source_uncertainty_clear(course.source_analysis)
    if course.status == "published":
        if idempotency_key:
            # Another request may have committed while this request waited for
            # the course lock. Read its exact replay row before rejecting the
            # already-published state; never create a second release.
            prior = await db.scalar(select(WorkflowIdempotencyKey).where(
                WorkflowIdempotencyKey.tenant_id == user.tenant_id,
                WorkflowIdempotencyKey.key == idempotency_key,
                WorkflowIdempotencyKey.operation == "course.publish",
            ))
            if prior is not None:
                if prior.request_fingerprint != publish_fingerprint:
                    raise HTTPException(status_code=409, detail="idempotency_conflict")
                course.reviewer = await _hydrate_reviewer(db, course)  # type: ignore[attr-defined]
                return CourseResponse.model_validate(course)
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
        # freeze_revision canonicalizes content with release_version=1. Approval
        # counters are independent of publication versions and cannot enter this
        # hash comparison; the release factory allocates its version separately.
        current_snapshot = await build_course_release_snapshot(db, course, version=1)
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
    from app.modules.courses.release_service import (
        CourseContentRequiredError,
        create_course_release,
        create_course_release_from_snapshot,
    )

    try:
        release = (
            await create_course_release_from_snapshot(
                db,
                course,
                approved_revision.snapshot,
                published_by=user.id,
                require_usable_content=True,
            )
            if approved_revision is not None
            else await create_course_release(
                db,
                course,
                published_by=user.id,
                require_usable_content=True,
            )
        )
    except CourseContentRequiredError as error:
        raise HTTPException(status_code=409, detail={"code": "course_content_required"}) from error
    course.status = "published"  # type: ignore[assignment]
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
    course.reviewer = await _hydrate_reviewer(db, course)  # type: ignore[attr-defined]
    if idempotency_key:
        try:
            async with db.begin_nested():
                db.add(WorkflowIdempotencyKey(
                    tenant_id=user.tenant_id,
                    key=idempotency_key,
                    operation="course.publish",
                    request_fingerprint=publish_fingerprint,
                    response={"course_id": str(course.id), "release_id": str(release.id)},
                ))
                await db.flush()
        except IntegrityError:
            # get_db rolls back the whole publication on this HTTP error. A
            # replay-row conflict must not leave a published course committed
            # without its receipt or issue a context-free post-rollback query.
            raise HTTPException(status_code=409, detail="idempotency_conflict") from None
    response = CourseResponse.model_validate(course)
    # COMMIT clears transaction-local RLS context. Publication, audit and replay
    # are atomic; return only the detached DTO and perform no subsequent DB read.
    await db.commit()
    return response


@router.post("/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    if not isinstance(idempotency_key, str):
        idempotency_key = None
    from app.modules.course_approval.models import WorkflowIdempotencyKey
    unpublish_fingerprint = canonical_json_sha256({"course_id": str(course_id)}) if idempotency_key else None
    if idempotency_key:
        if len(idempotency_key) > 200:
            raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
        prior = await db.scalar(select(WorkflowIdempotencyKey).where(WorkflowIdempotencyKey.tenant_id == user.tenant_id, WorkflowIdempotencyKey.key == idempotency_key, WorkflowIdempotencyKey.operation == "course.unpublish"))
        if prior is not None:
            if prior.request_fingerprint != unpublish_fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            existing = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
            if existing is None:
                raise HTTPException(status_code=404, detail="Course not found")
            existing.reviewer = await _hydrate_reviewer(db, existing)
            return CourseResponse.model_validate(existing)
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id).with_for_update())
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if idempotency_key:
        # A same-key request may have completed while this one waited for the
        # course lock. Replay without a second audit or assignment refresh.
        prior = await db.scalar(select(WorkflowIdempotencyKey).where(WorkflowIdempotencyKey.tenant_id == user.tenant_id, WorkflowIdempotencyKey.key == idempotency_key, WorkflowIdempotencyKey.operation == "course.unpublish"))
        if prior is not None:
            if prior.request_fingerprint != unpublish_fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            course.reviewer = await _hydrate_reviewer(db, course)  # type: ignore[attr-defined]
            return CourseResponse.model_validate(course)
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
    course.reviewer = await _hydrate_reviewer(db, course)
    if idempotency_key:
        try:
            async with db.begin_nested():
                db.add(WorkflowIdempotencyKey(tenant_id=user.tenant_id, key=idempotency_key, operation="course.unpublish", request_fingerprint=unpublish_fingerprint, response={"course_id": str(course.id)}))
                await db.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="idempotency_conflict") from None
    response = CourseResponse.model_validate(course)
    await db.commit()
    return response


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
