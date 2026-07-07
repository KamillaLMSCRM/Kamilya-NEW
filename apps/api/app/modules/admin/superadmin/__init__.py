"""Superadmin-only management endpoints.

Cross-tenant operations: list/edit tenants, manage per-tenant admins,
assign subscriptions. All endpoints require role=superadmin.

NOT covered (out of scope for v1):
- Real billing integration (Stripe, etc.) — the `plan`, `paid_until`,
  and `max_*` fields are informational and edited manually here.
- Per-tenant SSO config — separate epic.
- Audit log UI for superadmin actions — uses existing /audit endpoint,
  filtered by action prefix `superadmin.*`.
"""

from app.modules.admin.superadmin.schemas import (
    AdminCreate,
    AdminResponse,
    AdminUpdate,
    SubscriptionInfo,
    TenantCreate,
    TenantCreateResponse,
    TenantListResponse,
    TenantResponse,
    TenantStats,
    TenantUpdate,
)
from app.modules.admin.superadmin.service import SuperadminService

__all__ = [
    "AdminCreate",
    "AdminResponse",
    "AdminUpdate",
    "SubscriptionInfo",
    "SuperadminService",
    "TenantCreate",
    "TenantCreateResponse",
    "TenantListResponse",
    "TenantResponse",
    "TenantStats",
    "TenantUpdate",
]
