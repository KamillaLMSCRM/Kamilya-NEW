"""Domain services for immutable course approval and isolated review activity."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context
from app.models.courses import Course
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.courses.release_service import build_course_release_snapshot, canonical_json_sha256
from app.modules.integrations.crypto import encrypt_config

from .models import (
    CourseApprovalPolicy,
    CourseApprovalRequest,
    CourseApprovalReviewer,
    CourseApprovalRevision,
    CourseReviewAttempt,
    CourseReviewAttemptEvent,
    WorkflowAccessCredential,
    WorkflowDelivery,
    WorkflowEscalation,
    WorkflowReminder,
    WorkflowWorkItem,
)

PIN_HASHER = PasswordHasher()
TRANSIENT_DELIVERY_ERRORS = frozenset({"provider_timeout", "provider_unreachable", "provider_rate_limited", "provider_unavailable"})


def learner_safe_review_snapshot(snapshot: dict) -> dict:
    """Return reviewer content without answer keys or grading metadata.

    Approval attempts are an isolated learner-like surface.  The immutable
    publication snapshot intentionally contains answer keys for server-side
    grading, but those keys must never cross the reviewer API boundary.
    """
    import copy

    safe = copy.deepcopy(snapshot)
    # Keep the reviewer projection learner-like at every nesting level.  The
    # persisted release includes tenant and review/grading metadata for
    # server-side integrity, none of which belongs in the reviewer response.
    internal_fields = {
        "tenant_id",
        "reviewed_by",
        "reviewed_at",
        "review_comment",
        "review_status",
        "is_correct",
    }

    def strip(value):
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key not in internal_fields}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return strip(safe)


def score_review_submission(snapshot: dict, submissions: list[dict]) -> dict:
    """Score reviewer quiz answers from the immutable snapshot, never client data."""
    questions = {
        str(question.get("id")): question
        for module in snapshot.get("modules", [])
        for lesson in module.get("lessons", [])
        for quiz in lesson.get("quizzes", [])
        for question in quiz.get("questions", [])
    }
    answered: set[str] = set()
    correct = 0
    for submission in submissions:
        question_id = str(submission.get("question_id"))
        question = questions.get(question_id)
        if question is None or question_id in answered:
            continue
        answered.add(question_id)
        selected = {str(value) for value in submission.get("selected_choice_ids", [])}
        expected = {str(choice.get("id")) for choice in question.get("choices", []) if choice.get("is_correct") is True}
        if selected == expected:
            correct += 1
    total = len(questions)
    return {"answered": len(answered), "total": total, "correct": correct, "score_percent": round(correct * 100 / total, 2) if total else 100.0, "complete": bool(total == len(answered))}


async def get_policy(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> CourseApprovalPolicy | None:
    return await db.scalar(
        select(CourseApprovalPolicy).where(
            CourseApprovalPolicy.course_id == course_id,
            CourseApprovalPolicy.tenant_id == tenant_id,
        )
    )


async def set_policy(db: AsyncSession, *, course_id: UUID, tenant_id: UUID, requires_approval: bool, review_enabled: bool = True, actor_id: UUID):
    course = await db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id).with_for_update())
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    policy = await get_policy(db, course_id, tenant_id)
    if policy is None:
        policy = CourseApprovalPolicy(tenant_id=tenant_id, course_id=course_id)
        db.add(policy)
    policy.requires_approval = requires_approval
    policy.review_enabled = review_enabled
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


async def supersede_course_approvals(db: AsyncSession, *, course_id: UUID, tenant_id: UUID, actor_id: UUID) -> None:
    """Invalidate review state whenever mutable course content changes."""
    revisions = (await db.scalars(select(CourseApprovalRevision).where(
        CourseApprovalRevision.course_id == course_id,
        CourseApprovalRevision.tenant_id == tenant_id,
        CourseApprovalRevision.state.in_(("pending", "approved", "changes_requested")),
    ).with_for_update())).all()
    if not revisions:
        return
    revision_ids = [revision.id for revision in revisions]
    for revision in revisions:
        revision.state = "superseded"
    requests = (await db.scalars(select(CourseApprovalRequest).where(
        CourseApprovalRequest.revision_id.in_(revision_ids),
        CourseApprovalRequest.tenant_id == tenant_id,
    ).with_for_update())).all()
    for request in requests:
        request.outcome = "superseded"
    work_items = (await db.scalars(select(WorkflowWorkItem).where(
        WorkflowWorkItem.review_revision_id.in_(revision_ids),
        WorkflowWorkItem.tenant_id == tenant_id,
    ).with_for_update())).all()
    for item in work_items:
        item.outcome = "superseded"
        item.access_state = "revoked"
    credentials = (await db.scalars(select(WorkflowAccessCredential).where(
        WorkflowAccessCredential.work_item_id.in_([item.id for item in work_items]),
        WorkflowAccessCredential.tenant_id == tenant_id,
        WorkflowAccessCredential.revoked_at.is_(None),
    ).with_for_update())).all() if work_items else []
    now = datetime.now(UTC)
    for credential in credentials:
        credential.revoked_at = now
    await log_action(db, tenant_id, "course_approval.superseded", "course", course_id, actor_id, {"revision_count": len(revisions)})
    await db.flush()


async def create_request(db: AsyncSession, *, revision: CourseApprovalRevision, tenant_id: UUID, actor_id: UUID, reviewer_ids: list[UUID], delivery_mode: str, due_at=None, base_url: str | None = None, guest_reviewers: list[dict] | None = None):
    existing_request = await db.scalar(
        select(CourseApprovalRequest).where(
            CourseApprovalRequest.tenant_id == tenant_id,
            CourseApprovalRequest.revision_id == revision.id,
        )
    )
    if existing_request is not None:
        if existing_request.delivery_mode != delivery_mode:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        existing_reviewers = (await db.scalars(select(CourseApprovalReviewer).where(
            CourseApprovalReviewer.revision_id == revision.id,
            CourseApprovalReviewer.tenant_id == tenant_id,
        ))).all()
        existing_ids = {item.reviewer_user_id for item in existing_reviewers if item.reviewer_user_id is not None}
        existing_emails = {item.reviewer_email for item in existing_reviewers if item.reviewer_email is not None}
        requested_emails = {str(item.get("email", "")).strip().lower() for item in (guest_reviewers or [])}
        if existing_reviewers and (existing_ids != set(reviewer_ids) or existing_emails != requested_emails):
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        # Never turn a repeated create into a successful response with an
        # empty credential panel. Raw URL/PIN material is issued only by the
        # first create or explicit rotation; callers must use rotation after
        # an existing request is found.
        raise HTTPException(status_code=409, detail="credentials_already_issued")
    guest_reviewers = guest_reviewers or []
    guest_emails = [str(item.get("email", "")).strip().lower() for item in guest_reviewers]
    if len(set(reviewer_ids)) != len(reviewer_ids) or len(set(guest_emails)) != len(guest_emails) or not all(guest_emails):
        raise HTTPException(status_code=409, detail="Duplicate reviewer")
    if not reviewer_ids and not guest_reviewers:
        raise HTTPException(status_code=422, detail="At least one reviewer is required")
    if due_at is not None and due_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Due date must be in the future")
    # The explicit review capability is currently held by methodologists;
    # admins can configure/request but cannot become implicit reviewers.
    reviewers = list((await db.scalars(select(User).where(User.id.in_(reviewer_ids), User.tenant_id == tenant_id, User.is_active.is_(True), User.role == "methodologist"))).all()) if reviewer_ids else []
    if len(reviewers) != len(reviewer_ids):
        raise HTTPException(status_code=404, detail="Reviewer not found")
    reviewer_emails = {reviewer.id: (reviewer.email or "").strip().lower() or None for reviewer in reviewers}
    approval_request = CourseApprovalRequest(tenant_id=tenant_id, revision_id=revision.id, requested_by=actor_id, delivery_mode=delivery_mode, due_at=due_at)
    db.add(approval_request)
    access_credentials = []
    first_work_item = None
    first_access_url = None
    first_pin = None
    reviewer_specs = [(reviewer.id, None, None) for reviewer in reviewers]
    reviewer_specs.extend((uuid4(), item["email"].strip().lower(), item.get("name")) for item in guest_reviewers)
    for reviewer_id, reviewer_email, reviewer_name in reviewer_specs:
        # Review authority requires both the explicit assignment row and the
        # methodologist capability validated above.
        db.add(CourseApprovalReviewer(tenant_id=tenant_id, revision_id=revision.id, reviewer_user_id=reviewer_id if reviewer_email is None else None, reviewer_email=reviewer_email, reviewer_name=reviewer_name, required=True))
        work_item = WorkflowWorkItem(tenant_id=tenant_id, kind="reviewer", target_user_id=reviewer_id if reviewer_email is None else None, review_revision_id=revision.id, due_at=due_at, deadline_state="scheduled" if due_at is not None else "unset")
        db.add(work_item)
        await db.flush()
        if first_work_item is None:
            first_work_item = work_item
        recipient_email = reviewer_email or reviewer_emails.get(reviewer_id)
        raw_token = secrets.token_urlsafe(32)
        pin = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = due_at or (datetime.now(UTC) + timedelta(days=7))
        payload_encrypted = encrypt_config({
            "access_url": f"{(base_url or 'https://app.kml.kz').rstrip('/')}/course-review-access/{raw_token}",
            "pin": pin,
        }) if delivery_mode == "email" else None
        db.add(WorkflowDelivery(tenant_id=tenant_id, work_item_id=work_item.id, channel="cabinet", recipient_email=recipient_email, recipient_user_id=reviewer_id if reviewer_email is None else None, payload_encrypted=payload_encrypted, status="queued"))
        if delivery_mode == "email":
            db.add(WorkflowDelivery(tenant_id=tenant_id, work_item_id=work_item.id, channel="email", recipient_email=recipient_email, recipient_user_id=reviewer_id if reviewer_email is None else None, payload_encrypted=payload_encrypted, status="queued"))
        if delivery_mode in {"personal_link", "email"}:
            db.add(WorkflowAccessCredential(
                tenant_id=tenant_id, work_item_id=work_item.id, reviewer_user_id=reviewer_id,
                reviewer_email=reviewer_email,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                pin_hash=PIN_HASHER.hash(pin), expires_at=expires_at,
            ))
            access_url = f"{(base_url or 'https://app.kml.kz').rstrip('/')}/course-review-access/{raw_token}"
            access_credentials.append({"reviewer_id": reviewer_id, "access_url": access_url, "temporary_pin": pin, "expires_at": expires_at})
            if first_access_url is None:
                first_access_url, first_pin = access_url, pin
        if due_at is not None:
            reminder_at = due_at - timedelta(hours=24)
            reminder_channel = "email" if delivery_mode == "email" else "cabinet"
            operational_recipient = reviewer_id if reviewer_email is None else None
            if reminder_at > datetime.now(UTC):
                db.add(WorkflowReminder(tenant_id=tenant_id, work_item_id=work_item.id, rule_key="due_minus_24h", channel=reminder_channel, idempotency_key=f"review-reminder/{work_item.id}/due_minus_24h", scheduled_at=reminder_at, recipient_user_id=operational_recipient))
            db.add(WorkflowEscalation(tenant_id=tenant_id, work_item_id=work_item.id, rule_key="due_overdue", channel=reminder_channel, idempotency_key=f"review-escalation/{work_item.id}/due_overdue", scheduled_at=due_at, recipient_user_id=operational_recipient))
    await db.flush()
    await log_action(db, tenant_id, "course_approval.request_created", "course_approval_revision", revision.id, actor_id, {"reviewer_count": len(reviewer_specs), "delivery_mode": delivery_mode})
    return approval_request, first_work_item, first_access_url, first_pin, access_credentials


async def get_or_create_attempt(db: AsyncSession, *, revision_id: UUID, reviewer_user_id: UUID, tenant_id: UUID, reviewer_email: str | None = None):
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == revision_id, CourseApprovalRevision.tenant_id == tenant_id).with_for_update())
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    policy = await db.scalar(select(CourseApprovalPolicy).where(CourseApprovalPolicy.course_id == revision.course_id, CourseApprovalPolicy.tenant_id == tenant_id, CourseApprovalPolicy.review_enabled.is_(True)))
    if policy is None:
        raise HTTPException(status_code=403, detail="Course review access disabled")
    assignment_filter = CourseApprovalReviewer.reviewer_email == reviewer_email if reviewer_email else CourseApprovalReviewer.reviewer_user_id == reviewer_user_id
    assignment = await db.scalar(select(CourseApprovalReviewer).where(CourseApprovalReviewer.revision_id == revision_id, CourseApprovalReviewer.tenant_id == tenant_id, assignment_filter))
    if assignment is None:
        raise HTTPException(status_code=403, detail="Reviewer assignment required")
    attempt = await db.scalar(select(CourseReviewAttempt).where(CourseReviewAttempt.revision_id == revision_id, CourseReviewAttempt.tenant_id == tenant_id, CourseReviewAttempt.reviewer_user_id == reviewer_user_id).with_for_update())
    if attempt is None:
        attempt = CourseReviewAttempt(tenant_id=tenant_id, revision_id=revision_id, reviewer_user_id=reviewer_user_id, reviewer_email=reviewer_email, snapshot_sha256=revision.snapshot_sha256)
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
    policy = await db.scalar(select(CourseApprovalPolicy).where(CourseApprovalPolicy.course_id == revision.course_id, CourseApprovalPolicy.tenant_id == tenant_id, CourseApprovalPolicy.review_enabled.is_(True)))
    if policy is None:
        raise HTTPException(status_code=403, detail="Course review access disabled")
    if revision.state not in {"pending", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Review revision is no longer active")
    if attempt.activity_state in {"completed", "decision_pending"}:
        raise HTTPException(status_code=409, detail="Review attempt is already completed")
    previous = await db.scalar(select(CourseReviewAttemptEvent).where(CourseReviewAttemptEvent.attempt_id == attempt.id, CourseReviewAttemptEvent.tenant_id == tenant_id, CourseReviewAttemptEvent.sequence == sequence))
    payload_hash = canonical_json_sha256(payload)
    if previous:
        if previous.payload_sha256 != payload_hash:
            await log_action(db, tenant_id, "course_approval.progress_rejected", "course_review_attempt", attempt.id, attempt.reviewer_user_id, {"reason": "sequence_conflict", "sequence": sequence, "payload_sha256": payload_hash})
            raise HTTPException(status_code=409, detail="sequence_conflict")
        return attempt
    # Client activity_state is advisory only. Completion is derived from a
    # complete, ordered checkpoint set in the immutable revision snapshot.
    lesson_count = sum(len(module.get("lessons", [])) for module in revision.snapshot.get("modules", []))
    checkpoint_count = await db.scalar(select(func.count(CourseReviewAttemptEvent.id)).where(
        CourseReviewAttemptEvent.attempt_id == attempt.id,
        CourseReviewAttemptEvent.tenant_id == tenant_id,
        CourseReviewAttemptEvent.event_type == "checkpoint",
        CourseReviewAttemptEvent.sequence <= sequence,
    ))
    server_complete = event_type == "checkpoint" and lesson_count > 0 and lesson_position is not None and lesson_position >= lesson_count - 1 and int(checkpoint_count or 0) + 1 >= lesson_count
    effective_state = "decision_pending" if server_complete else "in_progress"
    attempt.activity_state = effective_state
    attempt.lesson_position = lesson_position
    attempt.last_activity_at = datetime.now(UTC)
    attempt.started_at = attempt.started_at or attempt.last_activity_at
    if server_complete:
        attempt.completed_at = attempt.last_activity_at
    db.add(CourseReviewAttemptEvent(tenant_id=tenant_id, attempt_id=attempt.id, sequence=sequence, event_type=event_type, payload=payload, payload_sha256=payload_hash))
    work_item = await db.scalar(select(WorkflowWorkItem).outerjoin(
        WorkflowAccessCredential,
        (WorkflowAccessCredential.work_item_id == WorkflowWorkItem.id) & (WorkflowAccessCredential.tenant_id == tenant_id),
    ).where(
        WorkflowWorkItem.review_revision_id == revision.id,
        WorkflowWorkItem.tenant_id == tenant_id,
        or_(WorkflowWorkItem.target_user_id == attempt.reviewer_user_id, WorkflowAccessCredential.reviewer_user_id == attempt.reviewer_user_id),
    ).with_for_update(of=WorkflowWorkItem))
    if work_item is not None:
        work_item.activity_state = "decision_pending" if server_complete else "in_progress"
        if server_complete:
            work_item.deadline_state = "closed"
        elif work_item.deadline_state in {"scheduled", "due", "overdue"}:
            work_item.deadline_state = "due"
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
    policy = await db.scalar(select(CourseApprovalPolicy).where(CourseApprovalPolicy.course_id == revision.course_id, CourseApprovalPolicy.tenant_id == tenant_id, CourseApprovalPolicy.review_enabled.is_(True)))
    if policy is None:
        raise HTTPException(status_code=403, detail="Course review access disabled")
    if revision.state not in {"pending", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Review revision is no longer active")
    validate_decision(decision, reason, warning_acknowledged, complete=bool(attempt.diagnostics.get("complete")) or attempt.activity_state == "decision_pending")
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
    work_items = (await db.scalars(select(WorkflowWorkItem).where(
        WorkflowWorkItem.review_revision_id == revision.id,
        WorkflowWorkItem.tenant_id == tenant_id,
    ).with_for_update())).all()
    for item in work_items:
        item.outcome = revision.state
        if reviewer.reviewer_user_id is not None and item.target_user_id == reviewer.reviewer_user_id:
            item.activity_state = "completed"
            item.deadline_state = "closed"
        elif reviewer.reviewer_email is not None:
            credential = await db.scalar(select(WorkflowAccessCredential.id).where(
                WorkflowAccessCredential.work_item_id == item.id,
                WorkflowAccessCredential.tenant_id == tenant_id,
                WorkflowAccessCredential.reviewer_email == reviewer.reviewer_email,
            ))
            if credential is not None:
                item.activity_state = "completed"
                item.deadline_state = "closed"
    await db.flush()
    await log_action(db, tenant_id, f"course_approval.{mapped}", "course_approval_revision", revision.id, actor_id, {"reason": reviewer.decision_reason, "warning_acknowledged": warning_acknowledged})
    return reviewer


async def verify_access_pin(db: AsyncSession, token: str, pin: str) -> dict:
    """Verify a one-time reviewer credential without issuing an account session."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    tenant_id = await db.scalar(text("SELECT lookup_course_review_tenant_by_token(:token)"), {"token": digest})
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="Review access not found")
    # Establish RLS context through the fail-closed auth seam.  A rejected
    # SELECT set_current_tenant must roll back before any ORM access.
    await _set_tenant_security_context(db, str(tenant_id))
    credential = await db.scalar(select(WorkflowAccessCredential).where(
        WorkflowAccessCredential.token_hash == digest,
        WorkflowAccessCredential.tenant_id == tenant_id,
    ))
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
        await log_action(db, tenant_id, "course_approval.access_rejected", "workflow_access_credential", credential.id, credential.reviewer_user_id, {"reason": "invalid_pin", "token_hash_prefix": digest[:12]})
        await db.commit()
        raise HTTPException(status_code=401, detail="Review access not verified")
    # PIN verification is not single-use: the same credential may resume an
    # active review until expiry/revocation. Rotation is explicit via resend.
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
            "reviewer_email": credential.reviewer_email,
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
    work_items = (await db.scalars(select(WorkflowWorkItem).where(
        WorkflowWorkItem.review_revision_id == revision.id,
        WorkflowWorkItem.tenant_id == tenant_id,
    ).with_for_update())).all()
    credentials = (await db.scalars(select(WorkflowAccessCredential).where(
        WorkflowAccessCredential.work_item_id.in_([item.id for item in work_items]),
        WorkflowAccessCredential.tenant_id == tenant_id,
        WorkflowAccessCredential.revoked_at.is_(None),
    ).with_for_update())).all() if work_items else []
    now = datetime.now(UTC)
    for credential in credentials:
        credential.revoked_at = now
    for item in work_items:
        item.access_state = "revoked"
        item.outcome = "cancelled"
    await log_action(db, tenant_id, "course_approval.cancelled", "course_approval_request", request_row.id, actor_id)
    await db.flush()
    return request_row


async def revoke_request_access(db: AsyncSession, *, request_id: UUID, tenant_id: UUID, actor_id: UUID):
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == tenant_id))
    if request_row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    work_items = (await db.scalars(select(WorkflowWorkItem).where(WorkflowWorkItem.review_revision_id == request_row.revision_id, WorkflowWorkItem.tenant_id == tenant_id).with_for_update())).all()
    if not work_items:
        raise HTTPException(status_code=404, detail="Review access not found")
    credentials = (await db.scalars(select(WorkflowAccessCredential).where(WorkflowAccessCredential.work_item_id.in_([item.id for item in work_items]), WorkflowAccessCredential.tenant_id == tenant_id, WorkflowAccessCredential.revoked_at.is_(None)).with_for_update())).all()
    now = datetime.now(UTC)
    for credential in credentials:
        credential.revoked_at = now
    for item in work_items:
        item.access_state = "revoked"
        item.outcome = "cancelled"
    await log_action(db, tenant_id, "course_approval.access_revoked", "course_approval_request", request_row.id, actor_id)
    await db.flush()
    return work_items[0]


async def resend_request_access(db: AsyncSession, *, request_id: UUID, tenant_id: UUID, actor_id: UUID, base_url: str, rotate_credentials: bool = False) -> dict:
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == tenant_id).with_for_update())
    if request_row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == request_row.revision_id, CourseApprovalRevision.tenant_id == tenant_id).with_for_update())
    if revision is None or revision.state not in {"pending", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Approval request is not active")
    work_items = (await db.scalars(select(WorkflowWorkItem).where(WorkflowWorkItem.review_revision_id == revision.id, WorkflowWorkItem.tenant_id == tenant_id).with_for_update())).all()
    if not work_items:
        raise HTTPException(status_code=404, detail="Review access not found")
    now = datetime.now(UTC)
    output = []
    retried = 0
    for item in work_items:
        channel = "email" if request_row.delivery_mode == "email" else "cabinet"
        latest_delivery = await db.scalar(select(WorkflowDelivery).where(
            WorkflowDelivery.work_item_id == item.id,
            WorkflowDelivery.tenant_id == tenant_id,
            WorkflowDelivery.channel == channel,
        ).order_by(WorkflowDelivery.generation.desc()).limit(1).with_for_update())
        if not rotate_credentials:
            if latest_delivery is None or latest_delivery.status != "failed" or latest_delivery.error_category not in TRANSIENT_DELIVERY_ERRORS:
                raise HTTPException(status_code=409, detail="Only retryable failed deliveries can be resent without credential rotation")
            latest_delivery.status = "queued"
            latest_delivery.next_attempt_at = None
            latest_delivery.error_category = None
            retried += 1
            continue
        active = (await db.scalars(select(WorkflowAccessCredential).where(WorkflowAccessCredential.work_item_id == item.id, WorkflowAccessCredential.tenant_id == tenant_id, WorkflowAccessCredential.revoked_at.is_(None)).with_for_update())).all()
        for credential in active:
            credential.revoked_at = now
        previous_credential = active[-1] if active else await db.scalar(select(WorkflowAccessCredential).where(
            WorkflowAccessCredential.work_item_id == item.id,
            WorkflowAccessCredential.tenant_id == tenant_id,
        ).order_by(WorkflowAccessCredential.id.desc()).limit(1))
        reviewer = await db.scalar(select(CourseApprovalReviewer).where(
            CourseApprovalReviewer.revision_id == revision.id,
            CourseApprovalReviewer.tenant_id == tenant_id,
            (CourseApprovalReviewer.reviewer_user_id == item.target_user_id) if item.target_user_id is not None else (CourseApprovalReviewer.reviewer_email == (previous_credential.reviewer_email if previous_credential else None)),
        ))
        reviewer_email = reviewer.reviewer_email if reviewer else (previous_credential.reviewer_email if previous_credential else None)
        raw_token = secrets.token_urlsafe(32)
        pin = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = request_row.due_at or (now + timedelta(days=7))
        payload_encrypted = encrypt_config({"access_url": f"{base_url.rstrip('/')}/course-review-access/{raw_token}", "pin": pin}) if request_row.delivery_mode == "email" else None
        reviewer_id = item.target_user_id or (previous_credential.reviewer_user_id if previous_credential else uuid4())
        db.add(WorkflowAccessCredential(tenant_id=tenant_id, work_item_id=item.id, reviewer_user_id=reviewer_id, reviewer_email=reviewer_email, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), pin_hash=PIN_HASHER.hash(pin), expires_at=expires_at))
        generation = int(await db.scalar(select(func.max(WorkflowDelivery.generation)).where(WorkflowDelivery.work_item_id == item.id, WorkflowDelivery.tenant_id == tenant_id)) or 0) + 1
        db.add(WorkflowDelivery(tenant_id=tenant_id, work_item_id=item.id, channel=channel, generation=generation, recipient_email=reviewer_email, recipient_user_id=item.target_user_id, payload_encrypted=payload_encrypted, status="queued"))
        item.access_state = "issued"
        output.append({"reviewer_id": reviewer_id if item.target_user_id is not None else None, "access_url": f"{base_url.rstrip('/')}/course-review-access/{raw_token}", "temporary_pin": pin, "expires_at": expires_at})
    await log_action(db, tenant_id, "course_approval.access_resent" if rotate_credentials else "course_approval.delivery_retried", "course_approval_request", request_row.id, actor_id, {"reviewer_count": len(output), "retried": retried, "rotated": rotate_credentials})
    await db.flush()
    return {"rotated": rotate_credentials, "retried": retried, "access_credentials": output}
