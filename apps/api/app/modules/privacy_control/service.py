"""Application seam for privacy decisions and append-only processing records."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import log_action
from app.modules.privacy_control.policy import (
    DisclosureOutcome,
    ProcessingDecision,
    ProcessingRequest,
    evaluate_processing,
)


class ProcessingDeniedError(PermissionError):
    """Raised when a caller reaches a processing seam outside its policy."""

    def __init__(self, decision: ProcessingDecision):
        super().__init__(f"privacy_processing_denied:{decision.reason_code}")
        self.operation = decision.operation
        self.reason_code = decision.reason_code


async def record_processing(
    db: AsyncSession,
    *,
    tenant_id: UUID | Column[UUID],
    actor_id: UUID | Column[UUID],
    actor_role: str | Column[str],
    operation: str,
    resource_type: str,
    resource_id: str | UUID | Column[str] | Column[UUID] | None = None,
) -> ProcessingDecision:
    """Evaluate and append a value-free processing record to ``audit_logs``.

    This first contract is observational: existing RBAC remains the enforcement
    owner.  The returned decision makes mismatches visible to callers and tests;
    a later contract can enforce masking or denial without changing the ledger.
    """

    # The project still has classic SQLAlchemy model annotations, so instance
    # attributes are statically exposed as ``Column[T]`` even though ORM-loaded
    # values are plain scalars at runtime. Keep that compatibility cast at this
    # single adapter boundary instead of duplicating it in every HTTP route.
    runtime_tenant_id = cast(UUID, tenant_id)
    runtime_actor_id = cast(UUID, actor_id)
    runtime_actor_role = cast(str, actor_role)
    runtime_resource_id = cast(str | UUID | None, resource_id)

    decision = evaluate_processing(
        ProcessingRequest(operation=operation, actor_role=runtime_actor_role)
    )
    if decision.outcome is not DisclosureOutcome.FULL:
        # Masking is also fail-closed until the calling adapter explicitly
        # implements the masked representation declared by a later contract.
        raise ProcessingDeniedError(decision)
    await log_action(
        db,
        tenant_id=runtime_tenant_id,
        user_id=runtime_actor_id,
        action=f"privacy.processing.{operation}",
        resource_type=resource_type,
        resource_id=runtime_resource_id,
        details={
            "policy_version": decision.policy_version,
            "operation": decision.operation,
            "purpose": decision.purpose,
            "outcome": decision.outcome.value,
            "reason_code": decision.reason_code,
            "field_names": list(decision.field_names),
            "data_classes": list(decision.data_classes),
        },
    )
    return decision
