from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[4] / "scripts" / "ops" / "verify_production_endpoint.py"
REPO_ROOT = Path(__file__).parents[4]


def _module():
    spec = importlib.util.spec_from_file_location("verify_production_endpoint", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_verifier_rejects_wrong_environment_and_release():
    module = _module()
    payload = {
        "status": "ok",
        "app": "Kamilya LMS",
        "app_environment": "production",
        "deployment_environment": "render-development",
        "release_sha": "a" * 40,
    }

    errors = module.validate_health_payload(
        payload,
        expected_deployment="kz-production",
        expected_release="b" * 40,
    )

    assert any("deployment_environment" in error for error in errors)
    assert any("release_sha" in error for error in errors)


def test_identity_verifier_accepts_exact_kz_release():
    module = _module()
    payload = {
        "status": "ok",
        "app": "Kamilya LMS",
        "app_environment": "production",
        "deployment_environment": "kz-production",
        "release_sha": "a" * 40,
    }

    assert module.validate_health_payload(
        payload,
        expected_deployment="kz-production",
        expected_release="a" * 40,
    ) == []


def test_identity_verifier_requires_full_commit_sha():
    module = _module()
    payload = {
        "status": "ok",
        "app": "Kamilya LMS",
        "app_environment": "production",
        "deployment_environment": "kz-production",
        "release_sha": "short",
    }

    errors = module.validate_health_payload(
        payload,
        expected_deployment="kz-production",
        expected_release="",
    )

    assert any("full 40-character" in error for error in errors)


def test_verifier_refuses_redirects():
    module = _module()

    assert module._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.test") is None


def test_monitoring_contract_targets_kz_runtime_and_exact_release():
    workflow = (REPO_ROOT / ".github" / "workflows" / "production-smoke.yml").read_text(encoding="utf-8")
    watchdog = (REPO_ROOT / "scripts" / "ops" / "healthcheck.sh").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "infra" / "compose" / "kamilya-app-worker.yml").read_text(encoding="utf-8")
    ops_unit = (REPO_ROOT / "infra" / "systemd" / "kamilya-ops-check.service").read_text(encoding="utf-8")
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "kamilya-lms-api.onrender.com" not in workflow
    assert "verify_production_endpoint.py" in workflow
    assert (
        "EXPECTED_RELEASE_SHA: ${{ github.event_name == 'push' && github.sha "
        "|| vars.KZ_PRODUCTION_RELEASE_SHA }}"
    ) in workflow
    assert "https://api.kml.kz/api/v1/health" in watchdog
    assert "EXPECTED_RELEASE_SHA" in watchdog
    assert "docker compose" in watchdog
    assert "BACKUP_FRESHNESS_PATH" in watchdog
    assert "kamilya-worker.service" not in watchdog
    assert "Requires=docker.service" in ops_unit
    assert "/opt/kamilya-runtime/scripts/ops/healthcheck.sh" in ops_unit
    assert "DEPLOYMENT_ENVIRONMENT: kz-production" in compose
    assert "RELEASE_SHA: ${KAMILYA_RELEASE_SHA" in compose
    assert "render-development" in render
