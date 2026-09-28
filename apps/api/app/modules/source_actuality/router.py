"""Methodologist API for source actuality and controlled retraining."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.modules.audit.service import log_action
from app.modules.source_actuality.models import DocumentChangeReview
from app.modules.source_actuality.schemas import (
    SourceActualityList,
    SourceChangeDecisionRequest,
    SourceChangeReviewRecord,
    SourcePolicyRecord,
    SourcePolicyUpdate,
)
from app.modules.source_actuality.service import (
    decide_review,
    derive_actuality_state,
    list_actuality,
    request_analysis,
    upsert_policy,
)
from app.modules.source_actuality.tasks import analyze_review_task

router = APIRouter(
    prefix="/admin/source-actuality",
    tags=["source-actuality"],
    dependencies=[Depends(require_tenant_user())],
)
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[Any, Depends(require_role("methodologist"))]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _review_record(review: DocumentChangeReview) -> SourceChangeReviewRecord:
    snapshot = review.impact_snapshot or {}
    return SourceChangeReviewRecord(
        id=review.id,
        tenant_id=review.tenant_id,
        source_family_id=review.source_family_id,
        previous_document_id=review.previous_document_id,
        new_document_id=review.new_document_id,
        status=review.status,
        added_fact_count=review.added_fact_count,
        removed_fact_count=review.removed_fact_count,
        changed_fact_count=review.changed_fact_count,
        unchanged_fact_count=review.unchanged_fact_count,
        impacted_course_count=review.impacted_course_count,
        impacted_lesson_count=review.impacted_lesson_count,
        assessment_questions_requiring_review=review.assessment_questions_requiring_review,
        impacted_courses=snapshot.get("impacted_courses", []),
        added_facts=snapshot.get("added_facts", []),
        removed_facts=snapshot.get("removed_facts", []),
        changed_facts=snapshot.get("changed_facts", []),
        analysis_truncated=bool(snapshot.get("analysis_truncated", False)),
        analysis_error_code=review.analysis_error_code,
        analysis_error_message=review.analysis_error_message,
        decision=review.decision,
        decision_reason=review.decision_reason,
        decision_snapshot=review.decision_snapshot,
        decided_by=review.decided_by,
        decided_at=review.decided_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.get("", response_model=SourceActualityList)
async def get_source_actuality(
    response: Response,
    db: DbSession,
    user: Methodologist,
):
    _no_store(response)
    return await list_actuality(db, tenant_id=user.tenant_id)


@router.put("/{source_family_id}/policy", response_model=SourcePolicyRecord)
async def put_source_policy(
    source_family_id: UUID,
    payload: SourcePolicyUpdate,
    request: Request,
    response: Response,
    db: DbSession,
    user: Methodologist,
):
    policy = await upsert_policy(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        source_family_id=source_family_id,
        owner_id=payload.owner_id,
        reviewed_at=payload.reviewed_at,
        next_review_at=payload.next_review_at,
    )
    record = SourcePolicyRecord.model_validate(
        {
            "id": policy.id,
            "tenant_id": policy.tenant_id,
            "source_family_id": policy.source_family_id,
            "owner_id": policy.owner_id,
            "reviewed_at": policy.reviewed_at,
            "next_review_at": policy.next_review_at,
            "actuality_state": derive_actuality_state(policy.next_review_at),
            "created_at": policy.created_at,
            "updated_at": policy.updated_at,
        }
    )
    await log_action(
        db,
        user.tenant_id,
        "source_actuality.policy_updated",
        "document_source_policy",
        resource_id=source_family_id,
        user_id=user.id,
        details={
            "owner_assigned": payload.owner_id is not None,
            "reviewed_at": payload.reviewed_at.isoformat() if payload.reviewed_at else None,
            "next_review_at": payload.next_review_at.isoformat() if payload.next_review_at else None,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    _no_store(response)
    return record


@router.post(
    "/documents/{new_document_id}/analyze",
    response_model=SourceChangeReviewRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_document_change(
    new_document_id: UUID,
    request: Request,
    response: Response,
    db: DbSession,
    user: Methodologist,
):
    review, should_enqueue = await request_analysis(
        db,
        tenant_id=user.tenant_id,
        new_document_id=new_document_id,
    )
    await log_action(
        db,
        user.tenant_id,
        "source_actuality.analysis_requested",
        "document_change_review",
        resource_id=review.id,
        user_id=user.id,
        details={"new_document_id": str(new_document_id), "queued": should_enqueue},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    if should_enqueue:
        try:
            analyze_review_task.apply_async(args=[str(user.tenant_id), str(review.id)])
        except Exception:
            review.status = "failed"
            review.analysis_error_code = "source_analysis_dispatch_failed"
            review.analysis_error_message = "Source analysis could not be queued. Retry the analysis."
            await db.commit()
            raise HTTPException(status_code=503, detail="Source analysis could not be queued") from None
    _no_store(response)
    return _review_record(review)


@router.get("/reviews/{review_id}", response_model=SourceChangeReviewRecord)
async def get_review(
    review_id: UUID,
    response: Response,
    db: DbSession,
    user: Methodologist,
):
    review = await db.get(DocumentChangeReview, review_id)
    if review is None or review.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Review not found")
    _no_store(response)
    return _review_record(review)


@router.post("/reviews/{review_id}/decision", response_model=SourceChangeReviewRecord)
async def decide_source_change(
    review_id: UUID,
    payload: SourceChangeDecisionRequest,
    request: Request,
    response: Response,
    db: DbSession,
    user: Methodologist,
):
    review = await decide_review(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        review_id=review_id,
        decision=payload.decision,
        reason=payload.reason,
        retraining_due_at=payload.retraining_due_at,
    )
    # The database trigger advances updated_at when the review is resolved.
    # Refresh explicitly before serializing so AsyncSession never attempts an
    # implicit lazy load outside greenlet_spawn.
    await db.refresh(review)
    record = _review_record(review)
    await log_action(
        db,
        user.tenant_id,
        "source_actuality.decision_recorded",
        "document_change_review",
        resource_id=review.id,
        user_id=user.id,
        details={
            "decision": payload.decision,
            "retraining_due_at": (
                payload.retraining_due_at.isoformat() if payload.retraining_due_at else None
            ),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    _no_store(response)
    return record
