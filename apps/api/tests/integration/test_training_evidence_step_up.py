"""Integration coverage for purpose-bound learner step-up OTP."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.email import EmailService
from app.main import app
from app.modules.training_evidence import step_up_service
from app.modules.training_evidence.service import record_event

pytestmark = pytest.mark.asyncio


class _UnavailableRateLimiter:
    async def check_rate_limit(self, key, max_requests, window_seconds):
        return False, {"unavailable": True, "reset": 0, "remaining": 0, "limit": max_requests}


async def _no_redis():
    return None


async def _create_event(db_session, tenant, actor, subject, *, payload_snapshot=None):
    return await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        user_id=subject.id,
        procedure_type="knowledge_check",
        payload_snapshot=payload_snapshot
        or {
            "course": "Internal training",
            "release_version": "1",
            "confirmation": {
                "statement": "Подтверждаю прохождение курса",
                "object_version": "release:1",
            },
        },
    )


@pytest.fixture(autouse=True)
def isolated_step_up_state(monkeypatch):
    monkeypatch.setattr(step_up_service, "_get_redis", _no_redis)
    monkeypatch.setattr(step_up_service, "_rate_limiter", _UnavailableRateLimiter())
    monkeypatch.setattr(step_up_service, "_memory_challenges", {})
    monkeypatch.setattr(step_up_service, "_memory_rate_limits", {})


async def _request_code(client, student, event, auth_headers):
    response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_valid_step_up_is_consumed_and_replay_is_rejected(
    client, db_session, make_tenant, make_user, auth_headers, monkeypatch
):
    tenant = await make_tenant(name="Step-up valid")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-valid@example.test")
    student = await make_user(tenant, role="student", email="student-valid@example.test")
    event = await _create_event(db_session, tenant, methodologist, student)
    sent = {}

    async def fake_send(self, **kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(EmailService, "send_training_confirmation_code", fake_send)
    challenge = await _request_code(client, student, event, auth_headers)

    verify_payload = {"challenge_id": challenge["challenge_id"], "code": sent["code"]}
    response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/verify",
        headers=auth_headers(student),
        json=verify_payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["confirmed"] is True
    assert sent["company_name"] == tenant.name

    replay = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/verify",
        headers=auth_headers(student),
        json=verify_payload,
    )
    assert replay.status_code == 409
    assert replay.json()["details"]["code"] == "confirmation_already_exists"

    duplicate_request = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert duplicate_request.status_code == 409
    assert duplicate_request.json()["details"]["code"] == "confirmation_already_exists"


async def test_wrong_code_does_not_confirm_and_expired_code_is_rejected(
    client, db_session, make_tenant, make_user, auth_headers, monkeypatch
):
    tenant = await make_tenant(name="Step-up expiry")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-expiry@example.test")
    student = await make_user(tenant, role="student", email="student-expiry@example.test")
    event = await _create_event(db_session, tenant, methodologist, student)
    sent = {}

    async def fake_send(self, **kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(EmailService, "send_training_confirmation_code", fake_send)
    challenge = await _request_code(client, student, event, auth_headers)
    base = {"challenge_id": challenge["challenge_id"]}
    wrong = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/verify",
        headers=auth_headers(student),
        json={**base, "code": "000000"},
    )
    assert wrong.status_code == 401
    assert challenge["challenge_id"] in step_up_service._memory_challenges

    step_up_service._memory_challenges[challenge["challenge_id"]]["expires_at"] = 0
    expired = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/verify",
        headers=auth_headers(student),
        json={**base, "code": sent["code"]},
    )
    assert expired.status_code == 401


async def test_client_cannot_supply_action_or_version(
    client, db_session, make_tenant, make_user, auth_headers, monkeypatch
):
    tenant = await make_tenant(name="Step-up binding")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-binding@example.test")
    student = await make_user(tenant, role="student", email="student-binding@example.test")
    event = await _create_event(db_session, tenant, methodologist, student)
    sent = {}

    async def fake_send(self, **kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(EmailService, "send_training_confirmation_code", fake_send)
    request_with_client_values = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={"action_text": "Подтверждаю другой текст", "object_version": "release:999"},
    )
    assert request_with_client_values.status_code == 422

    challenge = await _request_code(client, student, event, auth_headers)
    tampered = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/verify",
        headers=auth_headers(student),
        json={
            "challenge_id": challenge["challenge_id"],
            "code": sent["code"],
            "action_text": "Подтверждаю другой текст",
            "object_version": "release:999",
        },
    )
    assert tampered.status_code == 422
    assert challenge["challenge_id"] in step_up_service._memory_challenges

    valid = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/verify",
        headers=auth_headers(student),
        json={"challenge_id": challenge["challenge_id"], "code": sent["code"]},
    )
    assert valid.status_code == 200, valid.text


@pytest.mark.parametrize("operator_role", ["admin", "methodologist"])
async def test_operator_cannot_request_or_verify_for_student(
    client, db_session, make_tenant, make_user, auth_headers, operator_role
):
    tenant = await make_tenant(name=f"Step-up {operator_role}")
    operator = await make_user(tenant, role=operator_role, email=f"{operator_role}@operator.example.test")
    student = await make_user(tenant, role="student", email=f"student-{operator_role}@example.test")
    event = await _create_event(db_session, tenant, operator, student)
    response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(operator),
        json={},
    )
    assert response.status_code == 403


async def test_different_subject_and_cross_tenant_are_rejected(
    client, db_session, make_tenant, make_user, auth_headers, monkeypatch
):
    tenant_a = await make_tenant(name="Step-up tenant A")
    methodologist_a = await make_user(tenant_a, role="methodologist", email="methodologist-a@example.test")
    student_a = await make_user(tenant_a, role="student", email="student-a@example.test")
    student_other = await make_user(tenant_a, role="student", email="student-other@example.test")
    event = await _create_event(db_session, tenant_a, methodologist_a, student_a)
    different_subject = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student_other),
        json={},
    )
    assert different_subject.status_code == 403

    tenant_b = await make_tenant(name="Step-up tenant B")
    student_b = await make_user(tenant_b, role="student", email="student-b@example.test")
    cross_tenant = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student_b),
        json={},
    )
    assert cross_tenant.status_code == 404


async def test_provider_failure_removes_challenge_and_does_not_expose_details(
    client, db_session, make_tenant, make_user, auth_headers, monkeypatch
):
    tenant = await make_tenant(name="Step-up provider failure")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-provider@example.test")
    student = await make_user(tenant, role="student", email="student-provider@example.test")
    event = await _create_event(db_session, tenant, methodologist, student)

    async def failed_send(self, **kwargs):
        raise RuntimeError("provider secret must not escape")

    monkeypatch.setattr(EmailService, "send_training_confirmation_code", failed_send)
    response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert response.status_code == 503
    assert "provider secret" not in response.text
    assert not step_up_service._memory_challenges


async def test_missing_or_mismatched_confirmation_config_returns_conflict(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Step-up configuration")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-config@example.test")
    student = await make_user(tenant, role="student", email="student-config@example.test")

    missing = await _create_event(
        db_session,
        tenant,
        methodologist,
        student,
        payload_snapshot={"course": "Internal training", "release_version": "1"},
    )
    missing_response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{missing.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert missing_response.status_code == 409
    assert missing_response.json()["details"]["code"] == "confirmation_not_configured"

    mismatched = await _create_event(
        db_session,
        tenant,
        methodologist,
        student,
        payload_snapshot={
            "course": "Internal training",
            "release_version": "2",
            "confirmation": {"statement": "Подтверждаю", "object_version": "release:1"},
        },
    )
    mismatch_response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{mismatched.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert mismatch_response.status_code == 409
    assert mismatch_response.json()["details"]["code"] == "confirmation_not_configured"


async def test_revoked_event_cannot_be_confirmed(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Step-up revoked")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-revoked@example.test")
    student = await make_user(tenant, role="student", email="student-revoked@example.test")
    event = await _create_event(db_session, tenant, methodologist, student)
    await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=student.id,
        procedure_type=event.procedure_type,
        payload_snapshot={"revoked_event_id": str(event.id)},
        record_type="revocation",
        related_event_id=event.id,
        reason="Correction required",
    )

    response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert response.status_code == 409
    assert response.json()["details"]["code"] == "event_revoked"


async def test_descendant_revocation_blocks_confirmation_of_original(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Step-up descendant revocation")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist-descendant-revoked@example.test",
    )
    student = await make_user(
        tenant,
        role="student",
        email="student-descendant-revoked@example.test",
    )
    event = await _create_event(db_session, tenant, methodologist, student)
    correction = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=student.id,
        procedure_type=event.procedure_type,
        payload_snapshot={**event.payload_snapshot, "correction": "Updated wording"},
        record_type="correction",
        related_event_id=event.id,
        reason="Clarify the recorded wording",
    )
    await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=student.id,
        procedure_type=event.procedure_type,
        payload_snapshot={"revoked_event_id": str(correction.id)},
        record_type="revocation",
        related_event_id=correction.id,
        reason="Correction is invalid",
    )

    response = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={},
    )

    assert response.status_code == 409
    assert response.json()["details"]["code"] == "event_revoked"


async def test_rate_limit_is_applied_and_otp_is_not_logged(
    client, db_session, make_tenant, make_user, auth_headers, monkeypatch, caplog
):
    tenant = await make_tenant(name="Step-up rate limit")
    methodologist = await make_user(tenant, role="methodologist", email="methodologist-rate@example.test")
    student = await make_user(tenant, role="student", email="student-rate@example.test")
    event = await _create_event(db_session, tenant, methodologist, student)
    sent = {}

    async def fake_send(self, **kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(EmailService, "send_training_confirmation_code", fake_send)
    monkeypatch.setattr(step_up_service, "STEP_UP_RATE_LIMIT", 1)
    with caplog.at_level("INFO"):
        first = await _request_code(client, student, event, auth_headers)
    assert first["challenge_id"]
    assert sent["code"] not in caplog.text

    second = await client.post(
        f"/api/v1/training-evidence/step-up/events/{event.id}/request",
        headers=auth_headers(student),
        json={},
    )
    assert second.status_code == 429


async def test_router_is_registered_once_in_main():
    path = "/api/v1/training-evidence/step-up/events/{event_id}/request"
    assert path in app.openapi()["paths"]
    assert set(app.openapi()["paths"][path]) == {"post"}
    main_source = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    assert "training_evidence_step_up_router" in main_source
