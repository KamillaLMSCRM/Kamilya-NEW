"""Pure contract tests for operations guards and route registration."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.tenants import Tenant
from app.modules.admin.superadmin.operations import (
    CLEANUP_CONFIRM_TOKEN,
    MIN_CLEANUP_AGE_HOURS,
    SyntheticCleanupRequest,
    _is_allowed_synthetic_tenant,
)
from app.main import app


def _tenant(*, slug: str, is_demo: bool) -> Tenant:
    return Tenant(
        id=uuid4(),
        name="contract-only",
        slug=slug,
        is_demo=is_demo,
        created_at=datetime.now(UTC),
    )


def test_operations_router_is_registered_inside_superadmin_router():
    paths = app.openapi()["paths"]
    assert "/api/v1/admin/super/operations/summary" in paths
    assert "/api/v1/admin/super/operations/cleanup-synthetic" in paths


def test_cleanup_guard_requires_demo_flag_and_fixed_prefix():
    assert _is_allowed_synthetic_tenant(
        _tenant(slug="synthetic-contract", is_demo=True)
    )
    assert not _is_allowed_synthetic_tenant(
        _tenant(slug="synthetic-contract", is_demo=False)
    )
    assert not _is_allowed_synthetic_tenant(
        _tenant(slug="customer-contract", is_demo=True)
    )


def test_cleanup_defaults_to_dry_run_and_cannot_lower_age_floor():
    payload = SyntheticCleanupRequest()
    assert payload.dry_run is True
    assert payload.min_age_hours == MIN_CLEANUP_AGE_HOURS

    with pytest.raises(ValidationError):
        SyntheticCleanupRequest(min_age_hours=MIN_CLEANUP_AGE_HOURS - 1)

def test_confirmation_token_is_not_accepted_as_a_default():
    payload = SyntheticCleanupRequest(dry_run=False)
    assert payload.confirm is False
    assert payload.confirm_token is None
    assert CLEANUP_CONFIRM_TOKEN not in payload.model_dump_json()
