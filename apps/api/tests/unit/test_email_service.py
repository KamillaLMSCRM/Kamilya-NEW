from types import SimpleNamespace

import pytest

from app.core.email import EmailDeliveryError, EmailService, _subject_component


class _FakeResponse:
    status_code = 200
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"id": "msg_test_123"}


class _StatusResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict[str, str]:
        return {}


class _FakeAsyncClient:
    payload: dict[str, object] | None = None
    headers: dict[str, str] | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, _url, *, json, headers):
        self.payload = json
        type(self).payload = json
        type(self).headers = headers
        return _FakeResponse()


def test_tenant_name_cannot_inject_an_email_subject_line():
    subject_part = _subject_component("Tenant\r\nBcc: hidden@example.kz", fallback="Kamilya LMS")

    assert subject_part == "Tenant Bcc: hidden@example.kz"
    assert "\r" not in subject_part
    assert "\n" not in subject_part


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
async def test_initial_invitation_link_returns_resend_message_id(monkeypatch):
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

    message_id = await EmailService().send_invitation_link(
        to_email="learner@example.kz",
        invite_url="https://app.kml.kz/accept-invite?token=secret-token",
        company_name="Test company",
        learner_name="Learner",
    )

    assert message_id == "msg_test_123"
    assert _FakeAsyncClient.payload["to"] == ["learner@example.kz"]
    assert "secret-token" in _FakeAsyncClient.payload["text"]


@pytest.mark.asyncio
async def test_course_assignment_uses_stable_provider_idempotency_key(monkeypatch):
    monkeypatch.setattr(
        "app.core.email.get_settings",
        lambda: SimpleNamespace(
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-key",
            EMAIL_FROM="Kamilya LMS <noreply@example.kz>",
        ),
    )
    _FakeAsyncClient.headers = None
    monkeypatch.setattr("app.core.email.httpx.AsyncClient", _FakeAsyncClient)

    message_id = await EmailService().send_course_assignment(
        to_email="learner@example.kz",
        company_name="Test company",
        learner_name="Learner",
        course_title="Safety",
        access_url="https://app.kml.kz/courses/123",
        activation_required=False,
        idempotency_key="course-assignment/00000000-0000-0000-0000-000000000001",
    )

    assert message_id == "msg_test_123"
    assert _FakeAsyncClient.headers is not None
    assert _FakeAsyncClient.headers["Idempotency-Key"] == ("course-assignment/00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "subject_fragment", "text_fragment"),
    [
        ("ru", "приглашение в Kamilya LMS", "активации"),
        ("kk", "Kamilya LMS жүйесіне шақыру", "белсендіру"),
        ("en", "invitation to Kamilya LMS", "activation link"),
        ("de", "приглашение в Kamilya LMS", "активации"),
    ],
)
async def test_invitation_link_uses_tenant_language_and_russian_fallback(
    monkeypatch, language, subject_fragment, text_fragment
):
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

    await EmailService().send_invitation_link(
        to_email="learner@example.kz",
        invite_url="https://app.kml.kz/accept-invite?token=secret-token",
        company_name="Test company",
        learner_name="Learner",
        language=language,
    )

    payload = _FakeAsyncClient.payload
    assert payload is not None
    assert subject_fragment in payload["subject"]
    assert text_fragment in payload["text"]
    assert "ЭЦП" not in payload["text"]
    assert "EDS" not in payload["text"]
    assert (
        "activation" in payload["text"].lower()
        or "активац" in payload["text"].lower()
        or "белсендіру" in payload["text"]
    )


@pytest.mark.asyncio
async def test_invitation_link_escapes_html_context(monkeypatch):
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

    await EmailService().send_invitation_link(
        to_email="learner@example.kz",
        invite_url='https://app.kml.kz/accept-invite?token="quoted"&x=1',
        company_name="<Company & Co>",
        learner_name="<Learner>",
        language="ru",
    )

    html = _FakeAsyncClient.payload["html"]
    assert "&lt;Company &amp; Co&gt;" in html
    assert "&lt;Learner&gt;" in html
    assert "&quot;quoted&quot;" in html
    assert "<Company" not in html


@pytest.mark.asyncio
async def test_resend_rejection_is_sanitized_and_does_not_log_provider_payload(monkeypatch, caplog):
    class RejectedResponse:
        status_code = 422
        text = '{"message":"provider payload with secret-token"}'

    class RejectedClient(_FakeAsyncClient):
        async def post(self, _url, *, json, headers):
            return RejectedResponse()

    monkeypatch.setattr(
        "app.core.email.get_settings",
        lambda: SimpleNamespace(
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-key",
            EMAIL_FROM="Kamilya LMS <noreply@example.kz>",
        ),
    )
    monkeypatch.setattr("app.core.email.httpx.AsyncClient", RejectedClient)

    with pytest.raises(EmailDeliveryError) as exc_info:
        await EmailService().send_invitation_link(
            to_email="learner@example.kz",
            invite_url="https://app.kml.kz/accept-invite?token=secret-token",
            company_name="Test company",
            learner_name="Learner",
        )

    assert exc_info.value.category == "provider_rejected"
    assert "secret-token" not in str(exc_info.value)
    assert "provider payload" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "category"),
    [(429, "provider_rate_limited"), (500, "provider_unavailable"), (503, "provider_unavailable")],
)
async def test_resend_transient_provider_statuses_are_classified_for_retry(monkeypatch, status_code, category):
    class StatusClient(_FakeAsyncClient):
        async def post(self, _url, *, json, headers):
            return _StatusResponse(status_code)

    monkeypatch.setattr(
        "app.core.email.get_settings",
        lambda: SimpleNamespace(
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="test-key",
            EMAIL_FROM="Kamilya LMS <noreply@example.kz>",
        ),
    )
    monkeypatch.setattr("app.core.email.httpx.AsyncClient", StatusClient)

    with pytest.raises(EmailDeliveryError) as exc_info:
        await EmailService().send_invitation_link(
            to_email="learner@example.kz",
            invite_url="https://app.kml.kz/accept-invite?token=opaque",
            company_name="Test company",
            learner_name="Learner",
        )

    assert exc_info.value.category == category


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
