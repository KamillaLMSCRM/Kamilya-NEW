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
    """Handle incoming Telegram updates.

    Security (added 2026-06-30, smoke Bug 3): always require the
    X-Telegram-Bot-Api-Secret-Token header to match
    settings.TELEGRAM_WEBHOOK_SECRET. Telegram sends this header
    when you call setWebhook with secret_token. If the secret is
    not configured server-side, the webhook is closed (404) to
    prevent an open relay.

    The fail-closed default is intentional — we'd rather have a
    broken Telegram login than an open webhook. The webhook is
    configured once via:
        https://api.telegram.org/bot{TOKEN}/setWebhook
            ?url=https://kamilya-lms-api.onrender.com/api/v1/telegram/webhook
            &secret_token={TELEGRAM_WEBHOOK_SECRET}
    after which the secret_token becomes the value Telegram sends
    back in the X-Telegram-Bot-Api-Secret-Token header.
    """
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        # Fail closed: refuse traffic if the server is not configured.
        # Don't leak this in the response — pretend the URL doesn't exist.
        import logging
        logging.getLogger(__name__).error(
            "Telegram webhook called but TELEGRAM_WEBHOOK_SECRET is not "
            "configured. Set it in Render env to enable Telegram login."
        )
        raise HTTPException(status_code=404, detail="Not Found")

    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # Constant-time compare avoids leaking length / prefix.
    import hmac
    if not hmac.compare_digest(provided, settings.TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=404, detail="Not Found")

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
        print(f"[telegram-webhook] non-code message from telegram_id={telegram_id}: text={text!r}", flush=True)
        await send_telegram_message(
            chat_id,
            "❌ Неверный формат кода.\n"
            "Отправьте 6-значный числовой код из Kamilya LMS."
        )
        return {"ok": True}

    print(f"[telegram-webhook] received code from telegram_id={telegram_id}: code={text}", flush=True)

    # Find user by telegram_id. Multiple users can share a telegram_id
    # across tenants (e.g. a superadmin platform row plus per-tenant
    # admin rows). Resolution order:
    #   1. Most recently active tenant user — preferred for the daily flow.
    #      The platform superadmin row (tenant_id IS NULL) is now picked
    #      ONLY if there are no tenant-scoped candidates, so the bot's
    #      default landing is a real tenant admin context, not /admin/super.
    #   2. Superadmin (tenant_id IS NULL) — fallback.
    # To switch to the superadmin session, the user clicks the "Super admin"
    # button in the TopBar — that triggers a fresh superadmin-login round
    # trip with a separate code, never through this bot path.
    # Using scalar_one_or_none() here previously broke the bot with
    # MultipleResultsFound — see issue 2026-06-26.
    candidates = (
        await db.execute(
            select(User)
            .where(User.telegram_id == int(telegram_id))
            .order_by(
                # Prefer tenant-scoped rows over the NULL-tenant platform row.
                User.tenant_id.is_(None).asc(),
                User.last_login.desc().nulls_last(),
            )
        )
    ).scalars().all()
    user = candidates[0] if candidates else None

    if not user:
        print(f"[telegram-webhook] no User row found for telegram_id={telegram_id}", flush=True)
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

    # Build the tenant payload. We do an explicit fetch rather than
    # touch `user.tenant` because the User ORM model has no `tenant`
    # relationship declared — the previous code only worked by accident
    # (superadmin row has tenant_id IS NULL so the branch was skipped).
    # With tenant-scoped candidates now in play, the lazy access raised
    # AttributeError and the bot silently failed on every webhook.
    tenant_payload = None
    if user.tenant_id is not None:
        from app.models.tenants import Tenant  # local import to avoid cycle
        tenant_row = (
            await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one_or_none()
        if tenant_row is not None:
            tenant_payload = {
                "id": str(tenant_row.id),
                "name": tenant_row.name,
                "slug": tenant_row.slug,
                "is_demo": bool(tenant_row.is_demo),
                "plan": tenant_row.plan,
            }

    user_data = {
        "user_id": str(user.id),
        "tenant_id": user.tenant_id,  # UUID or None — never str(None)
        "telegram_id": telegram_id,
        "role": role,
        "full_name": f"{user.first_name} {user.last_name}",
        "tenant": tenant_payload,
    }

    success = await verify_code(text, telegram_id, user_data)
    print(f"[telegram-webhook] verify_code({text!r}, tg={telegram_id}, user_id={user.id}) -> {success}", flush=True)

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
