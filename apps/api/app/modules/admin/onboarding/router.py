"""Onboarding status router — GET /api/v1/admin/onboarding-status.

P0.6 first-tenant hardening.

Returns the 7-step onboarding status for the current tenant. Frontend
uses it to render the "Подготовить компанию" widget on the admin
dashboard.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.admin.onboarding.schemas import OnboardingStatus
from app.modules.admin.onboarding.service import compute_onboarding_status

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/onboarding-status",
    tags=["admin"],
)

# Roles: tenant admin / org_admin / methodologist own the dashboard.
# Excluded: student (irrelevant), methodologist (no admin view), superadmin
# (no tenant scope).
_ONBOARDING_ROLES = ("admin", "org_admin", "methodologist", "superadmin")


@router.get("", response_model=OnboardingStatus)
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ONBOARDING_ROLES)),
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
        )
    return await compute_onboarding_status(db, user.tenant_id)