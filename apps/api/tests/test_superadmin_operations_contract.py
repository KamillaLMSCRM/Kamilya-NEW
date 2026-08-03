"""Pure contract tests for operations guards and route registration."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import app
from app.models.tenants import Tenant
from app.modules.admin.superadmin import operations
from app.modules.admin.superadmin.operations import (
    CLEANUP_CONFIRM_TOKEN,
    DEFAULT_STALE_AI_JOB_AGE_HOURS,
    MAX_STALE_AI_JOB_AGE_HOURS,
    MIN_CLEANUP_AGE_HOURS,
    MIN_STALE_AI_JOB_AGE_HOURS,
    REQUIRED_CELERY_TASKS,
    STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN,
    STALE_AI_JOB_TERMINAL_STATUS,
    StaleAIJobRecoveryRequest,
    SyntheticCleanupRequest,
    _inspect_celery_worker,
    _is_allowed_synthetic_tenant,
    _runtime_summaries,
)


def _tenant(*, slug: str, is_demo: bool) -> Tenant:
    return Tenant(
        id=uuid4(),
        name="contract-only",
        slug=slug,
        is_demo=is_demo,
        created_at=datetime.now(UTC),
    )


def test_operations_router_is_registered_inside_superadmin_router():
    paths = app.openapi()["paths"]
    assert "/api/v1/admin/super/operations/summary" in paths
    assert "/api/v1/admin/super/operations/cleanup-synthetic" in paths
    assert "/api/v1/admin/super/operations/recover-stale-ai-jobs" in paths


def test_cleanup_guard_requires_demo_flag_and_fixed_prefix():
    assert _is_allowed_synthetic_tenant(
        _tenant(slug="synthetic-contract", is_demo=True)
    )
    assert not _is_allowed_synthetic_tenant(
        _tenant(slug="synthetic-contract", is_demo=False)
    )
    assert not _is_allowed_synthetic_tenant(
        _tenant(slug="customer-contract", is_demo=True)
    )


def test_cleanup_defaults_to_dry_run_and_cannot_lower_age_floor():
    payload = SyntheticCleanupRequest()
    assert payload.dry_run is True
    assert payload.min_age_hours == MIN_CLEANUP_AGE_HOURS

    with pytest.raises(ValidationError):
        SyntheticCleanupRequest(min_age_hours=MIN_CLEANUP_AGE_HOURS - 1)

def test_confirmation_token_is_not_accepted_as_a_default():
    payload = SyntheticCleanupRequest(dry_run=False)
    assert payload.confirm is False
    assert payload.confirm_token is None
    assert CLEANUP_CONFIRM_TOKEN not in payload.model_dump_json()


def test_stale_ai_job_recovery_is_dry_run_and_bounded():
    payload = StaleAIJobRecoveryRequest()
    assert payload.dry_run is True
    assert payload.min_age_hours == DEFAULT_STALE_AI_JOB_AGE_HOURS
    assert payload.confirm is False
    assert payload.confirm_token is None
    assert STALE_AI_JOB_TERMINAL_STATUS == "cancelled"
    assert STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN not in payload.model_dump_json()

    with pytest.raises(ValidationError):
        StaleAIJobRecoveryRequest(min_age_hours=MIN_STALE_AI_JOB_AGE_HOURS - 1)
    with pytest.raises(ValidationError):
        StaleAIJobRecoveryRequest(min_age_hours=MAX_STALE_AI_JOB_AGE_HOURS + 1)


def test_runtime_summary_is_safe_and_gracefully_allows_missing_metrics():
    host, process, filesystem = _runtime_summaries()

    assert host.cpu_percent is None or 0 <= host.cpu_percent <= 100
    assert process.process_id > 0
    assert process.rss_memory_bytes is None or process.rss_memory_bytes > 0
    assert filesystem.total_bytes is None or filesystem.total_bytes > 0
    assert filesystem.free_bytes is None or filesystem.free_bytes >= 0
    assert filesystem.used_percent is None or 0 <= filesystem.used_percent <= 100
    assert "C:\\" not in process.model_dump_json()


def test_celery_probe_returns_unavailable_without_broker_details(monkeypatch):
    def fail_inspect(*args, **kwargs):
        raise TimeoutError("broker details must not escape")

    monkeypatch.setattr(operations.celery_app.control, "inspect", fail_inspect)

    summary = _inspect_celery_worker()

    assert summary.status == "unavailable"
    assert summary.reachable is False
    assert summary.registered_required_tasks == []
    assert summary.missing_required_tasks == list(REQUIRED_CELERY_TASKS)
    assert "broker details" not in summary.model_dump_json()


def test_celery_probe_returns_only_required_task_names(monkeypatch):
    class FakeInspector:
        def registered(self):
            return {
                "worker-host-secret": [
                    "ai.generate_course",
                    "private.task.with.payload",
                ]
            }

    monkeypatch.setattr(
        operations.celery_app.control,
        "inspect",
        lambda **kwargs: FakeInspector(),
    )

    summary = _inspect_celery_worker()

    assert summary.status == "available"
    assert summary.worker_count == 1
    assert summary.registered_required_tasks == ["ai.generate_course"]
    assert "worker-host-secret" not in summary.model_dump_json()
    assert "private.task.with.payload" not in summary.model_dump_json()


@pytest.mark.asyncio
async def test_celery_probe_timeout_returns_unavailable(monkeypatch):
    monkeypatch.setattr(operations, "CELERY_INSPECT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(operations, "_inspect_celery_worker", lambda: time.sleep(0.1))

    summary = await operations._celery_worker_summary()

    assert summary.status == "unavailable"
    assert summary.reachable is False
