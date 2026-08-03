"""Integration coverage for the regulated-procedure evidence gate."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.modules.training_evidence.models import TrainingEvidenceEvent
from app.modules.training_evidence.service import canonical_json_sha256, record_event
from app.modules.training_procedures.models import TrainingProcedure

pytestmark = pytest.mark.asyncio


async def _active_procedure(db_session, tenant, actor, *, procedure_type="acknowledgement", code="ack-1"):
    procedure = TrainingProcedure(
        tenant_id=tenant.id,
        code=code,
        version=1,
        title="Employee acknowledgement",
        procedure_type=procedure_type,
        status="active",
        approval_reference="POL-2026-01",
        approval_date=date(2026, 8, 1),
        approved_by_name="HR Director",
        local_basis="Tenant internal procedure",
        confirmation_method="email_otp",
        retention_class="personnel-training",
        retention_days=1825,
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
    )
    if procedure_type == "internal_attestation":
        procedure.commission_snapshot_rules = {
            "members": ["chair", "member"],
            "quorum": "2 of 3",
            "decision_record": "commission protocol",
        }
    if procedure_type == "admission_decision":
        procedure.authorized_decision_rules = {
            "authority": "department head",
            "decision_record": "admission order",
            "effective_date": "decision date",
        }
    db_session.add(procedure)
    await db_session.flush()
    return procedure


async def test_regulated_manual_event_requires_procedure(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant(name="Procedure required")
    methodologist = await make_user(tenant, role="methodologist")

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "payload_snapshot": {"procedure": {"title": "caller supplied"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "training_procedure_required"


@pytest.mark.parametrize("procedure_status", ["draft", "retired"])
async def test_only_active_procedure_is_accepted(
    client, db_session, make_tenant, make_user, auth_headers, procedure_status
):
    tenant = await make_tenant(name=f"Procedure {procedure_status}")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(db_session, tenant, methodologist)
    procedure.status = procedure_status
    await db_session.flush()

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {"source": "test"},
        },
    )

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert "training_procedure_not_found" in response.json()["message"]


async def test_cross_tenant_procedure_is_hidden(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant_a = await make_tenant(name="Procedure A")
    methodologist_a = await make_user(tenant_a, role="methodologist")
    procedure = await _active_procedure(db_session, tenant_a, methodologist_a)

    tenant_b = await make_tenant(name="Procedure B")
    methodologist_b = await make_user(tenant_b, role="methodologist")
    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist_b),
        json={
            "user_id": str(methodologist_b.id),
            "procedure_type": "acknowledgement",
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {"source": "test"},
        },
    )

    assert response.status_code == 404


async def test_generic_post_rejects_regulated_type_before_procedure_binding(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Procedure type")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(db_session, tenant, methodologist)

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "admission_decision",
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {"source": "test"},
        },
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "regulated_evidence_workflow_required"


async def test_active_procedure_snapshot_overwrites_malicious_payload(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Procedure snapshot")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(db_session, tenant, methodologist)

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {
                "procedure": {"id": "evil", "title": "Caller procedure", "type": "admission_decision"},
                "training_procedure": {"id": "evil", "title": "Caller procedure"},
            },
        },
    )

    assert response.status_code == 201, response.text
    snapshot = response.json()["payload_snapshot"]
    assert snapshot["procedure"]["id"] == str(procedure.id)
    assert snapshot["procedure"]["title"] == procedure.title
    assert snapshot["procedure"]["type"] == "acknowledgement"
    assert snapshot["training_procedure"] == snapshot["procedure"]
    assert "commission" not in snapshot
    assert "decision" not in snapshot


async def test_acknowledgement_drops_commission_and_decision_claims(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Acknowledgement claims")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(db_session, tenant, methodologist)

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {
                "commission": {"members": ["caller"]},
                "decision": {"result": "admitted"},
            },
        },
    )

    assert response.status_code == 201, response.text
    snapshot = response.json()["payload_snapshot"]
    assert "commission" not in snapshot
    assert "decision" not in snapshot


@pytest.mark.parametrize(
    ("procedure_type", "payload_key"),
    [("internal_attestation", "commission"), ("admission_decision", "decision")],
)
async def test_attestation_and_admission_claims_require_dedicated_workflow(
    client, db_session, make_tenant, make_user, auth_headers, procedure_type, payload_key
):
    tenant = await make_tenant(name=f"Workflow required {procedure_type}")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(
        db_session,
        tenant,
        methodologist,
        procedure_type=procedure_type,
        code=f"{procedure_type}-1",
    )

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": procedure_type,
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {payload_key: {"caller": "must not be accepted"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "regulated_evidence_workflow_required"


async def test_system_event_rejects_procedure_id(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="System event")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(db_session, tenant, methodologist)

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "knowledge_check",
            "training_procedure_id": str(procedure.id),
            "payload_snapshot": {"source": "test"},
        },
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "system_evidence_workflow_required"


@pytest.mark.parametrize(
    ("procedure_type", "expected_code"),
    [
        ("training", "system_evidence_workflow_required"),
        ("knowledge_check", "system_evidence_workflow_required"),
        ("internal_attestation", "regulated_evidence_workflow_required"),
        ("admission_decision", "regulated_evidence_workflow_required"),
    ],
)
async def test_generic_correction_rejects_non_acknowledgement_evidence(
    client, db_session, make_tenant, make_user, auth_headers, procedure_type, expected_code
):
    tenant = await make_tenant(name=f"Correction workflow {procedure_type}")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = None
    if procedure_type in {"internal_attestation", "admission_decision"}:
        procedure = await _active_procedure(
            db_session,
            tenant,
            methodologist,
            procedure_type=procedure_type,
            code=f"{procedure_type}-correction",
        )
    original = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=methodologist.id,
        procedure_type=procedure_type,
        training_procedure_id=procedure.id if procedure else None,
        payload_snapshot={"source": "trusted-original"},
    )

    response = await client.post(
        f"/api/v1/training-evidence/events/{original.id}/corrections",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": procedure_type,
            "training_procedure_id": str(procedure.id) if procedure else None,
            "payload_snapshot": {"decision": {"outcome": "admitted"}},
            "reason": "Generic correction must fail closed",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["details"]["code"] == expected_code


@pytest.mark.parametrize("procedure_type", ["training", "knowledge_check"])
async def test_generic_post_rejects_system_evidence(
    client, make_tenant, make_user, auth_headers, procedure_type
):
    tenant = await make_tenant(name=f"System workflow {procedure_type}")
    methodologist = await make_user(tenant, role="methodologist")

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": procedure_type,
            "payload_snapshot": {"source": "manual caller"},
        },
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "system_evidence_workflow_required"


@pytest.mark.parametrize("procedure_type", ["internal_attestation", "admission_decision"])
async def test_generic_post_rejects_regulated_execution_types(
    client, make_tenant, make_user, auth_headers, procedure_type
):
    tenant = await make_tenant(name=f"Regulated workflow {procedure_type}")
    methodologist = await make_user(tenant, role="methodologist")

    response = await client.post(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": procedure_type,
            "training_procedure_id": str(methodologist.id),
            "payload_snapshot": {"source": "manual caller"},
        },
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "regulated_evidence_workflow_required"


async def test_database_check_rejects_system_event_with_procedure_id(
    db_session, make_tenant, make_user
):
    tenant = await make_tenant(name="Database procedure gate")
    methodologist = await make_user(tenant, role="methodologist")
    procedure = await _active_procedure(db_session, tenant, methodologist)
    payload = {"source": "direct insert"}
    event = TrainingEvidenceEvent(
        tenant_id=tenant.id,
        user_id=methodologist.id,
        procedure_type="knowledge_check",
        training_procedure_id=procedure.id,
        payload_snapshot=payload,
        payload_sha256=canonical_json_sha256(payload),
        recorded_by_user_id=methodologist.id,
    )

    savepoint = await db_session.begin_nested()
    try:
        db_session.add(event)
        with pytest.raises(DBAPIError):
            await db_session.flush()
    finally:
        await savepoint.rollback()


async def test_correction_preserves_procedure_and_cannot_switch(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Correction procedure")
    methodologist = await make_user(tenant, role="methodologist")
    first = await _active_procedure(db_session, tenant, methodologist, code="ack-1")
    second = await _active_procedure(db_session, tenant, methodologist, code="ack-2")
    original = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=methodologist.id,
        procedure_type="acknowledgement",
        training_procedure_id=first.id,
        payload_snapshot={"procedure": {"title": "caller value"}},
    )

    switched = await client.post(
        f"/api/v1/training-evidence/events/{original.id}/corrections",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "training_procedure_id": str(second.id),
            "payload_snapshot": {"corrected": True},
            "reason": "Corrected record",
        },
    )
    assert switched.status_code == 422

    preserved = await client.post(
        f"/api/v1/training-evidence/events/{original.id}/corrections",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "payload_snapshot": {"corrected": True},
            "reason": "Corrected record",
        },
    )
    assert preserved.status_code == 201, preserved.text
    body = preserved.json()
    assert body["training_procedure_id"] == str(first.id)
    assert body["procedure_type"] == "acknowledgement"
    assert body["payload_snapshot"]["procedure"]["id"] == str(first.id)

    caller_owned = await client.post(
        f"/api/v1/training-evidence/events/{original.id}/corrections",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "acknowledgement",
            "payload_snapshot": {
                "corrected": True,
                "procedure": {"id": "caller"},
                "commission": {"members": ["caller"]},
                "decision": {"outcome": "admitted"},
            },
            "reason": "Corrected record without regulated claims",
        },
    )
    assert caller_owned.status_code == 201, caller_owned.text
    caller_body = caller_owned.json()["payload_snapshot"]
    assert caller_body["procedure"]["id"] == str(first.id)
    assert "commission" not in caller_body
    assert "decision" not in caller_body


async def test_idempotency_key_includes_training_procedure(
    db_session, make_tenant, make_user
):
    tenant = await make_tenant(name="Idempotency procedure")
    methodologist = await make_user(tenant, role="methodologist")
    first = await _active_procedure(db_session, tenant, methodologist, code="ack-1")
    second = await _active_procedure(db_session, tenant, methodologist, code="ack-2")

    await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=methodologist.id,
        procedure_type="acknowledgement",
        training_procedure_id=first.id,
        source_event_key="same-source-key",
        payload_snapshot={"value": 1},
    )

    with pytest.raises(HTTPException) as exc:
        await record_event(
            db_session,
            tenant_id=tenant.id,
            actor_user_id=methodologist.id,
            user_id=methodologist.id,
            procedure_type="acknowledgement",
            training_procedure_id=second.id,
            source_event_key="same-source-key",
            payload_snapshot={"value": 1},
        )
    assert exc.value.status_code == 409
