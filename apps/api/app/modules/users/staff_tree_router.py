"""Staff tree view endpoint — DEPRECATED alias.

ADR-0011 consolidation: the canonical endpoint is now
  GET /admin/staff/structure
in `app.modules.positions.admin_router`. This file remains as a
backward-compat shim. Will be removed in v1.1.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User

router = APIRouter(prefix="/admin/staff", tags=["staff-tree"])


@router.get("/tree")
async def get_staff_tree_legacy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "methodologist")),
):
    """DEPRECATED alias for `/admin/staff/structure` (ADR-0011).

    Re-executes the new endpoint inline rather than redirecting so
    legacy clients keep getting the legacy response shape (no
    department_slug field). Will be removed in v1.1.
    """
    from app.modules.positions.admin_router import get_staff_structure
    new_resp = await get_staff_structure(db=db, user=user)

    legacy_departments = []
    for d in new_resp.departments:
        legacy_departments.append({
            "name": d.name,
            "position_count": d.position_count,
            "employee_count": d.employee_count,
            "ready_percent": d.ready_percent,
            "positions": [
                {
                    "id": p.id,
                    "name": p.name,
                    "department": p.department,
                    "employee_count": p.employee_count,
                    "ready_percent": p.ready_percent,
                    "employees": [e.model_dump() for e in p.employees],
                }
                for p in d.positions
            ],
        })
    return {
        "departments": legacy_departments,
        "summary": new_resp.summary,
        "_deprecated": "Use /admin/staff/structure instead. Will be removed in v1.1.",
    }
