"""User management API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.modules.users.schemas import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    PasswordReset,
    InvitationBulkCreateRequest,
    InvitationBulkCreateResponse,
    InvitationListItem,
    InvitationListResponse,
    InvitationResendResponse,
)
from app.modules.users.service import (
    list_users,
    get_user,
    create_user,
    update_user,
    delete_user,
    reset_password,
    change_role,
)
from app.modules.users.invitations_service import (
    bulk_create_invitations,
    resend_invitation,
)
from app.models.users import User, UserInvitation

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_tenant_user())],
)


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get the current authenticated user's profile.

    Returns the user object derived from the JWT — does not require admin role.
    """
    # Reload from DB to get fresh data (not the JWT-cached user from get_current_user).
    fresh = await db.get(User, user.id)
    if not fresh:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(fresh)


@router.patch("/me", response_model=UserResponse)
async def update_current_user_profile(
    req: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update the current authenticated user's profile (first_name, last_name, email).

    Tenant isolation: only fields allowed for self-update are accepted.
    """
    # Whitelist: regular users can only update their own first_name, last_name, email.
    # role/is_active changes must go through admin endpoints.
    updates = req.model_dump(exclude_unset=True, exclude={"role", "is_active"})

    target = await db.get(User, user.id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    for field, value in updates.items():
        if value is not None and hasattr(target, field):
            setattr(target, field, value)

    await db.flush()
    await db.refresh(target)
    return UserResponse.model_validate(target)


@router.get("", response_model=UserListResponse)
async def list_all_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "teacher")),
):
    """List users. Admin/org_admin/superadmin for full management; teacher
    included so methodologists can pick assignees for quiz assignments
    (POST /v1/quiz-assignments already accepts teacher role). The endpoint
    still scopes by tenant_id so cross-tenant access is impossible."""
    users, total = await list_users(
        db, user.tenant_id, page, per_page, search, role, is_active
    )
    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_detail(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Get user details (admin only)."""
    target = await get_user(db, user_id, user.tenant_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(target)


@router.post("", response_model=UserResponse, status_code=201)
async def create_new_user(
    req: UserCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Create a new user (admin only)."""
    from app.core.demo_limits import assert_can_create_user
    await assert_can_create_user(db, user.tenant_id)
    try:
        new_user = await create_user(
            db=db,
            tenant_id=user.tenant_id,
            email=req.email,
            first_name=req.first_name,
            last_name=req.last_name,
            role=req.role,
            password=req.password,
            is_active=req.is_active,
        )
        return UserResponse.model_validate(new_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user_detail(
    user_id: UUID,
    req: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Update user (admin only)."""
    updates = req.model_dump(exclude_unset=True)
    updated = await update_user(db, user_id, user.tenant_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(updated)


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Deactivate user (admin only)."""
    success = await delete_user(db, user_id, user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: UUID,
    req: PasswordReset,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Reset user password (admin only)."""
    success = await reset_password(db, user_id, user.tenant_id, req.new_password)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "ok"}


@router.post("/{user_id}/role")
async def change_user_role(
    user_id: UUID,
    role: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Change user role (admin only)."""
    try:
        updated = await change_role(db, user_id, user.tenant_id, role)
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse.model_validate(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Invitations (Phase 1 of employee onboarding epic) ──────────────


@router.post("/invitations/bulk", response_model=InvitationBulkCreateResponse)
async def bulk_invite_users(
    payload: InvitationBulkCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Bulk-create user invitations (Phase 1).

    Demo tenant: invitations are disabled -- prospect shouldn't be able
    to invite fake users. The DemoLimitExceeded exception is caught
    here and surfaced as a 403.

    Body: { items: [{email}, ...] } (max 200 per request)
    Response: {created: [{email, invitation_id, invite_url, expires_at}], skipped_existing, invalid}

    Email is NOT sent — methodologist copies invite_url and sends manually
    (Slack/Telegram/corp email). See design doc for rationale.

    All invited users default to role='student' (security: bulk can't create
    privileged roles). For admin/methodologist invites, use POST /users.
    """
    from app.core.config import get_settings
    from app.core.demo_limits import assert_can_send_invite
    await assert_can_send_invite(db, user.tenant_id)
    settings = get_settings()
    base_url = getattr(settings, "PUBLIC_URL", None)

    raw_emails = [item.email for item in payload.items]
    result = await bulk_create_invitations(
        db,
        tenant_id=user.tenant_id,
        invited_by=user.id,
        raw_emails=raw_emails,
        base_url=base_url,
        default_role="student",
    )

    return InvitationBulkCreateResponse(
        created=[
            {
                "email": c["email"],
                "invitation_id": c["invitation_id"],
                "invite_url": c["invite_url"],
                "expires_at": c["expires_at"],
            }
            for c in result["created"]
        ],
        skipped_existing=[
            {"email": s["email"], "reason": s["reason"]}
            for s in result["skipped_existing"]
        ],
        invalid=[
            {"input": i["input"], "reason": i["reason"]}
            for i in result["invalid"]
        ],
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    status: str | None = Query(None, description="Filter by status: pending|accepted|expired|revoked|superseded"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """List invitations for current tenant."""
    from sqlalchemy import desc, func as sqlfunc

    query = select(UserInvitation).where(UserInvitation.tenant_id == user.tenant_id)
    count_query = select(sqlfunc.count(UserInvitation.id)).where(
        UserInvitation.tenant_id == user.tenant_id
    )

    if status:
        query = query.where(UserInvitation.status == status)
        count_query = count_query.where(UserInvitation.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(desc(UserInvitation.created_at)).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.scalars().all()

    return InvitationListResponse(
        items=[
            InvitationListItem(
                id=r.id,
                email=r.email,
                role=r.role,
                status=r.status,
                invited_by=r.invited_by,
                created_at=r.created_at,
                expires_at=r.expires_at,
                accepted_at=r.accepted_at,
                user_id=r.user_id,
            )
            for r in rows
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationResendResponse)
async def resend_user_invitation(
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Re-invite: create new row with fresh token, mark old as superseded.

    Works for both 'pending' (link still valid, just send again) and
    'expired' (link timed out). Cannot re-invite 'accepted' rows.
    """
    from app.core.config import get_settings
    settings = get_settings()
    base_url = getattr(settings, "PUBLIC_URL", None)

    result = await resend_invitation(
        db,
        tenant_id=user.tenant_id,
        invitation_id=invitation_id,
        base_url=base_url,
    )
    return result
