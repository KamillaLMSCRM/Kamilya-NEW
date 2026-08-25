"""Contracts for tenant-scoped training-evidence retention."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.training_retention.router import router
from app.modules.training_retention.schemas import (
    PURGE_CONFIRMATION_TOKEN,
    RetentionPurgeRequest,
    TrainingRetentionPolicyCreate,
)
from app.modules.training_retention.service import purge


def test_active_policy_requires_legal_or_local_basis():
    with pytest.raises(ValidationError):
        TrainingRetentionPolicyCreate(
            procedure_type="training",
            retention_days=365,
            active=True,
        )


def test_dry_run_is_the_default_and_root_limit_is_bounded():
    request = RetentionPurgeRequest()
    assert request.dry_run is True
    assert request.max_roots == 100

    with pytest.raises(ValidationError):
        RetentionPurgeRequest(max_roots=101)


def test_execute_requires_confirmation_and_fresh_reauthentication_fields():
    assert PURGE_CONFIRMATION_TOKEN == "PURGE_TRAINING_EVIDENCE"
    request = RetentionPurgeRequest(
        dry_run=False,
        confirmation_token=PURGE_CONFIRMATION_TOKEN,
        reauth_password="Password123!",
    )
    assert request.dry_run is False
    assert request.reauth_password == "Password123!"


@pytest.mark.asyncio
async def test_execute_rejects_static_confirmation_without_reauthentication():
    db = AsyncMock()
    user = type("User", (), {"email": "methodologist@example.com", "id": uuid4(), "tenant_id": uuid4()})()

    with pytest.raises(HTTPException) as error:
        await purge(
            db,
            uuid4(),
            RetentionPurgeRequest(dry_run=False, confirmation_token=PURGE_CONFIRMATION_TOKEN),
            user=user,
        )

    assert getattr(error.value, "status_code", None) == 401
    assert error.value.detail["code"] == "reauth_required"


@pytest.mark.asyncio
async def test_execute_reauthenticates_before_calling_database_purge(monkeypatch):
    db = AsyncMock()
    tenant_id = uuid4()
    user = type("User", (), {"id": uuid4(), "tenant_id": tenant_id})()
    verify_password = Mock(return_value=True)
    monkeypatch.setattr("app.modules.auth.service.verify_current_password", verify_password)
    db.scalar.return_value = {
        "dry_run": False,
        "scan_budget": 10,
        "roots_scanned": 0,
        "truncated": False,
        "eligible_roots": 0,
        "purged_roots": 0,
        "purged_events": 0,
        "purged_confirmations": 0,
        "purged_hold_history": 0,
        "purged_shares": 0,
        "reason_counts": {},
    }

    response = await purge(
        db,
        tenant_id,
        RetentionPurgeRequest(
            dry_run=False,
            confirmation_token=PURGE_CONFIRMATION_TOKEN,
            reauth_password="Password123!",
        ),
        user=user,
    )

    verify_password.assert_called_once_with(user, "Password123!")
    assert response.dry_run is False


@pytest.mark.asyncio
async def test_execute_does_not_disclose_server_confirmation_phrase():
    db = AsyncMock()
    user = type("User", (), {"email": "methodologist@example.com", "id": uuid4(), "tenant_id": uuid4()})()

    with pytest.raises(HTTPException) as error:
        await purge(
            db,
            user.tenant_id,
            RetentionPurgeRequest(dry_run=False, confirmation_token="wrong", reauth_password="Password123!"),
            user=user,
        )

    assert error.value.status_code == 422
    assert "expected" not in error.value.detail


@pytest.mark.asyncio
async def test_dry_run_does_not_require_reauthentication_or_confirmation():
    db = AsyncMock()
    db.scalar.return_value = {
        "dry_run": True,
        "scan_budget": 10,
        "roots_scanned": 0,
        "truncated": False,
        "eligible_roots": 0,
        "purged_roots": 0,
        "purged_events": 0,
        "purged_confirmations": 0,
        "purged_hold_history": 0,
        "purged_shares": 0,
        "reason_counts": {},
    }

    response = await purge(db, uuid4(), RetentionPurgeRequest(dry_run=True))

    assert response.dry_run is True


def test_all_routes_are_methodologist_only():
    for route in router.routes:
        role_dependencies = [
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.call is not None and dependency.call.__name__ == "role_checker"
        ]
        assert role_dependencies, route.path
        assert role_dependencies[0].__closure__ is not None


def test_migration_is_additive_and_security_definer_is_bounded():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0088_training_evidence_retention.py"
    source = migration.read_text(encoding="utf-8")

    assert 'revision = "0088"' in source
    assert 'down_revision = "0087"' in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = public, pg_temp" in source
    assert "GRANT EXECUTE ON FUNCTION purge_training_evidence_chains" in source
    assert "REVOKE ALL ON FUNCTION purge_training_evidence_chains" in source
    assert "p_max_roots > 100" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "CREATE OR REPLACE FUNCTION prevent_training_evidence_event_mutation" in source
    assert "training_evidence_retention_purge_authorized()" in source
    assert "jsonb_build_object" in source
    assert "JOIN training_retention_policies p" in source
    assert "p.active = true" in source
    assert "CREATE TEMP TABLE IF NOT EXISTS retention_chain_ids" in source
    assert "CREATE TEMP TABLE IF NOT EXISTS retention_share_ids" in source
    assert "CREATE TEMP TABLE IF NOT EXISTS retention_root_candidates" in source
    assert "TRUNCATE retention_chain_ids, retention_share_ids, retention_root_candidates" in source
    assert "DELETE FROM training_evidence_shares" in source
    assert "s.revoked_at IS NOT NULL OR s.expires_at <= now()" in source
    assert "purged_shares" in source
    assert "active_legal_hold" in source
    assert "active_external_share" in source
    assert "p_dry_run" in source
    assert "EXECUTE IMMEDIATE" not in source
    assert "UNION\n                    SELECT child.id" in source
    assert "scan_budget := LEAST(p_max_roots * 10, 1000)" in source
    assert "LIMIT scan_budget + 1" in source
    assert "EXIT WHEN roots_scanned >= scan_budget OR eligible_roots >= p_max_roots" in source
    assert "'scan_budget', scan_budget" in source
    assert "'truncated', truncated" in source
    assert "reason_no_policy" not in source
    assert "LIMIT p_max_roots" not in source
    assert "CREATE TABLE training_evidence_retention_cursors" in source
    assert "ALTER TABLE training_evidence_retention_cursors ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE training_evidence_retention_cursors FORCE ROW LEVEL SECURITY" in source
    assert "FOR UPDATE" in source


def test_purge_contract_covers_starvation_share_cleanup_and_idempotency():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0088_training_evidence_retention.py"
    source = migration.read_text(encoding="utf-8")

    # Only active-policy roots enter the bounded candidate set. The query keeps
    # one sentinel row so the result can honestly report truncated work.
    assert "JOIN training_retention_policies p" in source
    assert "AND p.active = true" in source
    assert "LIMIT scan_budget + 1" in source
    assert "candidate_count > roots_scanned" in source
    assert "scan_budget := LEAST(p_max_roots * 10, 1000)" in source
    assert "eligible_roots >= p_max_roots" in source
    assert "(occurred_at, id) > (cursor_occurred_at, cursor_root_id)" in source
    assert "(occurred_at, id) <= (cursor_occurred_at, cursor_root_id)" in source
    assert "last_scanned_occurred_at" in source
    assert "last_root_id = last_scanned_root_id" in source

    # Repeated dry-run/execute calls in one transaction reuse and clear the
    # caller-owned temp state instead of failing on CREATE TEMP TABLE.
    assert source.count("CREATE TEMP TABLE IF NOT EXISTS") == 3
    assert "TRUNCATE retention_chain_ids, retention_share_ids, retention_root_candidates" in source

    # Legal holds and active shares are evaluated before an eligible chain is
    # queued; only expired/revoked packages are removed before event deletion.
    assert source.index("IF active_hold THEN") < source.index("eligible_roots := eligible_roots + 1")
    assert source.index("IF active_share THEN") < source.index("eligible_roots := eligible_roots + 1")
    share_delete = source.index("DELETE FROM training_evidence_shares")
    event_delete = source.index("DELETE FROM training_evidence_events e")
    assert share_delete < event_delete
    assert "s.revoked_at IS NOT NULL OR s.expires_at <= now()" in source
    assert "purged_shares := purged_shares + deleted_count" in source

    # The existing RESTRICT self-FK is respected by deleting leaves first;
    # an incomplete chain fails closed instead of partially purging it.
    assert "NOT EXISTS (" in source
    assert "deleted_this_chain <> chain_count" in source
    assert "integrity_constraint_violation" in source


def test_tenant_retention_api_surface_is_read_only():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/training-retention/policies" in paths
    assert set(app.openapi()["paths"]["/api/v1/training-retention/policies"]) == {"get"}
    assert "/api/v1/training-retention/policies/{policy_id}" not in paths
    assert "/api/v1/training-retention/purge" not in paths


@pytest.mark.asyncio
async def test_methodologist_cannot_mutate_policy_or_invoke_purge(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant(name="Read-only retention")
    methodologist = await make_user(tenant, role="methodologist")
    create_response = await client.post(
        "/api/v1/training-retention/policies",
        headers=auth_headers(methodologist),
        json={
            "procedure_type": "training",
            "retention_days": 365,
            "local_basis": "Tenant schedule",
        },
    )
    purge_response = await client.post(
        "/api/v1/training-retention/purge",
        headers=auth_headers(methodologist),
        json={"dry_run": True},
    )

    assert create_response.status_code == 405
    assert purge_response.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_manage_retention_policy(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant(name="Retention admin boundary")
    admin = await make_user(tenant, role="admin")
    response = await client.get("/api/v1/training-retention/policies", headers=auth_headers(admin))
    assert response.status_code == 403


@pytest.mark.parametrize("procedure_type", ["acknowledgement", "training", "knowledge_check", "internal_attestation", "admission_decision"])
def test_policy_accepts_all_evidence_procedure_types(procedure_type: str):
    policy = TrainingRetentionPolicyCreate(
        procedure_type=procedure_type,
        retention_days=365,
        local_basis="Tenant retention schedule",
        active=True,
    )
    assert policy.procedure_type == procedure_type


@pytest.mark.asyncio
async def test_purge_maps_share_count_from_database_aggregate():
    db = AsyncMock()
    db.scalar.return_value = {
        "dry_run": True,
        "scan_budget": 10,
        "roots_scanned": 1,
        "truncated": True,
        "eligible_roots": 1,
        "purged_roots": 0,
        "purged_events": 0,
        "purged_confirmations": 0,
        "purged_hold_history": 0,
        "purged_shares": 2,
        "reason_counts": {},
    }

    response = await purge(db, uuid4(), RetentionPurgeRequest())

    assert response.scan_budget == 10
    assert response.purged_shares == 2
    assert response.truncated is True


def test_purge_result_contract_exposes_bounded_scan_state():
    from app.modules.training_retention.schemas import RetentionPurgeResponse

    response = RetentionPurgeResponse(
        dry_run=True,
        scan_budget=10,
        roots_scanned=10,
        truncated=True,
        eligible_roots=1,
        purged_roots=0,
        purged_events=0,
        purged_confirmations=0,
        purged_hold_history=0,
        purged_shares=0,
        reason_counts={"active_legal_hold": 9, "newer_chain_event": 0, "active_external_share": 0},
        generated_at=datetime.now(UTC),
    )

    assert response.scan_budget == 10
    assert response.roots_scanned == 10
    assert response.truncated is True
    assert response.aggregate == {
        "scan_budget": 10,
        "roots_scanned": 10,
        "truncated": True,
        "eligible_roots": 1,
        "purged_roots": 0,
    }
