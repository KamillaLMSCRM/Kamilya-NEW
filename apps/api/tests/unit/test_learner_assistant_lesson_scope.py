from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.learner_assistant import router
from app.modules.learner_assistant.schemas import LearnerAssistantChatRequest
from app.modules.lessons.models import Lesson, Module


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_http_missing_lesson_never_enters_data_or_model_route(method):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_active_user, get_current_user
    from app.core.db import get_db

    app = FastAPI()
    app.include_router(router.router)
    db = SimpleNamespace(execute=AsyncMock(), get=AsyncMock())
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), role="student")
    app.dependency_overrides[get_current_active_user] = app.dependency_overrides[get_current_user]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if method == "GET":
            response = await client.get("/learner/assistant/messages", params={"course_id": str(uuid4())})
        else:
            response = await client.post("/learner/assistant/chat",
                                        json={"course_id": str(uuid4()), "message": "Explain"})
    assert response.status_code == 422
    db.execute.assert_not_awaited()
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_author_cannot_use_the_learner_message_route():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.core.auth import get_current_active_user, get_current_user
    from app.core.db import get_db

    app = FastAPI()
    app.include_router(router.router)
    db = SimpleNamespace(execute=AsyncMock(), get=AsyncMock())
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), role="methodologist")
    app.dependency_overrides[get_current_active_user] = app.dependency_overrides[get_current_user]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/learner/assistant/chat",
                                    json={"course_id": str(uuid4()), "lesson_id": str(uuid4()), "message": "Explain"})
    assert response.status_code == 403
    db.execute.assert_not_awaited()
    db.get.assert_not_awaited()


@pytest.mark.parametrize("lesson", ["missing", None])
def test_request_requires_a_concrete_lesson(lesson):
    payload = {"course_id": uuid4(), "message": "Explain"}
    if lesson is None:
        payload["lesson_id"] = None
    with pytest.raises(ValidationError):
        LearnerAssistantChatRequest(**payload)


def fixture_scope(*, content="RULE " + "x" * 9000 + " TAIL_RULE"):
    tenant, course, module, lesson = uuid4(), uuid4(), uuid4(), uuid4()
    c = SimpleNamespace(id=course, title="Course", description="OTHER_LESSON_SECRET")
    m = SimpleNamespace(id=module, course_id=course, tenant_id=tenant, title="Module")
    lesson_row = SimpleNamespace(id=lesson, module_id=module, tenant_id=tenant, title="Lesson", content=content)
    db = SimpleNamespace(get=AsyncMock(side_effect=lambda model, _id: lesson_row if model is Lesson else m))
    return db, tenant, c, m, lesson_row


@pytest.mark.asyncio
async def test_complete_current_lesson_without_other_course_material():
    db, tenant, course, _, lesson = fixture_scope()
    context, sources = await router._build_context(db, course, lesson.id, tenant)
    assert lesson.content in context
    assert context.endswith("TAIL_RULE")
    assert "OTHER_LESSON_SECRET" not in context
    assert sources == ["Курс: Course", "Урок: Lesson"]
    assert [call.args[0] for call in db.get.await_args_list] == [Lesson, Module]


@pytest.mark.asyncio
async def test_no_course_fallback_for_missing_lesson_even_in_internal_call():
    db, tenant, course, _, _ = fixture_scope()
    with pytest.raises(HTTPException) as error:
        await router._build_context(db, course, None, tenant)
    assert error.value.status_code == 422
    db.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["lesson_tenant", "module_tenant", "module_course", "lesson_missing", "module_missing"])
async def test_context_rejects_other_or_missing_objects(violation):
    db, tenant, course, module, lesson = fixture_scope()
    if violation == "lesson_tenant":
        lesson.tenant_id = uuid4()
    elif violation == "module_tenant":
        module.tenant_id = uuid4()
    elif violation == "module_course":
        module.course_id = uuid4()
    elif violation == "lesson_missing":
        db.get = AsyncMock(return_value=None)
    else:
        db.get = AsyncMock(side_effect=[lesson, None])
    with pytest.raises(HTTPException) as error:
        await router._build_context(db, course, lesson.id, tenant)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_empty_lesson_does_not_become_a_title_based_explanation():
    db, tenant, course, _, lesson = fixture_scope(content="  ")
    with pytest.raises(HTTPException) as error:
        await router._build_context(db, course, lesson.id, tenant)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_history_validates_lesson_scope_before_reading_messages(monkeypatch):
    tenant, course, lesson = uuid4(), uuid4(), uuid4()
    db = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(router, "_assert_course_access", AsyncMock(return_value=SimpleNamespace(id=course)))
    monkeypatch.setattr(router, "_lesson_scope", AsyncMock(side_effect=HTTPException(404, "Not found")))
    with pytest.raises(HTTPException) as error:
        await router.list_messages(course_id=course, lesson_id=lesson, db=db,
                                   user=SimpleNamespace(id=uuid4(), tenant_id=tenant))
    assert error.value.status_code == 404
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_luna_selection_is_request_local_without_paid_fallback(monkeypatch):
    tenant, course, lesson = uuid4(), uuid4(), uuid4()
    selected = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="Explanation")))
    default = SimpleNamespace(for_provider=lambda name: selected if name == "chatgpt-reserve" else None,
                              ainvoke=AsyncMock())
    monkeypatch.setattr(router, "_assert_course_mutation_access", AsyncMock(return_value=SimpleNamespace(id=course)))
    monkeypatch.setattr(router, "_build_context", AsyncMock(return_value=("CURRENT_RULE", ["Lesson"])))
    monkeypatch.setattr(router.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=default))
    db = SimpleNamespace(add=lambda _row: None, commit=AsyncMock())
    response = await router.learner_chat(
        LearnerAssistantChatRequest(course_id=course, lesson_id=lesson, message="Explain", provider="chatgpt_reserve"),
        db=db, user=SimpleNamespace(id=uuid4(), tenant_id=tenant))
    assert response["reply"] == "Explanation"
    selected.ainvoke.assert_awaited_once()
    default.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_selected_provider_never_calls_default(monkeypatch):
    tenant, course, lesson = uuid4(), uuid4(), uuid4()
    def unavailable(_name):
        raise ValueError("selected_provider_unavailable")
    default = SimpleNamespace(for_provider=unavailable, ainvoke=AsyncMock())
    monkeypatch.setattr(router, "_assert_course_mutation_access", AsyncMock(return_value=SimpleNamespace(id=course)))
    monkeypatch.setattr(router, "_build_context", AsyncMock(return_value=("CURRENT_RULE", [])))
    monkeypatch.setattr(router.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=default))
    db = SimpleNamespace(add=lambda _row: None, commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await router.learner_chat(
            LearnerAssistantChatRequest(course_id=course, lesson_id=lesson, message="Explain", provider="chatgpt_reserve"),
            db=db, user=SimpleNamespace(id=uuid4(), tenant_id=tenant))
    assert error.value.status_code == 503
    default.ainvoke.assert_not_awaited()
    db.commit.assert_not_awaited()
