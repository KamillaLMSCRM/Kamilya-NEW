import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

path = Path(__file__).resolve().parents[1] / "dev_private_model_acceptance.py"
spec = importlib.util.spec_from_file_location("dev_model_acceptance", path)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.mark.parametrize("change", [
    {"DEPLOYMENT_ENVIRONMENT": "kz-production"},
    {"DEV_MODEL_ACCEPTANCE_ROLE": "admin"},
    {"DEV_MODEL_ACCEPTANCE_ID": "unbounded"},
    {"DEV_MODEL_ACCEPTANCE_SCOPE": "unbounded"},
    {"DEV_MODEL_ACCEPTANCE_UNTIL": "invalid"},
    {"DEV_MODEL_ACCEPTANCE_UNTIL": "2026-10-16T08:00:00"},
    {"DEV_MODEL_ACCEPTANCE_UNTIL": "2026-10-16T08:00:00+00:00"},
    {"DEV_MODEL_ACCEPTANCE_UNTIL": "2026-10-17T09:00:00+00:00"},
])
def test_no_model_call_outside_bounded_explicit_dev_optin(change):
    now = datetime(2026, 10, 16, 9, tzinfo=UTC)
    config = {"DEPLOYMENT_ENVIRONMENT": "render-development", "DEV_MODEL_ACCEPTANCE_ROLE": "api",
        "DEV_MODEL_ACCEPTANCE_ID": "DEV-PRIVATE-20261016-A1",
        "DEV_MODEL_ACCEPTANCE_UNTIL": (now + timedelta(minutes=10)).isoformat()}
    assert acceptance.enabled(config, now)
    assert not acceptance.enabled({**config, **change}, now)


def test_active_request_deadline_cannot_outlive_expiry():
    now = datetime(2026, 10, 16, 9, tzinfo=UTC)
    config = {"DEPLOYMENT_ENVIRONMENT": "render-development", "DEV_MODEL_ACCEPTANCE_ROLE": "api",
        "DEV_MODEL_ACCEPTANCE_ID": "DEV-PRIVATE-20261016-A1",
        "DEV_MODEL_ACCEPTANCE_UNTIL": (now + timedelta(seconds=2)).isoformat()}
    assert acceptance.call_deadline(config, now) == 2
    assert acceptance.call_deadline(config, now + timedelta(seconds=3)) == 0


def test_worker_optin_requires_its_canonical_environment():
    now = datetime(2026, 10, 16, 9, tzinfo=UTC)
    config = {"DEPLOYMENT_ENVIRONMENT": "render-development-worker", "DEV_MODEL_ACCEPTANCE_ROLE": "worker",
        "DEV_MODEL_ACCEPTANCE_ID": "DEV-PRIVATE-20261016-A1",
        "DEV_MODEL_ACCEPTANCE_UNTIL": (now + timedelta(minutes=10)).isoformat()}
    assert acceptance.enabled(config, now)
    assert not acceptance.enabled({**config, "DEPLOYMENT_ENVIRONMENT": "render-development"}, now)


def test_owner_deferred_scope_is_explicitly_bounded():
    now = datetime(2026, 10, 16, 9, tzinfo=UTC)
    config = {"DEPLOYMENT_ENVIRONMENT": "render-development", "DEV_MODEL_ACCEPTANCE_ROLE": "api",
        "DEV_MODEL_ACCEPTANCE_ID": "DEV-PRIVATE-20261016-A1",
        "DEV_MODEL_ACCEPTANCE_SCOPE": "primary_chatgpt",
        "DEV_MODEL_ACCEPTANCE_UNTIL": (now + timedelta(minutes=10)).isoformat()}
    assert acceptance.enabled(config, now)
    assert acceptance.call_deadline(config, now) == 35


def test_partial_transport_chain_cannot_contact_asus_even_if_both_providers_fail():
    clients = [SimpleNamespace(config=name) for name in ("deepseek", "chatgpt", "glm-asus")]
    assert acceptance.permitted_provider_configs(clients, partial=True) == ["deepseek", "chatgpt"]
    assert acceptance.permitted_provider_configs(clients, partial=False) == ["deepseek", "chatgpt", "glm-asus"]
