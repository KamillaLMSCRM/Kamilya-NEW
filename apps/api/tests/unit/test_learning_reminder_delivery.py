from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.email import EmailDeliveryError
from app.modules.learning_reminders.store import ClaimedLearningReminder, DueLearningReminder, LearningReminderPayload
from app.modules.learning_reminders.tasks import deliver, recover_due_reminders

TENANT_ID = UUID("00000000-0000-0000-0000-000000000101")
REMINDER_ID = UUID("00000000-0000-0000-0000-000000000102")
TOKEN = UUID("00000000-0000-0000-0000-000000000103")


class FakeDb:
    def __init__(self) -> None:
        self.context_calls = 0

    async def execute(self, *_args, **_kwargs) -> None:
        self.context_calls += 1


class FakeSession:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    async def __aenter__(self) -> FakeDb:
        return self.db

    async def __aexit__(self, *_args) -> None:
        return None


class FakeStore:
    def __init__(self, db: FakeDb, *, payload: LearningReminderPayload | None = None, begin: bool = True, finalize_result: bool = True) -> None:
        self.db = db
        self.event = ClaimedLearningReminder(id=REMINDER_ID, tenant_id=TENANT_ID, claim_token=TOKEN)
        self.payload_value = payload or standard_payload()
        self.begin = begin
        self.finalize_result = finalize_result
        self.claims = 0
        self.begin_hashes: list[str] = []
        self.finalized: list[dict[str, object]] = []

    async def claim(self, **_kwargs):
        self.claims += 1
        return self.event

    async def payload(self, _event):
        return self.payload_value

    async def begin_send(self, _event, *, payload_hash: str, transport: str = "resend") -> bool:
        self.begin_hashes.append(payload_hash)
        self.transport = transport
        return self.begin

    async def finalize(self, _event, **kwargs) -> bool:
        self.finalized.append(kwargs)
        return self.finalize_result


class FakeEmail:
    def __init__(self, *, failure: Exception | None = None, message_id: str | None = "provider-message-1") -> None:
        self.failure = failure
        self.message_id = message_id
        self.calls: list[dict[str, object]] = []

    async def send_learning_reminder(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return self.message_id


def standard_payload(**changes) -> LearningReminderPayload:
    values = {
        "email": "learner@example.test",
        "learner_name": "Learner",
        "company_name": "Test Company",
        "title": "Safety",
        "target_type": "course",
        "target_id": UUID("00000000-0000-0000-0000-000000000104"),
        "due_at": datetime(2026, 9, 10, 12, tzinfo=UTC),
        "has_login_access": True,
    }
    values.update(changes)
    return LearningReminderPayload(**values)


def settings(*, enabled: bool = True, provider: str = "resend", key: str = "test-key"):
    return SimpleNamespace(
        LEARNING_REMINDERS_ENABLED=enabled,
        EMAIL_PROVIDER=provider,
        RESEND_API_KEY=key,
        PUBLIC_URL="https://app.example.test/",
        ASSIGNMENT_RECOVERY_DATABASE_URL="",
    )


@pytest.mark.asyncio
async def test_disabled_returns_before_session_store_or_provider_io():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled delivery must not open a session or construct email")

    assert await deliver(TENANT_ID, REMINDER_ID, session_factory=forbidden, email_factory=forbidden, settings_factory=lambda: settings(enabled=False)) == {"status": "disabled"}


@pytest.mark.asyncio
async def test_eligible_reminder_sends_with_stable_identity_and_restored_context():
    db = FakeDb()
    store = FakeStore(db)
    email = FakeEmail()

    result = await deliver(
        TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email,
        settings_factory=settings, store_factory=lambda _db: store,
    )

    assert result == {"status": "sent"}
    assert email.calls[0]["idempotency_key"] == f"learning-reminder/{REMINDER_ID}"
    assert email.calls[0]["access_url"] == "https://app.example.test/courses/00000000-0000-0000-0000-000000000104"
    assert store.finalized == [{"kind": "success", "message_id": "provider-message-1"}]
    assert db.context_calls >= 4


@pytest.mark.asyncio
async def test_ineligible_payload_finalizes_skipped_and_restores_context_without_email_io():
    db = FakeDb()
    store = FakeStore(db, payload=None)
    store.payload_value = None
    email = FakeEmail()

    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email, settings_factory=settings, store_factory=lambda _db: store)

    assert result == {"status": "skipped"}
    assert store.finalized == [{"kind": "skipped", "error_category": "ineligible"}]
    assert email.calls == []
    assert db.context_calls >= 4


@pytest.mark.asyncio
async def test_retry_uses_same_provider_identity_and_transient_category():
    db = FakeDb()
    store = FakeStore(db)
    email = FakeEmail(failure=EmailDeliveryError("provider_timeout", "safe"))

    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email, settings_factory=settings, store_factory=lambda _db: store)

    assert result == {"status": "transient"}
    assert email.calls[0]["idempotency_key"] == f"learning-reminder/{REMINDER_ID}"
    assert store.finalized == [{"kind": "transient", "error_category": "provider_timeout"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [None, ""])
async def test_provider_without_message_id_is_transient_not_sent(message_id: str | None):
    db = FakeDb()
    store = FakeStore(db)
    email = FakeEmail(message_id=message_id)

    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email, settings_factory=settings, store_factory=lambda _db: store)

    assert result == {"status": "transient"}
    assert store.finalized == [{"kind": "transient", "error_category": "provider_unavailable"}]
@pytest.mark.asyncio
async def test_success_finalization_claim_loss_never_reports_sent_or_retries_provider():
    db = FakeDb()
    store = FakeStore(db, finalize_result=False)
    email = FakeEmail()

    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email, settings_factory=settings, store_factory=lambda _db: store)

    assert result == {"status": "claim_lost"}
    assert len(email.calls) == 1
    assert store.finalized == [{"kind": "success", "message_id": "provider-message-1"}]


@pytest.mark.asyncio
async def test_cancellation_suppresses_before_provider_call():
    db = FakeDb()
    store = FakeStore(db, begin=False)
    email = FakeEmail()

    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email, settings_factory=settings, store_factory=lambda _db: store)

    assert result == {"status": "suppressed"}
    assert email.calls == []
    assert store.finalized == []


@pytest.mark.asyncio
async def test_changed_payload_hash_is_suppressed_before_a_second_provider_call():
    db = FakeDb()
    first_store = FakeStore(db)
    first_email = FakeEmail()
    assert await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: first_email, settings_factory=settings, store_factory=lambda _db: first_store) == {"status": "sent"}

    class HashGuardStore(FakeStore):
        async def begin_send(self, event, *, payload_hash: str, transport: str = "resend") -> bool:
            self.begin_hashes.append(payload_hash)
            return payload_hash == first_store.begin_hashes[0]

    changed_store = HashGuardStore(db, payload=standard_payload(title="Different title"))
    changed_email = FakeEmail()
    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: changed_email, settings_factory=settings, store_factory=lambda _db: changed_store)

    assert result == {"status": "suppressed"}
    assert changed_store.begin_hashes != first_store.begin_hashes
    assert changed_email.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "configuration", "expected"),
    [
        (standard_payload(email=None), settings(), {"kind": "terminal", "error_category": "recipient_missing"}),
        (standard_payload(has_login_access=False), settings(), {"kind": "terminal", "error_category": "activation_required"}),
        (standard_payload(target_type="unknown"), settings(), {"kind": "terminal", "error_category": "internal_error"}),
        (standard_payload(), settings(provider="smtp"), {"kind": "defer", "error_category": "configuration_missing"}),
    ],
)
async def test_missing_email_or_login_and_incomplete_configuration_never_send(payload, configuration, expected):
    db = FakeDb()
    store = FakeStore(db, payload=payload)
    email = FakeEmail()

    result = await deliver(TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db), email_factory=lambda: email, settings_factory=lambda: configuration, store_factory=lambda _db: store)

    assert result in ({"status": "dead"}, {"status": "deferred"})
    assert email.calls == []
    assert store.finalized == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["accepted", "timeout", "missing_id"])
async def test_configured_smtp_reserves_transport_and_never_requests_retry(outcome):
    db = FakeDb()
    store = FakeStore(db)
    configuration = settings(provider="smtp")
    configuration.SMTP_HOST = "smtp.example.test"
    configuration.SMTP_PORT = 587
    configuration.EMAIL = "sender@example.test"
    configuration.EMAIL_PASSWORD = "synthetic"
    email = FakeEmail(
        failure=EmailDeliveryError("provider_timeout", "safe") if outcome == "timeout" else None,
        message_id=None if outcome == "missing_id" else "<opaque@kml.kz>",
    )

    result = await deliver(
        TENANT_ID, REMINDER_ID, session_factory=lambda: FakeSession(db),
        email_factory=lambda: email, settings_factory=lambda: configuration,
        store_factory=lambda _db: store,
    )

    assert store.transport == "smtp"
    assert len(email.calls) == 1
    if outcome == "accepted":
        assert result == {"status": "sent"}
        assert store.finalized == [{"kind": "success", "message_id": "<opaque@kml.kz>"}]
    else:
        assert result == {"status": "terminal"}
        assert store.finalized == [{"kind": "terminal", "error_category": "delivery_uncertain"}]


class RecoveryStore:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    async def due(self, limit: int):
        assert limit == 100
        return [DueLearningReminder(id=REMINDER_ID, tenant_id=TENANT_ID), DueLearningReminder(id=TOKEN, tenant_id=TENANT_ID)]


@pytest.mark.asyncio
async def test_recovery_is_bounded_and_isolates_poison_items():
    db = FakeDb()
    calls: list[UUID] = []

    async def fake_delivery(_tenant_id: UUID, reminder_id: UUID):
        calls.append(reminder_id)
        if reminder_id == REMINDER_ID:
            raise RuntimeError("poison")
        return {"status": "sent"}

    result = await recover_due_reminders(
        999, settings_factory=settings, recovery_session_factory=lambda: FakeSession(db), delivery=fake_delivery,
        store_factory=lambda current_db: RecoveryStore(current_db),
    )

    assert result == {"due": 2, "processed": 2, "succeeded": 1, "failed": 1}
    assert calls == [REMINDER_ID, TOKEN]
