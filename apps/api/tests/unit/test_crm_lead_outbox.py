from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.tenants import crm_outbox
from app.modules.tenants.crm_outbox import (
    ClaimedLeadEvent,
    _deliver_with_adapters,
    signed_headers,
)

BODY = (
    b'{"company_name":"Kamilya QA","lead_id":'
    b'"00000000-0000-0000-0000-000000000001"}'
)
EVENT_ID = "lmslead_00000000000000000000000000000001"


def test_production_crm_webhook_requires_https():
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            JWT_SECRET="x" * 32,
            CRM_WEBHOOK_URL="http://crm.internal/webhooks/lms",
        )


def test_development_crm_webhook_can_use_http():
    settings = Settings(
        _env_file=None,
        APP_ENV="development",
        JWT_SECRET="x" * 32,
        CRM_WEBHOOK_URL="http://localhost:9000/webhooks/lms",
    )

    assert settings.CRM_WEBHOOK_URL.startswith("http://")


def test_health_url_is_explicit_and_production_safe():
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        JWT_SECRET="x" * 32,
        CRM_WEBHOOK_URL="https://crm.example/webhooks/lms",
        CRM_WEBHOOK_HEALTH_URL="https://crm.example/health",
    )

    assert settings.CRM_WEBHOOK_HEALTH_URL == "https://crm.example/health"


def test_production_crm_urls_reject_credentials_and_unsafe_health_scheme():
    with pytest.raises(ValidationError, match="credentials"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            JWT_SECRET="x" * 32,
            CRM_WEBHOOK_URL="https://user:password@crm.example/webhooks/lms",
        )
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            JWT_SECRET="x" * 32,
            CRM_WEBHOOK_URL="https://crm.example/webhooks/lms",
            CRM_WEBHOOK_HEALTH_URL="http://crm.example/health",
        )


@pytest.mark.asyncio
async def test_receiver_health_url_derives_from_webhook_origin():
    event = _event()
    store = FakeStore(event)
    transport = FakeTransport(200)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=transport,
        webhook_url="https://crm.example/webhooks/lms",
        webhook_secret="fixture-secret",
    )

    assert result["status"] == "success"
    assert transport.health_calls == ["https://crm.example/health"]


def test_production_crm_webhook_rejects_a_short_secret():
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            JWT_SECRET="x" * 32,
            CRM_WEBHOOK_SECRET="too-short",
        )


class FakeStore:
    def __init__(
        self,
        event: ClaimedLeadEvent | None,
        *,
        finalize_result: bool = True,
    ):
        self.event = event
        self.finalize_result = finalize_result
        self.finalizations: list[dict] = []
        self.claim_calls = 0

    async def claim(self, event_id: UUID) -> ClaimedLeadEvent | None:
        self.claim_calls += 1
        return self.event

    async def finalize(self, event, **kwargs) -> bool:
        self.finalizations.append(kwargs)
        return self.finalize_result


class FakeTransport:
    def __init__(self, status_code: int | None, *, health_status: int | None = 200):
        self.status_code = status_code
        self.health_status = health_status
        self.calls: list[dict] = []
        self.health_calls: list[str] = []

    async def check_health(self, *, url: str) -> bool:
        self.health_calls.append(url)
        if self.health_status is None:
            raise httpx.ConnectError(
                "unavailable",
                request=httpx.Request("GET", url),
            )
        return 200 <= self.health_status < 300

    async def send(self, **kwargs) -> int:
        self.calls.append(kwargs)
        if self.status_code is None:
            raise httpx.ConnectError(
                "unavailable",
                request=httpx.Request("POST", kwargs["url"]),
            )
        return self.status_code


def _event() -> ClaimedLeadEvent:
    return ClaimedLeadEvent(
        id=uuid4(),
        event_id=EVENT_ID,
        event_type="lead.submitted",
        payload_bytes=BODY,
        claim_token=uuid4(),
    )


def test_signature_matches_the_crm_exact_byte_fixture():
    headers = signed_headers(
        event_id=EVENT_ID,
        event_type="lead.submitted",
        body=BODY,
        secret="fixture-secret",
        now=datetime(2024, 8, 9, 10, 40, tzinfo=UTC),
    )

    assert headers["X-LMS-Timestamp"] == "1723200000000"
    assert headers["X-LMS-Signature"] == (
        "0f903e3eda1c480374a9a15c6730fcf1"
        "ca88aedd642883e3873fa3b80969d29d"
    )
    assert headers["X-LMS-Event-Id"] == EVENT_ID
    assert headers["X-LMS-Event-Type"] == "lead.submitted"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_kind", "expected_category"),
    [
        (200, "success", "success"),
        (204, "success", "success"),
        (202, "transient", "transient_http"),
        (400, "terminal", "terminal_http"),
        (422, "terminal", "terminal_http"),
        (429, "transient", "transient_http"),
        (500, "transient", "transient_http"),
    ],
)
async def test_delivery_classifies_http_outcomes(
    status_code,
    expected_kind,
    expected_category,
):
    event = _event()
    store = FakeStore(event)
    transport = FakeTransport(status_code)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=transport,
        webhook_url="https://crm.example/api/v1/webhooks/lms",
        webhook_secret="fixture-secret",
    )

    assert result == {"status": expected_kind, "http_status": status_code}
    assert store.finalizations == [
        {
            "kind": expected_kind,
            "status_code": status_code,
            "error_category": expected_category,
        }
    ]
    assert transport.calls[0]["body"] == BODY


@pytest.mark.asyncio
async def test_network_error_is_transient():
    event = _event()
    store = FakeStore(event)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=FakeTransport(None),
        webhook_url="https://crm.example/api/v1/webhooks/lms",
        webhook_secret="fixture-secret",
    )

    assert result == {"status": "transient", "http_status": 0}
    assert store.finalizations[0] == {
        "kind": "transient",
        "status_code": None,
        "error_category": "network",
    }


@pytest.mark.asyncio
async def test_missing_configuration_defers_without_an_http_call():
    event = _event()
    store = FakeStore(event)
    transport = FakeTransport(200)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=transport,
        webhook_url="",
        webhook_secret="",
    )

    assert result == {"status": "disabled"}
    assert transport.calls == []
    assert transport.health_calls == []
    assert store.claim_calls == 0
    assert store.finalizations == []


@pytest.mark.asyncio
async def test_receiver_not_ready_defers_before_claiming_or_sending():
    event = _event()
    store = FakeStore(event)
    transport = FakeTransport(200, health_status=503)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=transport,
        webhook_url="https://crm.example/api/v1/webhooks/lms",
        webhook_secret="fixture-secret",
        health_url="https://crm.example/health",
    )

    assert result == {"status": "deferred", "reason": "receiver_not_ready"}
    assert transport.health_calls == ["https://crm.example/health"]
    assert transport.calls == []
    assert store.claim_calls == 0
    assert store.finalizations == []


@pytest.mark.asyncio
async def test_receiver_wake_then_delivers_signed_payload():
    event = _event()
    store = FakeStore(event)
    transport = FakeTransport(200, health_status=204)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=transport,
        webhook_url="https://crm.example/api/v1/webhooks/lms",
        webhook_secret="fixture-secret",
        health_url="https://crm.example/health",
    )

    assert result == {"status": "success", "http_status": 200}
    assert transport.health_calls == ["https://crm.example/health"]
    assert transport.calls[0]["body"] == BODY
    assert store.claim_calls == 1
    assert store.finalizations[0]["kind"] == "success"


@pytest.mark.asyncio
async def test_recovery_skips_database_selection_when_integration_disabled(monkeypatch):
    class FailSessionFactory:
        def __call__(self):
            raise AssertionError("disabled integration must not open a database session")

    monkeypatch.setattr(crm_outbox, "async_session_factory", FailSessionFactory())
    monkeypatch.setattr(
        crm_outbox,
        "get_settings",
        lambda: type("Settings", (), {"CRM_WEBHOOK_URL": "", "CRM_WEBHOOK_SECRET": ""})(),
    )

    result = await crm_outbox.recover_due_events()

    assert result == {"status": "disabled", "due": 0, "processed": 0}


@pytest.mark.asyncio
async def test_immediate_dispatch_skips_database_claim_when_integration_disabled(monkeypatch):
    class FailSessionFactory:
        def __call__(self):
            raise AssertionError("disabled integration must not open a database session")

    monkeypatch.setattr(crm_outbox, "async_session_factory", FailSessionFactory())
    monkeypatch.setattr(
        crm_outbox,
        "get_settings",
        lambda: type("Settings", (), {"CRM_WEBHOOK_URL": "", "CRM_WEBHOOK_SECRET": ""})(),
    )

    result = await crm_outbox.deliver_event(uuid4())

    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_duplicate_delivery_is_skipped_when_claim_has_already_been_consumed():
    store = FakeStore(None)

    result = await _deliver_with_adapters(
        event_id=uuid4(),
        store=store,
        transport=FakeTransport(200),
        webhook_url="https://crm.example/api/v1/webhooks/lms",
        webhook_secret="fixture-secret",
    )

    assert result == {"status": "skipped"}
    assert store.finalizations == []


@pytest.mark.asyncio
async def test_lost_claim_does_not_report_delivery_success():
    event = _event()
    store = FakeStore(event, finalize_result=False)

    result = await _deliver_with_adapters(
        event_id=event.id,
        store=store,
        transport=FakeTransport(200),
        webhook_url="https://crm.example/api/v1/webhooks/lms",
        webhook_secret="fixture-secret",
    )

    assert result == {"status": "lost_claim"}


@pytest.mark.asyncio
async def test_recovery_processes_due_rows_directly_without_queue_fanout(
    monkeypatch,
):
    due_ids = [uuid4(), uuid4()]
    processed: list[UUID] = []

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    class FakeDueStore:
        def __init__(self, _db):
            pass

        async def due_ids(self, limit):
            assert limit == 20
            return due_ids

    async def fake_deliver(event_id):
        processed.append(event_id)
        return {"status": "success"}

    monkeypatch.setattr(
        crm_outbox,
        "async_session_factory",
        lambda: FakeSessionContext(),
    )
    monkeypatch.setattr(
        crm_outbox,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"CRM_WEBHOOK_URL": "https://crm.example/webhooks/lms", "CRM_WEBHOOK_SECRET": "fixture-secret"},
        )(),
    )
    monkeypatch.setattr(crm_outbox, "PostgresCRMOutboxStore", FakeDueStore)
    monkeypatch.setattr(crm_outbox, "deliver_event", fake_deliver)

    result = await crm_outbox.recover_due_events()

    assert result == {"due": 2, "processed": 2}
    assert processed == due_ids
