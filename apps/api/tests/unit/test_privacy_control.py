from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.privacy_control.policy import (
    DisclosureOutcome,
    ProcessingRequest,
    evaluate_processing,
)
from app.modules.privacy_control.service import ProcessingDeniedError, record_processing


def test_employee_create_is_classified_and_allowed_for_methodologist() -> None:
    decision = evaluate_processing(
        ProcessingRequest(operation="employee.create", actor_role="methodologist")
    )

    assert decision.outcome is DisclosureOutcome.FULL
    assert decision.purpose == "workforce_administration"
    assert decision.field_names == (
        "email",
        "first_name",
        "last_name",
        "organization_unit_id",
        "personnel_number",
        "phone",
        "position_id",
    )
    assert decision.data_classes == (
        "contact_identifier",
        "identity",
        "organization_assignment",
    )
    assert decision.reason_code == "policy_allow"


def test_processing_policy_fails_closed_for_unregistered_operation() -> None:
    decision = evaluate_processing(
        ProcessingRequest(operation="employee.unregistered", actor_role="admin")
    )

    assert decision.outcome is DisclosureOutcome.DENY
    assert decision.purpose == "unknown"
    assert decision.field_names == ()
    assert decision.data_classes == ()
    assert decision.reason_code == "policy_missing"


def test_users_export_is_denied_to_role_outside_catalog_policy() -> None:
    decision = evaluate_processing(
        ProcessingRequest(operation="employee.export", actor_role="methodologist")
    )

    assert decision.outcome is DisclosureOutcome.DENY
    assert decision.reason_code == "actor_role_denied"


def test_team_member_create_classifies_password_without_recording_its_value() -> None:
    decision = evaluate_processing(
        ProcessingRequest(operation="team_member.create", actor_role="admin")
    )

    assert decision.outcome is DisclosureOutcome.FULL
    assert "password" in decision.field_names
    assert "authentication_secret" in decision.data_classes


def test_employee_export_classifies_the_internal_identifier() -> None:
    decision = evaluate_processing(
        ProcessingRequest(operation="employee.export", actor_role="admin")
    )

    assert decision.outcome is DisclosureOutcome.FULL
    assert "id" in decision.field_names
    assert "internal_identifier" in decision.data_classes


def test_employee_import_classifies_employment_date() -> None:
    decision = evaluate_processing(
        ProcessingRequest(operation="employee.import", actor_role="methodologist")
    )

    assert decision.outcome is DisclosureOutcome.FULL
    assert "hire_date" in decision.field_names
    assert "employment" in decision.data_classes


@pytest.mark.asyncio
async def test_processing_ledger_records_policy_metadata_without_personal_values() -> None:
    db = MagicMock()
    db.flush = AsyncMock()
    tenant_id = uuid4()
    actor_id = uuid4()
    employee_id = uuid4()

    decision = await record_processing(
        db,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role="admin",
        operation="team_member.update",
        resource_type="user",
        resource_id=employee_id,
    )

    assert decision.outcome is DisclosureOutcome.FULL
    db.add.assert_called_once()
    db.flush.assert_awaited_once_with()
    entry = db.add.call_args.args[0]
    assert entry.tenant_id == tenant_id
    assert entry.user_id == actor_id
    assert entry.action == "privacy.processing.team_member.update"
    assert entry.resource_type == "user"
    assert entry.resource_id == str(employee_id)
    assert entry.details == {
        "policy_version": "2026-09-29.v1",
        "operation": "team_member.update",
        "purpose": "workforce_administration",
        "outcome": "full",
        "reason_code": "policy_allow",
        "field_names": [
            "email",
            "first_name",
            "is_active",
            "last_name",
        ],
        "data_classes": ["contact_identifier", "employment", "identity"],
    }
    serialized = repr(entry.details)
    assert "example.com" not in serialized
    assert "first_name_value" not in serialized


@pytest.mark.asyncio
async def test_processing_service_fails_closed_before_writing_denied_operation() -> None:
    db = MagicMock()
    db.flush = AsyncMock()

    with pytest.raises(ProcessingDeniedError) as exc_info:
        await record_processing(
            db,
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_role="methodologist",
            operation="employee.export",
            resource_type="user_export",
            resource_id="tenant-users",
        )

    assert exc_info.value.reason_code == "actor_role_denied"
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
