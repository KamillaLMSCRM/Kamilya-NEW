"""Tenant-scoped source actuality and controlled retraining operations.

This module deliberately owns no schema or registration side effects.  Its
public functions are used by the router and the durable Celery adapter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment_access import AssignmentAccessCredential
from app.models.document import Document
from app.models.enrollment import Enrollment
from app.models.enrollment_access_policy import EnrollmentAccessPolicy
from app.models.users import User
from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceError, load_direct_source_corpus
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.courses.models import Course
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.positions.batch_service import recompute_tenant_members
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.source_actuality.models import DocumentChangeReview, DocumentSourcePolicy
from app.modules.source_actuality.schemas import SourceActualityItem, SourceActualityList

FACT_LIMIT = 200
_SPACE = re.compile(r"\s+")


class SourceActualityTransientError(RuntimeError):
    """Retryable converter, storage or database failure without raw details."""


def _norm(value: object) -> str:
    return _SPACE.sub(" ", str(value or "").casefold().replace("ё", "е").strip())


def _fact_index(facts: Iterable[SourceFact]) -> dict[tuple[str, str, str], SourceFact]:
    """Index canonical Evidence V2 facts by normalized semantic content."""
    result: dict[tuple[str, str, str], SourceFact] = {}
    for fact in sorted(facts, key=lambda item: (item.source_locator, item.fact_id)):
        key = (_norm(fact.subject), _norm(fact.attribute), _norm(fact.value))
        if all(key):
            result.setdefault(key, fact)
    return result


def bounded_fact_diff(
    previous: Iterable[SourceFact],
    current: Iterable[SourceFact],
    *,
    limit: int = FACT_LIMIT,
) -> dict[str, Any]:
    """Return a bounded deterministic delta over canonical Evidence V2 facts."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    old, new = _fact_index(previous), _fact_index(current)
    old_keys, new_keys = set(old), set(new)
    removed_keys = sorted(old_keys - new_keys)
    added_keys = sorted(new_keys - old_keys)
    common_keys = sorted(old_keys & new_keys)
    changed_keys = [
        key
        for key in common_keys
        if (
            old[key].confidence != new[key].confidence
            or old[key].uncertainty != new[key].uncertainty
        )
    ]
    unchanged_count = len(common_keys) - len(changed_keys)
    changes = len(removed_keys) + len(added_keys) + len(changed_keys)
    budget = min(limit, changes)
    displayed_keys: list[list[tuple[str, str, str]]] = [[], [], []]
    groups = (removed_keys, added_keys, changed_keys)
    offsets = [0, 0, 0]
    while budget > 0 and any(offset < len(group) for offset, group in zip(offsets, groups, strict=True)):
        for index, group in enumerate(groups):
            if budget <= 0:
                break
            if offsets[index] < len(group):
                displayed_keys[index].append(group[offsets[index]])
                offsets[index] += 1
                budget -= 1
    removed = [
        {
            "change_kind": "removed",
            "subject": old[key].subject,
            "attribute": old[key].attribute,
            "old_value": old[key].value,
            "old_locator": old[key].source_locator,
        }
        for key in displayed_keys[0]
    ]
    added = [
        {
            "change_kind": "added",
            "subject": new[key].subject,
            "attribute": new[key].attribute,
            "new_value": new[key].value,
            "new_locator": new[key].source_locator,
        }
        for key in displayed_keys[1]
    ]
    changed = [
        {
            "change_kind": "metadata_changed",
            "subject": new[key].subject,
            "attribute": new[key].attribute,
            "old_value": old[key].value,
            "new_value": new[key].value,
            "old_locator": old[key].source_locator,
            "new_locator": new[key].source_locator,
            "old_confidence": old[key].confidence,
            "new_confidence": new[key].confidence,
            "old_uncertainty": old[key].uncertainty,
            "new_uncertainty": new[key].uncertainty,
        }
        for key in displayed_keys[2]
    ]
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "added_count": len(added_keys),
        "removed_count": len(removed_keys),
        "changed_count": len(changed_keys),
        "unchanged_count": unchanged_count,
        "truncated": changes > limit,
    }


def derive_actuality_state(next_review_at: datetime | None, now: datetime | None = None) -> str:
    if next_review_at is None:
        return "unassigned"
    now = now or datetime.now(UTC)
    if next_review_at <= now:
        return "overdue"
    if next_review_at <= now + timedelta(days=30):
        return "due_soon"
    return "current"


def _contains_document_id(value: Any, document_id: UUID) -> bool:
    expected = str(document_id)
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list | tuple):
        return any(_contains_document_id(item, document_id) for item in value)
    if isinstance(value, dict):
        return any(_contains_document_id(item, document_id) for item in value.values())
    return False


def _without_document_reference(value: Any, document_id: UUID) -> Any:
    """Remove evidence entries owned by one source while preserving others."""
    if isinstance(value, str):
        return None if value == str(document_id) else value
    if isinstance(value, list):
        cleaned = [_without_document_reference(item, document_id) for item in value]
        return [item for item in cleaned if item is not None]
    if isinstance(value, dict):
        if _contains_document_id(value, document_id):
            return None
        return value
    return value


async def list_actuality(db: AsyncSession, *, tenant_id: UUID, now: datetime | None = None) -> SourceActualityList:
    documents = (
        (
            await db.execute(
                select(Document).where(Document.tenant_id == tenant_id, Document.lifecycle_status == "active")
            )
        )
        .scalars()
        .all()
    )
    latest: dict[UUID, Document] = {}
    for document in documents:
        if document.source_family_id not in latest or document.version > latest[document.source_family_id].version:
            latest[document.source_family_id] = document
    policies = {
        policy.source_family_id: policy
        for policy in (
            await db.execute(select(DocumentSourcePolicy).where(DocumentSourcePolicy.tenant_id == tenant_id))
        ).scalars()
    }
    owner_ids = {policy.owner_id for policy in policies.values() if policy.owner_id is not None}
    owners = {
        owner.id: owner
        for owner in (
            (
                await db.execute(
                    select(User).where(
                        User.tenant_id == tenant_id,
                        User.id.in_(owner_ids),
                    )
                )
            ).scalars()
            if owner_ids
            else ()
        )
    }
    reviews = (
        (
            await db.execute(
                select(DocumentChangeReview).where(
                    DocumentChangeReview.tenant_id == tenant_id,
                    DocumentChangeReview.status.in_(("pending", "processing", "ready")),
                )
            )
        )
        .scalars()
        .all()
    )
    pending_by_family: dict[UUID, DocumentChangeReview] = {}
    for review in reviews:
        candidate = pending_by_family.get(review.source_family_id)
        if candidate is None or review.created_at > candidate.created_at:
            pending_by_family[review.source_family_id] = review
    items: list[SourceActualityItem] = []
    for family_id, document in sorted(latest.items(), key=lambda pair: (pair[1].title.casefold(), str(pair[0]))):
        policy = policies.get(family_id)
        pending = pending_by_family.get(family_id)
        owner = owners.get(policy.owner_id) if policy and policy.owner_id else None
        owner_name = None
        if owner is not None:
            owner_name = " ".join(part for part in (owner.first_name, owner.last_name) if part).strip()
            owner_name = owner_name or owner.email
        items.append(
            SourceActualityItem(
                source_family_id=family_id,
                latest_document_id=document.id,
                latest_version=document.version,
                title=document.title,
                filename=document.filename,
                actuality_state=derive_actuality_state(policy.next_review_at if policy else None, now),
                owner_id=policy.owner_id if policy else None,
                owner_name=owner_name,
                reviewed_at=policy.reviewed_at if policy else None,
                next_review_at=policy.next_review_at if policy else None,
                pending_review_id=pending.id if pending else None,
                pending_review_status=pending.status if pending else None,
            )
        )
    return SourceActualityList(
        items=items,
        due_soon_count=sum(item.actuality_state == "due_soon" for item in items),
        overdue_count=sum(item.actuality_state == "overdue" for item in items),
        pending_decision_count=sum(item.pending_review_status == "ready" for item in items),
    )


async def upsert_policy(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    source_family_id: UUID,
    owner_id: UUID | None,
    reviewed_at: datetime | None,
    next_review_at: datetime | None,
) -> DocumentSourcePolicy:
    family_exists = await db.scalar(
        select(Document.id)
        .where(
            Document.tenant_id == tenant_id,
            Document.source_family_id == source_family_id,
            Document.lifecycle_status == "active",
        )
        .limit(1)
    )
    if family_exists is None:
        raise HTTPException(status_code=404, detail="Source family not found")
    if owner_id is not None:
        owner = await db.scalar(
            select(User).where(User.id == owner_id, User.tenant_id == tenant_id, User.is_active.is_(True))
        )
        if owner is None or owner.role != "methodologist" or owner.status != "active":
            raise HTTPException(status_code=422, detail="Policy owner must be an active tenant methodologist")
    policy = await db.scalar(
        select(DocumentSourcePolicy).where(
            DocumentSourcePolicy.tenant_id == tenant_id, DocumentSourcePolicy.source_family_id == source_family_id
        )
    )
    if policy is None:
        policy = DocumentSourcePolicy(tenant_id=tenant_id, source_family_id=source_family_id, created_by=actor_id)
        db.add(policy)
    policy.owner_id, policy.reviewed_at, policy.next_review_at, policy.updated_by = (
        owner_id,
        reviewed_at,
        next_review_at,
        actor_id,
    )
    await db.flush()
    return policy


async def request_analysis(
    db: AsyncSession, *, tenant_id: UUID, new_document_id: UUID
) -> tuple[DocumentChangeReview, bool]:
    new = await db.scalar(select(Document).where(Document.id == new_document_id, Document.tenant_id == tenant_id))
    if new is None:
        raise HTTPException(status_code=404, detail="Document not found")
    latest_active_version = await db.scalar(
        select(func.max(Document.version)).where(
            Document.tenant_id == tenant_id,
            Document.source_family_id == new.source_family_id,
            Document.lifecycle_status == "active",
        )
    )
    if latest_active_version != new.version:
        raise HTTPException(status_code=409, detail="Only the latest active source revision can be analyzed")
    previous = await db.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_family_id == new.source_family_id,
            Document.version == new.version - 1,
        )
    )
    if previous is None or new.version <= 1:
        raise HTTPException(
            status_code=409, detail="Document must have an immediate predecessor in the same source family"
        )
    for document in (previous, new):
        if (
            document.lifecycle_status != "active"
            or document.index_status != "ready"
            or not re.fullmatch(r"[0-9a-f]{64}", str(document.content_sha256 or ""))
        ):
            raise HTTPException(
                status_code=409, detail="Both consecutive documents must be active, indexed, and content-hashed"
            )
    review = await db.scalar(
        select(DocumentChangeReview).where(
            DocumentChangeReview.tenant_id == tenant_id,
            DocumentChangeReview.previous_document_id == previous.id,
            DocumentChangeReview.new_document_id == new.id,
        )
    )
    if review is not None:
        if review.status == "failed":
            review.status = "pending"
            review.analysis_error_code = None
            review.analysis_error_message = None
            await db.flush()
        return review, review.status == "pending"
    review = DocumentChangeReview(
        tenant_id=tenant_id,
        source_family_id=new.source_family_id,
        previous_document_id=previous.id,
        new_document_id=new.id,
        status="pending",
    )
    db.add(review)
    await db.flush()
    return review, True


async def _impact_snapshot(db: AsyncSession, *, tenant_id: UUID, predecessor_id: UUID) -> dict[str, Any]:
    courses = (await db.execute(select(Course).where(Course.tenant_id == tenant_id))).scalars().all()
    impacted_courses = [
        course
        for course in courses
        if course.source_instruction_id == predecessor_id
        or _contains_document_id(course.source_document_ids, predecessor_id)
        or _contains_document_id(course.source_analysis, predecessor_id)
    ]
    result: list[dict[str, Any]] = []
    for course in impacted_courses:
        lessons = (
            (
                await db.execute(
                    select(Lesson)
                    .join(Module)
                    .where(Module.course_id == course.id, Module.tenant_id == tenant_id, Lesson.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        impacted_lessons = [
            lesson
            for lesson in lessons
            if _contains_document_id(lesson.source_document_ids, predecessor_id)
            or _contains_document_id(lesson.source_references, predecessor_id)
        ]
        if not impacted_lessons:
            # Older native courses may persist provenance only at course level.
            # In that case every lesson is reviewable; reporting zero would be
            # a false claim of precision.
            impacted_lessons = lessons
        lesson_ids = [lesson.id for lesson in impacted_lessons]
        questions = 0
        if lesson_ids:
            questions = int(
                (
                    await db.scalar(
                        select(func.count(Question.id))
                        .join(Quiz)
                        .where(Quiz.tenant_id == tenant_id, Quiz.lesson_id.in_(lesson_ids))
                    )
                )
                or 0
            )
        active = int(
            (
                await db.scalar(
                    select(func.count(Enrollment.id)).where(
                        Enrollment.tenant_id == tenant_id,
                        Enrollment.course_id == course.id,
                        Enrollment.status.in_(("enrolled", "in_progress")),
                    )
                )
            )
            or 0
        )
        completed = int(
            (
                await db.scalar(
                    select(func.count(Enrollment.id)).where(
                        Enrollment.tenant_id == tenant_id,
                        Enrollment.course_id == course.id,
                        Enrollment.status == "completed",
                    )
                )
            )
            or 0
        )
        result.append(
            {
                "course_id": str(course.id),
                "title": course.title,
                "status": course.status,
                "impacted_lesson_ids": [str(value) for value in lesson_ids],
                "assessment_questions_requiring_review": questions,
                "active_enrollments": active,
                "completed_enrollments": completed,
                "assessment_scope": "impacted_lessons",
            }
        )
    return {"impacted_courses": result}


def _single_document_corpus(corpus: DirectSourceCorpus, document_id: UUID) -> DirectSourceCorpus:
    document = next(
        (item for item in corpus.documents if item.doc_id == str(document_id)),
        None,
    )
    if document is None:
        raise DirectSourceError("documents_not_found", (str(document_id),))
    return DirectSourceCorpus(
        tenant_id=corpus.tenant_id,
        documents=(document,),
        total_chars=sum(len(chunk.text) for chunk in document.chunks),
        total_chunks=len(document.chunks),
    )


async def process_review(db: AsyncSession, *, tenant_id: UUID, review_id: UUID) -> DocumentChangeReview:
    review = await db.scalar(
        select(DocumentChangeReview)
        .where(DocumentChangeReview.id == review_id, DocumentChangeReview.tenant_id == tenant_id)
        .with_for_update()
    )
    if review is None:
        raise ValueError("review_not_found")
    if review.status in {"ready", "resolved"}:
        return review
    review.status, review.analysis_error_code, review.analysis_error_message = "processing", None, None
    await db.flush()
    try:
        documents = {
            document.id: document
            for document in (
                await db.execute(
                    select(Document).where(
                        Document.tenant_id == tenant_id,
                        Document.id.in_((review.previous_document_id, review.new_document_id)),
                    )
                )
            ).scalars()
        }
        previous = documents.get(review.previous_document_id)
        new = documents.get(review.new_document_id)
        if previous is None or new is None:
            raise DirectSourceError("documents_not_found")
        if previous.source_family_id != new.source_family_id or new.version != previous.version + 1:
            raise DirectSourceError("source_revision_invalid")
        latest_active_version = await db.scalar(
            select(func.max(Document.version)).where(
                Document.tenant_id == tenant_id,
                Document.source_family_id == new.source_family_id,
                Document.lifecycle_status == "active",
            )
        )
        if latest_active_version != new.version:
            raise DirectSourceError("source_revision_superseded")
        if any(
            document.lifecycle_status != "active" or document.index_status != "ready" or not document.content_sha256
            for document in (previous, new)
        ):
            raise DirectSourceError("source_not_ready")
        corpus = await load_direct_source_corpus(
            [str(previous.id), str(new.id)],
            tenant_id=tenant_id,
        )
        previous_source = build_evidence_source(_single_document_corpus(corpus, previous.id))
        new_source = build_evidence_source(_single_document_corpus(corpus, new.id))
        delta = bounded_fact_diff(previous_source.all_facts, new_source.all_facts)
        impact = await _impact_snapshot(db, tenant_id=tenant_id, predecessor_id=previous.id)
        courses = impact["impacted_courses"]
        (
            review.added_fact_count,
            review.removed_fact_count,
            review.changed_fact_count,
            review.unchanged_fact_count,
        ) = (
            delta["added_count"],
            delta["removed_count"],
            delta["changed_count"],
            delta["unchanged_count"],
        )
        review.impacted_course_count = len(courses)
        review.impacted_lesson_count = sum(len(course["impacted_lesson_ids"]) for course in courses)
        review.assessment_questions_requiring_review = sum(
            course["assessment_questions_requiring_review"] for course in courses
        )
        review.impact_snapshot = {
            **impact,
            "added_facts": delta["added"],
            "removed_facts": delta["removed"],
            "changed_facts": delta["changed"],
            "analysis_truncated": delta["truncated"],
            "evidence_format": "v2",
        }
        review.status = "ready"
    except DirectSourceError as exc:
        review.status, review.analysis_error_code, review.analysis_error_message = (
            "failed",
            exc.code[:80],
            "Source analysis could not be completed.",
        )
    except Exception as exc:
        raise SourceActualityTransientError("source_analysis_transient") from exc
    await db.flush()
    return review


async def _clone_course(
    db: AsyncSession,
    *,
    course: Course,
    tenant_id: UUID,
    actor_id: UUID,
    predecessor_id: UUID,
    replacement_id: UUID,
    impacted_lesson_ids: set[UUID],
) -> UUID:
    clone = Course(
        tenant_id=tenant_id,
        title=course.title,
        description=course.description,
        status="draft",
        delivery_type="native",
        thumbnail_url=course.thumbnail_url,
        created_by=actor_id,
        ai_generated=course.ai_generated,
        source_instruction_id=replacement_id
        if course.source_instruction_id == predecessor_id
        else course.source_instruction_id,
        source_document_ids=[
            str(replacement_id) if str(value) == str(predecessor_id) else str(value)
            for value in (course.source_document_ids or [])
        ],
        source_strategy=course.source_strategy,
        source_combination_goal=course.source_combination_goal,
        source_analysis={
            "source_actuality": {
                "replacement_document_id": str(replacement_id),
                "review_status": "needs_review",
            }
        },
        review_status="pending",
    )
    db.add(clone)
    await db.flush()
    modules = (
        (
            await db.execute(
                select(Module)
                .where(Module.course_id == course.id, Module.tenant_id == tenant_id)
                .order_by(Module.order_index, Module.id)
            )
        )
        .scalars()
        .all()
    )
    for module in modules:
        module_clone = Module(
            tenant_id=tenant_id,
            course_id=clone.id,
            title=module.title,
            description=module.description,
            order_index=module.order_index,
            ai_generated=module.ai_generated,
        )
        db.add(module_clone)
        await db.flush()
        lessons = (
            (
                await db.execute(
                    select(Lesson)
                    .where(Lesson.module_id == module.id, Lesson.tenant_id == tenant_id)
                    .order_by(Lesson.order_index, Lesson.id)
                )
            )
            .scalars()
            .all()
        )
        for lesson in lessons:
            impacted = lesson.id in impacted_lesson_ids or _contains_document_id(
                lesson.source_document_ids,
                predecessor_id,
            ) or _contains_document_id(lesson.source_references, predecessor_id)
            lesson_clone = Lesson(
                tenant_id=tenant_id,
                module_id=module_clone.id,
                title=lesson.title,
                content_type=lesson.content_type,
                content=lesson.content,
                duration_seconds=lesson.duration_seconds,
                order_index=lesson.order_index,
                ai_generated=lesson.ai_generated,
                source_document_ids=(
                    [
                        str(replacement_id) if str(value) == str(predecessor_id) else str(value)
                        for value in (lesson.source_document_ids or [])
                    ]
                    if impacted
                    else lesson.source_document_ids
                ),
                source_references=(
                    _without_document_reference(lesson.source_references, predecessor_id)
                    if impacted
                    else lesson.source_references
                ),
                source_validation_status="needs_review" if impacted else lesson.source_validation_status,
            )
            db.add(lesson_clone)
            await db.flush()
            blocks = (
                (
                    await db.execute(
                        select(ContentBlock)
                        .where(ContentBlock.lesson_id == lesson.id)
                        .order_by(ContentBlock.order_index, ContentBlock.id)
                    )
                )
                .scalars()
                .all()
            )
            db.add_all(
                [
                    ContentBlock(
                        lesson_id=lesson_clone.id,
                        block_type=block.block_type,
                        content=block.content,
                        order_index=block.order_index,
                        metadata_=block.metadata_,
                    )
                    for block in blocks
                ]
            )
            quizzes = (
                (await db.execute(select(Quiz).where(Quiz.lesson_id == lesson.id, Quiz.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
            for quiz in quizzes:
                quiz_clone = Quiz(
                    lesson_id=lesson_clone.id,
                    tenant_id=tenant_id,
                    title=quiz.title,
                    pass_score=quiz.pass_score,
                    time_limit=quiz.time_limit,
                    attempt_limit=quiz.attempt_limit,
                    deferral_days=quiz.deferral_days,
                    review_status="needs_review" if impacted else quiz.review_status,
                )
                db.add(quiz_clone)
                await db.flush()
                questions = (
                    (
                        await db.execute(
                            select(Question)
                            .where(Question.quiz_id == quiz.id)
                            .order_by(Question.order_index, Question.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                for question in questions:
                    question_clone = Question(
                        quiz_id=quiz_clone.id,
                        text=question.text,
                        type=question.type,
                        points=question.points,
                        explanation=question.explanation,
                        order_index=question.order_index,
                        pool_group=question.pool_group,
                    )
                    db.add(question_clone)
                    await db.flush()
                    choices = (
                        (
                            await db.execute(
                                select(QuizChoice)
                                .where(QuizChoice.question_id == question.id)
                                .order_by(QuizChoice.order_index, QuizChoice.id)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    db.add_all(
                        [
                            QuizChoice(
                                question_id=question_clone.id,
                                text=choice.text,
                                is_correct=choice.is_correct,
                                order_index=choice.order_index,
                            )
                            for choice in choices
                        ]
                    )
    return clone.id


async def decide_review(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    review_id: UUID,
    decision: str,
    reason: str,
    retraining_due_at: datetime | None,
) -> DocumentChangeReview:
    review = await db.scalar(
        select(DocumentChangeReview)
        .where(DocumentChangeReview.id == review_id, DocumentChangeReview.tenant_id == tenant_id)
        .with_for_update()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status == "resolved":
        prior_due_at = (review.decision_snapshot or {}).get("retraining_due_at")
        requested_due_at = retraining_due_at.isoformat() if retraining_due_at else None
        if review.decision == decision and review.decision_reason == reason and prior_due_at == requested_due_at:
            return review
        raise HTTPException(status_code=409, detail="Review was already resolved with a different decision")
    if review.status != "ready":
        raise HTTPException(status_code=409, detail="Only a ready review can be decided")
    snapshot: dict[str, Any] = {
        "draft_course_ids": [],
        "archived_course_ids": [],
        "retraining_due_at": retraining_due_at.isoformat() if retraining_due_at else None,
        "automatic_reassignment": False,
    }
    impact_courses = (review.impact_snapshot or {}).get("impacted_courses", [])
    if decision in {"update_future", "update_and_retrain", "suspend_old_assignments"}:
        for item in impact_courses:
            course = await db.scalar(
                select(Course)
                .where(Course.id == UUID(item["course_id"]), Course.tenant_id == tenant_id)
                .with_for_update()
            )
            if course is None or course.delivery_type != "native":
                continue
            if decision in {"update_future", "update_and_retrain"}:
                try:
                    impacted_lesson_ids = {UUID(value) for value in item.get("impacted_lesson_ids", [])}
                except (TypeError, ValueError, AttributeError):
                    raise HTTPException(status_code=409, detail="Review impact snapshot is invalid") from None
                snapshot["draft_course_ids"].append(
                    str(
                        await _clone_course(
                            db,
                            course=course,
                            tenant_id=tenant_id,
                            actor_id=actor_id,
                            predecessor_id=review.previous_document_id,
                            replacement_id=review.new_document_id,
                            impacted_lesson_ids=impacted_lesson_ids,
                        )
                    )
                )
            if decision == "suspend_old_assignments":
                course.status = "archived"
                snapshot["archived_course_ids"].append(str(course.id))
        if decision == "suspend_old_assignments" and snapshot["archived_course_ids"]:
            course_ids = [UUID(value) for value in snapshot["archived_course_ids"]]
            open_enrollment_ids = list(
                (
                    await db.scalars(
                        select(Enrollment.id).where(
                            Enrollment.tenant_id == tenant_id,
                            Enrollment.course_id.in_(course_ids),
                            Enrollment.status.in_(("enrolled", "in_progress")),
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            if open_enrollment_ids:
                await db.execute(
                    update(AssignmentAccessCredential)
                    .where(
                        AssignmentAccessCredential.tenant_id == tenant_id,
                        AssignmentAccessCredential.enrollment_id.in_(open_enrollment_ids),
                        AssignmentAccessCredential.revoked_at.is_(None),
                    )
                    .values(revoked_at=now, revoked_reason="Source revision suspended")
                )
                await db.execute(
                    update(EnrollmentAccessPolicy)
                    .where(
                        EnrollmentAccessPolicy.tenant_id == tenant_id,
                        EnrollmentAccessPolicy.enrollment_id.in_(open_enrollment_ids),
                    )
                    .values(revoked_at=now, revoked_reason="Source revision suspended")
                )
                await db.execute(
                    update(Enrollment)
                    .where(
                        Enrollment.tenant_id == tenant_id,
                        Enrollment.id.in_(open_enrollment_ids),
                    )
                    .values(status="cancelled")
                )
            snapshot["suspended_open_enrollment_count"] = len(open_enrollment_ids)
            snapshot["assignment_recompute"] = (await recompute_tenant_members(db, tenant_id)).to_dict()
    (
        review.status,
        review.decision,
        review.decision_reason,
        review.decision_snapshot,
        review.decided_by,
        review.decided_at,
    ) = "resolved", decision, reason, snapshot, actor_id, datetime.now(UTC)
    await db.flush()
    return review
