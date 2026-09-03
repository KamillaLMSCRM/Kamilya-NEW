"""Domain services for immutable course approval and isolated review activity."""

from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from uuid import UUID

from argon2 import PasswordHasher
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.courses.release_service import build_course_release_snapshot, canonical_json_sha256
from .models import (
    CourseApprovalPolicy,
    CourseApprovalRequest,
    CourseApprovalRevision,
    CourseApprovalReviewer,
    CourseReviewAttempt,
    CourseReviewAttemptEvent,
    WorkflowAccessCredential,
    WorkflowDelivery,
    WorkflowWorkItem,
)

PIN_HASHER = PasswordHasher()


async def get_policy(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> CourseApprovalPolicy | None:
    return await db.scalar(
        select(CourseApprovalPolicy).where(
            CourseApprovalPolicy.course_id == course_id,
            CourseApprovalPolicy.tenant_id == tenant_id,
        )
    )


async def set_policy(db: AsyncSession, *, course_id: UUID, tenant_id: UUID, requires_approval: bool, actor_id: UUID):
    course = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id).with_for_update())
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    policy = await get_policy(db, course_id, tenant_id)
    if policy is None:
        policy = CourseApprovalPolicy(tenant_id=tenant_id, course_id=course_id)
        db.add(policy)
    policy.requires_approval = requires_approval
    policy.updated_by = actor_id
    await db.flush()
    await log_action(db, tenant_id, "course_approval.configure", "course", course_id, actor_id, {"requires_approval": requires_approval})
    return policy


async def freeze_revision(db: AsyncSession, *, course_id: UUID, tenant_id: UUID, actor_id: UUID, source_fingerprint: str | None = None):
    course = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id).with_for_update())
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    snapshot = await build_course_release_snapshot(db, course, version=1)
    snapshot_hash = canonical_json_sha256(snapshot)
    fingerprint = source_fingerprint or snapshot_hash
    existing = await db.scalar(
        select(CourseApprovalRevision).where(
            CourseApprovalRevision.tenant_id == tenant_id,
            CourseApprovalRevision.course_id == course_id,
            CourseApprovalRevision.source_fingerprint == fingerprint,
        ).order_by(CourseApprovalRevision.revision_number.desc()).limit(1)
    )
    if existing is not None:
        return existing
    latest = await db.scalar(select(func.max(CourseApprovalRevision.revision_number)).where(CourseApprovalRevision.tenant_id == tenant_id, CourseApprovalRevision.course_id == course_id))
    revision = CourseApprovalRevision(
        tenant_id=tenant_id,
        course_id=course_id,
        revision_number=int(latest or 0) + 1,
        snapshot=snapshot,
        snapshot_sha256=snapshot_hash,
        source_fingerprint=fingerprint,
        state="pending",
        created_by=actor_id,
    )
    prior_revisions = (await db.scalars(select(CourseApprovalRevision).where(CourseApprovalRevision.tenant_id == tenant_id, CourseApprovalRevision.course_id == course_id, CourseApprovalRevision.state.in_(("pending", "approved", "changes_requested"))))).all()
    for prior in prior_revisions:
        prior.state = "superseded"
    db.add(revision)
    await db.flush()
    await log_action(db, tenant_id, "course_approval.revision_frozen", "course_approval_revision", revision.id, actor_id, {"snapshot_sha256": snapshot_hash, "revision_number": revision.revision_number})
    return revision


async def create_request(db: AsyncSession, *, revision: CourseApprovalRevision, tenant_id: UUID, actor_id: UUID, reviewer_ids: list[UUID], delivery_mode: str, due_at=None, base_url: str | None = None):
    existing_request = await db.scalar(
        select(CourseApprovalRequest).where(
            CourseApprovalRequest.tenant_id == tenant_id,
            CourseApprovalRequest.revision_id == revision.id,
        )
    )
    if existing_request is not None:
        if existing_request.delivery_mode != delivery_mode:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        existing_reviewers = set((await db.scalars(select(CourseApprovalReviewer.reviewer_user_id).where(CourseApprovalReviewer.revision_id == revision.id, CourseApprovalReviewer.tenant_id == tenant_id))).all())
        if existing_reviewers and existing_reviewers != set(reviewer_ids):
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        work_item = await db.scalar(select(WorkflowWorkItem).where(WorkflowWorkItem.review_revision_id == revision.id, WorkflowWorkItem.tenant_id == tenant_id))
        return existing_request, work_item, None, None, []
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise HTTPException(status_code=409, detail="Duplicate reviewer")
    if due_at is not None and due_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Due date must be in the future")
    reviewers = list((await db.scalars(select(User).where(User.id.in_(reviewer_ids), User.tenant_id == tenant_id, User.is_active.is_(True), User.role.in_(("admin", "methodologist"))))).all())
    if len(reviewers) != len(reviewer_ids):
        raise HTTPException(status_code=404, detail="Reviewer not found")
    approval_request = CourseApprovalRequest(tenant_id=tenant_id, revision_id=revision.id, requested_by=actor_id, delivery_mode=delivery_mode, due_at=due_at)
    db.add(approval_request)
    access_credentials = []
    first_work_item = None
    first_access_url = None
    first_pin = None
    for reviewer in reviewers:
        # Review authority is assignment-based; role is deliberately not used
        # as a substitute for an explicit reviewer assignment.
        db.add(CourseApprovalReviewer(tenant_id=tenant_id, revision_id=revision.id, reviewer_user_id=reviewer.id, required=True))
        work_item = WorkflowWorkItem(tenant_id=tenant_id, kind="reviewer", target_user_id=reviewer.id, review_revision_id=revision.id, due_at=due_at)
        db.add(work_item)
        await db.flush()
        if first_work_item is None:
            first_work_item = work_item
        db.add(WorkflowDelivery(tenant_id=tenant_id, work_item_id=work_item.id, channel="cabinet", status="delivered" if delivery_mode == "personal_link" else "queued"))
        if delivery_mode == "email":
            db.add(WorkflowDelivery(tenant_id=tenant_id, work_item_id=work_item.id, channel="email", status="queued"))
        if delivery_mode == "personal_link":
            raw_token = secrets.token_urlsafe(32)
            pin = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = due_at or (datetime.now(UTC) + timedelta(days=7))
            db.add(WorkflowAccessCredential(
                tenant_id=tenant_id, work_item_id=work_item.id, reviewer_user_id=reviewer.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                pin_hash=PIN_HASHER.hash(pin), expires_at=expires_at,
            ))
            access_url = f"{(base_url or 'https://app.kml.kz').rstrip('/')}/course-review-access/{raw_token}"
            access_credentials.append({"reviewer_id": reviewer.id, "access_url": access_url, "temporary_pin": pin, "expires_at": expires_at})
            if first_access_url is None:
                first_access_url, first_pin = access_url, pin
    await db.flush()
    await log_action(db, tenant_id, "course_approval.request_created", "course_approval_revision", revision.id, actor_id, {"reviewer_count": len(reviewer_ids), "delivery_mode": delivery_mode})
    return approval_request, first_work_item, first_access_url, first_pin, access_credentials


async def get_or_create_attempt(db: AsyncSession, *, revision_id: UUID, reviewer_user_id: UUID, tenant_id: UUID):
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == revision_id, CourseApprovalRevision.tenant_id == tenant_id))
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    assignment = await db.scalar(select(CourseApprovalReviewer).where(CourseApprovalReviewer.revision_id == revision_id, CourseApprovalReviewer.tenant_id == tenant_id, CourseApprovalReviewer.reviewer_user_id == reviewer_user_id))
    if assignment is None:
        raise HTTPException(status_code=403, detail="Reviewer assignment required")
    attempt = await db.scalar(select(CourseReviewAttempt).where(CourseReviewAttempt.revision_id == revision_id, CourseReviewAttempt.tenant_id == tenant_id, CourseReviewAttempt.reviewer_user_id == reviewer_user_id))
    if attempt is None:
        attempt = CourseReviewAttempt(tenant_id=tenant_id, revision_id=revision_id, reviewer_user_id=reviewer_user_id, snapshot_sha256=revision.snapshot_sha256)
        db.add(attempt)
        await db.flush()
    return attempt, revision


def validate_decision(decision: str, reason: str | None, warning_acknowledged: bool, *, complete: bool):
    if decision == "return" and not (reason and reason.strip()):
        raise HTTPException(status_code=422, detail="Return reason is required")
    if decision == "approve" and not complete and not warning_acknowledged:
        raise HTTPException(status_code=409, detail="Incomplete review acknowledgement required")
    return {"warning_acknowledged": bool(warning_acknowledged)}


async def record_progress(db: AsyncSession, *, attempt: CourseReviewAttempt, revision: CourseApprovalRevision, tenant_id: UUID, sequence: int, event_type: str, payload: dict, lesson_position: int | None, activity_state: str):
    previous = await db.scalar(select(CourseReviewAttemptEvent).where(CourseReviewAttemptEvent.attempt_id == attempt.id, CourseReviewAttemptEvent.tenant_id == tenant_id, CourseReviewAttemptEvent.sequence == sequence))
    payload_hash = canonical_json_sha256(payload)
    if previous:
        if previous.payload_sha256 != payload_hash:
            raise HTTPException(status_code=409, detail="sequence_conflict")
        return attempt
    attempt.activity_state = activity_state
    attempt.lesson_position = lesson_position
    attempt.last_activity_at = datetime.now(UTC)
    attempt.started_at = attempt.started_at or attempt.last_activity_at
    if activity_state == "completed":
        attempt.completed_at = attempt.last_activity_at
    db.add(CourseReviewAttemptEvent(tenant_id=tenant_id, attempt_id=attempt.id, sequence=sequence, event_type=event_type, payload=payload, payload_sha256=payload_hash))
    await db.flush()
    return attempt


async def decide(db: AsyncSession, *, attempt: CourseReviewAttempt, revision: CourseApprovalRevision, reviewer: CourseApprovalReviewer, tenant_id: UUID, actor_id: UUID, decision: str, reason: str | None, warning_acknowledged: bool):
    locked_revision = await db.scalar(select(CourseApprovalRevision).where(
        CourseApprovalRevision.id == revision.id,
        CourseApprovalRevision.tenant_id == tenant_id,
    ).with_for_update())
    locked_reviewer = await db.scalar(select(CourseApprovalReviewer).where(
        CourseApprovalReviewer.id == reviewer.id,
        CourseApprovalReviewer.revision_id == revision.id,
        CourseApprovalReviewer.tenant_id == tenant_id,
    ).with_for_update())
    if locked_revision is None or locked_reviewer is None:
        raise HTTPException(status_code=404, detail="Reviewer assignment not found")
    revision = locked_revision
    reviewer = locked_reviewer
    validate_decision(decision, reason, warning_acknowledged, complete=attempt.activity_state == "completed")
    if revision.snapshot_sha256 != attempt.snapshot_sha256:
        raise HTTPException(status_code=409, detail="approval_revision_mismatch")
    mapped = "approved" if decision == "approve" else "changes_requested"
    if reviewer.decision != "pending":
        if reviewer.decision == mapped and (reviewer.decision_reason or "") == (reason or ""):
            return reviewer
        raise HTTPException(status_code=409, detail="decision_conflict")
    reviewer.decision = mapped
    reviewer.decision_reason = reason.strip() if reason else None
    reviewer.warning_acknowledged = warning_acknowledged
    reviewer.decision_at = datetime.now(UTC)
    if mapped == "changes_requested":
        revision.state = "changes_requested"
    elif await db.scalar(select(func.count(CourseApprovalReviewer.id)).where(CourseApprovalReviewer.revision_id == revision.id, CourseApprovalReviewer.tenant_id == tenant_id, CourseApprovalReviewer.required.is_(True), CourseApprovalReviewer.decision != "approved")) == 0:
        revision.state = "approved"
        revision.approved_at = reviewer.decision_at
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.revision_id == revision.id, CourseApprovalRequest.tenant_id == tenant_id))
    if request_row is not None:
        request_row.outcome = revision.state
    await db.flush()
    await log_action(db, tenant_id, f"course_approval.{mapped}", "course_approval_revision", revision.id, actor_id, {"reason": reviewer.decision_reason, "warning_acknowledged": warning_acknowledged})
    return reviewer


async def verify_access_pin(db: AsyncSession, token: str, pin: str) -> dict:
    """Verify a one-time reviewer credential without issuing an account session."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    tenant_id = await db.scalar(text("SELECT lookup_course_review_tenant_by_token(:token)"), {"token": digest})
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="Review access not found")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
    credential = await db.scalar(select(WorkflowAccessCredential).where(WorkflowAccessCredential.token_hash == digest))
    now = datetime.now(UTC)
    if credential is None or credential.revoked_at is not None or credential.expires_at <= now:
        raise HTTPException(status_code=404, detail="Review access not found")
    if credential.locked_until and credential.locked_until > now:
        raise HTTPException(status_code=401, detail="Review access unavailable")
    try:
        valid = PIN_HASHER.verify(credential.pin_hash, pin)
    except Exception:
        valid = False
    if not valid:
        credential.failed_attempts += 1
        if credential.failed_attempts >= 5:
            credential.locked_until = now + timedelta(minutes=15)
        await db.commit()
        raise HTTPException(status_code=401, detail="Review access not verified")
    credential.verified_at = now
    credential.opened_at = credential.opened_at or now
    work_item = await db.scalar(select(WorkflowWorkItem).where(WorkflowWorkItem.id == credential.work_item_id, WorkflowWorkItem.tenant_id == credential.tenant_id))
    if work_item is None or work_item.review_revision_id is None:
        raise HTTPException(status_code=404, detail="Review access not found")
    work_item.access_state = "active"
    await db.commit()
    from app.core.auth import create_scoped_token
    review_token = create_scoped_token(
        {
            "sub": str(work_item.id),
            "tenant_id": str(work_item.tenant_id),
            "auth_method": "course_review",
            "review_work_item_id": str(work_item.id),
            "reviewer_user_id": str(credential.reviewer_user_id),
            "active_role": "methodologist",
        },
        token_type="course_review",
        expires_delta=timedelta(hours=4),
    )
    return {"work_item_id": work_item.id, "reviewer_user_id": credential.reviewer_user_id, "access_state": work_item.access_state, "review_token": review_token}


async def cancel_request(db: AsyncSession, *, request_id: UUID, tenant_id: UUID, actor_id: UUID):
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == tenant_id).with_for_update())
    if request_row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == request_row.revision_id, CourseApprovalRevision.tenant_id == tenant_id).with_for_update())
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    if revision.state not in {"pending", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Approval request is not cancellable")
    revision.state = request_row.outcome = "cancelled"
    await log_action(db, tenant_id, "course_approval.cancelled", "course_approval_request", request_row.id, actor_id)
    await db.flush()
    return request_row


async def revoke_request_access(db: AsyncSession, *, request_id: UUID, tenant_id: UUID, actor_id: UUID):
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == tenant_id))
    if request_row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    work_item = await db.scalar(select(WorkflowWorkItem).where(WorkflowWorkItem.review_revision_id == request_row.revision_id, WorkflowWorkItem.tenant_id == tenant_id))
    if work_item is None:
        raise HTTPException(status_code=404, detail="Review access not found")
    credentials = (await db.scalars(select(WorkflowAccessCredential).where(WorkflowAccessCredential.work_item_id == work_item.id, WorkflowAccessCredential.tenant_id == tenant_id, WorkflowAccessCredential.revoked_at.is_(None)).with_for_update())).all()
    now = datetime.now(UTC)
    for credential in credentials:
        credential.revoked_at = now
    work_item.access_state = "revoked"
    await log_action(db, tenant_id, "course_approval.access_revoked", "course_approval_request", request_row.id, actor_id)
    await db.flush()
    return work_item
