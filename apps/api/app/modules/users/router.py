"""User management API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from typing import Optional

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.modules.users.schemas import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    PasswordReset,
    RoleAssignmentRequest,
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
    assign_role,
    get_role_map,
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


async def _user_response(db: AsyncSession, user: User) -> UserResponse:
    roles = (await get_role_map(db, [user], user.tenant_id)).get(user.id, [user.role])
    return UserResponse.model_validate(user).model_copy(update={"roles": roles})


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
    response = await _user_response(db, fresh)
    return response.model_copy(update={"role": user.role})


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
    return await _user_response(db, target)


@router.get("", response_model=UserListResponse)
async def list_all_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=500),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    include_students: bool = Query(
        False,
        description="Audit §2.1 / ADR-0011: by default students are excluded "
                    "because they're auto-provisioned via Telegram/kiosk, "
                    "not managed here. Pass ?include_students=true to opt-in "
                    "(learning-manager only).",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist")),
):
    """List users (the team-management surface — ADR-0011).

    Admin/org_admin/superadmin for team management; methodologist
    are included so the learning team can pick learner assignees.

    By default students (role='student') are excluded — they're auto-
    provisioned via Telegram-bot or kiosk and are not team-managed.
    Pass ?include_students=true to see them (learning-manager only).

    per_page capped at 500 — large enough for most kazakhstan legal
    entities (typically <300 employees), small enough to not blow up
    the response.
    """
    if include_students and user.role not in ("superadmin", "methodologist"):
        raise HTTPException(
            status_code=403,
            detail="include_students=true requires a learning manager role",
        )

    effective_role = role
    if not include_students and role is None:
        # Default: exclude students from the listing. Audit §2.1 /
        # ADR-0011 — the /admin/team surface is for managing methodologists,
        # org_admins, and admins only. Students have their own surface
        # at /v1/students (read-only) and are provisioned via the
        # Telegram/kiosk flows.
        effective_role = "non_student"  # sentinel — handled in service

    users, total = await list_users(
        db, user.tenant_id, page, per_page, search, effective_role, is_active
    )
    role_map = await get_role_map(db, users, user.tenant_id)
    return UserListResponse(
        users=[
            UserResponse.model_validate(item).model_copy(
                update={"roles": role_map.get(item.id, [item.role])}
            )
            for item in users
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    status: str | None = Query(None, description="Filter by status: pending|accepted|expired|revoked|superseded"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    """List invitations for current tenant.

    This static route must remain above ``/{user_id}``: Starlette resolves
    routes in registration order, and otherwise "invitations" is treated as a
    user id before UUID validation or this learning-role dependency can run.
    """
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
                id=row.id,
                email=row.email,
                role=row.role,
                status=row.status,
                invited_by=row.invited_by,
                created_at=row.created_at,
                expires_at=row.expires_at,
                accepted_at=row.accepted_at,
                user_id=row.user_id,
            )
            for row in rows
        ],
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
    return await _user_response(db, target)


@router.post("", response_model=UserResponse, status_code=201)
async def create_new_user(
    req: UserCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Create a new team user (admin only).

    ADR-0011: only team-managed roles can be created via this endpoint.
    Students (role='student') must be provisioned via the Telegram-bot
    flow, kiosk, or staff import — see /admin/staff. Attempting to
    create a student here returns 400.
    """
    from app.core.demo_limits import assert_can_create_user
    from app.core.trial_limits import assert_can_create_system_users
    from app.modules.users.service import TEAM_ROLES

    if req.role not in TEAM_ROLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"role='{req.role}' cannot be created via this endpoint. "
                f"Students are provisioned via Telegram-bot or kiosk. "
                f"Allowed roles: {', '.join(TEAM_ROLES)}"
            ),
        )

    normalized_email = req.email.strip().lower()
    existing = (
        await db.execute(
            select(User).where(
                User.tenant_id == user.tenant_id,
                func.lower(User.email) == normalized_email,
            )
        )
    ).scalar_one_or_none()
    if existing:
        try:
            await assign_role(db, existing.id, user.tenant_id, req.role)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return await _user_response(db, existing)

    if not req.first_name or not req.first_name.strip():
        raise HTTPException(status_code=422, detail="First name is required for a new account")
    if not req.last_name or not req.last_name.strip():
        raise HTTPException(status_code=422, detail="Last name is required for a new account")
    if not req.password:
        raise HTTPException(status_code=422, detail="Password is required for a new account")

    await assert_can_create_user(db, user.tenant_id)
    await assert_can_create_system_users(db, user.tenant_id)
    try:
        new_user = await create_user(
            db=db,
            tenant_id=user.tenant_id,
            email=normalized_email,
            first_name=req.first_name.strip(),
            last_name=req.last_name.strip(),
            role=req.role,
            password=req.password,
            is_active=req.is_active,
        )
        return await _user_response(db, new_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user_detail(
    user_id: UUID,
    req: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Update user profile/status fields (admin only).

    Role changes are intentionally excluded here. Use
    POST /users/{id}/role so ADR-0011 team-role boundaries are enforced
    in one place.
    """
    updates = req.model_dump(exclude_unset=True, exclude={"role"})
    updated = await update_user(db, user_id, user.tenant_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return await _user_response(db, updated)


@router.post("/{user_id}/roles", response_model=UserResponse)
async def add_user_role(
    user_id: UUID,
    req: RoleAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Assign an additional team role without creating another account."""
    from app.modules.users.service import TEAM_ROLES

    if req.role not in TEAM_ROLES:
        raise HTTPException(status_code=400, detail="Role is not managed on the tenant team surface")
    try:
        target = await assign_role(db, user_id, user.tenant_id, req.role)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return await _user_response(db, target)


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
    """Change user role (admin only).

    ADR-0011: only team-managed roles are accepted. Demoting/promoting
    to 'student' must go through the regular student-provisioning flow.
    """
    from app.modules.users.service import TEAM_ROLES

    if role not in TEAM_ROLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"role='{role}' is not a team-managed role. "
                f"Allowed roles: {', '.join(TEAM_ROLES)}"
            ),
        )
    try:
        updated = await change_role(db, user_id, user.tenant_id, role)
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return await _user_response(db, updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Invitations (Phase 1 of employee onboarding epic) ──────────────


@router.post("/invitations/bulk", response_model=InvitationBulkCreateResponse)
async def bulk_invite_users(
    payload: InvitationBulkCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
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
    from app.core.trial_limits import assert_can_create_learners
    await assert_can_send_invite(db, user.tenant_id)
    await assert_can_create_learners(db, user.tenant_id, requested=len(payload.items))
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


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationResendResponse)
async def resend_user_invitation(
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
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
