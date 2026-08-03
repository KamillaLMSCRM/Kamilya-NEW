"""Focused integration coverage for the immutable training-evidence core."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.modules.training_evidence.models import (
    TrainingEvidenceEvent,
    TrainingEvidenceLegalHold,
    TrainingEvidenceStepUpConfirmation,
)
from app.modules.training_evidence.schemas import (
    EvidenceCorrectionCreate,
    EvidenceEventCreate,
    EvidenceRevocationCreate,
    LegalHoldCreate,
)
from app.modules.training_evidence.service import (
    canonical_json_sha256,
    confirm_step_up,
    record_event,
)

pytestmark = pytest.mark.asyncio


async def _create_event(db_session, tenant, actor, *, subject=None, procedure_type="knowledge_check"):
    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        user_id=(subject or actor).id,
        procedure_type=procedure_type,
        payload_snapshot={
            "course_title": "Internal microcredit rules",
            "release_version": 1,
            "result": "passed",
        },
    )
    await db_session.flush()
    return event


async def test_snapshot_hash_is_canonical_and_order_independent():
    assert canonical_json_sha256({"b": 2, "a": 1}) == canonical_json_sha256({"a": 1, "b": 2})
    assert canonical_json_sha256({"a": 1}) != canonical_json_sha256({"a": 2})


async def test_event_records_snapshot_hash_and_does_not_create_admission_decision(
    db_session, make_tenant, make_user
):
    tenant = await make_tenant(name="Evidence tenant")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist@evidence.example")
    learner = await make_user(tenant, role="student", email="learner@evidence.example")

    event = await _create_event(db_session, tenant, methodologist, subject=learner)

    assert event.procedure_type == "knowledge_check"
    assert event.record_type == "original"
    assert event.payload_sha256 == canonical_json_sha256(event.payload_snapshot)
    procedure_types = set(
        await db_session.scalars(
            select(TrainingEvidenceEvent.procedure_type).where(TrainingEvidenceEvent.tenant_id == tenant.id)
        )
    )
    assert procedure_types == {"knowledge_check"}
    assert "admission_decision" not in procedure_types


async def test_event_read_is_tenant_isolated(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant_a = await make_tenant(name="Evidence A")
    methodologist_a = await make_user(tenant_a, role="methodologist", email="methodologist-a@evidence.example")
    event = await _create_event(db_session, tenant_a, methodologist_a)

    tenant_b = await make_tenant(name="Evidence B")
    methodologist_b = await make_user(tenant_b, role="methodologist", email="methodologist-b@evidence.example")
    response = await client.get(
        f"/api/v1/training-evidence/events/{event.id}",
        headers=auth_headers(methodologist_b),
    )
    assert response.status_code == 404


async def test_database_trigger_rejects_cross_tenant_event_owner(
    db_session, make_tenant, make_user
):
    tenant_a = await make_tenant(name="DB owner A")
    user_a = await make_user(tenant_a, role="student", email="db-a@evidence.example")
    tenant_b = await make_tenant(name="DB owner B")
    recorder_b = await make_user(tenant_b, role="methodologist", email="db-b@evidence.example")

    event = TrainingEvidenceEvent(
        tenant_id=tenant_a.id,
        user_id=user_a.id,
        procedure_type="training",
        payload_snapshot={"source": "cross-tenant-test"},
        payload_sha256=canonical_json_sha256({"source": "cross-tenant-test"}),
        recorded_by_user_id=recorder_b.id,
    )
    savepoint = await db_session.begin_nested()
    try:
        db_session.add(event)
        with pytest.raises(DBAPIError):
            await db_session.flush()
    finally:
        await savepoint.rollback()


async def test_system_correction_fails_closed_and_revocation_remains_linked(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Correction tenant")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-c@evidence.example")
    original = await _create_event(db_session, tenant, methodologist, procedure_type="training")

    correction = await client.post(
        f"/api/v1/training-evidence/events/{original.id}/corrections",
        headers=auth_headers(methodologist),
        json={
            "user_id": str(methodologist.id),
            "procedure_type": "training",
            "payload_snapshot": {"release_version": 1, "result": "completed", "corrected": True},
            "reason": "Исправлена дата завершения",
        },
    )
    assert correction.status_code == 422, correction.text
    assert correction.json()["details"]["code"] == "system_evidence_workflow_required"

    revocation = await client.post(
        f"/api/v1/training-evidence/events/{original.id}/revocations",
        headers=auth_headers(methodologist),
        json={"reason": "Результат аннулирован приказом N 4"},
    )
    assert revocation.status_code == 201, revocation.text
    assert revocation.json()["record_type"] == "revocation"
    assert revocation.json()["related_event_id"] == str(original.id)

    rows = list(
        (
            await db_session.scalars(
                select(TrainingEvidenceEvent)
                .where(TrainingEvidenceEvent.tenant_id == tenant.id)
                .order_by(TrainingEvidenceEvent.created_at)
            )
        ).all()
    )
    assert len(rows) == 2
    assert rows[0].record_type == "original"
    assert rows[0].payload_snapshot["result"] == "passed"


async def test_step_up_confirmation_is_internal_and_checks_subject(
    db_session, make_tenant, make_user
):
    tenant = await make_tenant(name="Step-up tenant")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-s@evidence.example")
    learner = await make_user(tenant, role="student", email="learner-s@evidence.example")
    event = await _create_event(db_session, tenant, methodologist, subject=learner)

    confirmation = await confirm_step_up(
        db_session,
        tenant_id=tenant.id,
        event_id=event.id,
        user_id=learner.id,
        action_text="Подтверждаю прохождение проверки знаний по версии 1",
        object_version="content-release:v1",
        reauth_method="email_otp",
        ip_address="192.0.2.10",
        user_agent="evidence-test/1.0",
    )
    assert confirmation.action_text == "Подтверждаю прохождение проверки знаний по версии 1"
    assert confirmation.object_version == "content-release:v1"
    assert confirmation.reauth_method == "email_otp"
    assert confirmation.user_agent == "evidence-test/1.0"
    assert len(confirmation.confirmation_sha256) == 64

    with pytest.raises(HTTPException) as exc_info:
        await confirm_step_up(
            db_session,
            tenant_id=tenant.id,
            event_id=event.id,
            user_id=methodologist.id,
            action_text="Чужое подтверждение",
            object_version="content-release:v1",
            reauth_method="email_otp",
            ip_address=None,
            user_agent=None,
        )
    assert exc_info.value.status_code == 422


async def test_database_trigger_rejects_confirmation_for_different_subject(
    db_session, make_tenant, make_user
):
    tenant = await make_tenant(name="Confirmation ownership tenant")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-trigger@evidence.example")
    learner = await make_user(tenant, role="student", email="learner-trigger@evidence.example")
    event = await _create_event(db_session, tenant, methodologist, subject=learner)
    confirmation = TrainingEvidenceStepUpConfirmation(
        tenant_id=tenant.id,
        event_id=event.id,
        user_id=methodologist.id,
        action_text="Чужое подтверждение",
        object_version="content-release:v1",
        reauth_method="email_otp",
        ip_address=None,
        user_agent=None,
        confirmation_sha256="0" * 64,
    )
    savepoint = await db_session.begin_nested()
    try:
        db_session.add(confirmation)
        with pytest.raises(DBAPIError):
            await db_session.flush()
    finally:
        await savepoint.rollback()


async def test_event_and_legal_hold_are_immutable_and_have_valid_state_transitions(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Append-only tenant")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-i@evidence.example")
    event = await _create_event(db_session, tenant, methodologist)

    savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(
                update(TrainingEvidenceEvent)
                .where(TrainingEvidenceEvent.id == event.id)
                .values(payload_sha256="0" * 64)
            )
            await db_session.flush()
    finally:
        await savepoint.rollback()

    hold_response = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/legal-hold",
        headers=auth_headers(methodologist),
        json={"action": "placed", "reason": "Ожидается проверка комплаенс"},
    )
    assert hold_response.status_code == 201, hold_response.text

    duplicate_place = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/legal-hold",
        headers=auth_headers(methodologist),
        json={"action": "placed", "reason": "Повторная установка"},
    )
    assert duplicate_place.status_code == 422

    delete_savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(delete(TrainingEvidenceEvent).where(TrainingEvidenceEvent.id == event.id))
            await db_session.flush()
    finally:
        await delete_savepoint.rollback()

    hold_id = hold_response.json()["id"]
    hold_savepoint = await db_session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await db_session.execute(delete(TrainingEvidenceLegalHold).where(TrainingEvidenceLegalHold.id == hold_id))
            await db_session.flush()
    finally:
        await hold_savepoint.rollback()

    release = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/legal-hold",
        headers=auth_headers(methodologist),
        json={"action": "released", "reason": "Проверка завершена"},
    )
    assert release.status_code == 201, release.text
    duplicate_release = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/legal-hold",
        headers=auth_headers(methodologist),
        json={"action": "released", "reason": "Повторное снятие"},
    )
    assert duplicate_release.status_code == 422


async def test_admin_cannot_access_training_evidence_api(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant(name="Admin authorization tenant")
    admin = await make_user(tenant, role="admin", email="admin-evidence@evidence.example")
    response = await client.get("/api/v1/training-evidence/events", headers=auth_headers(admin))
    assert response.status_code == 403


async def test_student_cannot_list_correct_or_hold(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Student authorization tenant")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-auth@evidence.example")
    student = await make_user(tenant, role="student", email="student-auth@evidence.example")
    event = await _create_event(db_session, tenant, methodologist, subject=student)

    list_response = await client.get("/api/v1/training-evidence/events", headers=auth_headers(student))
    assert list_response.status_code == 403
    correction_response = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/corrections",
        headers=auth_headers(student),
        json={
            "user_id": str(student.id),
            "procedure_type": "knowledge_check",
            "payload_snapshot": {"corrected": True},
            "reason": "Попытка исправления",
        },
    )
    assert correction_response.status_code == 403
    hold_response = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/legal-hold",
        headers=auth_headers(student),
        json={"action": "placed", "reason": "Попытка удержания"},
    )
    assert hold_response.status_code == 403


async def test_manual_create_route_is_controlled_and_does_not_accept_client_timestamps():
    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/training-evidence/events"]
    assert "post" not in paths["/api/v1/training-evidence/events/{event_id}/step-up-confirmations"]
    assert "occurred_at" not in EvidenceEventCreate.model_fields


async def test_public_mutation_schemas_do_not_accept_client_timestamps():
    assert "occurred_at" not in EvidenceCorrectionCreate.model_fields
    assert "occurred_at" not in EvidenceRevocationCreate.model_fields
    assert "occurred_at" not in LegalHoldCreate.model_fields
