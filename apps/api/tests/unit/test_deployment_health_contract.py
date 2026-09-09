from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_health_exposes_non_secret_deployment_identity():
    expected_version = (Path(__file__).resolve().parents[4] / "VERSION").read_text(encoding="utf-8").strip()
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ok",
        "app": "Kamilya LMS",
        "product_version": expected_version,
        "app_environment": "test",
        "deployment_environment": "local",
        "release_sha": "unknown",
    }

    assert app.version == expected_version
