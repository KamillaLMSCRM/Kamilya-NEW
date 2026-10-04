"""New HTTP gates and wire contracts without database/provider calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException, Response

from app.modules.methodologist_workbench import document_router as router
from app.modules.methodologist_workbench.document_intent import DocumentCandidate, DocumentInterpretRequest
from app.modules.methodologist_workbench.plan_contract import ConfirmationRequest


@pytest.mark.parametrize("workbench,document", [(False, False), (False, True), (True, False)])
def test_document_gate_requires_both_flags(monkeypatch, workbench, document):
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        METHODOLOGIST_WORKBENCH_ENABLED=workbench, METHODOLOGIST_DOCUMENT_DRAFT_ENABLED=document))
    with pytest.raises(HTTPException) as error:
        router._context(SimpleNamespace(tenant_id=UUID(int=1)), Response())
    assert error.value.status_code == 404


@pytest.mark.parametrize("tenant,impersonating", [(None, False), (UUID(int=1), True)])
def test_document_context_rejects_missing_tenant_and_impersonation(monkeypatch, tenant, impersonating):
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        METHODOLOGIST_WORKBENCH_ENABLED=True, METHODOLOGIST_DOCUMENT_DRAFT_ENABLED=True))
    with pytest.raises(HTTPException) as error:
        router._context(SimpleNamespace(tenant_id=tenant, is_impersonating=impersonating), Response())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_interpretation_returns_six_editable_fields_not_authority(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        METHODOLOGIST_WORKBENCH_ENABLED=True, METHODOLOGIST_DOCUMENT_DRAFT_ENABLED=True))
    proposal = DocumentCandidate(language="ru", course_intent="Explain safety")
    monkeypatch.setattr(router, "interpret_document", AsyncMock(return_value=proposal))
    db = SimpleNamespace(commit=AsyncMock())
    response = Response()
    user = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), role="methodologist")
    result = await router.interpret_instruction(DocumentInterpretRequest(instruction="Explain safety", language="ru"), response, db, user)
    payload = result.model_dump(mode="json")
    assert payload["state"] == "interpreted"
    assert set(payload["candidate"]) == {"target_audience", "course_intent", "course_format", "language", "source_strategy", "combination_goal"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_confirm_path_mismatch_does_not_call_command(monkeypatch):
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        METHODOLOGIST_WORKBENCH_ENABLED=True, METHODOLOGIST_DOCUMENT_DRAFT_ENABLED=True))
    submit = AsyncMock()
    monkeypatch.setattr(router, "confirm_document_plan", submit)
    user = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), role="methodologist")
    body = ConfirmationRequest(plan_id=UUID(int=3), revision=1, fingerprint="a" * 64)
    with pytest.raises(HTTPException) as error:
        await router.confirm_document(UUID(int=4), body, Response(), SimpleNamespace(), user)
    assert error.value.status_code == 422
    submit.assert_not_awaited()
