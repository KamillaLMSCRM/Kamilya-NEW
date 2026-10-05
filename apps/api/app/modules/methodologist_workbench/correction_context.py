"""Resolve current draft and reconstruct only its exact source-owned facts."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.course_approval.models import CourseApprovalPolicy, CourseApprovalRevision
from app.modules.courses.models import Course
from app.modules.courses.release_service import build_course_release_snapshot, canonical_json_sha256
from app.modules.lessons.models import Lesson, Module

from .assignment_service import WorkbenchNotFound, _assert_actor
from .correction_contract import CorrectionError, CorrectionEvidence, CorrectionSource, LessonCorrectionContext
from .correction_proposal import MAX_SOURCE_CHARS, CorrectionExcerpt
from .correction_schemas import CorrectionCitation
from .document_service import resolve_document_sources
from .plan_contract import ActorContext


@dataclass(frozen=True)
class ResolvedLessonCorrection:
    context: LessonCorrectionContext
    title: str
    excerpts: tuple[CorrectionExcerpt, ...]


async def resolve_lesson_correction(
    db: AsyncSession,
    actor: ActorContext,
    lesson_id: UUID,
) -> ResolvedLessonCorrection:
    """Read only: no embedding, index, model, course or lesson write."""

    _assert_actor(actor)
    result = await db.execute(
        select(Lesson, Module, Course)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(
            Lesson.id == lesson_id,
            Lesson.tenant_id == actor.tenant_id,
            Module.tenant_id == actor.tenant_id,
            Course.tenant_id == actor.tenant_id,
        )
        .execution_options(populate_existing=True)
    )
    row = result.one_or_none()
    if row is None:
        raise WorkbenchNotFound("lesson_not_found")
    lesson, module, course = row
    if (
        any(item.tenant_id != actor.tenant_id for item in row)
        or lesson.module_id != module.id
        or module.course_id != course.id
    ):
        raise WorkbenchNotFound("lesson_not_found")
    if course.status == "published" or lesson.published_at is not None:
        raise CorrectionError("new_draft_required")
    if course.status != "draft" or course.delivery_type != "native" or lesson.content_type != "text":
        raise CorrectionError("lesson_correction_unsupported")
    if not isinstance(lesson.content, str) or not lesson.content.strip() or len(lesson.content) > 64_000:
        raise CorrectionError("lesson_correction_unsupported")
    references = lesson.source_references
    try:
        if not isinstance(lesson.source_document_ids, list) or not isinstance(course.source_document_ids, list):
            raise ValueError
        ids = [UUID(str(item)) for item in lesson.source_document_ids]
        course_ids = {UUID(str(item)) for item in course.source_document_ids}
        if not ids or len(ids) > 5 or len(set(ids)) != len(ids) or not set(ids) <= course_ids:
            raise ValueError
        if not isinstance(references, list) or not 1 <= len(references) <= 64:
            raise ValueError
        fact_keys = [item["fact_id"] for item in references]
        if any(not isinstance(key, str) or not key for key in fact_keys) or len(set(fact_keys)) != len(fact_keys):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise CorrectionError("lesson_source_provenance_unavailable") from None

    documents = list(
        (
            await db.scalars(
                select(Document)
                .where(Document.id.in_(ids), Document.tenant_id == actor.tenant_id)
                .order_by(Document.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if {document.id for document in documents} != set(ids):
        raise WorkbenchNotFound("documents_not_found")
    # Refresh identity-map rows before the shared metadata resolver reads them.
    # Otherwise a post-provider recheck in this same session could retain the
    # earlier version/index revision even though the SELECT reached the DB.
    sources = await resolve_document_sources(db, actor, ids)
    try:
        async with asyncio.timeout(90):
            corpus = await build_direct_source_corpus(documents, tenant_id=actor.tenant_id)
        facts = build_evidence_source(corpus).all_facts
    except Exception:
        raise CorrectionError("lesson_source_unavailable") from None
    by_id = {fact.fact_id: fact for fact in facts}
    if len(by_id) != len(facts):
        raise CorrectionError("lesson_source_provenance_unavailable")
    excerpts: list[CorrectionExcerpt] = []
    for reference in references:
        fact = by_id.get(reference["fact_id"])
        try:
            doc_id = UUID(str(reference["doc_id"]))
        except (ValueError, TypeError, KeyError):
            raise CorrectionError("lesson_source_provenance_unavailable") from None
        if (
            fact is None
            or doc_id not in ids
            or reference.get("source_locator") != fact.source_locator
            or not fact.source_locator.startswith(f"doc_id={doc_id};")
        ):
            raise CorrectionError("lesson_source_provenance_unavailable")
        source = next(source for source in sources if source.document_id == doc_id)
        if f";source_revision=document:{source.content_sha256};" not in fact.source_locator:
            raise CorrectionError("lesson_source_provenance_unavailable")
        evidence_text = f"{fact.subject}\n{fact.attribute}: {fact.value}"
        citation = CorrectionCitation(
            document_id=doc_id,
            locator=f"fact:{fact.fact_id}",
            evidence_hash=hashlib.sha256(evidence_text.encode()).hexdigest(),
        )
        excerpts.append(CorrectionExcerpt(citation, evidence_text))
    if sum(len(item.text) for item in excerpts) > MAX_SOURCE_CHARS:
        raise CorrectionError("correction_context_too_large")
    if {item.citation.document_id for item in excerpts} != set(ids):
        raise CorrectionError("lesson_source_provenance_unavailable")

    release = await build_course_release_snapshot(db, course, version=1, populate_existing=True)
    policy = await db.scalar(
        select(CourseApprovalPolicy)
        .where(
            CourseApprovalPolicy.course_id == course.id,
            CourseApprovalPolicy.tenant_id == actor.tenant_id,
        )
        .execution_options(populate_existing=True)
    )
    revisions = list(
        (
            await db.scalars(
                select(CourseApprovalRevision)
                .where(
                    CourseApprovalRevision.course_id == course.id,
                    CourseApprovalRevision.tenant_id == actor.tenant_id,
                )
                .order_by(CourseApprovalRevision.revision_number)
                .limit(101)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(revisions) > 100:
        raise CorrectionError("correction_context_too_large")
    lesson_payload = next(
        (
            payload
            for mod in release["modules"]
            if mod["id"] == str(module.id)
            for payload in mod["lessons"]
            if payload["id"] == str(lesson.id)
        ),
        None,
    )
    if lesson_payload is None or lesson_payload["content"] != lesson.content:
        raise CorrectionError("stale")
    course_version = canonical_json_sha256(
        {
            "release": release,
            "status": course.status,
            "current_release_id": str(course.current_release_id) if course.current_release_id else None,
            "published_at": course.published_at.isoformat() if course.published_at else None,
            "policy": None
            if policy is None
            else {
                "id": str(policy.id),
                "requires_approval": policy.requires_approval,
                "review_enabled": policy.review_enabled,
            },
            "revisions": [
                {
                    "id": str(rev.id),
                    "revision": rev.revision_number,
                    "state": rev.state,
                    "snapshot_sha256": rev.snapshot_sha256,
                    "source_fingerprint": rev.source_fingerprint,
                    "published_release_id": str(rev.published_release_id) if rev.published_release_id else None,
                }
                for rev in revisions
            ],
        }
    )
    context = LessonCorrectionContext(
        tenant_id=actor.tenant_id,
        course_id=cast(UUID, course.id),
        module_id=cast(UUID, module.id),
        lesson_id=lesson_id,
        course_version=course_version,
        lesson_version=canonical_json_sha256({"lesson": lesson_payload, "published_at": None}),
        lifecycle="draft",
        content=lesson.content,
        sources=tuple(
            CorrectionSource(
                document_id=source.document_id,
                version=source.version,
                content_sha256=source.content_sha256,
                index_revision=source.index_revision,
                evidence=tuple(
                    CorrectionEvidence(locator=item.citation.locator, evidence_hash=item.citation.evidence_hash)
                    for item in excerpts
                    if item.citation.document_id == source.document_id
                ),
            )
            for source in sources
        ),
    )
    return ResolvedLessonCorrection(context, lesson.title, tuple(excerpts))
