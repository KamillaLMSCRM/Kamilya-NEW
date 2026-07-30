from types import SimpleNamespace

import pytest

from app.core.email import EmailService


class _FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None


class _FakeAsyncClient:
    payload: dict[str, object] | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, _url, *, json, headers):
        self.payload = json
        type(self).payload = json
        return _FakeResponse()


@pytest.mark.asyncio
async def test_login_otp_email_is_russian_and_keeps_kamilya_branding(monkeypatch):
    monkeypatch.setattr(
        "app.core.email.get_settings",
        lambda: SimpleNamespace(
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-key",
            EMAIL_FROM="Kamilya LMS <noreply@example.kz>",
        ),
    )
    _FakeAsyncClient.payload = None
    monkeypatch.setattr("app.core.email.httpx.AsyncClient", _FakeAsyncClient)

    await EmailService().send_login_code(to_email="user@example.kz", code="123456")

    payload = _FakeAsyncClient.payload
    assert payload is not None
    assert payload["subject"] == "Kamilya LMS: код для входа"
    assert "Ваш код для входа в Kamilya LMS" in payload["text"]
    assert "Код действует 5 минут" in payload["text"]
    assert "Ваш код для входа в Kamilya LMS" in payload["html"]
    assert "Your Kamilya LMS login code" not in payload["text"]


@pytest.mark.asyncio
async def test_invitation_otp_email_is_russian_and_keeps_tenant_context(monkeypatch):
    monkeypatch.setattr(
        "app.core.email.get_settings",
        lambda: SimpleNamespace(
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-key",
            EMAIL_FROM="Kamilya LMS <noreply@example.kz>",
        ),
    )
    _FakeAsyncClient.payload = None
    monkeypatch.setattr("app.core.email.httpx.AsyncClient", _FakeAsyncClient)

    await EmailService().send_invitation_code(
        to_email="learner@example.kz",
        code="654321",
        company_name="ТОО Тест",
        learner_name="Айжан",
    )

    payload = _FakeAsyncClient.payload
    assert payload is not None
    assert "ТОО Тест" in payload["subject"]
    assert "Айжан" in payload["text"]
    assert "Код действует 5 минут" in payload["text"]
    assert "ТОО Тест" in payload["html"]
