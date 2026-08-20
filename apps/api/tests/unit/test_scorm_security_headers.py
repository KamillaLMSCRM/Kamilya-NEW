from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import security
from app.core.security import SecurityHeadersMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/v1/scorm/packages/pkg/launch")
    async def launch():
        return {"ok": True}

    return app


def test_only_isolated_scorm_origin_is_frameable(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: SimpleNamespace(
            API_PREFIX="/api/v1",
            SCORM_CONTENT_ORIGIN="https://scorm.kml.kz",
            PUBLIC_URL="https://app.kml.kz",
        ),
    )

    with TestClient(_app(), base_url="https://scorm.kml.kz") as client:
        isolated = client.get("/api/v1/scorm/packages/pkg/launch")
    assert isolated.status_code == 200
    assert "x-frame-options" not in isolated.headers
    assert "frame-ancestors https://app.kml.kz" in isolated.headers["content-security-policy"]
    assert isolated.headers["referrer-policy"] == "no-referrer"

    with TestClient(_app(), base_url="https://api.kml.kz") as client:
        trusted_api = client.get("/api/v1/scorm/packages/pkg/launch")
    assert trusted_api.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in trusted_api.headers["content-security-policy"]
