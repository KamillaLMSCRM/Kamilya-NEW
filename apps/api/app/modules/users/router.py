"""User management API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.modules.users.schemas import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    PasswordReset,
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
from app.models.users import User

router = APIRouter(prefix="/users", tags=["users"])


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
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """List users (admin only)."""
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
