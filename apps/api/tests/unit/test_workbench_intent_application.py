"""Interpretation HTTP/admission seams, without providers or live database."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.auth import get_current_active_user
from app.core.db import get_db
from app.modules.methodologist_workbench import assignment_router as routes
from app.modules.methodologist_workbench import assignment_service as assignments
from app.modules.methodologist_workbench import intent_application as application
from app.modules.methodologist_workbench.assignment_schemas import (
    AssignmentInterpretRequest,
    AssignmentPreview,
    Clarification,
    Recipient,
)
from app.modules.methodologist_workbench.plan_contract import ActorContext

NOW = datetime(2026, 10, 4, 8, tzinfo=UTC)
ACTOR = ActorContext(tenant_id=UUID(int=2), actor_id=UUID(int=3), active_role="methodologist")
BODY = AssignmentInterpretRequest(instruction="Подготовь курс Курс для отдела Отдел до 20 октября 2026 года", timezone_name="Asia/Qyzylorda")
CONTENT = json.dumps({"action": "assignment_preview", "course_query": "Курс", "department_query": "Отдел", "due_date": "2026-10-20", "due_time": "18:00:00", "notify": False, "include_descendants": False})


def setup(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock())
    charge = AsyncMock()
    refund = AsyncMock()
    provider = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=CONTENT)))
    resolver = AsyncMock(return_value=provider)
    monkeypatch.setattr(application, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(application, "refund_llm_budget", refund)
    monkeypatch.setattr(application, "_set_tenant_security_context", AsyncMock())
    monkeypatch.setattr(application, "_set_user_security_context", AsyncMock())
    return db, charge, refund, provider, resolver


async def test_one_interpretation_reserves_before_provider_and_never_assigns(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    events = []
    charge.side_effect = lambda *a, **k: events.append("charge")
    db.commit.side_effect = lambda: events.append("commit")
    resolver.side_effect = lambda *a: events.append("provider") or provider
    result = await application.interpret_assignment(db, ACTOR, BODY, provider_resolver=resolver, now=NOW)
    assert result.state == "interpreted" and result.candidate.due_time == "18:00:00"
    assert events == ["charge", "commit", "provider"]
    assert charge.call_args.kwargs == {"operation": "assignment_intent_parse", "estimated_cost_cents": 1}
    provider.ainvoke.assert_awaited_once()
    refund.assert_not_awaited()
    resolver.assert_awaited_once_with(ACTOR.tenant_id)


@pytest.mark.parametrize("failure", ["bad_json", "provider", "timeout", "expired_date", "forged_authority", "unsupported"])
async def test_failed_output_has_no_semantic_retry_and_refunds_estimate(monkeypatch, failure):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    if failure in {"provider", "timeout"}:
        provider.ainvoke.side_effect = RuntimeError("DO NOT EXPOSE secret endpoint") if failure == "provider" else TimeoutError()
    else:
        content = json.loads(CONTENT)
        if failure == "expired_date":
            content["due_date"] = "2020-01-01"
        if failure == "forged_authority":
            content["tenant_id"] = "forged"
        if failure == "unsupported":
            content["action"] = "unsupported"
        provider.ainvoke.return_value.content = "broken" if failure == "bad_json" else json.dumps(content)
    result = await application.interpret_assignment(db, ACTOR, BODY, provider_resolver=resolver, now=NOW)
    assert result.state == "clarification_needed"
    assert "secret" not in result.model_dump_json()
    assert result.course_choices == result.department_choices == ()
    provider.ainvoke.assert_awaited_once()
    refund.assert_awaited_once()
    application._set_tenant_security_context.assert_awaited_once_with(db, str(ACTOR.tenant_id))
    application._set_user_security_context.assert_awaited_once_with(db, ACTOR.actor_id)


async def test_budget_denial_precedes_provider_resolution(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    charge.side_effect = HTTPException(429, "llm_budget_exceeded")
    with pytest.raises(HTTPException):
        await application.interpret_assignment(db, ACTOR, BODY, provider_resolver=resolver, now=NOW)
    resolver.assert_not_awaited()
    provider.ainvoke.assert_not_awaited()
    refund.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_external_task_cancellation_refunds_committed_admission_and_propagates(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    provider.ainvoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await application.interpret_assignment(db, ACTOR, BODY, provider_resolver=resolver, now=NOW)
    charge.assert_awaited_once()
    refund.assert_awaited_once()
    assert db.commit.await_count == 2  # reservation, then cancellation refund
    application._set_tenant_security_context.assert_awaited_once_with(db, str(ACTOR.tenant_id))
    application._set_user_security_context.assert_awaited_once_with(db, ACTOR.actor_id)


@pytest.mark.parametrize("role", ["admin", "student", "superadmin"])
async def test_wrong_active_role_never_charges_or_resolves(monkeypatch, role):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    with pytest.raises(assignments.WorkbenchConflict, match="role_denied"):
        await application.interpret_assignment(db, ACTOR.model_copy(update={"active_role": role}), BODY, provider_resolver=resolver)
    charge.assert_not_awaited()
    resolver.assert_not_awaited()


async def test_invalid_timezone_never_charges(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    result = await application.interpret_assignment(db, ACTOR, BODY.model_copy(update={"timezone_name": "Bad/Zone"}), provider_resolver=resolver)
    assert result.code == "timezone_invalid"
    charge.assert_not_awaited()
    resolver.assert_not_awaited()


@pytest.mark.parametrize("instruction", ["Назначь курс завтра", "Assign tomorrow", "Ертең тағайында"])
async def test_known_relative_deadline_clarifies_without_paid_call(monkeypatch, instruction):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    result = await application.interpret_assignment(db, ACTOR, BODY.model_copy(update={"instruction": instruction}), provider_resolver=resolver)
    assert result.code == "intent_relative_deadline"
    charge.assert_not_awaited()
    resolver.assert_not_awaited()


async def test_foreign_or_expired_previous_plan_denied_before_admission(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    previous = AsyncMock(side_effect=assignments.WorkbenchNotFound("plan_not_found"))
    monkeypatch.setattr(application, "get_assignment_plan", previous)
    body = BODY.model_copy(update={"previous_plan_id": UUID(int=99)})
    with pytest.raises(assignments.WorkbenchNotFound):
        await application.interpret_assignment(db, ACTOR, body, provider_resolver=resolver)
    previous.assert_awaited_once_with(db, ACTOR, UUID(int=99))
    charge.assert_not_awaited()
    resolver.assert_not_awaited()


async def test_correction_uses_owned_minimal_context_and_preserves_time_not_pii(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    plan = AssignmentPreview(
        plan_id=UUID(int=10), revision=1, fingerprint="a" * 64,
        expires_at=NOW.replace(day=5), course_id=UUID(int=4), course_title="Курс",
        release_id=UUID(int=8), department_id=UUID(int=5), department_name="Отдел",
        timezone_name="Asia/Qyzylorda", due_at=datetime(2026, 10, 19, 13, tzinfo=UTC),
        notify=False, include_descendants=False,
        recipients=(Recipient(user_id=UUID(int=6), label="PRIVATE_RECIPIENT", already_assigned=False, access_warning=False),),
        new_count=1, skipped_count=0,
    )
    monkeypatch.setattr(application, "get_assignment_plan", AsyncMock(return_value=plan))
    content = json.loads(CONTENT)
    content.update(due_time=None, notify=None, include_descendants=None)
    provider.ainvoke.return_value.content = json.dumps(content)
    result = await application.interpret_assignment(
        db, ACTOR, BODY.model_copy(update={"previous_plan_id": plan.plan_id, "notify": True}),
        provider_resolver=resolver, now=NOW,
    )
    assert result.candidate.due_time == "18:00:00" and result.candidate.notify is True
    messages = provider.ainvoke.call_args.args[0]
    data = json.loads(messages[1]["content"])
    assert data["previous_candidate"]["course_query"] == "Курс"
    assert data["previous_candidate"]["due_time"] == "18:00:00"
    assert "PRIVATE_RECIPIENT" not in str(messages)
    assert str(plan.plan_id) not in str(messages)
    assert str(ACTOR.tenant_id) not in str(messages)


async def test_provider_factory_preserves_tenant_route_without_transport_retries(monkeypatch):
    factory = AsyncMock()
    monkeypatch.setattr(application.ResilientLLMClient, "from_settings_async", factory)
    await application.resolve_intent_provider(ACTOR.tenant_id)
    factory.assert_awaited_once_with(tenant_id=ACTOR.tenant_id, temperature=0, max_tokens=1200, max_retries_per_provider=0)


def client(monkeypatch, role="methodologist", enabled=True, impersonating=False):
    app = FastAPI()
    app.include_router(routes.router)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    user = SimpleNamespace(id=ACTOR.actor_id, tenant_id=ACTOR.tenant_id, role=role, is_impersonating=impersonating)
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(METHODOLOGIST_WORKBENCH_ENABLED=enabled))
    return TestClient(app), db


@pytest.mark.parametrize("role,enabled,impersonating,status", [("admin", True, False, 403), ("student", True, False, 403), ("superadmin", True, False, 403), ("methodologist", False, False, 404), ("methodologist", True, True, 403)])
def test_http_role_feature_impersonation_before_interpreter(monkeypatch, role, enabled, impersonating, status):
    http, db = client(monkeypatch, role, enabled, impersonating)
    call = AsyncMock()
    monkeypatch.setattr(routes, "interpret_assignment", call)
    response = http.post("/methodologist-workbench/interpret-assignment", json=BODY.model_dump(mode="json"))
    assert response.status_code == status
    call.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_http_clarification_no_store_and_commit(monkeypatch):
    http, db = client(monkeypatch)
    call = AsyncMock(return_value=Clarification(code="intent_clarification"))
    monkeypatch.setattr(routes, "interpret_assignment", call)
    response = http.post("/methodologist-workbench/interpret-assignment", json=BODY.model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["state"] == "clarification_needed"
    assert response.headers["cache-control"] == "no-store"
    db.commit.assert_awaited_once()


def test_http_budget_denial_rollback(monkeypatch):
    http, db = client(monkeypatch)
    monkeypatch.setattr(routes, "interpret_assignment", AsyncMock(side_effect=HTTPException(429, "llm_budget_exceeded")))
    response = http.post("/methodologist-workbench/interpret-assignment", json=BODY.model_dump(mode="json"))
    assert response.status_code == 429
    db.rollback.assert_awaited_once()


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "approved", "recipients", "course_id"])
def test_http_extra_authority_rejected_before_interpreter(monkeypatch, field):
    http, db = client(monkeypatch)
    call = AsyncMock()
    monkeypatch.setattr(routes, "interpret_assignment", call)
    response = http.post("/methodologist-workbench/interpret-assignment", json={**BODY.model_dump(mode="json"), field: "forged"})
    assert response.status_code == 422
    call.assert_not_awaited()
