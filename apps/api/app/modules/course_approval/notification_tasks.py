"""Durable course-review delivery, retry, reminder, and escalation workers."""

# Celery task decorators are untyped third-party callables and the ORM models
# use legacy declarative descriptors; application security remains runtime/RLS
# enforced.  Keep the worker boundary explicit without masking task behavior.
# mypy: disable-error-code="arg-type,assignment,attr-defined,misc,no-any-return,no-untyped-call,no-untyped-def,type-arg,untyped-decorator"

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.auth import _set_tenant_security_context
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.core.email import EmailDeliveryError, EmailService
from app.models.courses import Course
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.integrations.crypto import decrypt_config, encrypt_config
from app.modules.notifications import WorkflowNotificationIntentV1, materialize_notification

from .models import (
    CourseApprovalRequest,
    CourseApprovalReviewer,
    CourseApprovalRevision,
    WorkflowDelivery,
    WorkflowEscalation,
    WorkflowReminder,
    WorkflowWorkItem,
)

TRANSIENT_EMAIL_CATEGORIES = frozenset({"provider_timeout", "provider_unreachable", "provider_rate_limited", "provider_unavailable"})


async def _claim_delivery(db, *, tenant_id: UUID, delivery_id: UUID) -> WorkflowDelivery | None:
    now = datetime.now(UTC)
    delivery = await db.scalar(select(WorkflowDelivery).where(
        WorkflowDelivery.id == delivery_id,
        WorkflowDelivery.tenant_id == tenant_id,
        or_(
            and_(
                WorkflowDelivery.status.in_(("queued", "failed")),
                WorkflowDelivery.attempt_count < 8,
                or_(WorkflowDelivery.next_attempt_at.is_(None), WorkflowDelivery.next_attempt_at <= now),
            ),
            and_(WorkflowDelivery.status == "accepted", WorkflowDelivery.next_attempt_at <= now),
        ),
    ).with_for_update(skip_locked=True))
    if delivery is None:
        return None
    if delivery.status == "accepted" and delivery.attempt_count >= 8:
        delivery.status = "terminal"
        delivery.error_category = "claim_lease_exhausted"
        delivery.claim_token = None
        delivery.next_attempt_at = None
        await db.commit()
        return None
    delivery.status = "accepted"
    delivery.claim_token = uuid4()
    delivery.attempt_count += 1
    delivery.next_attempt_at = now + timedelta(minutes=5)
    await db.commit()
    return delivery


async def deliver_workflow_delivery(*, tenant_id: UUID, delivery_id: UUID) -> dict[str, str]:
    async with async_session_factory() as db:
        await _set_tenant_security_context(db, str(tenant_id))
        delivery = await _claim_delivery(db, tenant_id=tenant_id, delivery_id=delivery_id)
        if delivery is None:
            return {"status": "skipped"}
        await _set_tenant_security_context(db, str(tenant_id))
        row = (await db.execute(select(WorkflowDelivery, WorkflowWorkItem, CourseApprovalRevision, Course, CourseApprovalRequest).join(
            WorkflowWorkItem, WorkflowWorkItem.id == WorkflowDelivery.work_item_id
        ).join(CourseApprovalRevision, CourseApprovalRevision.id == WorkflowWorkItem.review_revision_id
        ).join(Course, Course.id == CourseApprovalRevision.course_id
        ).join(CourseApprovalRequest, CourseApprovalRequest.revision_id == CourseApprovalRevision.id).where(
            WorkflowDelivery.id == delivery.id,
            WorkflowDelivery.tenant_id == tenant_id,
            WorkflowWorkItem.tenant_id == tenant_id,
            CourseApprovalRevision.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
        ))).one_or_none()
        if row is None:
            delivery.status = "terminal"
            delivery.error_category = "binding_missing"
            delivery.claim_token = None
            delivery.next_attempt_at = None
            await db.commit()
            return {"status": "terminal"}
        stored_delivery, work_item, revision, course, approval_request = row
        if work_item.outcome != "pending" or work_item.deadline_state == "closed":
            stored_delivery.status = "terminal"
            stored_delivery.error_category = "workflow_terminal"
            stored_delivery.claim_token = None
            stored_delivery.next_attempt_at = None
            await db.commit()
            return {"status": "terminal"}
        if stored_delivery.channel == "cabinet":
            if stored_delivery.recipient_user_id is None:
                stored_delivery.status = "terminal"
                stored_delivery.error_category = "recipient_missing"
                stored_delivery.claim_token = None
                stored_delivery.next_attempt_at = None
                await db.commit()
                return {"status": "terminal"}
            kind = stored_delivery.message_kind if stored_delivery.message_kind != "invitation" else "course_review_assigned"
            action_path = f"/course-review-requests/{approval_request.id}" if kind != "course_review_overdue" else f"/admin/course-approvals?courseId={course.id}"
            await materialize_notification(db, WorkflowNotificationIntentV1(
                tenant_id=tenant_id, recipient_user_id=stored_delivery.recipient_user_id,
                source_delivery_id=stored_delivery.id, kind=kind, course_title=course.title,
                due_at=work_item.due_at, action_path=action_path,
            ))
            stored_delivery.status = "delivered"
            stored_delivery.claim_token = None
            stored_delivery.next_attempt_at = None
            work_item.delivery_state = "delivered"
            await db.commit()
            return {"status": "delivered"}
        if stored_delivery.payload_encrypted is None and stored_delivery.message_kind != "course_review_overdue":
            stored_delivery.status = "terminal"
            stored_delivery.error_category = "secret_missing"
            stored_delivery.claim_token = None
            stored_delivery.next_attempt_at = None
            await db.commit()
            return {"status": "terminal"}
        payload: dict[str, object] = {}
        if stored_delivery.payload_encrypted is not None:
            try:
                payload = decrypt_config(bytes(stored_delivery.payload_encrypted))
            except Exception:
                stored_delivery.status = "terminal"
                stored_delivery.error_category = "secret_invalid"
                stored_delivery.claim_token = None
                stored_delivery.next_attempt_at = None
                await db.commit()
                return {"status": "terminal"}
        recipient = stored_delivery.recipient_email
        if not recipient and stored_delivery.recipient_user_id is not None:
            recipient = await db.scalar(select(User.email).where(User.id == stored_delivery.recipient_user_id, User.tenant_id == tenant_id, User.is_active.is_(True)))
        if not recipient:
            stored_delivery.status = "terminal"
            stored_delivery.error_category = "email_missing"
            stored_delivery.claim_token = None
            stored_delivery.next_attempt_at = None
            await db.commit()
            return {"status": "terminal"}
        reviewer_name = await db.scalar(select(CourseApprovalReviewer.reviewer_name).where(
            CourseApprovalReviewer.revision_id == revision.id,
            CourseApprovalReviewer.tenant_id == tenant_id,
            (CourseApprovalReviewer.reviewer_user_id == work_item.target_user_id) if work_item.target_user_id is not None else (CourseApprovalReviewer.reviewer_email == recipient),
        ))
        try:
            if stored_delivery.message_kind == "course_review_reminder":
                message_id = await EmailService().send_course_review_reminder(
                    to_email=recipient, reviewer_name=reviewer_name, course_title=course.title,
                    access_url=str(payload["access_url"]), due_at=work_item.due_at,
                    idempotency_key=f"course-review-reminder/{stored_delivery.id}/{stored_delivery.generation}",
                )
            elif stored_delivery.message_kind == "course_review_overdue":
                requester_name = await db.scalar(select(User.first_name).where(User.id == approval_request.requested_by, User.tenant_id == tenant_id))
                message_id = await EmailService().send_course_review_escalation(
                    to_email=recipient, requester_name=requester_name, course_title=course.title,
                    action_url=f"{get_settings().PUBLIC_URL.rstrip('/')}/admin/course-approvals?courseId={course.id}", due_at=work_item.due_at,
                    idempotency_key=f"course-review-escalation/{stored_delivery.id}/{stored_delivery.generation}",
                )
            else:
                message_id = await EmailService().send_course_review_invitation(
                    to_email=recipient, reviewer_name=reviewer_name, course_title=course.title,
                    access_url=str(payload["access_url"]), pin=str(payload["pin"]),
                    idempotency_key=f"course-review/{stored_delivery.id}/{stored_delivery.generation}",
                )
        except EmailDeliveryError as exc:
            stored_delivery.status = "terminal" if exc.category not in TRANSIENT_EMAIL_CATEGORIES else "failed"
            stored_delivery.error_category = exc.category[:64]
            stored_delivery.claim_token = None
            stored_delivery.next_attempt_at = datetime.now(UTC) + timedelta(minutes=min(60, 2 ** min(stored_delivery.attempt_count, 6))) if exc.category in TRANSIENT_EMAIL_CATEGORIES else None
            await db.commit()
            return {"status": "failed" if exc.category in TRANSIENT_EMAIL_CATEGORIES else "terminal"}
        except Exception:
            stored_delivery.status = "terminal"
            stored_delivery.error_category = "internal_error"
            stored_delivery.claim_token = None
            stored_delivery.next_attempt_at = None
            await db.commit()
            return {"status": "terminal"}
        stored_delivery.status = "delivered"
        stored_delivery.provider_message_id = message_id
        stored_delivery.error_category = None
        stored_delivery.claim_token = None
        stored_delivery.next_attempt_at = None
        work_item.delivery_state = "delivered"
        await log_action(db, tenant_id, "course_approval.delivery_delivered", "workflow_delivery", stored_delivery.id, None, {"channel": stored_delivery.channel, "generation": stored_delivery.generation})
        await db.commit()
        return {"status": "delivered"}


async def recover_workflow_deliveries(limit: int = 100) -> dict[str, int]:
    bounded = max(1, min(limit, 100))
    recovery_url = get_settings().ASSIGNMENT_RECOVERY_DATABASE_URL
    if not recovery_url:
        raise RuntimeError("ASSIGNMENT_RECOVERY_DATABASE_URL is required for global course-approval recovery")
    recovery_engine = create_async_engine(recovery_url, poolclass=NullPool)
    recovery_sessions = async_sessionmaker(recovery_engine, expire_on_commit=False)
    try:
        async with recovery_sessions() as db:
            rows = (await db.execute(text("SELECT tenant_id, id FROM due_course_approval_deliveries(:limit)"), {"limit": bounded})).all()
    finally:
        await recovery_engine.dispose()
    processed = 0
    for tenant_id, delivery_id in rows:
        await deliver_workflow_delivery(tenant_id=tenant_id, delivery_id=delivery_id)
        processed += 1
    return {"due": len(rows), "processed": processed}


async def recover_workflow_deadlines(limit: int = 100) -> dict[str, int]:
    bounded = max(1, min(limit, 100))
    recovery_url = get_settings().ASSIGNMENT_RECOVERY_DATABASE_URL
    if not recovery_url:
        raise RuntimeError("ASSIGNMENT_RECOVERY_DATABASE_URL is required for global course-approval deadline recovery")
    recovery_engine = create_async_engine(recovery_url, poolclass=NullPool)
    recovery_sessions = async_sessionmaker(recovery_engine, expire_on_commit=False)
    try:
        async with recovery_sessions() as recovery_db:
            due_rows = (await recovery_db.execute(text("SELECT kind, tenant_id, id FROM due_course_approval_deadlines(:limit)"), {"limit": bounded})).all()
    finally:
        await recovery_engine.dispose()
    reminder_count = 0
    escalation_count = 0
    async with async_session_factory() as db:
        for kind, tenant_id, deadline_id in due_rows:
            await _set_tenant_security_context(db, str(tenant_id))
            if kind == "reminder":
                row = await db.scalar(select(WorkflowReminder).where(WorkflowReminder.id == deadline_id, WorkflowReminder.tenant_id == tenant_id).with_for_update(skip_locked=True))
            else:
                row = await db.scalar(select(WorkflowEscalation).where(WorkflowEscalation.id == deadline_id, WorkflowEscalation.tenant_id == tenant_id).with_for_update(skip_locked=True))
            if row is None or row.status != "queued":
                continue
            item = await db.scalar(select(WorkflowWorkItem).where(WorkflowWorkItem.id == row.work_item_id, WorkflowWorkItem.tenant_id == tenant_id))
            if item is None or item.outcome != "pending":
                row.status = "cancelled"
                continue
            original = await db.scalar(select(WorkflowDelivery).where(WorkflowDelivery.work_item_id == row.work_item_id, WorkflowDelivery.tenant_id == tenant_id, WorkflowDelivery.channel == row.channel).order_by(WorkflowDelivery.generation.desc()).limit(1))
            if original is None:
                original = await db.scalar(select(WorkflowDelivery).where(WorkflowDelivery.work_item_id == row.work_item_id, WorkflowDelivery.tenant_id == tenant_id).order_by(WorkflowDelivery.generation.desc()).limit(1))
            if original is None:
                row.status = "terminal"
                await log_action(db, tenant_id, "course_approval.deadline_terminal", kind, row.id, None, {"error_category": "delivery_binding_missing"})
                continue
            recipient_id = row.recipient_user_id or original.recipient_user_id
            recipient_email = original.recipient_email
            message_kind = "course_review_reminder" if kind == "reminder" else "course_review_overdue"
            if kind == "escalation":
                recipient_id = await db.scalar(select(CourseApprovalRequest.requested_by).where(CourseApprovalRequest.revision_id == item.review_revision_id))
                recipient_email = None
            followup_payload = None
            if kind == "reminder" and original.payload_encrypted is not None:
                try:
                    original_payload = decrypt_config(bytes(original.payload_encrypted))
                    access_url = original_payload.get("access_url")
                    if access_url:
                        followup_payload = encrypt_config({"access_url": str(access_url)})
                except Exception:
                    followup_payload = None
            if row.channel == "email" and kind == "reminder" and followup_payload is None:
                row.status = "terminal"
                await log_action(db, tenant_id, "course_approval.deadline_terminal", kind, row.id, None, {"error_category": "safe_access_url_missing"})
                continue
            if recipient_id is None and recipient_email is None:
                row.status = "terminal"
                await log_action(db, tenant_id, "course_approval.deadline_terminal", kind, row.id, None, {"error_category": "recipient_missing"})
                continue
            db.add(WorkflowDelivery(tenant_id=tenant_id, work_item_id=row.work_item_id, channel=row.channel, message_kind=message_kind, recipient_email=recipient_email, recipient_user_id=recipient_id, payload_encrypted=followup_payload, generation=original.generation + 1, status="queued"))
            row.status = "delivered"
            if kind == "reminder":
                reminder_count += 1
                if item.deadline_state == "scheduled":
                    item.deadline_state = "due"
            else:
                escalation_count += 1
                item.deadline_state = "overdue"
        await db.commit()
    return {"reminders": reminder_count, "escalations": escalation_count}


@celery_app.task(name="course_approval.deliver_workflow_delivery")
def deliver_workflow_delivery_task(tenant_id: str, delivery_id: str) -> dict[str, str]:
    return asyncio.run(deliver_workflow_delivery(tenant_id=UUID(tenant_id), delivery_id=UUID(delivery_id)))


@celery_app.task(name="course_approval.recover_workflow_deliveries")
def recover_workflow_deliveries_task() -> dict[str, int]:
    return asyncio.run(recover_workflow_deliveries())


@celery_app.task(name="course_approval.recover_workflow_deadlines")
def recover_workflow_deadlines_task() -> dict[str, int]:
    return asyncio.run(recover_workflow_deadlines())
