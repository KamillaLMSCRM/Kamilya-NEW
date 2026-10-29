"""QA holds cannot change production or other DEV tenants."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.courses.source_uncertainty import qa_source_holds_enabled, require_source_uncertainty_clear


def test_other_tenants_do_not_load_qa_runtime_settings(monkeypatch):
    def unavailable_settings():
        raise AssertionError("Non-QA source inspection must not require runtime settings")

    monkeypatch.setattr("app.core.config.get_settings", unavailable_settings)
    assert not qa_source_holds_enabled(uuid4())


def test_hold_scope_is_explicit_dev_qa_only(monkeypatch):
    settings = SimpleNamespace(AI_QA_LUNA_DEV_ENABLED=True, DEPLOYMENT_ENVIRONMENT="render-development",
        AI_LESSON_CYCLE_DEV_ENABLED=True, AI_LESSON_CYCLE_DEV_TENANTS=[str(QA_TENANT)])
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    assert qa_source_holds_enabled(QA_TENANT)
    settings.DEPLOYMENT_ENVIRONMENT = "render-development-worker"
    assert qa_source_holds_enabled(QA_TENANT)
    settings.DEPLOYMENT_ENVIRONMENT = "render-development"
    assert not qa_source_holds_enabled(uuid4())
    settings.AI_QA_LUNA_DEV_ENABLED = False
    assert not qa_source_holds_enabled(QA_TENANT)
    settings.AI_QA_LUNA_DEV_ENABLED = True
    settings.DEPLOYMENT_ENVIRONMENT = "production"
    with pytest.raises(HTTPException) as error:
        qa_source_holds_enabled(QA_TENANT)
    assert error.value.status_code == 503
    settings.AI_QA_LUNA_DEV_ENABLED = False
    assert not qa_source_holds_enabled(QA_TENANT)
    settings.AI_QA_LUNA_DEV_ENABLED = True
    settings.DEPLOYMENT_ENVIRONMENT = "render-development"
    settings.AI_LESSON_CYCLE_DEV_TENANTS = []
    with pytest.raises(HTTPException) as error:
        qa_source_holds_enabled(QA_TENANT)
    assert error.value.status_code == 503


@pytest.mark.parametrize("analysis", [None, [], "invalid"])
def test_malformed_source_analysis_is_held(analysis):
    with pytest.raises(HTTPException) as error:
        require_source_uncertainty_clear(analysis)
    assert error.value.status_code == 409
