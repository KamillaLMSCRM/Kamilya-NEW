"""Explicit contour-gated staff workspace opt-in."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings


def staff_workspace_enabled() -> bool:
    settings = get_settings()
    # APP_ENV intentionally remains production on Render DEV for secure runtime
    # behavior. DEPLOYMENT_ENVIRONMENT identifies the actual delivery contour.
    contour = settings.DEPLOYMENT_ENVIRONMENT.strip().lower()
    return settings.STAFF_STRUCTURE_V3_ENABLED and (
        contour == "render-development"
        or contour == "kz-production"
        or (contour == "local" and settings.APP_ENV.lower() in {"development", "dev", "test"})
    )


def reject_unreviewed_placement(changed: bool) -> None:
    if changed and staff_workspace_enabled():
        raise ValueError("placement_requires_reviewed_transfer")


def reject_hr_record_write(record: object) -> None:
    from .change_policy import hr_managed

    if staff_workspace_enabled() and hr_managed({"source_metadata": getattr(record, "source_metadata", None)}):
        raise ValueError("hr_managed")


async def reject_hr_employee_write(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
    if not staff_workspace_enabled():
        return
    from sqlalchemy import select

    from app.modules.staff_sync.models import StaffSyncIdentity

    if (
        await db.scalar(
            select(StaffSyncIdentity.id)
            .where(StaffSyncIdentity.tenant_id == tenant_id, StaffSyncIdentity.user_id == user_id)
            .limit(1)
        )
        is not None
    ):
        raise ValueError("hr_managed")
