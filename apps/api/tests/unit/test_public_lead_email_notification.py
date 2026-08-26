from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.core.legal_versions import CURRENT_PUBLIC_LEAD_CONSENT_VERSION
from app.modules.tenants.router import public_router

LEAD_ID = UUID("00000000-0000-0000-0000-000000000321")


class _ScalarResult:
    def scalar_one(self):
        return LEAD_ID


class _FakeDb:
    committed = False

    async def execute(self, _statement, _params):
        return _ScalarResult()

    async def commit(self):
        self.committed = True


def _payload() -> dict[str, object]:
    return {
        "name": "Аскар Амирханов",
        "company": "ТОО Document. KZ",
        "email": "lead@example.kz",
        "phone": "+7 707 275 0007",
        "companySize": 75,
        "industry": "finance",
        "interest": "demo",
        "message": "Нужен показ для руководителя и HR",
        "locale": "ru",
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "kz_finance_search_ru",
        "utm_content": "ag_knowledge_rsa_a",
        "utm_term": "обучение сотрудников",
        "gclid": "test-gclid",
        "referrer": "https://google.kz/",
        "landing_page": "https://kml.kz/ru/finance",
        "attribution_captured_at": "2026-08-13T14:25:00Z",
        "consent_version": CURRENT_PUBLIC_LEAD_CONSENT_VERSION,
        "source_section": "finance_hero",
        "plan": "corporate",
        "roi_employees": 75,
        "roi_industry": "finance",
        "roi_employee_band": "51-100",
        "roi_formula_version": "lead-assessment-v1",
    }


def _client(fake_db: _FakeDb) -> TestClient:
    app = FastAPI()
    app.include_router(public_router, prefix="/api/v1")

    async def override_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_public_lead_api_sends_complete_copy_only_after_commit(monkeypatch):
    fake_db = _FakeDb()
    delivered = []

    async def capture_notification(_service, *, to_email, notification):
        assert fake_db.committed is True
        delivered.append((to_email, notification))

    monkeypatch.setattr(
        "app.modules.tenants.router.get_settings",
        lambda: SimpleNamespace(
            PUBLIC_LEAD_NOTIFICATION_EMAIL=(
                "askar@kml.kz, askar0007amirkhanov@gmail.com; ASKAR@KML.KZ"
            )
        ),
    )
    monkeypatch.setattr("app.modules.tenants.router._dispatch_crm_lead_outbox", lambda _event_id: None)
    monkeypatch.setattr(
        "app.modules.tenants.router.EmailService.send_public_lead_notification",
        capture_notification,
    )

    with _client(fake_db) as client:
        response = client.post("/api/v1/public/leads", json=_payload())

    assert response.status_code == 201
    assert response.json() == {"id": str(LEAD_ID), "ok": True}
    assert len(delivered) == 2
    assert [item[0] for item in delivered] == [
        "askar@kml.kz",
        "askar0007amirkhanov@gmail.com",
    ]
    notification = delivered[0][1]
    assert notification.lead_id == LEAD_ID
    assert notification.name == "Аскар Амирханов"
    assert notification.company == "ТОО Document. KZ"
    assert notification.phone == "+7 707 275 0007"
    assert notification.utm_campaign == "kz_finance_search_ru"
    assert notification.gclid == "test-gclid"
    assert notification.consent_version == CURRENT_PUBLIC_LEAD_CONSENT_VERSION


def test_public_lead_api_stays_successful_when_email_provider_fails(monkeypatch, caplog):
    fake_db = _FakeDb()
    attempted_recipients = []

    async def fail_notification(_service, *, to_email, notification):
        attempted_recipients.append(to_email)
        raise RuntimeError("provider unavailable with private payload")

    monkeypatch.setattr(
        "app.modules.tenants.router.get_settings",
        lambda: SimpleNamespace(
            PUBLIC_LEAD_NOTIFICATION_EMAIL=(
                "askar@kml.kz,askar0007amirkhanov@gmail.com"
            )
        ),
    )
    monkeypatch.setattr("app.modules.tenants.router._dispatch_crm_lead_outbox", lambda _event_id: None)
    monkeypatch.setattr(
        "app.modules.tenants.router.EmailService.send_public_lead_notification",
        fail_notification,
    )

    with _client(fake_db) as client:
        response = client.post("/api/v1/public/leads", json=_payload())

    assert response.status_code == 201
    assert response.json() == {"id": str(LEAD_ID), "ok": True}
    assert fake_db.committed is True
    assert attempted_recipients == [
        "askar@kml.kz",
        "askar0007amirkhanov@gmail.com",
    ]
    assert "private payload" not in caplog.text
