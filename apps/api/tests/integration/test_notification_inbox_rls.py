"""Database-backed tenant and recipient isolation checks for notifications."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

# Register the Enrollment mapper before flushing WorkflowWorkItem, whose
# optional enrollment_id foreign key is resolved by SQLAlchemy's metadata.
from app.models.enrollment import Enrollment  # noqa: F401


async def _make_delivery(
    db_session: Any,
    tenant: Any,
    recipient: Any,
    make_course: Any,
    set_current_tenant: Any,
) -> Any:
    from app.modules.course_approval.models import (
        CourseApprovalRevision,
        WorkflowDelivery,
        WorkflowWorkItem,
    )

    course = await make_course(tenant, recipient)
    revision = CourseApprovalRevision(
        tenant_id=tenant.id,
        course_id=course.id,
        revision_number=1,
        snapshot={"course": {"id": str(course.id)}, "modules": []},
        snapshot_sha256="0" * 64,
        source_fingerprint="1" * 64,
        created_by=recipient.id,
    )
    await set_current_tenant(tenant)
    db_session.add(revision)
    await db_session.flush()

    work_item = WorkflowWorkItem(
        tenant_id=tenant.id,
        kind="reviewer",
        target_user_id=recipient.id,
        review_revision_id=revision.id,
    )
    db_session.add(work_item)
    await db_session.flush()

    delivery = WorkflowDelivery(
        tenant_id=tenant.id,
        work_item_id=work_item.id,
        channel="cabinet",
        message_kind="course_review_assigned",
        recipient_user_id=recipient.id,
    )
    db_session.add(delivery)
    await db_session.flush()
    return delivery


async def _make_notification(
    db_session: Any,
    tenant: Any,
    recipient: Any,
    source_delivery: Any,
    set_current_tenant: Any,
    *,
    read_at: Any = None,
) -> Any:
    from app.modules.notifications.models import NotificationInboxItem

    await set_current_tenant(tenant)
    await db_session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(recipient.id)},
    )
    item = NotificationInboxItem(
        tenant_id=tenant.id,
        recipient_user_id=recipient.id,
        source_delivery_id=source_delivery.id,
        kind="course_review_assigned",
        context={"course_title": "Test course", "due_at": None},
        action_path=f"/course-review-requests/{uuid4()}",
        read_at=read_at,
    )
    db_session.add(item)
    await db_session.flush()
    return item


@pytest.mark.asyncio
async def test_notification_http_is_scoped_to_authenticated_principal_and_tenant(
    client,
    auth_headers,
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="Notification tenant A")
    tenant_b = await make_tenant(name="Notification tenant B")
    user_a = await make_user(tenant_a, role="student")
    user_b = await make_user(tenant_a, role="student")
    user_cross_tenant = await make_user(tenant_b, role="student")

    delivery_b = await _make_delivery(
        db_session, tenant_a, user_b, make_course, set_current_tenant
    )
    notification_b = await _make_notification(
        db_session, tenant_a, user_b, delivery_b, set_current_tenant
    )
    delivery_cross_tenant = await _make_delivery(
        db_session,
        tenant_b,
        user_cross_tenant,
        make_course,
        set_current_tenant,
    )
    notification_cross_tenant = await _make_notification(
        db_session,
        tenant_b,
        user_cross_tenant,
        delivery_cross_tenant,
        set_current_tenant,
    )

    listed = await client.get(
        "/api/v1/notifications",
        headers=auth_headers(user_a),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"items": [], "unread_count": 0}

    for inaccessible_id in (
        notification_b.id,
        notification_cross_tenant.id,
        uuid4(),
    ):
        read = await client.post(
            f"/api/v1/notifications/{inaccessible_id}/read",
            headers=auth_headers(user_a),
        )
        assert read.status_code == 404, read.text

    assert await db_session.scalar(
        text("SELECT read_at FROM notification_inbox WHERE id=:notification_id"),
        {"notification_id": notification_b.id},
    ) is None


@pytest.mark.asyncio
async def test_runtime_role_rejects_cross_tenant_notification_inbox_insert(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
):
    tenant_a = await make_tenant(name="Notification insert tenant A")
    tenant_b = await make_tenant(name="Notification insert tenant B")
    user_a = await make_user(tenant_a, role="student")
    delivery_a = await _make_delivery(
        db_session, tenant_a, user_a, make_course, set_current_tenant
    )

    # Managed PostgreSQL can provide separate migration and runtime
    # credentials while deliberately denying the migration owner SET ROLE.
    # Keep this transaction-isolated test authoritative where role switching
    # is supported; dedicated-runtime environments are verified through their
    # lms_app connection instead of treating that provider boundary as an RLS
    # failure.
    role_probe = await db_session.begin_nested()
    try:
        await db_session.execute(text("SET LOCAL ROLE lms_app"))
    except ProgrammingError:
        await role_probe.rollback()
        pytest.skip("configured migration owner cannot SET ROLE lms_app")
    else:
        await role_probe.commit()
    await set_current_tenant(tenant_b)
    await db_session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_a.id)},
    )
    notification_id = uuid4()

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO notification_inbox "
                    "(id, tenant_id, recipient_user_id, source_delivery_id, "
                    "kind, context, action_path) VALUES "
                    "(:id, :tenant_id, :recipient_user_id, :source_delivery_id, "
                    "'course_review_assigned', '{\"course_title\": \"Test\", "
                    "\"due_at\": null}'::jsonb, :action_path)"
                ),
                {
                    "id": notification_id,
                    "tenant_id": tenant_a.id,
                    "recipient_user_id": user_a.id,
                    "source_delivery_id": delivery_a.id,
                    "action_path": f"/course-review-requests/{uuid4()}",
                },
            )

    await db_session.execute(text("RESET ROLE"))
    assert await db_session.scalar(
        text("SELECT count(*) FROM notification_inbox WHERE id=:notification_id"),
        {"notification_id": notification_id},
    ) == 0


@pytest.mark.asyncio
async def test_notification_inbox_trigger_rejects_source_recipient_mismatch(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
):
    from app.modules.notifications.models import NotificationInboxItem

    tenant = await make_tenant(name="Notification trigger tenant")
    source_recipient = await make_user(tenant, role="student")
    wrong_recipient = await make_user(tenant, role="student")
    delivery = await _make_delivery(
        db_session, tenant, source_recipient, make_course, set_current_tenant
    )

    await set_current_tenant(tenant)
    await db_session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(wrong_recipient.id)},
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                NotificationInboxItem(
                    tenant_id=tenant.id,
                    recipient_user_id=wrong_recipient.id,
                    source_delivery_id=delivery.id,
                    kind="course_review_assigned",
                    context={"course_title": "Test course", "due_at": None},
                    action_path=f"/course-review-requests/{uuid4()}",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context", "action_path"),
    [
        ({"course_title": "Test", "due_at": None, "pin": "1234"}, "/course-review-requests/00000000-0000-4000-8000-000000000000"),
        ({"course_title": "Test", "due_at": None}, "https://evil.example/review"),
        ({"course_title": "Test", "due_at": None}, "/course-review-requests/../admin"),
    ],
)
async def test_notification_inbox_rejects_unsafe_persisted_payload(
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
    context,
    action_path,
):
    from app.modules.notifications.models import NotificationInboxItem

    tenant = await make_tenant(name="Notification safe payload tenant")
    recipient = await make_user(tenant, role="student")
    delivery = await _make_delivery(db_session, tenant, recipient, make_course, set_current_tenant)
    await set_current_tenant(tenant)
    await db_session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(recipient.id)},
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(NotificationInboxItem(
                tenant_id=tenant.id,
                recipient_user_id=recipient.id,
                source_delivery_id=delivery.id,
                kind="course_review_assigned",
                context=context,
                action_path=action_path,
            ))
            await db_session.flush()


@pytest.mark.asyncio
async def test_notification_read_all_updates_only_authenticated_recipient(
    client,
    auth_headers,
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
):
    from app.modules.notifications.models import NotificationInboxItem

    tenant = await make_tenant(name="Notification read-all tenant")
    user_a = await make_user(tenant, role="student")
    user_b = await make_user(tenant, role="student")

    delivery_a_1 = await _make_delivery(
        db_session, tenant, user_a, make_course, set_current_tenant
    )
    notification_a_1 = await _make_notification(
        db_session, tenant, user_a, delivery_a_1, set_current_tenant
    )
    delivery_a_2 = await _make_delivery(
        db_session, tenant, user_a, make_course, set_current_tenant
    )
    notification_a_2 = await _make_notification(
        db_session, tenant, user_a, delivery_a_2, set_current_tenant
    )
    delivery_b = await _make_delivery(
        db_session, tenant, user_b, make_course, set_current_tenant
    )
    notification_b = await _make_notification(
        db_session, tenant, user_b, delivery_b, set_current_tenant
    )

    read_all = await client.post(
        "/api/v1/notifications/read-all",
        headers=auth_headers(user_a),
    )
    assert read_all.status_code == 200, read_all.text
    assert read_all.json() == {"updated": 2, "unread_count": 0}

    rows = (
        await db_session.scalars(
            select(NotificationInboxItem).where(
                NotificationInboxItem.id.in_(
                    [notification_a_1.id, notification_a_2.id, notification_b.id]
                )
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    assert by_id[notification_a_1.id].read_at is not None
    assert by_id[notification_a_2.id].read_at is not None
    other_recipient_row = by_id.get(notification_b.id)
    assert other_recipient_row is None or other_recipient_row.read_at is None

    user_b_list = await client.get(
        "/api/v1/notifications",
        headers=auth_headers(user_b),
    )
    assert user_b_list.status_code == 200, user_b_list.text
    assert user_b_list.json()["unread_count"] == 1
    assert user_b_list.json()["items"][0]["id"] == str(notification_b.id)
    assert user_b_list.json()["items"][0]["read_at"] is None
