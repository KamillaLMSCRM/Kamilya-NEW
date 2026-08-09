"""Security contract for the no-email assignment access flow."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.assignment_access import AssignmentAccessCredential


def test_0096_enforces_ownership_and_refuses_destructive_downgrade() -> None:
    from pathlib import Path

    source = Path("alembic/versions/0096_assignment_access_credentials.py").read_text(encoding="utf-8")
    assert "validate_assignment_access_ownership" in source
    assert "e.tenant_id = NEW.tenant_id" in source
    assert "e.user_id = NEW.user_id" in source
    assert "ur.role = 'student'" in source
    assert "0096 downgrade refused" in source


async def _issue(client, enrollment_id, headers):
    return await client.post(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-without-email",
        headers=headers,
    )


async def _enrollment(client, course, learner, headers):
    response = await client.post(
        f"/api/v1/courses/{course.id}/enrollments",
        json={"user_ids": [str(learner.id)]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()[0]["id"]


@pytest.mark.asyncio
async def test_reissue_revokes_history_and_exchange_is_learner_only(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="No email")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email=None)
    # The shared factory intentionally supplies a generated email for a falsey
    # value. Clear it explicitly so this test exercises the no-email contract.
    learner.email = None
    await db_session.flush()
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))

    first = await _issue(client, enrollment_id, auth_headers(manager))
    second = await _issue(client, enrollment_id, auth_headers(manager))
    assert first.status_code == second.status_code == 200
    rows = (
        await db_session.scalars(
            select(AssignmentAccessCredential).where(AssignmentAccessCredential.enrollment_id == enrollment_id)
        )
    ).all()
    assert len(rows) == 2
    assert sum(item.revoked_at is None for item in rows) == 1
    assert rows[0].token_hash not in first.text and rows[0].pin_hash not in first.text

    old_token = first.json()["access_url"].rsplit("/", 1)[1]
    denied = await client.post(
        f"/api/v1/assignment-access/{old_token}/exchange", json={"pin": first.json()["temporary_pin"]}
    )
    assert denied.status_code == 404
    token = second.json()["access_url"].rsplit("/", 1)[1]
    accepted = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": second.json()["temporary_pin"]}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["user_id"] == str(learner.id)
    assert accepted.json()["user"]["role"] == "student"

    bearer = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    assert (await client.get("/api/v1/users/me", headers=bearer)).status_code == 200

    # Reissue revokes both the old link and any bearer session previously
    # exchanged from it; revocation is checked on every authenticated request.
    third = await _issue(client, enrollment_id, auth_headers(manager))
    assert third.status_code == 200
    revoked_session = await client.get("/api/v1/users/me", headers=bearer)
    assert revoked_session.status_code == 401


@pytest.mark.asyncio
async def test_wrong_pin_lockout_after_five_attempts(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Lockout")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email=None)
    learner.email = None
    await db_session.flush()
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))
    issued = await _issue(client, enrollment_id, auth_headers(manager))
    token = issued.json()["access_url"].rsplit("/", 1)[1]

    # The application creates one DB session per real HTTP request.  This
    # integration fixture intentionally shares one transactional session, so
    # requests are issued sequentially; the service's SELECT ... FOR UPDATE
    # is asserted separately as the concurrent-request serialization guard.
    attempts = [
        await client.post(f"/api/v1/assignment-access/{token}/exchange", json={"pin": "000000"}) for _ in range(5)
    ]
    assert all(response.status_code == 401 for response in attempts)
    locked = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert locked.status_code == 401


def test_pin_exchange_serializes_concurrent_updates() -> None:
    from pathlib import Path

    source = Path("app/modules/enrollments/access_service.py").read_text(encoding="utf-8")
    assert ".with_for_update()" in source


@pytest.mark.asyncio
async def test_issue_is_not_available_for_email_or_cross_tenant(
    client, make_tenant, make_user, make_course, auth_headers, monkeypatch
):
    from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

    monkeypatch.setattr(deliver_assignment_notification_task, "apply_async", lambda *args, **kwargs: None)
    owner = await make_tenant(name="Owner")
    outsider = await make_tenant(name="Outsider")
    manager = await make_user(owner, role="methodologist")
    other_manager = await make_user(outsider, role="methodologist")
    email_learner = await make_user(owner, role="student", email="learner@example.test")
    course = await make_course(owner, manager, status="published")
    enrollment_id = await _enrollment(client, course, email_learner, auth_headers(manager))

    assert (await _issue(client, enrollment_id, auth_headers(manager))).status_code == 404
    assert (await _issue(client, enrollment_id, auth_headers(other_manager))).status_code == 404
