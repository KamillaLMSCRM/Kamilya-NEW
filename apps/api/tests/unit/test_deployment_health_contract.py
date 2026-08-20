from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_exposes_non_secret_deployment_identity():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ok",
        "app": "Kamilya LMS",
        "app_environment": "test",
        "deployment_environment": "local",
        "release_sha": "unknown",
    }
