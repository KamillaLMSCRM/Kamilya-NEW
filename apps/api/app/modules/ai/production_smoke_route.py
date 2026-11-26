"""Provider scope for the existing synthetic production smoke tenant."""

from uuid import UUID

from app.core.config import Settings

PRODUCTION_SMOKE_TENANT = UUID("83552ce6-8058-4561-abe3-cfbda14e030a")


def uses_production_smoke_route(settings: Settings, tenant_id: object | None) -> bool:
    return (
        getattr(settings, "AI_PRODUCTION_SMOKE_LUNA_ONLY", False) is True
        and settings.DEPLOYMENT_ENVIRONMENT == "kz-production"
        and str(tenant_id) == str(PRODUCTION_SMOKE_TENANT)
    )
