from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.staff_sync import router as staff_sync_router
from app.modules.staff_sync.auth import hash_staff_sync_token
from app.modules.staff_sync.schemas import StaffSyncEventRequest
from app.modules.staff_sync.service import canonical_event_sha256, integrity_conflict_code


def _upsert_payload() -> dict:
    return {
        "event_id": "evt-001",
        "source": "tenant-hr",
        "action": "upsert",
        "external_employee_id": "employee-42",
        "effective_at": datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
        "employee": {
            "personnel_number": "0042",
            "first_name": "Synthetic",
            "last_name": "Employee",
            "email": "synthetic@example.kz",
            "position_external_key": "position-operator",
        },
    }


def test_staff_sync_event_hash_is_deterministic_and_sensitive_to_change():
    first = StaffSyncEventRequest.model_validate(_upsert_payload())
    second = StaffSyncEventRequest.model_validate(dict(reversed(list(_upsert_payload().items()))))
    assert canonical_event_sha256(first) == canonical_event_sha256(second)

    changed = _upsert_payload()
    changed["employee"] = {**changed["employee"], "last_name": "Changed"}
    assert canonical_event_sha256(first) != canonical_event_sha256(
        StaffSyncEventRequest.model_validate(changed)
    )


def test_upsert_requires_employee_payload():
    payload = _upsert_payload()
    payload["employee"] = None
    with pytest.raises(ValidationError):
        StaffSyncEventRequest.model_validate(payload)


def test_staff_sync_contract_rejects_unknown_fields():
    payload = _upsert_payload()
    payload["tenant_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ValidationError):
        StaffSyncEventRequest.model_validate(payload)


def test_staff_sync_token_hash_never_returns_plaintext():
    token = "synthetic-token-with-more-than-thirty-two-characters"
    digest = hash_staff_sync_token(token)
    assert len(digest) == 64
    assert token not in digest


@pytest.mark.asyncio
async def test_event_endpoint_rejects_mismatched_idempotency_key():
    payload = StaffSyncEventRequest.model_validate(_upsert_payload())

    with pytest.raises(HTTPException) as exc_info:
        await staff_sync_router.receive_staff_event(
            payload,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            "another-event",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "idempotency_key_mismatch"


@pytest.mark.asyncio
async def test_event_endpoint_routes_matching_idempotency_key(monkeypatch):
    payload = StaffSyncEventRequest.model_validate(_upsert_payload())
    expected = object()

    async def fake_process_event(db, context, request):
        assert db == "db"
        assert context == "context"
        assert request is payload
        return expected

    monkeypatch.setattr(staff_sync_router, "process_event", fake_process_event)

    result = await staff_sync_router.receive_staff_event(
        payload,
        "db",  # type: ignore[arg-type]
        "context",  # type: ignore[arg-type]
        payload.event_id,
    )

    assert result is expected


def test_staff_sync_migration_keeps_credentials_private_and_forces_rls():
    migration = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0132_staff_sync_api.py"
    ).read_text(encoding="utf-8")

    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "for table in TABLES" in migration
    for table in ("staff_sync_credentials", "staff_sync_identities", "staff_sync_events"):
        assert table in migration
    assert "CREATE FUNCTION lookup_staff_sync_credential" in migration
    assert "SECURITY DEFINER" in migration
    assert "REVOKE ALL ON FUNCTION lookup_staff_sync_credential" in migration
    assert "GRANT EXECUTE ON FUNCTION lookup_staff_sync_credential" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app" in migration
    assert "pg_advisory_xact_lock" not in migration


def test_staff_sync_service_serializes_duplicate_event_processing():
    service = (
        Path(__file__).parents[1] / "app" / "modules" / "staff_sync" / "service.py"
    ).read_text(encoding="utf-8")

    assert "pg_advisory_xact_lock(hashtextextended(:lock_key, 0))" in service
    assert "staff-sync:{context.tenant_id}:{payload.source}:{payload.event_id}" in service


@pytest.mark.parametrize(
    ("constraint_name", "expected"),
    [
        ("uq_users_tenant_email_ci", "email_conflict"),
        ("uq_users_tenant_personnel", "personnel_number_conflict"),
        ("uq_staff_sync_external_identity", "external_identity_conflict"),
        ("unrelated_constraint", None),
    ],
)
def test_integrity_conflicts_are_mapped_only_for_known_identity_constraints(
    constraint_name,
    expected,
):
    driver_error = type("DriverError", (), {"constraint_name": constraint_name})()
    wrapped_error = type("WrappedError", (), {"__cause__": driver_error})()
    integrity_error = type("IntegrityLike", (), {"orig": wrapped_error})()

    assert integrity_conflict_code(integrity_error) == expected  # type: ignore[arg-type]
