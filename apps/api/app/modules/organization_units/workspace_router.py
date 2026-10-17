"""DEV workspace transport; serializable mutation begins before its first query."""

from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal, Never, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, _set_user_security_context, require_role
from app.core.db import async_session_factory, engine, get_db
from app.models.users import User

from .change_service import confirm_change, preview_change
from .workspace_config import staff_workspace_enabled
from .workspace_read import employee_roster, workspace_overview

router = APIRouter()
Methodologist = Annotated[User, Depends(require_role("methodologist"))]
Db = Annotated[AsyncSession, Depends(get_db)]
type JSONObject = dict[str, Any]


def enabled() -> None:
    if not staff_workspace_enabled():
        raise HTTPException(503, "staff_workspace_disabled")


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["employee", "unit"]
    target_id: UUID
    organization_unit_id: UUID | None
    position_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.kind == "employee") != (self.position_id is not None):
            raise ValueError("position_required_only_for_employee")
        if len(self.reason.strip()) < 3:
            raise ValueError("reason_required")
        return self


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


def is_change_conflict(exc: DBAPIError) -> bool:
    """Map known retryable races only; unrelated integrity failures stay errors."""
    original = exc.orig
    if getattr(original, "sqlstate", None) in {"40001", "40P01"}:
        return True
    cause = getattr(original, "__cause__", None)
    constraint = getattr(original, "constraint_name", None) or getattr(cause, "constraint_name", None)
    return getattr(original, "sqlstate", None) == "23505" and constraint == "uq_enrollments_current_occurrence"


async def change_db(user: Methodologist) -> AsyncGenerator[AsyncSession]:
    enabled()
    tenant_id = str(user.tenant_id)
    actor_id = cast(UUID, user.id)
    async with async_session_factory(bind=engine.execution_options(isolation_level="SERIALIZABLE")) as db:
        try:
            await _set_tenant_security_context(db, tenant_id)
            await _set_user_security_context(db, actor_id)
            yield db
            await db.commit()
        except DBAPIError as exc:
            await db.rollback()
            if is_change_conflict(exc):
                raise HTTPException(409, "serialization_conflict") from None
            raise
        except Exception:
            await db.rollback()
            raise


def transport_error(exc: Exception) -> Never:
    code = str(exc)
    invalid = {
        "student_only",
        "hierarchy_cycle",
        "maximum_depth_exceeded",
        "head_office_must_be_root",
        "duplicate_sibling",
        "inactive_target",
        "inactive_position",
    }
    conflicts = {"preview_stale", "preview_expired", "hr_managed", "course_release_missing", "preview_limit"}
    status = 404 if isinstance(exc, LookupError) else 422 if code in invalid else 409 if code in conflicts else 503
    safe_code = (
        code
        if code in invalid | conflicts | {"resource_not_found", "plan_not_found", "impact_snapshot_too_large"}
        else "change_impact_unavailable"
    )
    raise HTTPException(status, safe_code) from exc


@router.get("/workspace")
async def overview(db: Db, user: Methodologist, access: Literal["all", "active", "inactive"] = "active") -> JSONObject:
    enabled()
    return await workspace_overview(db, cast(UUID, user.tenant_id), access)


@router.get("/employees")
async def employees(
    db: Db,
    user: Methodologist,
    unit_id: UUID | None = None,
    unplaced: bool = False,
    scope: Literal["direct", "subtree"] = "subtree",
    access: Literal["all", "active", "inactive"] = "active",
    q: str = Query("", max_length=100),
    position_id: UUID | None = None,
    missing_position: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> JSONObject:
    enabled()
    if (unit_id and unplaced) or (position_id and missing_position):
        raise HTTPException(422, "conflicting_filters")
    try:
        return await employee_roster(
            db,
            cast(UUID, user.tenant_id),
            unit_id=unit_id,
            unplaced=unplaced,
            scope=scope,
            access=access,
            q=q,
            position_id=position_id,
            missing_position=missing_position,
            page=page,
            page_size=page_size,
        )
    except (LookupError, ValueError) as exc:
        transport_error(exc)


@router.post("/changes/preview")
async def preview(
    body: ChangeRequest, user: Methodologist, db: Annotated[AsyncSession, Depends(change_db)]
) -> JSONObject:
    try:
        result = await preview_change(
            db, tenant_id=cast(UUID, user.tenant_id), actor_id=cast(UUID, user.id), command=body.model_dump(mode="json")
        )
        await db.commit()
        return result
    except (LookupError, ValueError) as exc:
        transport_error(exc)


@router.post("/changes/{plan_id}/confirm")
async def confirm(
    plan_id: UUID, body: ConfirmRequest, user: Methodologist, db: Annotated[AsyncSession, Depends(change_db)]
) -> JSONObject:
    try:
        result = await confirm_change(
            db, tenant_id=cast(UUID, user.tenant_id), actor_id=cast(UUID, user.id), plan_id=plan_id
        )
        await db.commit()
        return result
    except (LookupError, ValueError) as exc:
        transport_error(exc)
