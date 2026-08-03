"""Focused invitation RBAC and lifecycle regression coverage."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.auth import require_role
from app.modules.users.schemas import InvitationBulkCreateRequest


def _user(*, tenant_id=None, role="methodologist"):
    return SimpleNamespace(id=uuid4(), tenant_id=tenant_id or uuid4(), role=role)


@pytest.mark.asyncio
async def test_methodologist_passes_invitation_role_guard():
    checker = require_role("methodologist")
    user = _user()

    assert await checker(user) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "student"])
async def test_non_owning_roles_are_forbidden_from_invitation_mutations(role):
    checker = require_role("methodologist")

    with pytest.raises(HTTPException) as exc_info:
        await checker(_user(role=role))

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_methodologist_can_create_student_invitation_in_non_demo_tenant():
    from app.modules.users.router import bulk_invite_users

    user = _user()
    db = AsyncMock()
    created = {
        "created": [{
            "email": "learner@example.kz",
            "invitation_id": uuid4(),
            "invite_url": "https://app.kml.kz/accept-invite?token=test",
            "expires_at": "2026-07-26T00:00:00Z",
        }],
        "skipped_existing": [],
        "invalid": [],
    }

    with (
        patch("app.core.demo_limits.assert_can_send_invite", new=AsyncMock()) as demo_guard,
        patch("app.core.trial_limits.assert_can_create_learners", new=AsyncMock()) as learner_guard,
        patch("app.modules.users.router.bulk_create_invitations", new=AsyncMock(return_value=created)) as create,
        patch("app.modules.users.tasks.deliver_invitation_task.apply_async") as enqueue,
    ):
        response = await bulk_invite_users(
            payload=InvitationBulkCreateRequest(items=[{"email": "learner@example.kz"}]),
            db=db,
            user=user,
        )

    demo_guard.assert_awaited_once_with(db, user.tenant_id)
    learner_guard.assert_awaited_once_with(db, user.tenant_id, requested=1)
    create.assert_awaited_once()
    assert response.created[0].email == "learner@example.kz"
    assert response.created[0].invite_url.endswith("token=test")
    enqueue.assert_called_once_with(
        args=[str(user.tenant_id), str(created["created"][0]["invitation_id"])],
        retry=False,
    )
    assert response.created[0].delivery_status == "pending"


@pytest.mark.asyncio
async def test_methodologist_creates_link_for_exact_selected_user_id():
    from app.modules.users.router import create_user_invitation_link

    user = _user()
    target_user_id = uuid4()
    db = AsyncMock()
    expected = {
        "email": "learner@example.kz",
        "invitation_id": uuid4(),
        "invite_url": "https://app.kml.kz/accept-invite?token=exact",
        "expires_at": "2026-08-03T00:00:00Z",
        "superseded_old_id": None,
    }

    with (
        patch("app.core.demo_limits.assert_can_send_invite", new=AsyncMock()) as demo_guard,
        patch(
            "app.modules.users.router.create_or_refresh_user_invitation",
            new=AsyncMock(return_value=expected),
        ) as create,
        patch(
            "app.modules.users.router.attempt_invitation_delivery",
            new=AsyncMock(return_value={
                "delivery_status": "pending",
                "delivery_message_id": None,
                "delivery_last_attempt_at": None,
                "delivery_attempt_count": 0,
                "delivery_failure_category": None,
                "delivery_failure_message": None,
            }),
        ),
    ):
        response = await create_user_invitation_link(
            user_id=target_user_id,
            db=db,
            user=user,
        )

    demo_guard.assert_awaited_once_with(db, user.tenant_id)
    create.assert_awaited_once_with(
        db,
        tenant_id=user.tenant_id,
        invited_by=user.id,
        user_id=target_user_id,
        base_url=ANY,
    )
    assert response["invite_url"].endswith("token=exact")


@pytest.mark.asyncio
async def test_batch_invitation_creation_reports_partial_delivery_without_rollback():
    from app.modules.users.router import bulk_invite_users

    user = _user()
    created = {
        "created": [
            {
                "email": "one@example.kz",
                "invitation_id": uuid4(),
                "invite_url": "https://app.kml.kz/accept-invite?token=one",
                "expires_at": "2026-08-04T00:00:00Z",
            },
            {
                "email": "two@example.kz",
                "invitation_id": uuid4(),
                "invite_url": "https://app.kml.kz/accept-invite?token=two",
                "expires_at": "2026-08-04T00:00:00Z",
            },
        ],
        "skipped_existing": [],
        "invalid": [],
    }
    with (
        patch("app.core.demo_limits.assert_can_send_invite", new=AsyncMock()),
        patch("app.core.trial_limits.assert_can_create_learners", new=AsyncMock()),
        patch("app.modules.users.router.bulk_create_invitations", new=AsyncMock(return_value=created)),
        patch("app.modules.users.tasks.deliver_invitation_task.apply_async") as enqueue,
    ):
        response = await bulk_invite_users(
            payload=InvitationBulkCreateRequest(
                items=[{"email": "one@example.kz"}, {"email": "two@example.kz"}]
            ),
            db=AsyncMock(),
            user=user,
        )

    assert [item.delivery_status for item in response.created] == ["pending", "pending"]
    assert enqueue.call_count == 2
    assert all(call.kwargs["retry"] is False for call in enqueue.call_args_list)


@pytest.mark.asyncio
async def test_bulk_queue_failure_keeps_manual_link_fallback_honest():
    from app.modules.users.router import bulk_invite_users

    user = _user()
    invitation_id = uuid4()
    created = {
        "created": [{
            "email": "learner@example.kz",
            "invitation_id": invitation_id,
            "invite_url": "https://app.kml.kz/accept-invite?token=one",
            "expires_at": "2026-08-04T00:00:00Z",
        }],
        "skipped_existing": [],
        "invalid": [],
    }
    db = AsyncMock()

    with (
        patch("app.core.demo_limits.assert_can_send_invite", new=AsyncMock()),
        patch("app.core.trial_limits.assert_can_create_learners", new=AsyncMock()),
        patch("app.modules.users.router.bulk_create_invitations", new=AsyncMock(return_value=created)),
        patch(
            "app.modules.users.tasks.deliver_invitation_task.apply_async",
            side_effect=RuntimeError("broker unavailable"),
        ),
    ):
        response = await bulk_invite_users(
            payload=InvitationBulkCreateRequest(items=[{"email": "learner@example.kz"}]),
            db=db,
            user=user,
        )

    assert response.created[0].delivery_status == "pending"
    assert response.created[0].delivery_failure_category == "queue_unavailable"
    assert "activation link" in response.created[0].delivery_failure_message
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_tenant_resend_is_not_disclosed():
    from app.modules.users.invitations_service import resend_invitation

    tenant_a, tenant_b = uuid4(), uuid4()
    invitation = SimpleNamespace(id=uuid4(), tenant_id=tenant_b)
    db = SimpleNamespace(get=AsyncMock(return_value=invitation))

    with pytest.raises(HTTPException) as exc_info:
        await resend_invitation(db, tenant_a, invitation.id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Invitation not found"


@pytest.mark.asyncio
async def test_expired_invitation_can_be_resent_once_then_old_link_is_superseded():
    from app.modules.users.invitations_service import resend_invitation

    tenant_id = uuid4()
    old = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="learner@example.kz",
        first_name="",
        last_name="",
        role="student",
        invited_by=uuid4(),
        user_id=uuid4(),
        status="expired",
        superseded_by=None,
    )
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = None
    db = SimpleNamespace(
        get=AsyncMock(return_value=old),
        execute=AsyncMock(return_value=settings_result),
        add=MagicMock(),
        commit=AsyncMock(),
    )

    result = await resend_invitation(db, tenant_id, old.id, base_url="https://app.kml.kz")

    assert old.status == "superseded"
    assert old.superseded_by == result["invitation_id"]
    assert result["invite_url"].startswith("https://app.kml.kz/accept-invite?token=")
    db.commit.assert_awaited_once()

    with pytest.raises(HTTPException) as exc_info:
        await resend_invitation(db, tenant_id, old.id)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_delivery_success_records_provider_acceptance_without_token_fields():
    from app.modules.users.invitations_service import attempt_invitation_delivery

    tenant_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="learner@example.kz",
        first_name="Learner",
        last_name="One",
        delivery_status="pending",
        delivery_message_id=None,
        delivery_last_attempt_at=None,
        delivery_attempt_count=0,
        delivery_failure_category=None,
        delivery_failure_message=None,
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[Result(None), Result(invitation), Result("Test company"), Result("kk")]
        ),
        commit=AsyncMock(),
    )

    with (
        patch("app.modules.users.invitations_service.EmailService.delivery_ready", return_value=True),
        patch(
            "app.modules.users.invitations_service.EmailService.send_invitation_link",
            new=AsyncMock(return_value="msg_123"),
        ) as send,
    ):
        result = await attempt_invitation_delivery(
            db,
            tenant_id=tenant_id,
            invitation_id=invitation.id,
            invite_url="https://app.kml.kz/accept-invite?token=opaque",
        )

    assert result["delivery_status"] == "sent"
    assert result["delivery_message_id"] == "msg_123"
    assert invitation.delivery_attempt_count == 1
    assert invitation.delivery_failure_message is None
    send.assert_awaited_once()
    assert send.await_args.kwargs["language"] == "kk"
    assert "token" not in result


@pytest.mark.asyncio
async def test_delivery_failure_records_safe_category_and_message():
    from app.core.email import EmailDeliveryError
    from app.modules.users.invitations_service import attempt_invitation_delivery

    tenant_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="learner@example.kz",
        first_name="",
        last_name="",
        delivery_status="pending",
        delivery_message_id=None,
        delivery_last_attempt_at=None,
        delivery_attempt_count=0,
        delivery_failure_category=None,
        delivery_failure_message=None,
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[Result(None), Result(invitation), Result("Test company"), Result(None)]
        ),
        commit=AsyncMock(),
    )

    with (
        patch("app.modules.users.invitations_service.EmailService.delivery_ready", return_value=True),
        patch(
            "app.modules.users.invitations_service.EmailService.send_invitation_link",
            new=AsyncMock(
                side_effect=EmailDeliveryError(
                    "provider_rejected",
                    "The email provider rejected the message (HTTP 422).",
                )
            ),
        ),
    ):
        result = await attempt_invitation_delivery(
            db,
            tenant_id=tenant_id,
            invitation_id=invitation.id,
            invite_url="https://app.kml.kz/accept-invite?token=opaque",
        )

    assert result["delivery_status"] == "failed"
    assert result["delivery_failure_category"] == "provider_rejected"
    assert result["delivery_failure_message"] == "The email provider rejected the message (HTTP 422)."
    assert invitation.delivery_attempt_count == 1
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_tenant_delivery_attempt_is_not_disclosed():
    from app.modules.users.invitations_service import attempt_invitation_delivery

    tenant_a, tenant_b = uuid4(), uuid4()

    class Result:
        def scalar_one_or_none(self):
            return None

    db = SimpleNamespace(execute=AsyncMock(side_effect=[Result(), Result()]))

    with pytest.raises(HTTPException) as exc_info:
        await attempt_invitation_delivery(
            db,
            tenant_id=tenant_a,
            invitation_id=uuid4(),
            invite_url="https://app.kml.kz/accept-invite?token=opaque",
        )

    assert tenant_a != tenant_b
    assert exc_info.value.status_code == 404
