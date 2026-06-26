"""Telegram bot webhook handler."""
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.modules.auth.auth_sessions import verify_code
from app.models.users import User
from app.models.user_roles import UserRole

settings = get_settings()
router = APIRouter(prefix="/telegram", tags=["telegram"])

TELEGRAM_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_telegram_message(chat_id: int, text: str):
    """Send a message via Telegram Bot API."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )


@router.post("/webhook")
async def handle_telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle incoming Telegram updates."""
    update = await request.json()

    # Extract message data
    message = update.get("message")
    if not message:
        return {"ok": True}

    text = message.get("text", "").strip()
    telegram_id = str(message["from"]["id"])
    chat_id = message["chat"]["id"]

    # Handle /start command
    if text == "/start":
        await send_telegram_message(
            chat_id,
            "👋 Добро пожаловать в Kamilya LMS!\n\n"
            "Отправьте 6-значный код из приложения для входа в систему."
        )
        return {"ok": True}

    # Validate 6-digit code format
    if not text.isdigit() or len(text) != 6:
        await send_telegram_message(
            chat_id,
            "❌ Неверный формат кода.\n"
            "Отправьте 6-значный числовой код из Kamilya LMS."
        )
        return {"ok": True}

    # Find user by telegram_id
    result = await db.execute(
        select(User).where(User.telegram_id == int(telegram_id))
    )
    user = result.scalar_one_or_none()

    if not user:
        await send_telegram_message(
            chat_id,
            "⚠️ Ваш Telegram не привязан к аккаунту Kamilya LMS.\n"
            "Обратитесь к администратору для привязки Telegram."
        )
        return {"ok": True}

    # Get role from user_roles table
    role_result = await db.execute(
        select(UserRole.role)
        .where(UserRole.user_id == user.id, UserRole.tenant_id == user.tenant_id)
        .limit(1)
    )
    role_row = role_result.scalar_one_or_none()
    role = role_row if role_row else user.role

    user_data = {
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "telegram_id": telegram_id,
        "role": role,
        "full_name": f"{user.first_name} {user.last_name}",
        "tenant": {
            "id": str(user.tenant_id),
            "name": user.tenant.name if user.tenant else "",
            "slug": user.tenant.slug if user.tenant else "",
            "is_demo": bool(user.tenant.is_demo) if user.tenant else False,
            "plan": user.tenant.plan if user.tenant else "free",
        },
    }

    success = await verify_code(text, telegram_id, user_data)

    if success:
        await send_telegram_message(
            chat_id,
            f"✅ Вход выполнен успешно!\n"
            f"Добро пожаловать, {user.first_name}!"
        )
    else:
        await send_telegram_message(
            chat_id,
            "❌ Код не найден или истёк.\n"
            "Попробуйте получить новый код в приложении."
        )

    return {"ok": True}
