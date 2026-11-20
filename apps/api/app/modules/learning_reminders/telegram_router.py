"""Personal subscription and Telegram webhook for the learning reminder bot."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.models.users import User

router = APIRouter(prefix="/learning-notifications/telegram", tags=["learning notifications"])
Db = Annotated[AsyncSession, Depends(get_db)]
Student = Annotated[User, Depends(require_role("student"))]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]
CODE = re.compile(r"[A-Fa-f0-9]{12}\Z")
LINK = re.compile(r"[A-Za-z0-9_-]{32}\Z")


def bot_ready(settings: Settings) -> bool:
    return bool(
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", settings.TELEGRAM_REMINDER_BOT_USERNAME)
        and re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{25,100}", settings.TELEGRAM_REMINDER_BOT_TOKEN.get_secret_value())
        and re.fullmatch(r"[A-Za-z0-9_-]{32,256}", settings.TELEGRAM_REMINDER_WEBHOOK_SECRET.get_secret_value())
    )


class Subscription(BaseModel):
    available: bool
    connected: bool = False
    pending_confirmation: bool = False


class StartLink(BaseModel):
    url: str


class ConfirmLink(BaseModel):
    code: str = Field(min_length=12, max_length=12)


class DeliveryStatus(BaseModel):
    id: UUID
    step: str
    status: str
    reason: str | None
    scheduled_at: datetime
    sent_at: datetime | None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _owner(user: User) -> dict[str, UUID]:
    if (user.tenant_id is None or getattr(user, "is_impersonating", False)
            or getattr(user, "kiosk_access_kiosk_id", None) is not None
            or getattr(user, "assignment_access_enrollment_id", None) is not None):
        raise HTTPException(403, "A personal learner session is required")
    return {"tenant": cast(UUID, user.tenant_id), "learner": cast(UUID, user.id)}


async def _available(db: AsyncSession, tenant: UUID) -> bool:
    if not bot_ready(get_settings()):
        return False
    return bool(await db.scalar(text("""
        SELECT enabled FROM public.telegram_reminder_workspaces WHERE tenant_id=:tenant
    """), {"tenant": tenant}))


@router.get("/subscription")
async def subscription(db: Db, user: Student) -> Subscription:
    owner = _owner(user)
    available = await _available(db, owner["tenant"])
    if not available:
        return Subscription(available=False)
    row = (await db.execute(text("""
        SELECT chat_id IS NOT NULL AS connected,
               pending_chat_id IS NOT NULL AND pending_until>clock_timestamp() AS pending
        FROM public.telegram_reminder_subscriptions WHERE tenant_id=:tenant AND user_id=:learner
    """), owner)).mappings().one_or_none()
    return Subscription(available=True, connected=bool(row and row["connected"]),
                        pending_confirmation=bool(row and row["pending"]))


@router.post("/subscription/link")
async def start_link(db: Db, user: Student) -> StartLink:
    owner = _owner(user)
    if not await _available(db, owner["tenant"]):
        raise HTTPException(404, "Telegram reminders are unavailable")
    nonce = secrets.token_urlsafe(24)
    await db.execute(text("""
        INSERT INTO public.telegram_reminder_subscriptions (tenant_id,user_id,pending_link_hash,pending_until)
        VALUES (:tenant,:learner,:digest,clock_timestamp()+interval '10 minutes')
        ON CONFLICT (tenant_id,user_id) DO UPDATE SET
          pending_link_hash=EXCLUDED.pending_link_hash,pending_until=EXCLUDED.pending_until,
          pending_chat_id=NULL,pending_code_hash=NULL
    """), {**owner, "digest": _digest(nonce)})
    await db.commit()
    username = get_settings().TELEGRAM_REMINDER_BOT_USERNAME
    return StartLink(url=f"https://t.me/{username}?start={nonce}")


@router.post("/subscription/confirm")
async def confirm_link(payload: ConfirmLink, db: Db, user: Student) -> Subscription:
    owner = _owner(user)
    if not await _available(db, owner["tenant"]):
        raise HTTPException(404, "Telegram reminders are unavailable")
    if not CODE.fullmatch(payload.code):
        raise HTTPException(422, "Invalid or expired Telegram confirmation code")
    try:
        result = await db.scalar(text("""
            UPDATE public.telegram_reminder_subscriptions SET
              chat_id=pending_chat_id,connected_at=CASE WHEN chat_id=pending_chat_id
                THEN connected_at ELSE clock_timestamp() END,
              pending_chat_id=NULL,pending_code_hash=NULL,pending_link_hash=NULL,pending_until=NULL
            WHERE tenant_id=:tenant AND user_id=:learner AND pending_chat_id IS NOT NULL
              AND pending_until>clock_timestamp() AND pending_code_hash=:digest
            RETURNING user_id
        """), {**owner, "digest": _digest(payload.code.upper())})
    except IntegrityError:
        raise HTTPException(409, "This Telegram chat is already linked in this workspace") from None
    if result is None:
        raise HTTPException(422, "Invalid or expired Telegram confirmation code")
    await db.commit()
    return Subscription(available=True, connected=True)


@router.delete("/subscription")
async def disconnect(db: Db, user: Student) -> Subscription:
    owner = _owner(user)
    await db.execute(text("""
        DELETE FROM public.telegram_reminder_subscriptions WHERE tenant_id=:tenant AND user_id=:learner
    """), owner)
    return Subscription(available=await _available(db, owner["tenant"]))


def _private_chat(message: object, sender: object) -> int | None:
    if not isinstance(message, dict) or not isinstance(sender, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if type(chat_id) is int and 0 < chat_id < 2**63 and chat.get("type") == "private" and sender.get("id") == chat_id:
        return chat_id
    return None


def _reply(chat_id: int, message: str, **kwargs: object) -> dict[str, object]:
    return {"method": "sendMessage", "chat_id": chat_id, "text": message, **kwargs}


@router.post("/webhook")
async def telegram_webhook(
    request: Request, db: Db,
    secret: Annotated[str, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = "",
) -> dict[str, object]:
    settings = get_settings()
    expected = settings.TELEGRAM_REMINDER_WEBHOOK_SECRET.get_secret_value()
    if not bot_ready(settings) or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(403, "Telegram webhook rejected")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    if not isinstance(update, dict):
        return {"ok": True}
    message = update.get("message")
    if isinstance(message, dict):
        chat = _private_chat(message, message.get("from"))
        command = message.get("text")
        if chat is None or not isinstance(command, str):
            return {"ok": True}
        parts = command.split(maxsplit=1)
        if not parts:
            return {"ok": True}
        action = parts[0].partition("@")[0]
        if action == "/start" and len(parts) == 2 and LINK.fullmatch(parts[1]):
            code = secrets.token_hex(6).upper()
            found = await db.scalar(text("SELECT public.telegram_accept_learning_start(:link,:chat,:code)"),
                                    {"link": _digest(parts[1]), "chat": chat, "code": _digest(code)})
            if found:
                await db.commit()
                return _reply(chat, f"Код привязки Telegram / Telegram қосу коды: {code}\nВведите код в кабинете LMS. / Кодты LMS кабинетіне енгізіңіз.")
        if action == "/settings":
            rows = (await db.execute(text("SELECT * FROM public.telegram_bound_learning_workspaces(:chat)"),
                                     {"chat": chat})).mappings()
            buttons = [[{"text": row["workspace"][:52], "callback_data": f"unlink:{row['tenant_id']}"}] for row in rows]
            if buttons:
                return _reply(chat, "Отключить Telegram для кабинета / Кабинет үшін Telegram-ды өшіру",
                              reply_markup={"inline_keyboard": buttons})
        if action in {"/start", "/help", "/settings"}:
            return _reply(chat, "Откройте профиль в LMS и выберите «Подключить Telegram». / LMS профилінде «Telegram қосу» түймесін таңдаңыз.")
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        chat = _private_chat(callback.get("message"), callback.get("from"))
        data = callback.get("data")
        callback_id = callback.get("id")
        if chat is not None and isinstance(data, str) and isinstance(callback_id, str) and data.startswith("unlink:"):
            try:
                tenant = UUID(data.removeprefix("unlink:"))
            except ValueError:
                return {"ok": True}
            await db.scalar(text("SELECT public.telegram_toggle_learning_workspace(:chat,:tenant)"),
                            {"chat": chat, "tenant": tenant})
            await db.commit()
            return {"method": "answerCallbackQuery", "callback_query_id": callback_id,
                    "text": "Telegram отключён для этого кабинета / Бұл кабинет үшін Telegram өшірілді"}
    return {"ok": True}


@router.get("/delivery/{source}/{source_id}")
async def delivery_status(
    source: Literal["course", "program", "check", "reminder"], source_id: UUID, db: Db, user: Methodologist,
) -> list[DeliveryStatus]:
    if not await _available(db, cast(UUID, user.tenant_id)):
        return []
    rows = (await db.execute(text("""
        SELECT * FROM public.telegram_learning_delivery_statuses(:tenant,:source,:source_id)
    """), {"tenant": user.tenant_id, "source": source, "source_id": source_id})).mappings()
    return [DeliveryStatus.model_validate(row) for row in rows]


@router.get("/learner/{learner_id}")
async def learner_status(learner_id: UUID, db: Db, user: Methodologist) -> Subscription:
    if not await _available(db, cast(UUID, user.tenant_id)):
        return Subscription(available=False)
    learner = await db.scalar(text("SELECT id FROM public.users WHERE tenant_id=:tenant AND id=:learner"),
                              {"tenant": user.tenant_id, "learner": learner_id})
    if learner is None:
        raise HTTPException(404, "Learner not found")
    connected = await db.scalar(text("SELECT public.telegram_learner_is_connected(:tenant,:learner)"),
                                 {"tenant": user.tenant_id, "learner": learner_id})
    return Subscription(available=True, connected=bool(connected))
