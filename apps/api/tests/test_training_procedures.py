"""Focused contracts for tenant-configurable procedure definitions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from inspect import getclosurevars
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.training_procedures.models import TrainingProcedure
from app.modules.training_procedures.router import (
    _procedure_actor_id,
    _procedure_tenant_id,
    router,
)
from app.modules.training_procedures.schemas import TrainingProcedureCreate, TrainingProcedureResponse
from app.modules.training_procedures.service import ActivationIncompleteError, validate_activation_ready


def _draft(procedure_type: str = "acknowledgement") -> TrainingProcedure:
    return TrainingProcedure(
        tenant_id=uuid4(),
        code="SAFETY_ACK",
        version=1,
        title="Safety acknowledgement",
        procedure_type=procedure_type,
        confirmation_method="manual_record",
    )


def _complete(procedure_type: str = "acknowledgement") -> TrainingProcedure:
    procedure = _draft(procedure_type)
    procedure.approval_reference = "POL-2026-01"
    procedure.approval_date = date(2026, 8, 1)
    procedure.approved_by_name = "HR Director"
    procedure.local_basis = "Tenant internal procedure"
    procedure.retention_class = "personnel-training"
    procedure.retention_days = 1825
    if procedure_type == "internal_attestation":
        procedure.commission_snapshot_rules = {
            "members": ["chair", "member"],
            "quorum": "2 of 3",
            "decision_record": "signed commission protocol",
        }
    if procedure_type == "admission_decision":
        procedure.authorized_decision_rules = {
            "authority": "department head",
            "decision_record": "explicit admission order",
            "effective_date": "decision date",
        }
    return procedure


def test_activation_requires_approval_retention_and_basis():
    with pytest.raises(ActivationIncompleteError) as exc:
        validate_activation_ready(_draft())

    assert set(exc.value.fields) == {
        "approval_reference",
        "approval_date",
        "approved_by_name",
        "legal_basis_or_local_basis",
        "retention_class",
        "retention_days",
    }


@pytest.mark.parametrize("procedure_type", ["internal_attestation", "admission_decision"])
def test_specialized_procedures_require_explicit_rules(procedure_type):
    procedure = _complete(procedure_type)
    if procedure_type == "internal_attestation":
        procedure.commission_snapshot_rules = None
        field = "commission_snapshot_rules"
    else:
        procedure.authorized_decision_rules = None
        field = "authorized_decision_rules"

    with pytest.raises(ActivationIncompleteError) as exc:
        validate_activation_ready(procedure)

    assert exc.value.fields == [field]


@pytest.mark.parametrize("procedure_type", ["acknowledgement", "internal_attestation", "admission_decision"])
def test_complete_configurable_procedure_can_activate(procedure_type):
    validate_activation_ready(_complete(procedure_type))


def test_system_training_types_are_not_configurable_labels():
    with pytest.raises(ValidationError):
        TrainingProcedureCreate(
            code="QUIZ",
            version=1,
            title="Knowledge check",
            procedure_type="knowledge_check",
            confirmation_method="manual_record",
        )


def test_procedure_code_is_normalized_to_lowercase_ascii_slug():
    first = TrainingProcedureCreate(
        code="  Safety Policy 2026 ",
        version=1,
        title="Safety policy",
        procedure_type="acknowledgement",
        confirmation_method="manual_record",
    )
    second = TrainingProcedureCreate(
        code="SAFETY-POLICY-2026",
        version=2,
        title="Safety policy v2",
        procedure_type="acknowledgement",
        confirmation_method="manual_record",
    )

    assert first.code == "safety-policy-2026"
    assert second.code == first.code


@pytest.mark.parametrize("code", ["", "-safety", "safety/policy", "Правила", "_safety"])
def test_procedure_code_rejects_non_slug_values(code):
    with pytest.raises(ValidationError):
        TrainingProcedureCreate(
            code=code,
            version=1,
            title="Safety policy",
            procedure_type="acknowledgement",
            confirmation_method="manual_record",
        )


def test_all_routes_are_methodologist_only():
    for route in router.routes:
        role_dependencies = [
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.call is not None and dependency.call.__name__ == "role_checker"
        ]
        assert role_dependencies, route.path
        assert getclosurevars(role_dependencies[0]).nonlocals["allowed_roles"] == ("methodologist",)


def test_impersonation_never_fabricates_a_tenant_procedure_actor():
    real_actor_id = uuid4()

    assert _procedure_actor_id(SimpleNamespace(id=real_actor_id, is_impersonating=False)) == real_actor_id
    assert _procedure_actor_id(SimpleNamespace(id=real_actor_id, is_impersonating=True)) is None


def test_impersonated_procedure_response_accepts_audited_null_authors():
    now = datetime.now(UTC)

    response = TrainingProcedureResponse.model_validate(
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "code": "qa-acknowledgement",
            "version": 1,
            "title": "QA acknowledgement",
            "description": "",
            "procedure_type": "acknowledgement",
            "status": "draft",
            "approval_reference": None,
            "approval_date": None,
            "approved_by_name": None,
            "legal_basis": None,
            "local_basis": None,
            "confirmation_method": "manual_record",
            "retention_class": None,
            "retention_days": None,
            "commission_snapshot_rules": None,
            "authorized_decision_rules": None,
            "created_by_user_id": None,
            "updated_by_user_id": None,
            "created_at": now,
            "updated_at": now,
            "activated_at": None,
            "retired_at": None,
        }
    )

    assert response.created_by_user_id is None
    assert response.updated_by_user_id is None


def test_methodologist_dependency_supplies_the_effective_tenant_context():
    tenant_id = uuid4()

    assert _procedure_tenant_id(SimpleNamespace(tenant_id=tenant_id)) == tenant_id


def test_migration_has_force_rls_runtime_grants_and_additive_predecessor():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0086_training_procedures.py"
    source = migration.read_text(encoding="utf-8")

    assert 'revision = "0086"' in source
    assert 'down_revision = "0085"' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON training_procedures TO lms_app" in source
    assert "tenant_training_procedures_isolation" in source
    assert "uq_training_procedures_one_active_code" in source
    assert "status = 'active'" in source
    assert "ck_training_procedures_code_format" in source


def test_impersonation_actor_migration_keeps_non_null_authors_tenant_scoped():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0138_allow_impersonated_training_procedure_actor.py"
    source = migration.read_text(encoding="utf-8")

    assert 'revision = "0138"' in source
    assert 'down_revision = "0137"' in source
    assert "created_by_user_id IS NOT NULL" in source
    assert "updated_by_user_id IS NOT NULL" in source
    assert "creator_tenant <> NEW.tenant_id" in source
    assert "updater_tenant <> NEW.tenant_id" in source


def test_main_registers_the_procedure_api_surface():
    from app.main import app

    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/training-procedures",
        "/api/v1/training-procedures/{procedure_id}",
        "/api/v1/training-procedures/{procedure_id}/activate",
        "/api/v1/training-procedures/{procedure_id}/retire",
    }
    assert expected <= paths


@pytest.mark.asyncio
async def test_cross_tenant_methodologist_cannot_read_procedure(
    client, make_tenant, make_user, auth_headers
):
    tenant_a = await make_tenant(name="Tenant A")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    create_response = await client.post(
        "/api/v1/training-procedures",
        headers=auth_headers(methodologist_a),
        json={
            "code": "A_ACK",
            "version": 1,
            "title": "Tenant A acknowledgement",
            "procedure_type": "acknowledgement",
            "confirmation_method": "manual_record",
        },
    )
    assert create_response.status_code == 201, create_response.text
    procedure_id = create_response.json()["id"]

    tenant_b = await make_tenant(name="Tenant B")
    methodologist_b = await make_user(tenant_b, role="methodologist")
    read_response = await client.get(
        f"/api/v1/training-procedures/{procedure_id}",
        headers=auth_headers(methodologist_b),
    )

    assert read_response.status_code == 404


@pytest.mark.asyncio
async def test_activation_rejects_incomplete_definition_and_never_infers_attestation(
    client, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    create_response = await client.post(
        "/api/v1/training-procedures",
        headers=auth_headers(methodologist),
        json={
            "code": "ATTEST",
            "version": 1,
            "title": "Internal attestation",
            "procedure_type": "internal_attestation",
            "confirmation_method": "manual_record",
            "local_basis": "Internal policy",
        },
    )
    assert create_response.status_code == 201, create_response.text

    response = await client.post(
        f"/api/v1/training-procedures/{create_response.json()['id']}/activate",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "activation_incomplete"
    assert "commission_snapshot_rules" in response.json()["details"]["missing_fields"]


@pytest.mark.asyncio
async def test_activation_rejects_second_active_version_without_auto_retire(
    client, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Stable procedure versions")
    methodologist = await make_user(tenant, role="methodologist")

    def payload(version: int) -> dict[str, object]:
        return {
            "code": "safety-policy",
            "version": version,
            "title": f"Safety policy v{version}",
            "procedure_type": "acknowledgement",
            "confirmation_method": "manual_record",
            "approval_reference": "POL-2026-01",
            "approval_date": "2026-08-01",
            "approved_by_name": "HR Director",
            "local_basis": "Tenant internal procedure",
            "retention_class": "personnel-training",
            "retention_days": 1825,
        }

    first = await client.post(
        "/api/v1/training-procedures",
        headers=auth_headers(methodologist),
        json=payload(1),
    )
    assert first.status_code == 201, first.text
    first_activation = await client.post(
        f"/api/v1/training-procedures/{first.json()['id']}/activate",
        headers=auth_headers(methodologist),
    )
    assert first_activation.status_code == 200, first_activation.text

    second = await client.post(
        "/api/v1/training-procedures",
        headers=auth_headers(methodologist),
        json=payload(2),
    )
    assert second.status_code == 201, second.text
    second_activation = await client.post(
        f"/api/v1/training-procedures/{second.json()['id']}/activate",
        headers=auth_headers(methodologist),
    )

    assert second_activation.status_code == 409
    assert second_activation.json()["details"]["code"] == "active_procedure_version_exists"
    assert "Retire the active version first" in second_activation.json()["details"]["message"]

    second_read = await client.get(
        f"/api/v1/training-procedures/{second.json()['id']}",
        headers=auth_headers(methodologist),
    )
    assert second_read.status_code == 200
    assert second_read.json()["status"] == "draft"
