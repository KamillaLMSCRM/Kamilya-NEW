# FastAPI resolves dependency/header/body defaults from function signatures;
# B008's module-level-singleton recommendation would alter that established
# request dependency contract, so keep the framework-native declarations.
# ruff: noqa: B008
# SQLAlchemy's legacy declarative Column descriptors and FastAPI dependency
# factories are intentionally dynamic in this module; keep those boundaries
# explicit while type-checking business helpers.
# mypy: disable-error-code="arg-type,assignment,attr-defined,misc,no-any-return,no-untyped-call,no-untyped-def,type-arg"

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, decode_token, get_current_user, require_tenant_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.permissions import COURSE_APPROVAL_PERMISSIONS, require_permission
from app.models.users import User
from app.modules.audit.service import log_action

from .models import (
    CourseApprovalPolicy,
    CourseApprovalRequest,
    CourseApprovalReviewer,
    CourseApprovalRevision,
    CourseReviewAttempt,
    WorkflowAccessCredential,
    WorkflowDelivery,
    WorkflowIdempotencyKey,
    WorkflowWorkItem,
)
from .schemas import (
    ApprovalPolicyRequest,
    ApprovalPolicyResponse,
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    ApprovalRevisionResponse,
    ResendAccessRequest,
    ReviewDecisionRequest,
    ReviewerStatusResponse,
    ReviewPinRequest,
    ReviewProgressRequest,
    ReviewTestSubmission,
    ScopedReviewRequestResponse,
)
from .service import (
    cancel_request,
    canonical_json_sha256,
    create_request,
    decide,
    freeze_revision,
    get_or_create_attempt,
    learner_safe_review_snapshot,
    record_progress,
    resend_request_access,
    revoke_request_access,
    score_review_submission,
    set_policy,
)


async def require_course_approval_enabled() -> None:
    """Runtime kill switch that preserves historical rows when disabled."""
    if not get_settings().COURSE_APPROVAL_WORKFLOW_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course approval workflow unavailable")


async def _read_idempotency(db: AsyncSession, *, tenant_id: UUID, key: str | None, operation: str, fingerprint: str):
    if not key:
        return None
    if len(key) > 200:
        raise HTTPException(status_code=422, detail="Idempotency-Key is too long")
    row = await db.scalar(select(WorkflowIdempotencyKey).where(
        WorkflowIdempotencyKey.tenant_id == tenant_id,
        WorkflowIdempotencyKey.key == key,
        WorkflowIdempotencyKey.operation == operation,
    ))
    if row is not None:
        if row.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        return row.response
    return None


async def _write_idempotency(db: AsyncSession, *, tenant_id: UUID, key: str | None, operation: str, fingerprint: str, response: dict):
    if not key:
        return
    # Most workflow handlers commit their domain mutation before persisting
    # the replay row.  ``set_current_tenant`` is transaction-local, so the
    # commit clears the RLS context; restore the transaction-local tenant RLS setting
    # for the exact validated tenant before this second write rather than relying
    # on ORM predicates alone.
    await _set_tenant_security_context(db, str(tenant_id))
    try:
        async with db.begin_nested():
            db.add(WorkflowIdempotencyKey(
                tenant_id=tenant_id,
                key=key,
                operation=operation,
                request_fingerprint=fingerprint,
                response=response,
            ))
            await db.flush()
    except IntegrityError:
        row = await db.scalar(select(WorkflowIdempotencyKey).where(
            WorkflowIdempotencyKey.tenant_id == tenant_id,
            WorkflowIdempotencyKey.key == key,
            WorkflowIdempotencyKey.operation == operation,
        ))
        if row is None or row.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="idempotency_conflict") from None
    await db.commit()


def _redact_issued_credentials(response: ApprovalRequestResponse) -> dict:
    """Persist/replay request metadata without one-time URL/PIN material."""
    persisted = response.model_dump(mode="json")
    persisted.update({"credentials_issued": bool(response.access_credentials), "access_url": None, "temporary_pin": None, "access_credentials": []})
    return persisted


router = APIRouter(tags=["course-approval"])
tenant = [Depends(require_tenant_user())]
workflow_write = tenant + [Depends(require_course_approval_enabled)]
review_workflow_write = [Depends(require_course_approval_enabled)]
review_bearer = HTTPBearer(auto_error=False)


async def _request_projection(db: AsyncSession, row: CourseApprovalRequest, tenant_id: UUID) -> dict:
    reviewers = (await db.scalars(select(CourseApprovalReviewer).where(CourseApprovalReviewer.revision_id == row.revision_id, CourseApprovalReviewer.tenant_id == tenant_id))).all()
    items = (await db.scalars(select(WorkflowWorkItem).where(WorkflowWorkItem.review_revision_id == row.revision_id, WorkflowWorkItem.tenant_id == tenant_id))).all()
    item_ids = [item.id for item in items]
    user_ids = [reviewer.reviewer_user_id for reviewer in reviewers if reviewer.reviewer_user_id is not None]
    users = {user.id: user for user in (await db.scalars(select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id))).all()} if user_ids else {}
    deliveries = (await db.scalars(select(WorkflowDelivery).where(WorkflowDelivery.work_item_id.in_(item_ids), WorkflowDelivery.tenant_id == tenant_id))).all() if item_ids else []
    attempts = (await db.scalars(select(CourseReviewAttempt).where(CourseReviewAttempt.revision_id == row.revision_id, CourseReviewAttempt.tenant_id == tenant_id))).all()
    return {
        "request_id": row.id,
        "revision_id": row.revision_id,
        "outcome": row.outcome,
        "delivery_mode": row.delivery_mode,
        "due_at": row.due_at,
        "reviewer_count": len(reviewers),
        "all_required_approved": all((not reviewer.required) or reviewer.decision == "approved" for reviewer in reviewers),
        "reviewers": [{"reviewer_id": reviewer.reviewer_user_id, "reviewer_name": reviewer.reviewer_name or (f"{users[reviewer.reviewer_user_id].first_name} {users[reviewer.reviewer_user_id].last_name}".strip() if reviewer.reviewer_user_id in users else None), "reviewer_email": reviewer.reviewer_email or (users[reviewer.reviewer_user_id].email if reviewer.reviewer_user_id in users else None), "decision": reviewer.decision, "decision_at": reviewer.decision_at, "required": reviewer.required} for reviewer in reviewers],
        "work_items": [{"id": item.id, "delivery_state": item.delivery_state, "access_state": item.access_state, "activity_state": item.activity_state, "deadline_state": item.deadline_state, "outcome": item.outcome} for item in items],
        "deliveries": [{"channel": delivery.channel, "status": delivery.status, "attempt_count": delivery.attempt_count, "error_category": delivery.error_category} for delivery in deliveries],
        "progress": [{"attempt_id": attempt.id, "reviewer_user_id": attempt.reviewer_user_id, "activity_state": attempt.activity_state, "lesson_position": attempt.lesson_position, "last_activity_at": attempt.last_activity_at, "diagnostics": attempt.diagnostics} for attempt in attempts],
    }


async def _scoped_request_projection(db: AsyncSession, *, principal, request_id: UUID | None = None) -> dict:
    """Return only the request bound to a validated review capability."""
    work_item = await db.scalar(select(WorkflowWorkItem).where(
        WorkflowWorkItem.id == principal.review_work_item_id,
        WorkflowWorkItem.tenant_id == principal.tenant_id,
        WorkflowWorkItem.review_revision_id == principal.review_revision_id,
    ))
    if work_item is None:
        raise HTTPException(status_code=404, detail="Review request not found")
    row = await db.scalar(select(CourseApprovalRequest).where(
        CourseApprovalRequest.revision_id == work_item.review_revision_id,
        CourseApprovalRequest.tenant_id == principal.tenant_id,
        *([CourseApprovalRequest.id == request_id] if request_id is not None else []),
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Review request not found")
    reviewer_filter = CourseApprovalReviewer.reviewer_email == getattr(principal, "reviewer_email", None) if getattr(principal, "reviewer_email", None) else CourseApprovalReviewer.reviewer_user_id == principal.id
    reviewer = await db.scalar(select(CourseApprovalReviewer).where(
        CourseApprovalReviewer.revision_id == row.revision_id,
        CourseApprovalReviewer.tenant_id == principal.tenant_id,
        reviewer_filter,
    ))
    attempt = await db.scalar(select(CourseReviewAttempt).where(
        CourseReviewAttempt.revision_id == row.revision_id,
        CourseReviewAttempt.tenant_id == principal.tenant_id,
        CourseReviewAttempt.reviewer_user_id == principal.id,
    ))
    if reviewer is None:
        raise HTTPException(status_code=404, detail="Review request not found")
    identity = reviewer.reviewer_user_id
    if identity is not None and getattr(principal, "role", None) == "methodologist":
        user = await db.scalar(select(User).where(User.id == identity, User.tenant_id == principal.tenant_id))
        reviewer_name = reviewer.reviewer_name or (f"{user.first_name} {user.last_name}".strip() if user else None)
        reviewer_email = reviewer.reviewer_email or (user.email if user else None)
    else:
        reviewer_name = reviewer.reviewer_name
        reviewer_email = reviewer.reviewer_email
    diagnostics = attempt.diagnostics if attempt is not None else {}
    progress = {"attempt_id": attempt.id, "activity_state": attempt.activity_state, "lesson_position": attempt.lesson_position, "last_activity_at": attempt.last_activity_at} if attempt is not None else {}
    required = (await db.scalar(select(CourseApprovalReviewer.id).where(CourseApprovalReviewer.revision_id == row.revision_id, CourseApprovalReviewer.tenant_id == principal.tenant_id, CourseApprovalReviewer.required.is_(True), CourseApprovalReviewer.decision != "approved").limit(1))) is None
    return {
        "request_id": row.id,
        "revision_id": row.revision_id,
        "outcome": row.outcome,
        "delivery_mode": row.delivery_mode,
        "due_at": row.due_at,
        "reviewer": ReviewerStatusResponse(
            reviewer_id=identity if getattr(principal, "role", None) == "methodologist" else None,
            reviewer_name=reviewer_name,
            reviewer_email=reviewer_email,
            decision=reviewer.decision,
            decision_at=reviewer.decision_at,
            required=reviewer.required,
            delivery_state=work_item.delivery_state,
            access_state=work_item.access_state,
            activity_state=work_item.activity_state,
            deadline_state=work_item.deadline_state,
            outcome=work_item.outcome,
            progress=progress,
            diagnostics=diagnostics,
        ),
        "all_required_approved": required,
    }


class _ReviewPrincipal:
    __slots__ = ("_user", "review_work_item_id", "review_revision_id")

    def __init__(self, user: User, *, work_item_id: UUID, revision_id: UUID):
        self._user = user
        self.review_work_item_id = work_item_id
        self.review_revision_id = revision_id

    def __getattr__(self, name):
        return getattr(self._user, name)


class _GuestReviewPrincipal:
    __slots__ = ("id", "tenant_id", "role", "email", "reviewer_email", "review_work_item_id", "review_revision_id")

    def __init__(self, identity_id: UUID, tenant_id: UUID, email: str, *, work_item_id: UUID, revision_id: UUID):
        self.id = identity_id
        self.tenant_id = tenant_id
        self.role = "guest_reviewer"
        self.email = email
        self.reviewer_email = email
        self.review_work_item_id = work_item_id
        self.review_revision_id = revision_id


async def require_review_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(review_bearer),
    db: AsyncSession = Depends(get_db),
):
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access required")
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "course_review":
        # Signed-in users still need the reviewer-capable role; assignment is
        # checked at the route/service seam before any attempt is created.
        user = await get_current_user(credentials=credentials, db=db)
        if user.role != "methodologist":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer role required")
        return user
    tenant_id = payload.get("tenant_id")
    work_item_id = payload.get("review_work_item_id")
    reviewer_user_id = payload.get("reviewer_user_id")
    reviewer_email = payload.get("reviewer_email")
    if not tenant_id or not work_item_id or not reviewer_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid review access")
    try:
        tenant_uuid = UUID(tenant_id)
        work_item_uuid = UUID(work_item_id)
        reviewer_uuid = UUID(reviewer_user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid review access") from None
    await _set_tenant_security_context(db, str(tenant_uuid))
    work_item = await db.scalar(select(WorkflowWorkItem).where(
        WorkflowWorkItem.id == work_item_uuid,
        WorkflowWorkItem.tenant_id == tenant_uuid,
        WorkflowWorkItem.review_revision_id.is_not(None),
    ))
    credential = await db.scalar(select(WorkflowAccessCredential).where(
        WorkflowAccessCredential.work_item_id == work_item_uuid,
        WorkflowAccessCredential.reviewer_user_id == reviewer_uuid,
        WorkflowAccessCredential.tenant_id == tenant_uuid,
        WorkflowAccessCredential.revoked_at.is_(None),
        WorkflowAccessCredential.expires_at > datetime.now(UTC),
        WorkflowAccessCredential.verified_at.is_not(None),
    ))
    if work_item is None or credential is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    if credential.reviewer_email != reviewer_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    user = await db.scalar(select(User).where(User.id == reviewer_uuid, User.tenant_id == tenant_uuid, User.is_active.is_(True), User.status == "active"))
    if user is None and not reviewer_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    if user is not None and user.role != "methodologist":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer role required")
    if user is not None and work_item.target_user_id != reviewer_uuid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    if user is None and work_item.target_user_id is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    assignment = await db.scalar(select(CourseApprovalReviewer).where(
        CourseApprovalReviewer.revision_id == work_item.review_revision_id,
        (CourseApprovalReviewer.reviewer_user_id == reviewer_uuid) if user is not None else (CourseApprovalReviewer.reviewer_email == reviewer_email),
        CourseApprovalReviewer.tenant_id == tenant_uuid,
    ))
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    policy = await db.scalar(select(CourseApprovalPolicy).join(
        CourseApprovalRevision, CourseApprovalRevision.course_id == CourseApprovalPolicy.course_id
    ).where(
        CourseApprovalRevision.id == work_item.review_revision_id,
        CourseApprovalPolicy.tenant_id == tenant_uuid,
        CourseApprovalPolicy.review_enabled.is_(True),
    ))
    if policy is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Course review access disabled")
    # The assignment is checked again by each attempt/decision service; this
    # dependency authenticates the capability and preserves its exact scope.
    if user is None:
        return _GuestReviewPrincipal(reviewer_uuid, tenant_uuid, str(reviewer_email), work_item_id=work_item_uuid, revision_id=work_item.review_revision_id)
    return _ReviewPrincipal(user, work_item_id=work_item_uuid, revision_id=work_item.review_revision_id)


@router.patch("/courses/{course_id}/approval-policy", response_model=ApprovalPolicyResponse, dependencies=workflow_write)
async def configure_policy(course_id: UUID, req: ApprovalPolicyRequest, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.CONFIGURE)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"course_id": str(course_id), "requires_approval": req.requires_approval, "review_enabled": req.review_enabled})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.configure", fingerprint=fingerprint)
    if replay is not None:
        return replay
    policy = await set_policy(db, course_id=course_id, tenant_id=user.tenant_id, requires_approval=req.requires_approval, review_enabled=req.review_enabled, actor_id=user.id)
    # Server defaults/on-update values may be expired after the service flush;
    # refresh them before synchronous response-model construction so async
    # SQLAlchemy never attempts implicit IO (MissingGreenlet).
    await db.refresh(policy, attribute_names=["requires_approval", "review_enabled", "updated_at"])
    response = ApprovalPolicyResponse(course_id=course_id, requires_approval=policy.requires_approval, review_enabled=policy.review_enabled, updated_at=policy.updated_at)
    await db.commit()
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.configure", fingerprint=fingerprint, response=response.model_dump(mode="json"))
    return response


@router.post("/courses/{course_id}/approval-revisions", response_model=ApprovalRevisionResponse, dependencies=workflow_write)
async def create_revision(course_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"course_id": str(course_id)})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.revision", fingerprint=fingerprint)
    if replay is not None:
        return replay
    revision = await freeze_revision(db, course_id=course_id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.refresh(revision)
    response = {"id": revision.id, "course_id": revision.course_id, "revision_number": revision.revision_number, "snapshot_sha256": revision.snapshot_sha256, "state": revision.state, "created_at": revision.created_at}
    await db.commit()
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.revision", fingerprint=fingerprint, response={**response, "id": str(response["id"]), "course_id": str(response["course_id"]), "created_at": response["created_at"].isoformat() if response["created_at"] else None})
    return response


@router.get("/courses/{course_id}/approval-revisions", response_model=list[ApprovalRevisionResponse], dependencies=tenant)
async def list_revisions(course_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    rows = await db.scalars(select(CourseApprovalRevision).where(CourseApprovalRevision.course_id == course_id, CourseApprovalRevision.tenant_id == user.tenant_id).order_by(CourseApprovalRevision.revision_number.desc()))
    return list(rows.all())


@router.post("/course-approval-revisions/{revision_id}/requests", response_model=ApprovalRequestResponse, dependencies=workflow_write)
async def request_review(revision_id: UUID, req: ApprovalRequestCreate, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == revision_id, CourseApprovalRevision.tenant_id == user.tenant_id))
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    idem = None
    if idempotency_key:
        fingerprint = canonical_json_sha256({"revision_id": str(revision_id), **req.model_dump(mode="json")})
        idem = await db.scalar(select(WorkflowIdempotencyKey).where(WorkflowIdempotencyKey.tenant_id == user.tenant_id, WorkflowIdempotencyKey.key == idempotency_key, WorkflowIdempotencyKey.operation == "course_approval.request"))
        if idem is not None:
            if idem.request_fingerprint != fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            if idem.response.get("credentials_issued"):
                raise HTTPException(status_code=409, detail="credentials_already_issued")
            return idem.response
    approval_request, _work_item, access_url, pin, access_credentials = await create_request(db, revision=revision, tenant_id=user.tenant_id, actor_id=user.id, reviewer_ids=req.reviewer_user_ids, guest_reviewers=[item.model_dump() for item in req.guest_reviewers], delivery_mode=req.delivery_mode, due_at=req.due_at, base_url=str(request.base_url).rstrip("/"))
    await db.commit()
    response = ApprovalRequestResponse(request_id=approval_request.id, revision_id=revision.id, reviewer_ids=req.reviewer_user_ids, outcome=revision.state, delivery_mode=req.delivery_mode, access_url=access_url, temporary_pin=pin, access_credentials=access_credentials)
    if idempotency_key:
        # The request commit above clears the transaction-local tenant RLS
        # setting; restore it before inserting the replay record.
        await _set_tenant_security_context(db, str(user.tenant_id))
        try:
            async with db.begin_nested():
                persisted = _redact_issued_credentials(response)
                db.add(WorkflowIdempotencyKey(tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.request", request_fingerprint=fingerprint, response=persisted))
                await db.flush()
        except IntegrityError:
            existing = await db.scalar(select(WorkflowIdempotencyKey).where(
                WorkflowIdempotencyKey.tenant_id == user.tenant_id,
                WorkflowIdempotencyKey.key == idempotency_key,
                WorkflowIdempotencyKey.operation == "course_approval.request",
            ))
            if existing is None or existing.request_fingerprint != fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict") from None
            if existing.response.get("credentials_issued"):
                raise HTTPException(status_code=409, detail="credentials_already_issued") from None
            return existing.response
        await db.commit()
    return response


@router.get("/course-approval-requests", dependencies=tenant)
async def list_requests(db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    rows = await db.scalars(select(CourseApprovalRequest).where(CourseApprovalRequest.tenant_id == user.tenant_id).order_by(CourseApprovalRequest.created_at.desc()))
    return [await _request_projection(db, row, user.tenant_id) for row in rows.all()]


@router.get("/course-review-requests", response_model=ScopedReviewRequestResponse)
async def list_scoped_requests(db: AsyncSession = Depends(get_db), user=Depends(require_review_principal)):
    return await _scoped_request_projection(db, principal=user)


@router.get("/course-review-requests/{request_id}", response_model=ScopedReviewRequestResponse)
async def get_scoped_request(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal)):
    return await _scoped_request_projection(db, principal=user, request_id=request_id)


@router.get("/course-approval-requests/{request_id}", dependencies=tenant)
async def get_request(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == user.tenant_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return await _request_projection(db, row, user.tenant_id)


@router.post("/course-approval-requests/{request_id}/cancel", dependencies=workflow_write)
async def cancel(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"request_id": str(request_id)})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.cancel", fingerprint=fingerprint)
    if replay is not None:
        return replay
    row = await cancel_request(db, request_id=request_id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.commit()
    response = {"request_id": row.id, "outcome": row.outcome}
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.cancel", fingerprint=fingerprint, response={"request_id": str(row.id), "outcome": row.outcome})
    return response


@router.post("/course-approval-requests/{request_id}/revoke", dependencies=workflow_write)
async def revoke(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"request_id": str(request_id)})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.revoke", fingerprint=fingerprint)
    if replay is not None:
        return replay
    item = await revoke_request_access(db, request_id=request_id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.commit()
    response = {"request_id": request_id, "access_state": item.access_state}
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.revoke", fingerprint=fingerprint, response={"request_id": str(request_id), "access_state": item.access_state})
    return response


@router.post("/course-approval-requests/{request_id}/resend", dependencies=workflow_write)
async def resend(request_id: UUID, request: Request, req: ResendAccessRequest | None = Body(default=None), db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    req = req or ResendAccessRequest()
    fingerprint = canonical_json_sha256({"request_id": str(request_id), **req.model_dump(mode="json")})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.resend", fingerprint=fingerprint)
    if replay is not None:
        if replay.get("rotated"):
            raise HTTPException(status_code=409, detail="credentials_already_rotated")
        return replay
    result = await resend_request_access(db, request_id=request_id, tenant_id=user.tenant_id, actor_id=user.id, base_url=str(request.base_url).rstrip("/"), rotate_credentials=req.rotate_credentials)
    await db.commit()
    response = {"request_id": request_id, **result}
    persisted = {"request_id": str(request_id), "rotated": result["rotated"], "retried": result["retried"], "access_credentials": []}
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_approval.resend", fingerprint=fingerprint, response=persisted)
    return response


@router.post("/course-approval-requests/{request_id}/attempts", dependencies=review_workflow_write)
async def start_attempt(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal)):
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == user.tenant_id))
    if request_row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    scoped_revision = getattr(user, "review_revision_id", None)
    if scoped_revision is not None and scoped_revision != request_row.revision_id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    reviewer_filter = CourseApprovalReviewer.reviewer_email == getattr(user, "reviewer_email", None) if getattr(user, "reviewer_email", None) else CourseApprovalReviewer.reviewer_user_id == user.id
    assignment = await db.scalar(select(CourseApprovalReviewer).where(
        CourseApprovalReviewer.revision_id == request_row.revision_id,
        CourseApprovalReviewer.tenant_id == user.tenant_id,
        reviewer_filter,
    ))
    if assignment is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    attempt, revision = await get_or_create_attempt(db, revision_id=request_row.revision_id, reviewer_user_id=user.id, reviewer_email=getattr(user, "reviewer_email", None), tenant_id=user.tenant_id)
    await log_action(db, user.tenant_id, "course_approval.attempt_started", "course_review_attempt", attempt.id, user.id, {"revision_id": str(revision.id), "snapshot_sha256": attempt.snapshot_sha256, "active_role": getattr(user, "role", None)})
    await db.commit()
    return {"attempt_id": attempt.id, "revision_id": revision.id, "snapshot_sha256": attempt.snapshot_sha256, "activity_state": attempt.activity_state, "snapshot": learner_safe_review_snapshot(revision.snapshot)}


@router.put("/course-review-attempts/{attempt_id}/progress", dependencies=review_workflow_write)
async def save_progress(attempt_id: UUID, req: ReviewProgressRequest, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"attempt_id": str(attempt_id), **req.model_dump(mode="json")})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_review.progress", fingerprint=fingerprint)
    if replay is not None:
        return replay
    attempt = await db.scalar(select(CourseReviewAttempt).where(CourseReviewAttempt.id == attempt_id, CourseReviewAttempt.tenant_id == user.tenant_id, CourseReviewAttempt.reviewer_user_id == user.id).with_for_update())
    if attempt is None:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    scoped_revision = getattr(user, "review_revision_id", None)
    if scoped_revision is not None and scoped_revision != attempt.revision_id:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == attempt.revision_id, CourseApprovalRevision.tenant_id == user.tenant_id))
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    await record_progress(db, attempt=attempt, revision=revision, tenant_id=user.tenant_id, sequence=req.sequence, event_type=req.event_type, payload=req.payload, lesson_position=req.lesson_position, activity_state=req.activity_state)
    await log_action(db, user.tenant_id, "course_approval.progress_recorded", "course_review_attempt", attempt.id, user.id, {"revision_id": str(revision.id), "sequence": req.sequence, "event_type": req.event_type, "activity_state": attempt.activity_state, "active_role": getattr(user, "role", None)})
    await db.commit()
    response = {"attempt_id": attempt.id, "activity_state": attempt.activity_state, "lesson_position": attempt.lesson_position}
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_review.progress", fingerprint=fingerprint, response={"attempt_id": str(attempt.id), "activity_state": attempt.activity_state, "lesson_position": attempt.lesson_position})
    return response


@router.post("/course-review-attempts/{attempt_id}/test", dependencies=review_workflow_write)
async def submit_test(attempt_id: UUID, req: list[ReviewTestSubmission], db: AsyncSession = Depends(get_db), user=Depends(require_review_principal), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"attempt_id": str(attempt_id), "submissions": [item.model_dump(mode="json") for item in req]})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_review.test", fingerprint=fingerprint)
    if replay is not None:
        return replay
    attempt = await db.scalar(select(CourseReviewAttempt).where(
        CourseReviewAttempt.id == attempt_id,
        CourseReviewAttempt.tenant_id == user.tenant_id,
        CourseReviewAttempt.reviewer_user_id == user.id,
    ).with_for_update())
    if attempt is None:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    revision = await db.scalar(select(CourseApprovalRevision).where(
        CourseApprovalRevision.id == attempt.revision_id,
        CourseApprovalRevision.tenant_id == user.tenant_id,
    ).with_for_update())
    if revision is None or revision.state not in {"pending", "changes_requested"}:
        raise HTTPException(status_code=409, detail="Review revision is no longer active")
    diagnostics = score_review_submission(revision.snapshot, [item.model_dump(mode="json") for item in req])
    attempt.diagnostics = diagnostics
    if diagnostics["complete"]:
        attempt.activity_state = "decision_pending"
        attempt.completed_at = datetime.now(UTC)
    attempt.last_activity_at = datetime.now(UTC)
    work_item = await db.scalar(select(WorkflowWorkItem).outerjoin(
        WorkflowAccessCredential,
        (WorkflowAccessCredential.work_item_id == WorkflowWorkItem.id) & (WorkflowAccessCredential.tenant_id == user.tenant_id),
    ).where(
        WorkflowWorkItem.review_revision_id == attempt.revision_id,
        WorkflowWorkItem.tenant_id == user.tenant_id,
        or_(WorkflowWorkItem.target_user_id == attempt.reviewer_user_id, WorkflowAccessCredential.reviewer_user_id == attempt.reviewer_user_id),
    ).with_for_update(of=WorkflowWorkItem))
    if work_item is not None:
        work_item.activity_state = "decision_pending" if diagnostics["complete"] else "in_progress"
        work_item.deadline_state = "closed" if diagnostics["complete"] else ("due" if work_item.deadline_state in {"scheduled", "due", "overdue"} else work_item.deadline_state)
    await log_action(db, user.tenant_id, "course_approval.test_submitted", "course_review_attempt", attempt.id, user.id, {"revision_id": str(revision.id), "answered": diagnostics["answered"], "total": diagnostics["total"], "correct": diagnostics["correct"], "complete": diagnostics["complete"], "active_role": getattr(user, "role", None)})
    await db.commit()
    response = {"attempt_id": attempt.id, "diagnostics": diagnostics, "activity_state": attempt.activity_state}
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_review.test", fingerprint=fingerprint, response={"attempt_id": str(attempt.id), "diagnostics": diagnostics, "activity_state": attempt.activity_state})
    return response


@router.post("/course-review-attempts/{attempt_id}/decision", dependencies=review_workflow_write)
async def submit_decision(attempt_id: UUID, req: ReviewDecisionRequest, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    fingerprint = canonical_json_sha256({"attempt_id": str(attempt_id), **req.model_dump(mode="json")})
    replay = await _read_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_review.decision", fingerprint=fingerprint)
    if replay is not None:
        return replay
    attempt = await db.scalar(select(CourseReviewAttempt).where(CourseReviewAttempt.id == attempt_id, CourseReviewAttempt.tenant_id == user.tenant_id, CourseReviewAttempt.reviewer_user_id == user.id))
    if attempt is None:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    scoped_revision = getattr(user, "review_revision_id", None)
    if scoped_revision is not None and scoped_revision != attempt.revision_id:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == attempt.revision_id, CourseApprovalRevision.tenant_id == user.tenant_id))
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    reviewer_filter = CourseApprovalReviewer.reviewer_email == getattr(user, "reviewer_email", None) if getattr(user, "reviewer_email", None) else CourseApprovalReviewer.reviewer_user_id == user.id
    assignment = await db.scalar(select(CourseApprovalReviewer).where(CourseApprovalReviewer.revision_id == revision.id, reviewer_filter, CourseApprovalReviewer.tenant_id == user.tenant_id))
    if revision is None or assignment is None:
        raise HTTPException(status_code=404, detail="Reviewer assignment not found")
    result = await decide(db, attempt=attempt, revision=revision, reviewer=assignment, tenant_id=user.tenant_id, actor_id=user.id, decision=req.decision, reason=req.reason, warning_acknowledged=req.acknowledge_incomplete_warning)
    await log_action(db, user.tenant_id, "course_approval.decision_submitted", "course_review_attempt", attempt.id, user.id, {"revision_id": str(revision.id), "decision": result.decision, "active_role": getattr(user, "role", None)})
    await db.commit()
    response = {"revision_id": revision.id, "decision": result.decision, "outcome": revision.state, "activity_state": attempt.activity_state}
    await _write_idempotency(db, tenant_id=user.tenant_id, key=idempotency_key, operation="course_review.decision", fingerprint=fingerprint, response={"revision_id": str(revision.id), "decision": result.decision, "outcome": revision.state, "activity_state": attempt.activity_state})
    return response


@router.post("/course-review-access/{token}/verify-pin")
async def verify_pin(token: str, payload: ReviewPinRequest = Body(...), db: AsyncSession = Depends(get_db)):
    from .service import verify_access_pin
    return await verify_access_pin(db, token, payload.pin)
