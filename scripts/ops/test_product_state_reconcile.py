from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ops.product_state_reconcile import (
    ProductStateError,
    parse_frontend_health,
    reconcile_product_state,
)


SOURCE_SHA = "e" * 40
API_SHA = "a" * 40
WEB_SHA = "b" * 40
SCRIPT = Path(__file__).with_name("product_state_reconcile.py")


def _api(release_sha: str = SOURCE_SHA, version: str = "0.11.11") -> dict[str, str]:
    return {
        "status": "ok",
        "app": "Kamilya LMS",
        "product_version": version,
        "app_environment": "production",
        "deployment_environment": "kz-production",
        "release_sha": release_sha,
    }


def test_reconciliation_reports_exact_alignment() -> None:
    result = reconcile_product_state(
        source_version="0.11.11",
        source_sha=SOURCE_SHA,
        api_payload=_api(),
        frontend_sha=SOURCE_SHA,
        is_ancestor=lambda older, newer: older == newer,
    )

    assert result["status"] == "ALIGNED"
    assert result["source"]["sha"] == SOURCE_SHA
    assert result["api"]["exact"] is True
    assert result["frontend"]["exact"] is True


def test_reconciliation_preserves_legitimate_split_runtime_identity() -> None:
    known_ancestors = {(API_SHA, SOURCE_SHA), (WEB_SHA, SOURCE_SHA)}

    result = reconcile_product_state(
        source_version="0.11.11",
        source_sha=SOURCE_SHA,
        api_payload=_api(API_SHA, "0.11.9"),
        frontend_sha=WEB_SHA,
        is_ancestor=lambda older, newer: (older, newer) in known_ancestors,
    )

    assert result["status"] == "SPLIT_ANCESTRY"
    assert result["api"] == {
        "version": "0.11.9",
        "sha": API_SHA,
        "exact": False,
        "ancestor_of_source": True,
    }
    assert result["frontend"]["ancestor_of_source"] is True


def test_reconciliation_fails_closed_for_runtime_outside_source_history() -> None:
    result = reconcile_product_state(
        source_version="0.11.11",
        source_sha=SOURCE_SHA,
        api_payload=_api(API_SHA, "0.11.9"),
        frontend_sha=WEB_SHA,
        is_ancestor=lambda _older, _newer: False,
    )

    assert result["status"] == "DRIFT"
    assert result["api"]["ancestor_of_source"] is False
    assert result["frontend"]["ancestor_of_source"] is False


def test_frontend_health_requires_matching_body_and_header_sha() -> None:
    assert parse_frontend_health(f"ok {WEB_SHA}", WEB_SHA) == WEB_SHA

    with pytest.raises(ProductStateError, match="frontend_release_mismatch"):
        parse_frontend_health(f"ok {WEB_SHA}", SOURCE_SHA)

    with pytest.raises(ProductStateError, match="frontend_health_invalid"):
        parse_frontend_health("ok latest", "latest")


def test_direct_script_entrypoint_loads_project_modules() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
        cwd=SCRIPT.parent,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--web-health-url" in completed.stdout
