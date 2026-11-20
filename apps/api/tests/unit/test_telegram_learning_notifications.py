from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.core.log_redaction import redact_sensitive_text
from app.modules.learning_reminders import telegram_router
from app.modules.learning_reminders.telegram_delivery import message_body, send
from app.modules.learning_reminders.telegram_router import _owner, _private_chat, bot_ready

FAKE_BOT_TOKEN = "12345678:" + "A" * 35


def test_separate_credentials_and_private_chat_binding():
    config = SimpleNamespace(
        TELEGRAM_REMINDER_BOT_USERNAME="ExampleReminderBot",
        TELEGRAM_REMINDER_BOT_TOKEN=SecretStr(FAKE_BOT_TOKEN),
        TELEGRAM_REMINDER_WEBHOOK_SECRET=SecretStr("a" * 32),
    )
    assert bot_ready(config)
    config.TELEGRAM_REMINDER_WEBHOOK_SECRET = SecretStr("")
    assert not bot_ready(config)
    assert _private_chat({"chat": {"id": 42, "type": "private"}}, {"id": 42}) == 42
    assert _private_chat({"chat": {"id": 42, "type": "group"}}, {"id": 42}) is None
    assert _private_chat({"chat": {"id": 42, "type": "private"}}, {"id": 43}) is None
    assert _private_chat({"chat": {"id": True, "type": "private"}}, {"id": 1}) is None


async def test_only_secret_authenticated_private_start_can_issue_a_code(monkeypatch):
    secret = "a" * 32
    config = SimpleNamespace(
        TELEGRAM_REMINDER_BOT_USERNAME="ExampleReminderBot",
        TELEGRAM_REMINDER_BOT_TOKEN=SecretStr(FAKE_BOT_TOKEN),
        TELEGRAM_REMINDER_WEBHOOK_SECRET=SecretStr(secret),
    )
    monkeypatch.setattr(telegram_router, "get_settings", lambda: config)
    db = SimpleNamespace(scalar=AsyncMock(return_value=True), commit=AsyncMock())
    update = {"message": {"text": "/start " + "a" * 32, "chat": {"id": 42, "type": "private"}, "from": {"id": 42}}}
    request = SimpleNamespace(json=AsyncMock(return_value=update))
    with pytest.raises(HTTPException) as exc:
        await telegram_router.telegram_webhook(request, db, "wrong")
    assert exc.value.status_code == 403
    db.scalar.assert_not_awaited()

    update["message"]["chat"]["type"] = "group"
    assert await telegram_router.telegram_webhook(request, db, secret) == {"ok": True}
    db.scalar.assert_not_awaited()
    update["message"]["chat"]["type"] = "private"
    result = await telegram_router.telegram_webhook(request, db, secret)
    assert result["method"] == "sendMessage" and result["chat_id"] == 42
    params = db.scalar.await_args.args[1]
    assert len(params["link"]) == len(params["code"]) == 64
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("claim", ["is_impersonating", "assignment_access_enrollment_id", "kiosk_access_kiosk_id"])
def test_limited_learner_session_cannot_connect_telegram(claim):
    with pytest.raises(HTTPException) as exc:
        _owner(SimpleNamespace(id=uuid4(), tenant_id=uuid4(), **{claim: uuid4()}))
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("http_status", "payload", "expected"),
    [
        (200, {"ok": True, "result": {"chat": {"id": 42}, "message_id": 16}}, ("sent", 16)),
        (200, {"ok": True, "result": {"chat": {"id": 43}, "message_id": 16}}, ("uncertain", None)),
        (403, {"ok": False}, ("failed", None)),
        (503, {"ok": False}, ("uncertain", None)),
        (200, None, ("uncertain", None)),
    ],
)
async def test_transport_distinguishes_rejection_from_unknown(http_status, payload, expected):
    calls = []

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(http_status, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await send(client, FAKE_BOT_TOKEN, {"chat_id": 42}) == expected
    assert calls == ["sendMessage"]


async def test_timeout_does_not_resend_an_uncertain_message():
    requests = []

    def handler(request):
        requests.append(request.url.host)
        raise httpx.ReadTimeout("injected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await send(client, FAKE_BOT_TOKEN, {"chat_id": 42}) == ("uncertain", None)
    assert requests == ["api.telegram.org"]


def test_workspace_message_uses_its_route_and_deadline_and_redacts_tokens():
    assignment = uuid4()
    payload = message_body({
        "workspace": "Компания 2", "origin": "https://two.example", "language": "kk",
        "title": "Учебный тест", "chat_id": 42, "target_type": "check", "target_id": assignment,
        "step": "overdue", "deadline": datetime(2026, 11, 20, 4, 0, tzinfo=UTC),
    })
    assert "Компания 2" in payload["text"] and "09:00 UTC+0500" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["url"] == f"https://two.example/my-knowledge-checks/{assignment}"
    for token_in_url in (FAKE_BOT_TOKEN, FAKE_BOT_TOKEN.replace(":", "%3A")):
        raw = f"POST https://api.telegram.org/bot{token_in_url}/sendMessage"
        assert redact_sensitive_text(raw) == "POST https://api.telegram.org/bot<redacted-token>/sendMessage"
