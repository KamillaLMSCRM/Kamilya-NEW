"""Tenant-scoped source actuality and controlled retraining operations.

This module deliberately owns no schema or registration side effects.  Its
public functions are used by the router and the durable Celery adapter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
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
from app.modules.course_approval.models import CourseApprovalPolicy
from app.modules.courses.localizations import POLICY_KEY, read_policy
from app.modules.courses.models import Course
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.positions.batch_service import recompute_tenant_members
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from app.modules.source_actuality.models import DocumentChangeReview, DocumentSourcePolicy
from app.modules.source_actuality.schemas import SourceActualityItem, SourceActualityList
from app.modules.source_actuality.spans import WorkingTextChanges
from app.modules.source_editorial_review.service import SOURCE_PINS, pin_reviews, resolve_pins, review_enabled

FACT_LIMIT = 200
_SPACE = re.compile(r"\s+")


class SourceActualityTransientError(RuntimeError):
    """Retryable converter, storage or database failure without raw details."""


def _norm(value: object) -> str:
    return _SPACE.sub(" ", str(value or "").casefold().replace("ё", "е").strip())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


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
        family_id = cast(UUID, document.source_family_id)
        if family_id not in latest or int(document.version) > int(latest[family_id].version):
            latest[family_id] = document
    policies: dict[UUID, DocumentSourcePolicy] = {
        policy.source_family_id: policy
        for policy in (
            await db.execute(select(DocumentSourcePolicy).where(DocumentSourcePolicy.tenant_id == tenant_id))
        ).scalars()
    }
    owner_ids = {policy.owner_id for policy in policies.values() if policy.owner_id is not None}
    owners: dict[UUID, User] = {
        cast(UUID, owner.id): owner
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
                    DocumentChangeReview.new_document_id.in_([item.id for item in latest.values()]),
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
            first_name = cast(str | None, owner.first_name)
            last_name = cast(str | None, owner.last_name)
            owner_email = cast(str, owner.email)
            owner_name = " ".join(part for part in (first_name, last_name) if part).strip()
            owner_name = owner_name or owner_email
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
    actor_id: UUID | None,
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
        ).with_for_update()
    )
    if review is not None:
        approvals_changed = False
        if review.status == "ready" and review_enabled():
            pins = await _comparison_pins(db, tenant_id, cast(UUID, previous.id), cast(UUID, new.id))
            approvals_changed = bool(pins) and pins != (review.impact_snapshot or {}).get("editorial_pins")
        if review.status == "failed" or approvals_changed:
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


async def _comparison_pins(
    db: AsyncSession, tenant_id: UUID, previous_id: UUID, new_id: UUID,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for document_id in (previous_id, new_id):
        try:
            result.extend(await pin_reviews(db, tenant_id, [document_id]))
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    return result


async def _impact_snapshot(
    db: AsyncSession, *, tenant_id: UUID, predecessor_id: UUID, working_changes: WorkingTextChanges,
    compared_pins: list[dict[str, Any]],
) -> dict[str, Any]:
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
            impacted_lessons = list(lessons)
        rebased: dict[str, dict[str, Any]] = {}
        unchanged: set[UUID] = set()
        covered_references: list[dict[str, Any]] = []
        course_pins = cast(dict[str, Any], course.source_analysis or {}).get(SOURCE_PINS) or []
        if compared_pins and len(compared_pins) == 2:
            comparable = compared_pins[0] in course_pins
        else:
            comparable = not course_pins
        for lesson in impacted_lessons if comparable else ():
            refs = lesson.source_references
            if not isinstance(refs, list) or not all(isinstance(ref, dict) for ref in refs):
                continue
            predecessor_refs = [ref for ref in refs if ref.get("doc_id") == str(predecessor_id)]
            if not predecessor_refs:
                continue
            pairs = [working_changes.rebind(ref) for ref in predecessor_refs]
            replacements = [pair for pair in pairs if pair is not None]
            if len(replacements) != len(predecessor_refs):
                continue
            changed = any(changed for _, changed in replacements)
            covered_references.extend(predecessor_refs)
            rebased[str(lesson.id)] = {
                "previous": refs,
                "changed": changed,
                "replacement": [
                    *(ref for ref in refs if ref.get("doc_id") != str(predecessor_id)),
                    *(ref for ref, _ in replacements),
                ],
            }
            if not changed:
                unchanged.add(lesson.id)
        unmatched_source_changes = not working_changes.edits_are_covered(covered_references)
        if not unmatched_source_changes:
            impacted_lessons = [lesson for lesson in impacted_lessons if lesson.id not in unchanged]
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
                "impacted_lessons": [
                    {"lesson_id": str(lesson.id), "title": lesson.title}
                    for lesson in impacted_lessons
                ],
                "rebased_lesson_references": rebased,
                "unmatched_source_changes": unmatched_source_changes,
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
        documents: dict[UUID, Document] = {
            cast(UUID, document.id): document
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
        previous_id = cast(UUID, previous.id)
        new_id = cast(UUID, new.id)
        ids = [str(previous_id), str(new_id)]
        editorial_pins = (await _comparison_pins(db, tenant_id, previous_id, new_id)) if review_enabled() else []
        if len(editorial_pins) == 2:
            approved = await resolve_pins(db, tenant_id, ids, editorial_pins)
            corpus = await load_direct_source_corpus(ids, tenant_id=tenant_id, approved_documents=approved)
        else:
            corpus = await load_direct_source_corpus(ids, tenant_id=tenant_id)
        previous_corpus = _single_document_corpus(corpus, previous_id)
        new_corpus = _single_document_corpus(corpus, new_id)
        previous_source = build_evidence_source(previous_corpus)
        new_source = build_evidence_source(new_corpus)
        delta = bounded_fact_diff(previous_source.all_facts, new_source.all_facts)
        working_changes = WorkingTextChanges(previous_corpus.documents[0], new_corpus.documents[0])
        impact = await _impact_snapshot(
            db, tenant_id=tenant_id, predecessor_id=previous_id,
            working_changes=working_changes,
            compared_pins=editorial_pins,
        )
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
            "unmapped_working_text_changes": working_changes.has_unmapped_changes or any(
                item["unmatched_source_changes"] for item in courses
            ),
            "evidence_format": "v2",
            "editorial_pins": editorial_pins,
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


@dataclass(frozen=True)
class DerivedDraft:
    course_id: UUID
    lessons: list[dict[str, str]]


async def _clone_course(
    db: AsyncSession,
    *,
    course: Course,
    tenant_id: UUID,
    actor_id: UUID | None,
    predecessor_id: UUID,
    replacement_id: UUID,
    impacted_lesson_ids: set[UUID],
    rebased_references: dict[str, dict[str, Any]] | None = None,
    editorial_pins: list[dict[str, Any]] | None = None,
) -> DerivedDraft:
    rebased_references = rebased_references or {}
    prior_analysis = getattr(course, "source_analysis", None) or {}
    policy = read_policy(course) if POLICY_KEY in prior_analysis else None
    replacement = str(replacement_id)
    predecessor = str(predecessor_id)
    pins = prior_analysis.get(SOURCE_PINS)
    if pins:
        analyzed = {pin["document_id"]: pin for pin in (editorial_pins or [])}
        previous_pin = next((pin for pin in pins if pin["document_id"] == predecessor), None)
        replacement_pin = analyzed.get(replacement)
        if not replacement_pin or previous_pin is None:
            raise HTTPException(409, detail={"code": "source_actuality_approved_comparison_required"})
        if (await pin_reviews(db, tenant_id, [replacement_id]))[0] != replacement_pin:
            raise HTTPException(409, detail={"code": "source_actuality_approved_comparison_required"})
        if previous_pin != analyzed.get(predecessor):
            rebased_references = {}
        pins = [replacement_pin if pin["document_id"] == predecessor else pin for pin in pins]
    elif len(editorial_pins or []) == 2:
        # The hashes from approved working text must never be resolved against raw text.
        rebased_references = {}
    analysis: dict[str, Any] = {}
    if pins:
        analysis[SOURCE_PINS] = pins
    if policy:
        analysis[POLICY_KEY] = policy.model_dump()
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
        source_instruction_version_at=(
            None if course.source_instruction_id == predecessor_id
            else getattr(course, "source_instruction_version_at", None)
        ),
        source_document_ids=[
            str(replacement_id) if str(value) == str(predecessor_id) else str(value)
            for value in _string_list(course.source_document_ids)
        ],
        source_strategy=course.source_strategy,
        source_combination_goal=course.source_combination_goal,
        source_analysis=analysis,
        review_status="pending",
    )
    db.add(clone)
    await db.flush()
    approval = await db.scalar(select(CourseApprovalPolicy).where(
        CourseApprovalPolicy.tenant_id == tenant_id, CourseApprovalPolicy.course_id == course.id,
    ))
    if approval is not None:
        db.add(CourseApprovalPolicy(
            tenant_id=tenant_id, course_id=clone.id, requires_approval=approval.requires_approval,
            review_enabled=approval.review_enabled, updated_by=actor_id,
        ))
    node_ids = {str(clone.id): str(course.id)}
    affected: list[dict[str, str]] = []
    grounded: list[str] = []
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
        node_ids[str(module_clone.id)] = str(module.id)
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
            rebased = rebased_references.get(str(lesson.id), {})
            references = rebased.get("replacement") if rebased.get("previous") == lesson.source_references else None
            linked = _contains_document_id(lesson.source_document_ids, predecessor_id) or _contains_document_id(
                lesson.source_references, predecessor_id)
            impacted = lesson.id in impacted_lesson_ids or (linked and references is None)
            source_ids = [replacement if value == predecessor else value
                          for value in _string_list(lesson.source_document_ids)]
            if impacted and not source_ids and replacement in (clone.source_document_ids or []):
                source_ids = [replacement]
            lesson_clone = Lesson(
                tenant_id=tenant_id,
                module_id=module_clone.id,
                title=lesson.title,
                content_type=lesson.content_type,
                content=lesson.content,
                duration_seconds=lesson.duration_seconds,
                order_index=lesson.order_index,
                ai_generated=lesson.ai_generated,
                source_document_ids=source_ids,
                source_references=(
                    references if references is not None
                    else _without_document_reference(lesson.source_references, predecessor_id)
                    if impacted or linked
                    else lesson.source_references
                ),
                source_validation_status="needs_review" if impacted else lesson.source_validation_status,
            )
            db.add(lesson_clone)
            await db.flush()
            node_ids[str(lesson_clone.id)] = str(lesson.id)
            if impacted:
                affected.append({"lesson_id": str(lesson_clone.id), "title": str(lesson.title)})
                if rebased.get("changed") and references and all(
                    ref.get("kind") == "working_text_span_v1" for ref in references
                ):
                    grounded.append(str(lesson_clone.id))
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
            block_clones = [
                ContentBlock(
                    lesson_id=lesson_clone.id,
                    block_type=block.block_type,
                    content=block.content,
                    order_index=block.order_index,
                    metadata_=block.metadata_,
                )
                for block in blocks
            ]
            db.add_all(block_clones)
            if block_clones and policy:
                await db.flush()
                node_ids.update((str(new.id), str(old.id)) for new, old in zip(block_clones, blocks, strict=True))
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
                node_ids[str(quiz_clone.id)] = str(quiz.id)
                questions = (
                    (
                        await db.execute(
                            select(Question)
                            .join(Quiz)
                            .where(Question.quiz_id == quiz.id, Quiz.tenant_id == tenant_id)
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
                        source_quote=question.source_quote if not impacted else None,
                        order_index=question.order_index,
                        pool_group=question.pool_group,
                    )
                    db.add(question_clone)
                    await db.flush()
                    node_ids[str(question_clone.id)] = str(question.id)
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
                    choice_clones = [
                        QuizChoice(
                            question_id=question_clone.id,
                            text=choice.text,
                            is_correct=choice.is_correct,
                            order_index=choice.order_index,
                        )
                        for choice in choices
                    ]
                    db.add_all(choice_clones)
                    if choice_clones and policy:
                        await db.flush()
                        node_ids.update((str(new.id), str(old.id)) for new, old in zip(choice_clones, choices, strict=True))
    previous_release = getattr(course, "current_release_id", None)
    cast(Any, clone).source_analysis = {
        **analysis,
        "source_actuality": {
            "replacement_document_id": replacement,
            "previous_course_id": str(course.id),
            "previous_release_id": str(previous_release) if previous_release else None,
            "language_field_owners": node_ids if policy and previous_release else {},
            "affected_lesson_ids": [item["lesson_id"] for item in affected],
            "grounded_lesson_ids": grounded,
            "review_status": "needs_review",
        },
    }
    return DerivedDraft(cast(UUID, clone.id), affected)


async def decide_review(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_id: UUID | None,
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
        "draft_courses": [],
        "archived_course_ids": [],
        "retraining_due_at": retraining_due_at.isoformat() if retraining_due_at else None,
        "automatic_reassignment": False,
    }
    impact_courses = (review.impact_snapshot or {}).get("impacted_courses", [])
    if decision in {"update_future", "update_and_retrain", "suspend_old_assignments"}:
        latest_id = await db.scalar(select(Document.id).where(
            Document.tenant_id == tenant_id, Document.source_family_id == review.source_family_id,
            Document.lifecycle_status == "active",
        ).order_by(Document.version.desc()).limit(1))
        if latest_id != review.new_document_id:
            raise HTTPException(409, detail={"code": "source_revision_superseded"})
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
                draft = await _clone_course(
                    db,
                    course=course,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    predecessor_id=review.previous_document_id,
                    replacement_id=review.new_document_id,
                    impacted_lesson_ids=impacted_lesson_ids,
                    rebased_references=item.get("rebased_lesson_references"),
                    editorial_pins=(review.impact_snapshot or {}).get("editorial_pins"),
                )
                snapshot["draft_course_ids"].append(str(draft.course_id))
                snapshot["draft_courses"].append({
                    "course_id": str(draft.course_id), "title": item.get("title", ""),
                    "lessons": draft.lessons,
                })
            if decision == "suspend_old_assignments":
                course.status = cast(Any, "archived")
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
