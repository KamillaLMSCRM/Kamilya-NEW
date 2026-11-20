"""Independent, bounded Telegram delivery through the existing notifications worker."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.log_redaction import SensitiveDataFilter
from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings

from .tasks import _delivery_session, _set_tenant_context, _typed_celery_task
from .telegram_router import bot_ready

logger = logging.getLogger(__name__)
DeliveryResult = tuple[Literal["sent", "failed", "uncertain"], int | None]


def message_body(row: Any) -> dict[str, object]:
    path = {
        "course": f"/courses/{row['target_id']}",
        "learning_path": f"/learning-paths#program-{row['target_id']}",
        "program": f"/learning-paths#program-{row['target_id']}",
        "check": f"/my-knowledge-checks/{row['target_id']}",
    }[row["target_type"]]
    phrases = {
        "assigned": ("Назначено обучение", "Оқу тағайындалды", "Training assigned"),
        "before_due": ("Приближается срок обучения", "Оқу мерзімі жақындап қалды", "Training is due soon"),
        "overdue": ("Срок обучения прошёл", "Оқу мерзімі өтіп кетті", "Training is overdue"),
    }[row["step"]]
    deadline: datetime | None = row["deadline"]
    when = deadline.astimezone(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y %H:%M UTC%z") if deadline else None
    text_parts = [row["workspace"], row["title"][:400]]
    if row["language"] == "en":
        text_parts.insert(1, phrases[2])
        if when:
            text_parts.append(f"Due: {when}")
        button = "Open training"
    else:
        text_parts.insert(1, f"{phrases[0]} / {phrases[1]}")
        if when:
            text_parts.append(f"Срок / Мерзімі: {when}")
        button = "Открыть обучение / Оқуды ашу"
    return {
        "chat_id": row["chat_id"],
        "text": "\n".join(text_parts),
        "link_preview_options": {"is_disabled": True},
        "reply_markup": {"inline_keyboard": [[{"text": button, "url": row["origin"] + path}]]},
    }


async def send(client: httpx.AsyncClient, token: str, payload: dict[str, object]) -> DeliveryResult:
    # Telegram has no caller-owned idempotency key. A timeout, lost response,
    # malformed success or provider 5xx could mean the message was sent.
    try:
        response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
        result = response.json()
    except (httpx.HTTPError, ValueError):
        return "uncertain", None
    if not isinstance(result, dict):
        return "uncertain", None
    if 400 <= response.status_code < 500 and result.get("ok") is False:
        return "failed", None
    if response.is_success and result.get("ok") is True:
        message = result.get("result")
        if isinstance(message, dict):
            chat = message.get("chat")
            message_id = message.get("message_id")
            if isinstance(chat, dict) and chat.get("id") == payload["chat_id"] and type(message_id) is int and message_id > 0:
                return "sent", message_id
    return "uncertain", None


async def recover_telegram_learning() -> dict[str, int | str]:
    settings = get_settings()
    if not bot_ready(settings):
        return {"status": "disabled"}
    if not settings.ASSIGNMENT_RECOVERY_DATABASE_URL:
        return {"status": "recovery_unavailable"}
    limit = (await resolve_runtime_settings()).integer("outbox.reminders.batch_size")
    recovery_engine = create_async_engine(settings.ASSIGNMENT_RECOVERY_DATABASE_URL, poolclass=NullPool)
    try:
        recovery = async_sessionmaker(recovery_engine, expire_on_commit=False)
        async with recovery() as db:
            rows = (await db.execute(text("SELECT * FROM public.telegram_due_learning_events(:max_items)"),
                                     {"max_items": limit})).mappings().all()
            await db.commit()
    finally:
        await recovery_engine.dispose()
    token = settings.TELEGRAM_REMINDER_BOT_TOKEN.get_secret_value()
    # Celery's logging setup is distinct from the HTTP application's.
    http_logger = logging.getLogger("httpx")
    if not any(isinstance(item, SensitiveDataFilter) for item in http_logger.filters):
        http_logger.addFilter(SensitiveDataFilter())
    sent = 0
    async with httpx.AsyncClient(timeout=8, trust_env=False, follow_redirects=False) as client:
        for event in rows:
            tenant_id: UUID = event["tenant_id"]
            key = {"tenant": tenant_id, "event": event["id"]}
            try:
                async with _delivery_session(None, settings) as db:
                    await _set_tenant_context(db, tenant_id)
                    row = (await db.execute(text("SELECT * FROM public.telegram_claim_learning_event(:tenant,:event)"),
                                            key)).mappings().one_or_none()
                    await db.commit()
                    if row is None:
                        continue
                    status, message_id = await send(client, token, message_body(row))
                    await _set_tenant_context(db, tenant_id)
                    accepted = await db.scalar(text("""
                        SELECT public.telegram_finish_learning_event(:tenant,:event,:status,:message)
                    """), {**key, "status": status, "message": message_id})
                    await db.commit()
                    sent += int(status == "sent" and bool(accepted))
            except Exception as exc:
                logger.warning("Telegram learning event processing failed id=%s type=%s", event["id"], type(exc).__name__)
    return {"status": "processed", "due": len(rows), "sent": sent}


@_typed_celery_task(name="learning_reminders.recover_telegram")
def recover_telegram_learning_task() -> dict[str, int | str]:
    return asyncio.run(recover_telegram_learning())
