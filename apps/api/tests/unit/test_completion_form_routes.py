"""In-process HTTP contracts with injected identities, not live JWT/RLS evidence."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.modules.training_evidence import router as form_router
from app.modules.training_evidence.form_settings import TrainingEvidenceFormSettings


def _app(monkeypatch, *, role="admin", tenant_id=None):
    tenant_id = tenant_id or uuid4()
    tenant = SimpleNamespace(name="QA Tenant", settings={"unrelated": True})

    class Database:
        async def get(self, _model, requested_tenant_id):
            assert requested_tenant_id == tenant_id
            return tenant

        async def flush(self):
            pass

    async def identity():
        return SimpleNamespace(id=uuid4(), role=role, tenant_id=tenant_id if role != "superadmin" else None)

    async def database():
        yield Database()

    async def log_action(*_args, **_kwargs):
        pass

    monkeypatch.setattr(form_router, "log_action", log_action)
    monkeypatch.setattr("app.modules.training_evidence.form_settings.flag_modified", lambda *_args: None)
    app = FastAPI()
    app.include_router(form_router.router, prefix="/v1")
    app.dependency_overrides[get_current_active_user] = identity
    app.dependency_overrides[get_db] = database
    return app, tenant


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["student", "methodologist", "superadmin"])
async def test_non_admin_cannot_configure_or_preview(monkeypatch, role):
    app, _ = _app(monkeypatch, role=role)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://unit") as client:
        for method, path in [
            ("GET", "/form-fields"),
            ("GET", "/form-settings"),
            ("PUT", "/form-settings"),
            ("POST", "/form-settings/preview"),
        ]:
            response = await client.request(
                method,
                f"/v1/training-evidence{path}",
                json=TrainingEvidenceFormSettings().model_dump() if method != "GET" else None,
            )
            assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_catalog_save_reload_and_pdf_preview(monkeypatch):
    app, tenant = _app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://unit") as client:
        catalog = await client.get("/v1/training-evidence/form-fields")
        assert catalog.status_code == 200
        required = [item["id"] for item in catalog.json()["fields"] if item["required"]]
        assert set(required) == {"employee_name", "course_title", "test_results"}
        selected = [*required, "test_score"]
        settings = TrainingEvidenceFormSettings(selected_fields=selected).model_dump()
        saved = await client.put("/v1/training-evidence/form-settings", json=settings)
        assert saved.status_code == 200
        reloaded = await client.get("/v1/training-evidence/form-settings")
        assert reloaded.json()["selected_fields"] == selected
        assert tenant.settings["unrelated"] is True
        preview = await client.post("/v1/training-evidence/form-settings/preview", json=reloaded.json())
        assert preview.status_code == 200 and preview.content.startswith(b"%PDF-")
        assert preview.headers["cache-control"] == "no-store"
        invalid = await client.put(
            "/v1/training-evidence/form-settings", json={**settings, "selected_fields": [*required, "email"]}
        )
        assert invalid.status_code == 422
        assert tenant.settings["training_evidence_form_settings"]["selected_fields"] == selected
