from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import router as ai_router
from app.modules.ai.llm_client import ResilientLLMClient
from app.modules.ai.schemas import AIChatRequest
from app.modules.editor_assistant import router as editor_router
from app.modules.learner_assistant import router as learner_router
from app.modules.learner_assistant.schemas import LearnerAssistantChatRequest
from app.modules.positions import jd_router, recommendations_router

USER_FACING_AI_MODULES = (
    "modules/ai/pipeline.py",
    "modules/ai/router.py",
    "modules/editor_assistant/router.py",
    "modules/learner_assistant/router.py",
    "modules/positions/jd_router.py",
    "modules/positions/recommendations_router.py",
    "modules/quizzes/ai.py",
)


def _missing_tenant_keywords(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    missing: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr != "from_settings_async":
            continue
        if not any(keyword.arg == "tenant_id" for keyword in node.keywords):
            missing.append(node.lineno)
    return missing


def test_every_user_facing_ai_provider_resolution_is_tenant_bound() -> None:
    app_root = Path(__file__).parents[2] / "app"
    missing = {
        relative_path: lines
        for relative_path in USER_FACING_AI_MODULES
        if (lines := _missing_tenant_keywords(app_root / relative_path))
    }

    assert missing == {}


@pytest.mark.asyncio
async def test_methodologist_chat_forwards_authenticated_tenant_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()

    class StubLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="Безопасный ответ по курсу.")

    resolve_provider = AsyncMock(return_value=StubLLM())
    monkeypatch.setattr(ai_router, "_fetch_course_summary", AsyncMock(return_value="Курс: ОТ"))
    monkeypatch.setattr(
        ai_router.ResilientLLMClient,
        "from_settings_async",
        resolve_provider,
    )

    response = await ai_router.chat(
        AIChatRequest(course_id=uuid4(), message="Что улучшить?", language="ru"),
        db=object(),  # type: ignore[arg-type]
        user=SimpleNamespace(tenant_id=tenant_id, role="methodologist"),
    )

    assert response.reply == "Безопасный ответ по курсу."
    assert resolve_provider.await_args.kwargs["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_learner_assistant_forwards_authenticated_tenant_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    course_id = uuid4()

    class StubLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="Ответ по материалам урока.")

    class StubDB:
        def add(self, _value) -> None:
            return None

        commit = AsyncMock()

    resolve_provider = AsyncMock(return_value=StubLLM())
    monkeypatch.setattr(
        learner_router,
        "_assert_course_mutation_access",
        AsyncMock(return_value=SimpleNamespace(id=course_id)),
    )
    monkeypatch.setattr(
        learner_router,
        "_build_context",
        AsyncMock(return_value=("Материал урока", [])),
    )
    monkeypatch.setattr(
        learner_router.ResilientLLMClient,
        "from_settings_async",
        resolve_provider,
    )

    response = await learner_router.learner_chat(
        LearnerAssistantChatRequest(course_id=course_id, message="Объясни термин"),
        db=StubDB(),  # type: ignore[arg-type]
        user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
    )

    assert response["reply"] == "Ответ по материалам урока."
    assert resolve_provider.await_args.kwargs["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_editor_preview_provider_requires_and_forwards_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    expected = object()
    resolve_provider = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        editor_router.ResilientLLMClient,
        "from_settings_async",
        resolve_provider,
    )

    provider = await editor_router._resolve_question_preview_provider(tenant_id)

    assert provider is expected
    assert resolve_provider.await_args.kwargs["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_editor_preview_provider_rejects_missing_tenant_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_provider = AsyncMock(side_effect=AssertionError("provider must not resolve"))
    monkeypatch.setattr(
        editor_router.ResilientLLMClient,
        "from_settings_async",
        resolve_provider,
    )

    with pytest.raises(RuntimeError, match="tenant_context_required"):
        await editor_router._resolve_question_preview_provider(None)  # type: ignore[arg-type]

    resolve_provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_jd_analysis_forwards_tenant_to_analysis_and_audit_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()

    class StubLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "name": "Инженер",
                        "department": "Производство",
                        "level": "middle",
                        "responsibilities": "Контроль процесса",
                        "requirements": "Знание регламента",
                    }
                )
            )

    resolve_provider = AsyncMock(return_value=StubLLM())
    monkeypatch.setattr(jd_router, "_extract_text", lambda _content, _filename: "Текст ДИ")
    monkeypatch.setattr(ResilientLLMClient, "from_settings_async", resolve_provider)
    monkeypatch.setattr(jd_router, "_audit_jd_text", AsyncMock(return_value=[]))

    result = await jd_router._analyze_jd_content(b"document", "role.txt", tenant_id)

    assert result["name"] == "Инженер"
    assert resolve_provider.await_args.kwargs["tenant_id"] == tenant_id


@pytest.mark.parametrize(
    "resolver",
    (
        jd_router._require_ai_tenant_id,
        recommendations_router._require_ai_tenant_id,
    ),
)
def test_position_ai_provider_resolution_rejects_missing_tenant(resolver) -> None:
    with pytest.raises(HTTPException) as exc_info:
        resolver(SimpleNamespace(tenant_id=None))

    assert exc_info.value.status_code == 403
