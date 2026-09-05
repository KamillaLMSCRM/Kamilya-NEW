"""Fail-closed delivery and broker-independent recovery for learning reminders."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Any, TypeVar, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.email import EmailDeliveryError, EmailService

from .store import RECOVERY_BATCH_SIZE, ClaimedLearningReminder, LearningReminderPayload, PostgresLearningReminderStore

logger = logging.getLogger(__name__)
TRANSIENT_EMAIL_CATEGORIES = frozenset({"provider_timeout", "provider_unreachable", "provider_rate_limited", "provider_unavailable"})
_TaskFunction = TypeVar("_TaskFunction", bound=Callable[..., object])


def _typed_celery_task(*, name: str) -> Callable[[_TaskFunction], _TaskFunction]:
    """Contain Celery's untyped decorator at the task-registration seam."""
    return cast(Callable[[_TaskFunction], _TaskFunction], celery_app.task(name=name))


async def _set_tenant_context(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})


def _enabled(settings: Any) -> bool:
    return bool(getattr(settings, "LEARNING_REMINDERS_ENABLED", False))


def _transport_ready(settings: Any) -> bool:
    provider = settings.EMAIL_PROVIDER.lower().strip()
    if provider == "resend":
        return bool(settings.RESEND_API_KEY)
    if provider == "smtp":
        return all(getattr(settings, key, None) for key in ("SMTP_HOST", "SMTP_PORT", "EMAIL", "EMAIL_PASSWORD"))
    return False


def _access_url(settings: Any, payload: LearningReminderPayload) -> str:
    base_url = settings.PUBLIC_URL.rstrip("/")
    if payload.target_type == "course":
        return f"{base_url}/courses/{payload.target_id}"
    if payload.target_type == "learning_path":
        return f"{base_url}/learning-paths"
    raise ValueError("unsupported learning reminder target type")


def _payload_hash(*, payload: LearningReminderPayload, access_url: str, idempotency_key: str) -> str:
    arguments = {
        "access_url": access_url,
        "company_name": payload.company_name,
        "due_at": payload.due_at.astimezone(UTC).isoformat(),
        "idempotency_key": idempotency_key,
        "learner_name": payload.learner_name,
        "to_email": payload.email.strip() if payload.email else None,
        "training_kind": payload.target_type,
        "training_title": payload.title,
    }
    serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _finalize(store: PostgresLearningReminderStore, event: ClaimedLearningReminder, **kwargs: Any) -> bool:
    result = await store.finalize(event, **kwargs)
    await _set_tenant_context(store.db, event.tenant_id)
    return result


@asynccontextmanager
async def _delivery_session(
    session_factory: Callable[[], Any] | None, settings: Any,
) -> AsyncIterator[AsyncSession]:
    # Celery entrypoints create a new event loop per run. Never borrow the API's
    # pooled asyncpg connections, which belong to the loop that opened them.
    engine = None
    if session_factory is None:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            yield db
    finally:
        if engine is not None:
            await engine.dispose()


async def deliver(
    tenant_id: UUID,
    reminder_id: UUID,
    *,
    session_factory: Callable[[], Any] | None = None,
    email_factory: Callable[[], EmailService] = EmailService,
    settings_factory: Callable[[], Any] = get_settings,
    store_factory: Callable[[AsyncSession], PostgresLearningReminderStore] = PostgresLearningReminderStore,
) -> dict[str, str]:
    """Deliver one claimed reminder without letting a disabled feature touch IO."""
    settings = settings_factory()
    if not _enabled(settings):
        return {"status": "disabled"}

    async with _delivery_session(session_factory, settings) as db:
        await _set_tenant_context(db, tenant_id)
        store = store_factory(db)
        event = await store.claim(tenant_id=tenant_id, reminder_id=reminder_id)
        if event is None:
            return {"status": "skipped"}
        await _set_tenant_context(db, tenant_id)
        payload = await store.payload(event)
        # payload() commits because the SQL function can suppress stale work.
        await _set_tenant_context(db, tenant_id)
        if payload is None:
            if not await _finalize(store, event, kind="skipped", error_category="ineligible"):
                return {"status": "claim_lost"}
            return {"status": "skipped"}
        if not payload.email or not payload.email.strip():
            if not await _finalize(store, event, kind="terminal", error_category="recipient_missing"):
                return {"status": "claim_lost"}
            return {"status": "dead"}
        if not payload.has_login_access:
            if not await _finalize(store, event, kind="terminal", error_category="activation_required"):
                return {"status": "claim_lost"}
            return {"status": "dead"}
        if not _transport_ready(settings):
            if not await _finalize(store, event, kind="defer", error_category="configuration_missing"):
                return {"status": "claim_lost"}
            return {"status": "deferred"}

        try:
            access_url = _access_url(settings, payload)
        except ValueError:
            if not await _finalize(store, event, kind="terminal", error_category="internal_error"):
                return {"status": "claim_lost"}
            return {"status": "dead"}
        idempotency_key = f"learning-reminder/{event.id}"
        transport = settings.EMAIL_PROVIDER.lower().strip()
        if not await store.begin_send(event, payload_hash=_payload_hash(payload=payload, access_url=access_url, idempotency_key=idempotency_key), transport=transport):
            return {"status": "suppressed"}
        await _set_tenant_context(db, tenant_id)

        try:
            message_id = await email_factory().send_learning_reminder(
                to_email=payload.email.strip(), company_name=payload.company_name, learner_name=payload.learner_name,
                training_title=payload.title, training_kind=payload.target_type, due_at=payload.due_at,
                access_url=access_url, idempotency_key=idempotency_key,
            )
        except EmailDeliveryError as exc:
            kind = "transient" if transport == "resend" and exc.category in TRANSIENT_EMAIL_CATEGORIES else "terminal"
            category = "delivery_uncertain" if transport == "smtp" and exc.category in TRANSIENT_EMAIL_CATEGORIES else exc.category
            if not await _finalize(store, event, kind=kind, error_category=category):
                return {"status": "claim_lost"}
            return {"status": kind}
        except Exception:
            if not await _finalize(store, event, kind="terminal", error_category="internal_error"):
                return {"status": "claim_lost"}
            return {"status": "dead"}
        if not message_id:
            kind = "terminal" if transport == "smtp" else "transient"
            category = "delivery_uncertain" if transport == "smtp" else "provider_unavailable"
            if not await _finalize(store, event, kind=kind, error_category=category):
                return {"status": "claim_lost"}
            return {"status": kind}
        if not await _finalize(store, event, kind="success", message_id=message_id):
            return {"status": "claim_lost"}
        return {"status": "sent"}


async def recover_due_reminders(
    limit: int = RECOVERY_BATCH_SIZE,
    *,
    settings_factory: Callable[[], Any] = get_settings,
    recovery_session_factory: Callable[[], Any] | None = None,
    delivery: Callable[[UUID, UUID], Any] = deliver,
    store_factory: Callable[[AsyncSession], PostgresLearningReminderStore] = PostgresLearningReminderStore,
) -> dict[str, int | str]:
    settings = settings_factory()
    if not _enabled(settings):
        return {"status": "disabled", "due": 0, "processed": 0, "succeeded": 0, "failed": 0}
    bounded = max(1, min(limit, 100))
    if recovery_session_factory is None:
        recovery_url = settings.ASSIGNMENT_RECOVERY_DATABASE_URL
        if not recovery_url:
            raise RuntimeError("ASSIGNMENT_RECOVERY_DATABASE_URL is required for learning reminder recovery")
        engine = create_async_engine(recovery_url, poolclass=NullPool)
        recovery_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    else:
        engine = None
    try:
        async with recovery_session_factory() as db:
            rows = await store_factory(db).due(bounded)
    finally:
        if engine is not None:
            await engine.dispose()
    succeeded = failed = 0
    for item in rows:
        try:
            await delivery(item.tenant_id, item.id)
        except Exception as exc:
            failed += 1
            logger.warning("Learning reminder recovery failed for item %s (%s)", item.id, type(exc).__name__)
        else:
            succeeded += 1
    return {"due": len(rows), "processed": len(rows), "succeeded": succeeded, "failed": failed}


@_typed_celery_task(name="learning_reminders.deliver")
def deliver_learning_reminder_task(tenant_id: str, reminder_id: str) -> dict[str, str]:
    return asyncio.run(deliver(UUID(tenant_id), UUID(reminder_id)))


@_typed_celery_task(name="learning_reminders.recover")
def recover_due_reminders_task() -> dict[str, int | str]:
    return asyncio.run(recover_due_reminders())
