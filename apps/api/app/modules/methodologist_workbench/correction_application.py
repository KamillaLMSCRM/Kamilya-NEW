"""One confirmed draft write + review invalidation + immutable digest receipt."""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.user_roles import UserRole
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.course_approval.models import (
    CourseApprovalPolicy,
    CourseApprovalRequest,
    CourseApprovalRevision,
    WorkflowAccessCredential,
    WorkflowWorkItem,
)
from app.modules.course_approval.service import supersede_course_approvals
from app.modules.courses.models import Course
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.lessons.schemas import LessonUpdate
from app.modules.lessons.service import update_lesson
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.scorm.models import ScormPackage

from .assignment_service import WorkbenchConflict, WorkbenchNotFound, _assert_actor
from .correction_context import resolve_lesson_correction
from .correction_contract import LessonCorrectionSnapshot, prepare_lesson_correction, preview_lesson_correction
from .correction_models import LessonCorrectionApplication
from .correction_proposal import CorrectionPatchAdapter
from .correction_schemas import CorrectionApplicationResponse, CorrectionProposal
from .correction_service import _assert_live_actor, _base_response, _database_now, _owned, _security_context
from .plan_contract import ActorContext, ConfirmationRequest


async def _receipt(db: AsyncSession, actor: ActorContext, plan_id: UUID) -> LessonCorrectionApplication | None:
    return cast(
        LessonCorrectionApplication | None,
        await db.scalar(
            select(LessonCorrectionApplication)
            .where(
                LessonCorrectionApplication.plan_id == plan_id,
                LessonCorrectionApplication.tenant_id == actor.tenant_id,
                LessonCorrectionApplication.actor_id == actor.actor_id,
            )
            .execution_options(populate_existing=True)
        ),
    )


async def get_correction_application(
    db: AsyncSession, actor: ActorContext, plan_id: UUID
) -> CorrectionApplicationResponse:
    _assert_actor(actor)
    await _security_context(db, actor)
    await _assert_live_actor(db, actor)
    row = await _receipt(db, actor, plan_id)
    if row is None:
        raise WorkbenchNotFound("application_not_found")
    # Historical receipt, never expiry/current-content revalidation or mutation.
    return CorrectionApplicationResponse.model_validate(row)


async def _lock_course_tree(db: AsyncSession, actor: ActorContext, course_id: UUID) -> Course:
    """Lock current rows parent first. Real immediate FK phantom proof is a DEV gate."""
    course = await db.scalar(
        select(Course)
        .where(Course.id == course_id, Course.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if course is None:
        raise WorkbenchNotFound("course_not_found")
    modules = list(
        (
            await db.scalars(
                select(Module)
                .where(Module.course_id == course_id, Module.tenant_id == actor.tenant_id)
                .order_by(Module.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    module_ids = [row.id for row in modules]
    lessons = list(
        (
            await db.scalars(
                select(Lesson)
                .where(Lesson.module_id.in_(module_ids), Lesson.tenant_id == actor.tenant_id)
                .order_by(Lesson.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    lesson_ids = [row.id for row in lessons]
    await db.scalars(
        select(ContentBlock.id)
        .where(ContentBlock.lesson_id.in_(lesson_ids))
        .order_by(ContentBlock.id)
        .with_for_update()
    )
    quiz_ids = list(
        (
            await db.scalars(
                select(Quiz.id)
                .where(Quiz.lesson_id.in_(lesson_ids), Quiz.tenant_id == actor.tenant_id)
                .order_by(Quiz.id)
                .with_for_update()
            )
        ).all()
    )
    question_ids = list(
        (
            await db.scalars(
                select(Question.id).where(Question.quiz_id.in_(quiz_ids)).order_by(Question.id).with_for_update()
            )
        ).all()
    )
    await db.scalars(
        select(QuizChoice.id).where(QuizChoice.question_id.in_(question_ids)).order_by(QuizChoice.id).with_for_update()
    )
    await db.scalars(
        select(ScormPackage.id)
        .where(ScormPackage.course_id == course_id, ScormPackage.tenant_id == actor.tenant_id)
        .order_by(ScormPackage.id)
        .with_for_update()
    )
    try:
        raw_ids = cast(object, course.source_document_ids)
        if not isinstance(raw_ids, list):
            raise ValueError
        source_ids = {UUID(str(value)) for value in raw_ids}
        instruction_id = cast(UUID | None, course.source_instruction_id)
        if instruction_id:
            source_ids.add(instruction_id)
        for lesson in lessons:
            lesson_ids_value = cast(object, lesson.source_document_ids)
            if not isinstance(lesson_ids_value, list):
                raise ValueError
            source_ids.update(UUID(str(value)) for value in lesson_ids_value)
    except (ValueError, TypeError):
        raise WorkbenchConflict("correction_record_invalid") from None
    await db.scalars(
        select(Document.id)
        .where(Document.id.in_(sorted(source_ids, key=str)), Document.tenant_id == actor.tenant_id)
        .order_by(Document.id)
        .with_for_update()
    )
    # Other approval owners use different lock orders. Never wait on one of
    # these rows while holding another: prelock NOWAIT before any domain write.
    await db.scalars(
        select(CourseApprovalPolicy.id)
        .where(CourseApprovalPolicy.course_id == course_id, CourseApprovalPolicy.tenant_id == actor.tenant_id)
        .order_by(CourseApprovalPolicy.id)
        .with_for_update(nowait=True)
    )
    revision_ids = list(
        (
            await db.scalars(
                select(CourseApprovalRevision.id)
                .where(
                    CourseApprovalRevision.course_id == course_id, CourseApprovalRevision.tenant_id == actor.tenant_id
                )
                .order_by(CourseApprovalRevision.id)
                .with_for_update(nowait=True)
            )
        ).all()
    )
    await db.scalars(
        select(CourseApprovalRequest.id)
        .where(CourseApprovalRequest.revision_id.in_(revision_ids), CourseApprovalRequest.tenant_id == actor.tenant_id)
        .order_by(CourseApprovalRequest.id)
        .with_for_update(nowait=True)
    )
    work_item_ids = list(
        (
            await db.scalars(
                select(WorkflowWorkItem.id)
                .where(
                    WorkflowWorkItem.review_revision_id.in_(revision_ids), WorkflowWorkItem.tenant_id == actor.tenant_id
                )
                .order_by(WorkflowWorkItem.id)
                .with_for_update(nowait=True)
            )
        ).all()
    )
    await db.scalars(
        select(WorkflowAccessCredential.id)
        .where(
            WorkflowAccessCredential.work_item_id.in_(work_item_ids),
            WorkflowAccessCredential.tenant_id == actor.tenant_id,
        )
        .order_by(WorkflowAccessCredential.id)
        .with_for_update(nowait=True)
    )
    return course


async def apply_correction_preview(
    db: AsyncSession, actor: ActorContext, request: ConfirmationRequest
) -> CorrectionApplicationResponse:
    """Own the complete transaction. No returned success before its single commit."""
    _assert_actor(actor)
    try:
        async with asyncio.timeout(100):
            await _security_context(db, actor)
            await db.execute(text("SET LOCAL lock_timeout = '3s'"))
            await db.execute(text("SET LOCAL statement_timeout = '15s'"))
            # SHARE blocks permission revocation without excluding the KEY SHARE
            # locks acquired by unrelated audit-user FKs.
            await db.scalars(
                select(User.id)
                .where(User.id == actor.actor_id, User.tenant_id == actor.tenant_id)
                .with_for_update(read=True)
            )
            await db.scalars(
                select(UserRole.id)
                .where(UserRole.user_id == actor.actor_id, UserRole.tenant_id == actor.tenant_id)
                .order_by(UserRole.id)
                .with_for_update(read=True)
            )
            await _assert_live_actor(db, actor)
            row = await _owned(db, actor, request.plan_id, lock=True)
            _base_response(row)  # parent/snapshot/expiry identity, even on replay
            snapshot = LessonCorrectionSnapshot.model_validate(row.snapshot)
            if request.revision != snapshot.revision or request.fingerprint != row.fingerprint:
                raise WorkbenchConflict("correction_confirmation_mismatch")
            existing = await _receipt(db, actor, request.plan_id)
            if existing is not None:
                if existing.revision != request.revision or existing.fingerprint != request.fingerprint:
                    raise WorkbenchConflict("correction_confirmation_mismatch")
                response = CorrectionApplicationResponse.model_validate(existing)
                await db.commit()  # release locks; no new business/audit/receipt write
                return response
            if row.status != "ready":
                raise WorkbenchConflict("correction_preview_not_ready")
            course = await _lock_course_tree(db, actor, snapshot.context.course_id)
            current = await resolve_lesson_correction(db, actor, snapshot.context.lesson_id)
            proposal = CorrectionProposal.model_validate(row.proposal)
            now = await _database_now(db)
            preview = preview_lesson_correction(
                snapshot,
                actor=actor,
                current=current.context,
                provider=CorrectionPatchAdapter(snapshot.context.content, proposal),
                now=now,
            )
            plan = prepare_lesson_correction(preview, request, actor=actor, current=current.context, now=now)
            if plan.destination != "current_draft":
                raise WorkbenchConflict("correction_record_invalid")
            operation = plan.patch.operations[0]
            await update_lesson(
                db, snapshot.context.lesson_id, actor.tenant_id, LessonUpdate(content=operation.after_value)
            )
            await supersede_course_approvals(
                db, course_id=snapshot.context.course_id, tenant_id=actor.tenant_id, actor_id=actor.actor_id
            )
            for field, value in {
                "review_status": "pending",
                "reviewed_by": None,
                "reviewed_at": None,
                "review_comment": None,
            }.items():
                setattr(course, field, value)
            await db.flush()
            applied = LessonCorrectionApplication(
                plan_id=request.plan_id,
                tenant_id=actor.tenant_id,
                actor_id=actor.actor_id,
                course_id=snapshot.context.course_id,
                lesson_id=snapshot.context.lesson_id,
                revision=request.revision,
                fingerprint=request.fingerprint,
                before_sha256=operation.before_hash,
                after_sha256=operation.after_hash,
            )
            db.add(applied)
            await db.flush()  # invoker guard, immutable source seal and DB timestamp
            await db.refresh(applied)
            await log_action(
                db,
                actor.tenant_id,
                "workbench.lesson_correction_applied",
                "lesson",
                snapshot.context.lesson_id,
                actor.actor_id,
                {
                    "plan_id": str(request.plan_id),
                    "fingerprint": request.fingerprint,
                    "before_sha256": applied.before_sha256,
                    "after_sha256": applied.after_sha256,
                },
            )
            response = CorrectionApplicationResponse.model_validate(applied)
            await db.commit()
            return response
    except BaseException:
        await db.rollback()
        raise
