"""Synthetic public-seam tests for bounded document interpretation."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.modules.methodologist_workbench import document_intent as application
from app.modules.methodologist_workbench.assignment_service import WorkbenchConflict
from app.modules.methodologist_workbench.plan_contract import ActorContext

ACTOR = ActorContext(tenant_id=UUID(int=2), actor_id=UUID(int=3), active_role="methodologist")
BODY = application.DocumentInterpretRequest(instruction="Сделай вводный курс для склада", language="ru")
CONTENT = json.dumps(
    {
        "action": "document_draft",
        "target_audience": "Сотрудники склада",
        "course_intent": "Научить базовым операциям приемки",
        "course_format": "standard",
        "language": "ru",
        "source_strategy": "single_topic",
        "combination_goal": "",
    },
    ensure_ascii=False,
)


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


async def test_candidate_reserves_before_provider_and_has_no_authority(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    result = await application.interpret_document(db, ACTOR, BODY, provider_resolver=resolver)
    assert result.state == "interpreted"
    assert result.language == "ru"
    assert not any(key in result.model_dump() for key in ("tenant_id", "actor_id", "document_id", "job_id"))
    charge.assert_awaited_once_with(db, "00000000-0000-0000-0000-000000000002", operation="document_intent_parse", estimated_cost_cents=1)
    db.commit.assert_awaited_once()
    provider.ainvoke.assert_awaited_once()
    refund.assert_not_awaited()
    resolver.assert_awaited_once_with(ACTOR.tenant_id)


@pytest.mark.parametrize(
    "content,code",
    [
        ('{"action":"document_draft","target_audience":"a","target_audience":"b"}', "intent_invalid_response"),
        ('{"action":"document_draft","target_audience":"a","unexpected":true}', "intent_invalid_response"),
        ("not-json", "intent_invalid_response"),
        (json.dumps({"action": "unsupported", "code": "no"}), "intent_unsupported"),
        (json.dumps({**json.loads(CONTENT), "source_strategy": "intentional_combination", "combination_goal": "short"}), "source_combination_goal_required"),
    ],
)
async def test_invalid_or_ambiguous_output_refunds_once(monkeypatch, content, code):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    provider.ainvoke.return_value.content = content
    result = await application.interpret_document(db, ACTOR, BODY, provider_resolver=resolver)
    assert result.state == "clarification_needed"
    assert result.code == code
    refund.assert_awaited_once()
    assert db.commit.await_count == (2 if code == "intent_unsupported" else 1)


async def test_budget_denial_precedes_provider(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    charge.side_effect = HTTPException(429, "llm_budget_exceeded")
    with pytest.raises(HTTPException):
        await application.interpret_document(db, ACTOR, BODY, provider_resolver=resolver)
    resolver.assert_not_awaited()
    provider.ainvoke.assert_not_awaited()
    refund.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_cancellation_refunds_committed_admission_and_propagates(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    provider.ainvoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await application.interpret_document(db, ACTOR, BODY, provider_resolver=resolver)
    refund.assert_awaited_once()
    assert db.commit.await_count == 2


async def test_wrong_role_never_charges_or_resolves(monkeypatch):
    db, charge, refund, provider, resolver = setup(monkeypatch)
    with pytest.raises(WorkbenchConflict, match="role_denied"):
        await application.interpret_document(db, ACTOR.model_copy(update={"active_role": "admin"}), BODY, provider_resolver=resolver)
    charge.assert_not_awaited()
    resolver.assert_not_awaited()


def test_default_language_is_selected_and_prompt_is_bounded():
    result = application.parse_model_candidate(
        json.dumps({"action": "document_draft", "target_audience": "", "course_intent": "", "course_format": "automatic", "source_strategy": "single_topic"}),
        default_language="kk",
    )
    assert result.language == "kk"
    messages = application.build_document_intent_messages("x", "kk")
    assert "tenant" in messages[0]["content"] and "x" in messages[1]["content"]
