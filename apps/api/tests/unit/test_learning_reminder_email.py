from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.email import EmailDeliveryError, EmailService


class _FakeSMTP:
    message = None
    refusal: dict[object, object] = {}
    send_error: Exception | None = None

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def login(self, *_args) -> None:
        return None

    def send_message(self, message):
        type(self).message = message
        if type(self).send_error:
            raise type(self).send_error
        return type(self).refusal


async def _run_in_process(callable_):
    return callable_()


def _smtp_settings() -> SimpleNamespace:
    return SimpleNamespace(
        EMAIL_PROVIDER="smtp",
        RESEND_API_KEY="",
        SMTP_HOST="mail.example.kz",
        SMTP_PORT=465,
        SMTP_USE_SSL=True,
        EMAIL="sender@example.kz",
        EMAIL_PASSWORD="synthetic-password",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("training_kind", "label"),
    [("course", "курс"), ("learning_path", "программу")],
)
async def test_learning_reminder_renders_contract_and_reuses_idempotency_key(training_kind, label):
    service = EmailService()
    service._send = AsyncMock(return_value="msg-reminder")
    due_at = datetime(2026, 9, 5, 15, 30, tzinfo=UTC)

    result = await service.send_learning_reminder(
        to_email="learner@example.kz",
        company_name="ТОО Тест",
        learner_name="Айжан",
        training_title="Охрана труда",
        training_kind=training_kind,
        due_at=due_at,
        access_url="https://app.kml.kz/courses/course-123",
        idempotency_key="learning-reminder/reminder-123",
    )

    assert result == "msg-reminder"
    service._send.assert_awaited_once_with(
        to_email="learner@example.kz",
        subject=f"ТОО Тест: напоминание о {'курсе' if label == 'курс' else 'программе'}",
        text=(
            f"Айжан, организация ТОО Тест напоминает: вам нужно пройти {label} "
            "«Охрана труда».\n\n"
            "Срок: 05.09.2026 15:30 UTC\n"
            "Открыть обучение: https://app.kml.kz/courses/course-123"
        ),
        html=(
            f"<p>Айжан, организация <strong>ТОО Тест</strong> напоминает: вам нужно пройти {label} "
            "<strong>Охрана труда</strong>.</p>"
            "<p>Срок: 05.09.2026 15:30 UTC</p>"
            '<p><a href="https://app.kml.kz/courses/course-123">Открыть обучение</a></p>'
        ),
        idempotency_key="learning-reminder/reminder-123",
        require_delivery=True,
    )


@pytest.mark.asyncio
async def test_learning_reminder_escapes_all_html_interpolation_and_converts_to_utc():
    service = EmailService()
    service._send = AsyncMock()

    await service.send_learning_reminder(
        to_email="learner@example.kz",
        company_name="<Компания & партнёры>",
        learner_name='<Ученик "А">',
        training_title="Курс <важный>",
        training_kind="course",
        due_at=datetime(2026, 9, 5, 20, 30, tzinfo=timezone(timedelta(hours=5))),
        access_url='https://app.kml.kz/courses/123?next="x"&mode=learn',
        idempotency_key="learning-reminder/escape",
    )

    html = service._send.await_args.kwargs["html"]
    assert "&lt;Ученик &quot;А&quot;&gt;" in html
    assert "&lt;Компания &amp; партнёры&gt;" in html
    assert "Курс &lt;важный&gt;" in html
    assert "next=&quot;x&quot;&amp;mode=learn" in html
    assert "<Ученик" not in html
    assert "<Компания" not in html
    assert "05.09.2026 15:30 UTC" in html


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"training_kind": "lesson", "due_at": datetime(2026, 9, 5, 15, 30, tzinfo=UTC)},
        {"training_kind": "course", "due_at": datetime(2026, 9, 5, 15, 30)},
    ],
)
async def test_learning_reminder_rejects_invalid_kind_or_naive_deadline(kwargs):
    service = EmailService()
    service._send = AsyncMock()

    with pytest.raises(ValueError):
        await service.send_learning_reminder(
            to_email="learner@example.kz",
            company_name="ТОО Тест",
            learner_name="Айжан",
            training_title="Охрана труда",
            access_url="https://app.kml.kz/courses/course-123",
            idempotency_key="learning-reminder/invalid",
            **kwargs,
        )

    service._send.assert_not_awaited()


@pytest.mark.asyncio
async def test_required_delivery_fails_closed_before_log_fallback_but_default_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        "app.core.email.get_settings",
        lambda: SimpleNamespace(EMAIL_PROVIDER="log"),
    )
    service = EmailService()
    message = {"to_email": "learner@example.kz", "subject": "Subject", "text": "Text", "html": "<p>HTML</p>"}

    with pytest.raises(EmailDeliveryError) as exc_info:
        await service._send(**message, require_delivery=True)

    assert exc_info.value.category == "configuration_missing"
    assert str(exc_info.value) == "Transactional email delivery is not configured."
    assert await service._send(**message) is None


@pytest.mark.asyncio
async def test_required_smtp_reminder_plumbs_stable_message_id_after_acceptance(monkeypatch):
    monkeypatch.setattr("app.core.email.get_settings", _smtp_settings)
    monkeypatch.setattr("app.core.email.smtplib.SMTP_SSL", _FakeSMTP)
    to_thread = AsyncMock(side_effect=_run_in_process)
    monkeypatch.setattr("app.core.email.asyncio.to_thread", to_thread)
    _FakeSMTP.message = None
    _FakeSMTP.refusal = {}
    _FakeSMTP.send_error = None

    message_id = await EmailService().send_learning_reminder(
        to_email="learner@example.kz",
        company_name="ТОО Тест",
        learner_name="Айжан",
        training_title="Охрана труда",
        training_kind="course",
        due_at=datetime(2026, 9, 5, 15, 30, tzinfo=UTC),
        access_url="https://app.kml.kz/courses/course-123",
        idempotency_key="learning-reminder/reminder-123",
    )

    assert message_id == "<learning-reminder-8533ae52705dde0b4318336b07819ad4d2c8c79a90f68d0377eb79a294846934@kml.kz>"
    assert _FakeSMTP.message["Message-ID"] == message_id
    assert _FakeSMTP.message["Subject"] == "ТОО Тест: напоминание о курсе"
    to_thread.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refusal", "send_error", "category"),
    [
        ({"learner@example.kz": (550, b"refused")}, None, "provider_rejected"),
        ({}, TimeoutError(), "provider_timeout"),
    ],
)
async def test_required_smtp_reminder_never_returns_message_id_after_refusal_or_timeout(
    monkeypatch, refusal, send_error, category
):
    monkeypatch.setattr("app.core.email.get_settings", _smtp_settings)
    monkeypatch.setattr("app.core.email.smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("app.core.email.asyncio.to_thread", AsyncMock(side_effect=_run_in_process))
    _FakeSMTP.message = None
    _FakeSMTP.refusal = refusal
    _FakeSMTP.send_error = send_error

    with pytest.raises(EmailDeliveryError) as exc_info:
        await EmailService().send_learning_reminder(
            to_email="learner@example.kz",
            company_name="ТОО Тест",
            learner_name="Айжан",
            training_title="Охрана труда",
            training_kind="course",
            due_at=datetime(2026, 9, 5, 15, 30, tzinfo=UTC),
            access_url="https://app.kml.kz/courses/course-123",
            idempotency_key="learning-reminder/reminder-123",
        )

    assert exc_info.value.category == category
    assert _FakeSMTP.message["Message-ID"].startswith("<learning-reminder-")


@pytest.mark.asyncio
async def test_legacy_smtp_call_keeps_none_return_and_no_message_id(monkeypatch):
    monkeypatch.setattr("app.core.email.get_settings", _smtp_settings)
    monkeypatch.setattr("app.core.email.smtplib.SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr("app.core.email.asyncio.to_thread", AsyncMock(side_effect=_run_in_process))
    _FakeSMTP.message = None
    _FakeSMTP.refusal = {}
    _FakeSMTP.send_error = None

    result = await EmailService()._send(
        to_email="recipient@example.kz",
        subject="Legacy",
        text="Plain text",
        html="<p>HTML</p>",
    )

    assert result is None
    assert _FakeSMTP.message["Message-ID"] is None


@pytest.mark.asyncio
async def test_required_smtp_delivery_without_key_fails_closed_before_transport(monkeypatch):
    monkeypatch.setattr("app.core.email.get_settings", _smtp_settings)
    send_smtp = AsyncMock()
    service = EmailService()
    service._send_smtp = send_smtp

    with pytest.raises(EmailDeliveryError) as exc_info:
        await service._send(
            to_email="learner@example.kz",
            subject="Reminder",
            text="Text",
            html="<p>HTML</p>",
            require_delivery=True,
        )

    assert exc_info.value.category == "idempotency_key_missing"
    send_smtp.assert_not_awaited()
