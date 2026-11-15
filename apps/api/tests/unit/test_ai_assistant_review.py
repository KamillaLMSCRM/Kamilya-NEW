import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.assistant_context import compact_course_context
from app.modules.ai.assistant_review import (
    Decision,
    Draft,
    Finding,
    ReviewProtocolError,
    adjudication_messages,
    read_decisions,
    render_review,
    review_course,
)


def body():
    quote = "Соседний раздел.\n" + "пример " * 700 + "Книга печатается ежедневно."
    return {"sources": {"status": "complete", "documents": [
        {"document_id": "doc", "title": "Source", "text": quote}]},
        "course": {"id": "course"}, "modules": [{"id": "module", "lessons": [
            {"id": "lesson", "title": "Lesson", "text": "Хорошее правило, не переписывать.",
             "source_references": [{"quote": quote}], "quizzes": [{"questions": [
                 {"id": "q1", "text": "Когда?", "source_quote": quote},
                 {"id": "q2", "text": "Откуда?", "source_quote": quote}]}]}]}]}


def response(value):
    return SimpleNamespace(content=json.dumps(value), finish_reason="stop", content_is_reasoning=False)


def draft():
    return Draft(reviewed_lesson_ids=["lesson"], findings=[
        Finding(target_kind="question", target_id="q1", problem="Нет основания в цитате", replacement="Заменить цитату"),
        Finding(target_kind="lesson", target_id="lesson", problem="Настоящее замечание", replacement="Исправление"),
    ])


def test_citations_are_interned_losslessly_without_mutating_input_or_clipping():
    original = body()
    saved = copy.deepcopy(original)
    compact = compact_course_context(original)
    assert original == saved
    assert compact["sources"] == original["sources"]
    assert len(compact["quote_texts"]) == 1

    def expand(value):
        if isinstance(value, list):
            return [expand(x) for x in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {"quote_ref"}:
            return compact["quote_texts"][value["quote_ref"]]
        return {k: expand(v) for k, v in value.items()}

    assert expand(compact["modules"]) == original["modules"]
    assert compact["inventory"]["question_count"] == 2
    assert compact["inventory"]["lessons"][0]["question_ids"] == ["q1", "q2"]
    assert len(json.dumps(compact)) < len(json.dumps(original))


def test_near_equal_quotes_are_not_normalized_or_merged():
    value = body()
    value["modules"][0]["lessons"][0]["quizzes"][0]["questions"][1]["source_quote"] += " "
    assert len(compact_course_context(value)["quote_texts"]) == 2


def test_compaction_can_be_repeated_without_dangling_quote_references():
    compact = compact_course_context(body())
    assert compact_course_context(compact) == compact


def test_malformed_decision_preserves_its_candidate_and_valid_peers():
    decisions = read_decisions(response({"decisions": [
        {"finding_id": "finding-1", "verdict": "invented-verdict"},
        {"finding_id": "finding-2", "verdict": "confirmed", "reason": "Сравнено", "source_document_id": "doc", "source_evidence": "Книга печатается ежедневно."},
    ]}))
    report = render_review(compact_course_context(body()), draft(), decisions, "ru")
    assert "Требует дополнительной проверки" in report and "Нет основания в цитате" in report
    assert "Подтверждённые замечания" in report and "Настоящее замечание" in report


def test_missing_question_coverage_cannot_be_reported_as_complete():
    report = render_review(compact_course_context(body()), Draft(reviewed_lesson_ids=["lesson"], findings=[]), [], "ru")
    assert "Проверка охватывает не все уроки или вопросы" in report


def test_adjudicator_receives_the_tail_and_full_source_not_only_quote_heading():
    compact = compact_course_context(body())
    raw = adjudication_messages(compact, [{"finding_id": "finding-1", **draft().findings[0].model_dump()}], "ru")
    payload = json.loads(raw[1]["content"])
    assert next(iter(payload["course_context"]["quote_texts"].values())).endswith("Книга печатается ежедневно.")
    assert payload["course_context"]["sources"]["documents"][0]["text"].endswith("Книга печатается ежедневно.")


@pytest.mark.parametrize("decisions", [[], [Decision(finding_id="finding-other", verdict="rejected", reason="No", source_document_id="", source_evidence="")]])
def test_missing_or_foreign_decision_cannot_hide_any_finding(decisions):
    report = render_review(compact_course_context(body()), draft(), decisions, "ru")
    assert "Требует дополнительной проверки" in report
    assert "Настоящее замечание" in report and "Нет основания в цитате" in report
    assert "Подтверждённые замечания:" not in report


def test_one_rejection_does_not_clear_another_unanswered_finding():
    decision = Decision(finding_id="finding-1", verdict="rejected", reason="Нужное правило в конце", source_document_id="doc", source_evidence="Книга печатается ежедневно.")
    report = render_review(compact_course_context(body()), draft(), [decision], "ru")
    assert "Отклонено при перепроверке" in report and "Требует дополнительной проверки" in report
    assert "Настоящее замечание" in report


def test_confirmed_without_literal_source_witness_is_still_unverified():
    decision = Decision(finding_id="finding-2", verdict="confirmed", reason="Проверено", source_document_id="doc", source_evidence="Придуманное правило")
    report = render_review(compact_course_context(body()), draft(), [decision], "ru")
    assert "Подтверждённые замечания:" not in report
    assert "Требует дополнительной проверки" in report


def test_duplicate_decisions_never_confirm_or_silently_clear_a_finding():
    d = Decision(finding_id="finding-1", verdict="rejected", reason="No", source_document_id="", source_evidence="")
    report = render_review(compact_course_context(body()), draft(), [d, d], "ru")
    assert "Требует дополнительной проверки" in report and "Нет основания в цитате" in report


@pytest.mark.asyncio
async def test_missing_source_does_not_infer_or_claim_a_source_review():
    value = compact_course_context(body())
    value["sources"]["status"] = "unavailable"
    llm = SimpleNamespace(ainvoke=AsyncMock())
    assert "не выполнена" in await review_course(llm, value, "Проверь", "ru")
    llm.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_native_model_stages_and_server_owned_counts():
    llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        response(draft().model_dump()), response({"decisions": [
            {"finding_id": "finding-1", "verdict": "rejected", "reason": "Полная цитата содержит правило", "source_document_id": "doc", "source_evidence": "Книга печатается ежедневно."},
            {"finding_id": "finding-2", "verdict": "confirmed", "reason": "Сравнено", "source_document_id": "doc", "source_evidence": "Книга печатается ежедневно."},
        ]}),
    ]))
    report = await review_course(llm, compact_course_context(body()), "Проверь", "ru")
    assert llm.ainvoke.await_count == 2
    assert "Всего вопросов в курсе: 2" in report
    assert "Подтверждённые замечания" in report and "Отклонено при перепроверке" in report
    assert "Ничего не применено" in report


@pytest.mark.asyncio
async def test_invalid_draft_is_not_retried_or_promoted_to_review():
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=response({"reply": "All good"})))
    with pytest.raises(ReviewProtocolError):
        await review_course(llm, compact_course_context(body()), "Проверь", "ru")
    assert llm.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_real_router_dispatches_explicit_review_through_both_stages(monkeypatch):
    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import router
    from app.modules.ai.schemas import AIChatRequest

    llm = SimpleNamespace(ainvoke=AsyncMock(side_effect=[response(draft().model_dump()),
        response({"decisions": [{"finding_id": "finding-1", "verdict": "rejected", "reason": "Полная цитата содержит правило",
            "source_document_id": "doc", "source_evidence": "Книга печатается ежедневно."}]})]))
    monkeypatch.setattr(router, "_fetch_course_summary", AsyncMock(return_value=json.dumps(compact_course_context(body()))))
    monkeypatch.setattr(router.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=llm))
    monkeypatch.setattr(runtime, "resolve_runtime_settings", AsyncMock(return_value=SimpleNamespace(integer=lambda _:32768)))
    result = await router.chat(AIChatRequest(course_id=uuid4(), message="Проверь курс", intent="course_review"),
        db=SimpleNamespace(), user=SimpleNamespace(tenant_id=uuid4(), role="methodologist"))
    assert llm.ainvoke.await_count == 2
    assert "Требует дополнительной проверки" in result.reply
    assert result.apply_lesson_id is None and result.apply_lesson_content is None


def test_provider_selection_cannot_enable_or_reorder_a_resolved_chain():
    from app.modules.ai.llm_client import LLMProviderConfig, ResilientLLMClient
    configs = [LLMProviderConfig(name=name, base_url="https://example.invalid", api_key="fixture", model="fixture")
               for name in ("deepseek", "chatgpt-reserve")]
    original = ResilientLLMClient(configs, temperature=0.4, max_tokens=32768)
    before = original.cache_fingerprint()
    selected = original.for_provider("chatgpt-reserve")
    assert [c.name for c in selected._clients] == ["chatgpt-reserve"]
    assert selected.max_tokens == 32768 and selected.temperature == 0.4
    assert selected._clients[0].config.extra_body == configs[1].extra_body
    assert original.cache_fingerprint() == before
    with pytest.raises(ValueError, match="selected_provider_unavailable"):
        ResilientLLMClient(configs[:1]).for_provider("chatgpt-reserve")


@pytest.mark.parametrize("patch", [{"intent": None}, {"context": "lesson", "target_id": str(uuid4())},
                                      {"review_provider": "deepseek"}, {"target_id": str(uuid4())}])
def test_selected_review_provider_is_not_a_general_client_override(patch):
    from pydantic import ValidationError

    from app.modules.ai.schemas import AIChatRequest
    with pytest.raises(ValidationError):
        AIChatRequest.model_validate({"course_id": str(uuid4()), "message": "Review", "intent": "course_review",
                                      "review_provider": "chatgpt_reserve", **patch})


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_native_review_selects_luna_without_default_fallback(monkeypatch, available):
    from unittest.mock import Mock

    from fastapi import HTTPException

    from app.modules.admin.runtime_configuration import runtime
    from app.modules.ai import router
    from app.modules.ai.schemas import AIChatRequest
    value = compact_course_context(body())
    selected = SimpleNamespace(ainvoke=AsyncMock(return_value=response({"reviewed_lesson_ids": ["lesson"], "findings": []})))
    choose = Mock(return_value=selected) if available else Mock(side_effect=ValueError("selected_provider_unavailable"))
    default = SimpleNamespace(for_provider=choose, ainvoke=AsyncMock())
    monkeypatch.setattr(router, "_fetch_course_summary", AsyncMock(return_value=json.dumps(value)))
    monkeypatch.setattr(router.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=default))
    monkeypatch.setattr(runtime, "resolve_runtime_settings", AsyncMock(return_value=SimpleNamespace(integer=lambda _:32768)))
    req = AIChatRequest(course_id=uuid4(), message="Review", intent="course_review", review_provider="chatgpt_reserve")
    args = {"db": SimpleNamespace(), "user": SimpleNamespace(tenant_id=uuid4(), role="methodologist")}
    if available:
        await router.chat(req, **args)
        selected.ainvoke.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await router.chat(req, **args)
        assert error.value.status_code == 503 and error.value.detail["code"] == "assistant_provider_unavailable"
        selected.ainvoke.assert_not_awaited()
    choose.assert_called_once_with("chatgpt-reserve")
    default.ainvoke.assert_not_awaited()
