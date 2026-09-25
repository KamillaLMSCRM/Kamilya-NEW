"""Pure contract tests for operations guards and route registration."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import app
from app.models.tenants import Tenant
from app.modules.admin.superadmin import operations
from app.modules.admin.superadmin.operations import (
    CLEANUP_CONFIRM_TOKEN,
    CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN,
    DEFAULT_STALE_AI_JOB_AGE_HOURS,
    MAX_STALE_AI_JOB_AGE_HOURS,
    MIN_CLEANUP_AGE_HOURS,
    MIN_STALE_AI_JOB_AGE_HOURS,
    REQUIRED_CELERY_TASKS,
    STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN,
    STALE_AI_JOB_TERMINAL_STATUS,
    CRMLeadOutboxOperationsSummary,
    CRMLeadOutboxRequeueRequest,
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
    assert "/api/v1/admin/super/operations/requeue-failed-crm-leads" in paths


def test_cleanup_guard_requires_demo_flag_and_fixed_prefix():
    assert _is_allowed_synthetic_tenant(_tenant(slug="synthetic-contract", is_demo=True))
    assert not _is_allowed_synthetic_tenant(_tenant(slug="synthetic-contract", is_demo=False))
    assert not _is_allowed_synthetic_tenant(_tenant(slug="customer-contract", is_demo=True))


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


def test_crm_outbox_requeue_is_dry_run_and_requires_explicit_confirmation():
    payload = CRMLeadOutboxRequeueRequest()
    assert payload.dry_run is True
    assert payload.limit == 20
    assert payload.confirm is False
    assert payload.confirm_token is None
    assert CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN not in payload.model_dump_json()

    with pytest.raises(ValidationError):
        CRMLeadOutboxRequeueRequest(limit=0)
    with pytest.raises(ValidationError):
        CRMLeadOutboxRequeueRequest(limit=101)


def test_crm_operations_summary_exposes_disabled_held_state():
    summary = CRMLeadOutboxOperationsSummary(
        integration_status="disabled",
        held_count=147,
        pending_count=41,
        retry_count=106,
        claimed_count=0,
        dead_count=0,
        delivered_count=0,
    )

    assert summary.integration_status == "disabled"
    assert summary.held_count == 147


def test_runtime_summary_is_safe_and_gracefully_allows_missing_metrics():
    host, process, filesystem = _runtime_summaries()

    assert host.cpu_percent is None or 0 <= host.cpu_percent <= 100
    assert host.total_memory_bytes is None or host.total_memory_bytes > 0
    assert host.available_memory_bytes is None or host.available_memory_bytes >= 0
    assert host.used_memory_bytes is None or host.used_memory_bytes >= 0
    assert host.used_memory_percent is None or 0 <= host.used_memory_percent <= 100
    assert process.process_id > 0
    assert process.rss_memory_bytes is None or process.rss_memory_bytes > 0
    assert filesystem.total_bytes is None or filesystem.total_bytes > 0
    assert filesystem.free_bytes is None or filesystem.free_bytes >= 0
    assert filesystem.used_percent is None or 0 <= filesystem.used_percent <= 100
    assert "C:\\" not in process.model_dump_json()


def test_runtime_summary_maps_host_memory_without_confusing_it_with_process_rss(monkeypatch):
    monkeypatch.setattr(
        operations.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(
            total=16 * 1024**3,
            available=6 * 1024**3,
            used=10 * 1024**3,
            percent=62.5,
        ),
    )

    host, process, _filesystem = _runtime_summaries()

    assert host.total_memory_bytes == 16 * 1024**3
    assert host.available_memory_bytes == 6 * 1024**3
    assert host.used_memory_bytes == 10 * 1024**3
    assert host.used_memory_percent == 62.5
    assert process.rss_memory_bytes != host.used_memory_bytes


def test_celery_probe_returns_unavailable_without_broker_details(monkeypatch):
    def fail_inspect(*args, **kwargs):
        raise TimeoutError("broker details must not escape")

    monkeypatch.setattr(operations.celery_app.control, "inspect", fail_inspect)

    summary = _inspect_celery_worker()

    assert summary.status == "unavailable"
    assert summary.health == "unavailable"
    assert summary.reachable is False
    assert [worker.role for worker in summary.workers] == ["fast", "documents", "ai"]
    assert all(worker.status == "unavailable" for worker in summary.workers)
    assert summary.registered_required_tasks == []
    assert summary.missing_required_tasks == list(REQUIRED_CELERY_TASKS)
    assert "broker details" not in summary.model_dump_json()


def test_celery_probe_returns_only_required_task_names(monkeypatch):
    class FakeInspector:
        def registered(self):
            return {
                "fast@worker-host-secret": [
                    "ai.generate_course",
                    "private.task.with.payload",
                ],
                "documents@worker-host-secret": ["documents.reindex"],
                "ai@worker-host-secret": ["ai.generate_course"],
            }

        def active_queues(self):
            return {
                "fast@worker-host-secret": [
                    {"name": "maintenance"},
                    {"name": "notifications"},
                ],
                "documents@worker-host-secret": [{"name": "documents"}],
                "ai@worker-host-secret": [{"name": "ai"}],
            }

    monkeypatch.setattr(
        operations.celery_app.control,
        "inspect",
        lambda **kwargs: FakeInspector(),
    )

    summary = _inspect_celery_worker()

    assert summary.status == "available"
    assert summary.health == "degraded"
    assert summary.worker_count == 3
    assert summary.registered_required_tasks == [
        "ai.generate_course",
        "documents.reindex",
    ]
    assert [worker.role for worker in summary.workers] == ["fast", "documents", "ai"]
    assert all(worker.status == "healthy" for worker in summary.workers)
    assert "worker-host-secret" not in summary.model_dump_json()
    assert "private.task.with.payload" not in summary.model_dump_json()


def test_celery_probe_reports_partial_queue_degradation_without_hiding_healthy_roles(monkeypatch):
    class FakeInspector:
        def registered(self):
            return {
                "fast@private-node": list(REQUIRED_CELERY_TASKS),
                "documents@private-node": list(REQUIRED_CELERY_TASKS),
                "ai@private-node": list(REQUIRED_CELERY_TASKS),
            }

        def active_queues(self):
            return {
                "fast@private-node": [{"name": "maintenance"}],
                "documents@private-node": [{"name": "documents"}],
                "ai@private-node": [{"name": "ai"}],
            }

    monkeypatch.setattr(
        operations.celery_app.control,
        "inspect",
        lambda **kwargs: FakeInspector(),
    )

    summary = _inspect_celery_worker()
    workers = {worker.role: worker for worker in summary.workers}

    assert summary.status == "available"
    assert summary.health == "degraded"
    assert workers["fast"].status == "degraded"
    assert workers["fast"].active_queues == ["maintenance"]
    assert workers["fast"].missing_queues == ["notifications"]
    assert workers["documents"].status == "healthy"
    assert workers["ai"].status == "healthy"
    assert "private-node" not in summary.model_dump_json()


def test_celery_probe_degrades_role_without_exposing_unapproved_queue_name(monkeypatch):
    class FakeInspector:
        def registered(self):
            return {
                "fast@private-node": list(REQUIRED_CELERY_TASKS),
                "documents@private-node": list(REQUIRED_CELERY_TASKS),
                "ai@private-node": list(REQUIRED_CELERY_TASKS),
            }

        def active_queues(self):
            return {
                "fast@private-node": [
                    {"name": "maintenance"},
                    {"name": "notifications"},
                    {"name": "customer-private-queue"},
                ],
                "documents@private-node": [{"name": "documents"}],
                "ai@private-node": [{"name": "ai"}],
            }

    monkeypatch.setattr(
        operations.celery_app.control,
        "inspect",
        lambda **kwargs: FakeInspector(),
    )

    summary = _inspect_celery_worker()
    workers = {worker.role: worker for worker in summary.workers}

    assert summary.health == "degraded"
    assert workers["fast"].status == "degraded"
    assert workers["fast"].unapproved_queue_count == 1
    assert "customer-private-queue" not in summary.model_dump_json()


@pytest.mark.parametrize("active_queues", [None, {}, []])
def test_celery_probe_fails_closed_when_queue_topology_is_missing(monkeypatch, active_queues):
    class FakeInspector:
        def registered(self):
            return {"fast@private-node": list(REQUIRED_CELERY_TASKS)}

        def active_queues(self):
            return active_queues

    monkeypatch.setattr(
        operations.celery_app.control,
        "inspect",
        lambda **kwargs: FakeInspector(),
    )

    summary = _inspect_celery_worker()

    assert summary.status == "unavailable"
    assert summary.health == "unavailable"
    assert summary.reachable is False
    assert all(worker.status == "unavailable" for worker in summary.workers)
    assert "private-node" not in summary.model_dump_json()


@pytest.mark.asyncio
async def test_celery_probe_timeout_returns_unavailable(monkeypatch):
    monkeypatch.setattr(operations, "CELERY_INSPECT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(operations, "CELERY_INSPECT_OUTER_MARGIN_SECONDS", 0.01)
    monkeypatch.setattr(operations, "_inspect_celery_worker", lambda: time.sleep(0.1))

    summary = await operations._celery_worker_summary()

    assert summary.status == "unavailable"
    assert summary.reachable is False


@pytest.mark.asyncio
async def test_celery_probe_outer_timeout_allows_inspect_margin(monkeypatch):
    inspector_calls = 0
    probe_calls = 0

    class SlowInspector:
        def registered(self):
            nonlocal probe_calls
            probe_calls += 1
            time.sleep(0.04)
            return {
                "fast@private-node": list(REQUIRED_CELERY_TASKS),
                "documents@private-node": list(REQUIRED_CELERY_TASKS),
                "ai@private-node": list(REQUIRED_CELERY_TASKS),
            }

        def active_queues(self):
            nonlocal probe_calls
            probe_calls += 1
            time.sleep(0.04)
            return {
                "fast@private-node": [
                    {"name": "maintenance"},
                    {"name": "notifications"},
                ],
                "documents@private-node": [{"name": "documents"}],
                "ai@private-node": [{"name": "ai"}],
            }

    def inspect_once(**kwargs):
        nonlocal inspector_calls
        inspector_calls += 1
        return SlowInspector()

    monkeypatch.setattr(operations, "CELERY_INSPECT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(operations, "CELERY_INSPECT_OUTER_MARGIN_SECONDS", 0.05)
    monkeypatch.setattr(
        operations.celery_app.control,
        "inspect",
        inspect_once,
    )

    summary = await operations._celery_worker_summary()

    assert summary.status == "available"
    assert summary.worker_count == 3
    assert inspector_calls == 1
    assert probe_calls == 2
