"""Demo sandbox usage endpoint — returns current counts + limits for the banner UI."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.core.demo_limits import get_demo_usage
from app.models.users import User

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/usage")
async def get_usage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist", "student")),
):
    """Return current usage counters for the demo sandbox tenant.

    Returns an empty object if the tenant is not in demo mode so the
    frontend can render the banner conditionally without a separate
    is_demo check.
    """
    return await get_demo_usage(db, user.tenant_id)