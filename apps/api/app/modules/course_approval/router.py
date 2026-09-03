from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, decode_token, get_current_user, require_tenant_user
from app.core.db import get_db
from app.core.permissions import COURSE_APPROVAL_PERMISSIONS, require_permission
from app.models.users import User
from .models import (
    CourseApprovalRequest,
    CourseApprovalRevision,
    CourseApprovalReviewer,
    CourseReviewAttempt,
    WorkflowAccessCredential,
    WorkflowWorkItem,
)
from .schemas import (
    ApprovalPolicyRequest, ApprovalPolicyResponse, ApprovalRequestCreate, ApprovalRequestResponse,
    ApprovalRevisionResponse, ReviewDecisionRequest, ReviewProgressRequest,
    ReviewPinRequest,
)
from .service import cancel_request, create_request, decide, freeze_revision, get_or_create_attempt, record_progress, revoke_request_access, set_policy

router = APIRouter(tags=["course-approval"])
tenant = [Depends(require_tenant_user())]
review_bearer = HTTPBearer(auto_error=False)


class _ReviewPrincipal:
    __slots__ = ("_user", "review_work_item_id", "review_revision_id")

    def __init__(self, user: User, *, work_item_id: UUID, revision_id: UUID):
        self._user = user
        self.review_work_item_id = work_item_id
        self.review_revision_id = revision_id

    def __getattr__(self, name):
        return getattr(self._user, name)


async def require_review_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(review_bearer),
    db: AsyncSession = Depends(get_db),
):
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access required")
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "course_review":
        # Normal signed-in reviewers retain the ordinary access-token path.
        return await get_current_user(credentials=credentials, db=db)
    tenant_id = payload.get("tenant_id")
    work_item_id = payload.get("review_work_item_id")
    reviewer_user_id = payload.get("reviewer_user_id")
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
        WorkflowWorkItem.target_user_id == reviewer_uuid,
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
    if credential is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    user = await db.scalar(select(User).where(User.id == reviewer_uuid, User.tenant_id == tenant_uuid, User.is_active.is_(True), User.status == "active"))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    if work_item is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    assignment = await db.scalar(select(CourseApprovalReviewer).where(
        CourseApprovalReviewer.revision_id == work_item.review_revision_id,
        CourseApprovalReviewer.reviewer_user_id == reviewer_uuid,
        CourseApprovalReviewer.tenant_id == tenant_uuid,
    ))
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Review access revoked")
    # The assignment is checked again by each attempt/decision service; this
    # dependency authenticates the capability and preserves its exact scope.
    return _ReviewPrincipal(user, work_item_id=work_item_uuid, revision_id=work_item.review_revision_id)


@router.patch("/courses/{course_id}/approval-policy", response_model=ApprovalPolicyResponse, dependencies=tenant)
async def configure_policy(course_id: UUID, req: ApprovalPolicyRequest, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.CONFIGURE)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    policy = await set_policy(db, course_id=course_id, tenant_id=user.tenant_id, requires_approval=req.requires_approval, actor_id=user.id)
    await db.commit()
    return ApprovalPolicyResponse(course_id=course_id, requires_approval=policy.requires_approval, updated_at=policy.updated_at)


@router.post("/courses/{course_id}/approval-revisions", response_model=ApprovalRevisionResponse, dependencies=tenant)
async def create_revision(course_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    revision = await freeze_revision(db, course_id=course_id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.commit()
    return revision


@router.get("/courses/{course_id}/approval-revisions", response_model=list[ApprovalRevisionResponse], dependencies=tenant)
async def list_revisions(course_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    rows = await db.scalars(select(CourseApprovalRevision).where(CourseApprovalRevision.course_id == course_id, CourseApprovalRevision.tenant_id == user.tenant_id).order_by(CourseApprovalRevision.revision_number.desc()))
    return list(rows.all())


@router.post("/course-approval-revisions/{revision_id}/requests", response_model=ApprovalRequestResponse, dependencies=tenant)
async def request_review(revision_id: UUID, req: ApprovalRequestCreate, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST)), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == revision_id, CourseApprovalRevision.tenant_id == user.tenant_id))
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    approval_request, _work_item, access_url, pin, access_credentials = await create_request(db, revision=revision, tenant_id=user.tenant_id, actor_id=user.id, reviewer_ids=req.reviewer_user_ids, delivery_mode=req.delivery_mode, due_at=req.due_at, base_url=str(request.base_url).rstrip("/"))
    await db.commit()
    return ApprovalRequestResponse(request_id=approval_request.id, revision_id=revision.id, reviewer_ids=req.reviewer_user_ids, outcome=revision.state, delivery_mode=req.delivery_mode, access_url=access_url, temporary_pin=pin, access_credentials=access_credentials)


@router.get("/course-approval-requests", dependencies=tenant)
async def list_requests(db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    rows = await db.scalars(select(CourseApprovalRequest).where(CourseApprovalRequest.tenant_id == user.tenant_id).order_by(CourseApprovalRequest.created_at.desc()))
    return [{"request_id": row.id, "revision_id": row.revision_id, "outcome": row.outcome, "delivery_mode": row.delivery_mode} for row in rows.all()]


@router.get("/course-approval-requests/{request_id}", dependencies=tenant)
async def get_request(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == user.tenant_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"request_id": row.id, "revision_id": row.revision_id, "outcome": row.outcome, "delivery_mode": row.delivery_mode}


@router.post("/course-approval-requests/{request_id}/cancel", dependencies=tenant)
async def cancel(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    row = await cancel_request(db, request_id=request_id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.commit()
    return {"request_id": row.id, "outcome": row.outcome}


@router.post("/course-approval-requests/{request_id}/revoke", dependencies=tenant)
async def revoke(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_permission(COURSE_APPROVAL_PERMISSIONS.REQUEST))):
    item = await revoke_request_access(db, request_id=request_id, tenant_id=user.tenant_id, actor_id=user.id)
    await db.commit()
    return {"request_id": request_id, "access_state": item.access_state}


@router.post("/course-approval-requests/{request_id}/attempts")
async def start_attempt(request_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal)):
    request_row = await db.scalar(select(CourseApprovalRequest).where(CourseApprovalRequest.id == request_id, CourseApprovalRequest.tenant_id == user.tenant_id))
    if request_row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    scoped_revision = getattr(user, "review_revision_id", None)
    if scoped_revision is not None and scoped_revision != request_row.revision_id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    attempt, revision = await get_or_create_attempt(db, revision_id=request_row.revision_id, reviewer_user_id=user.id, tenant_id=user.tenant_id)
    await db.commit()
    return {"attempt_id": attempt.id, "revision_id": revision.id, "snapshot_sha256": attempt.snapshot_sha256, "activity_state": attempt.activity_state, "snapshot": revision.snapshot}


@router.put("/course-review-attempts/{attempt_id}/progress")
async def save_progress(attempt_id: UUID, req: ReviewProgressRequest, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal)):
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
    await db.commit()
    return {"attempt_id": attempt.id, "activity_state": attempt.activity_state, "lesson_position": attempt.lesson_position}


@router.post("/course-review-attempts/{attempt_id}/decision")
async def submit_decision(attempt_id: UUID, req: ReviewDecisionRequest, db: AsyncSession = Depends(get_db), user=Depends(require_review_principal)):
    attempt = await db.scalar(select(CourseReviewAttempt).where(CourseReviewAttempt.id == attempt_id, CourseReviewAttempt.tenant_id == user.tenant_id, CourseReviewAttempt.reviewer_user_id == user.id))
    if attempt is None:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    scoped_revision = getattr(user, "review_revision_id", None)
    if scoped_revision is not None and scoped_revision != attempt.revision_id:
        raise HTTPException(status_code=404, detail="Review attempt not found")
    revision = await db.scalar(select(CourseApprovalRevision).where(CourseApprovalRevision.id == attempt.revision_id, CourseApprovalRevision.tenant_id == user.tenant_id))
    if revision is None:
        raise HTTPException(status_code=404, detail="Review revision not found")
    assignment = await db.scalar(select(CourseApprovalReviewer).where(CourseApprovalReviewer.revision_id == revision.id, CourseApprovalReviewer.reviewer_user_id == user.id, CourseApprovalReviewer.tenant_id == user.tenant_id))
    if revision is None or assignment is None:
        raise HTTPException(status_code=404, detail="Reviewer assignment not found")
    result = await decide(db, attempt=attempt, revision=revision, reviewer=assignment, tenant_id=user.tenant_id, actor_id=user.id, decision=req.decision, reason=req.reason, warning_acknowledged=req.acknowledge_incomplete_warning)
    await db.commit()
    return {"revision_id": revision.id, "decision": result.decision, "outcome": revision.state, "activity_state": attempt.activity_state}


@router.post("/course-review-access/{token}/verify-pin")
async def verify_pin(token: str, payload: ReviewPinRequest = Body(...), db: AsyncSession = Depends(get_db)):
    from .service import verify_access_pin
    return await verify_access_pin(db, token, payload.pin)
