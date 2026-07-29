"""Onboarding status router — GET /api/v1/admin/onboarding-status.

P0.6 first-tenant hardening.

Returns the role-specific onboarding status for the current tenant. Frontend
uses it to render the "Подготовить компанию" widget on the admin
dashboard.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.modules.admin.onboarding.schemas import OnboardingStatus
from app.modules.admin.onboarding.service import compute_onboarding_status

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/onboarding-status",
    tags=["admin"],
)

# Tenant admin and methodologist can read onboarding state for their active
# tenant. Superadmin is accepted but receives the explicit no-tenant response.
# Students are excluded.
_ONBOARDING_ROLES = ("admin", "methodologist", "superadmin")


async def _get_onboarding_user(user: User = Depends(get_current_user)) -> User:  # noqa: B008
    """Allow the read-only support surface after trial expiry."""
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not active")
    if user.role not in _ONBOARDING_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of roles: {_ONBOARDING_ROLES}",
        )
    return user


@router.get("", response_model=OnboardingStatus)
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    user: User = Depends(_get_onboarding_user),  # noqa: B008
):
    if user.tenant_id is None:
        # Superadmin without a tenant — return an empty status rather than
        # 500. We can't compute anything without a tenant scope.
        return OnboardingStatus(
            steps=[],
            completed=False,
            trial_ends_at=None,
            trial_days_remaining=None,
            plan=None,
            max_users=None,
            active_users=0,
            role="superadmin",
            trial_state="not_trial",
            trial_access_state="not_applicable",
        )
    return await compute_onboarding_status(db, user.tenant_id, user.role)
