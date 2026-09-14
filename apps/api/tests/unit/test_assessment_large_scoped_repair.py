import json
from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import (
    ASSESSMENT_DROP_ONLY_POLICY_VERSION,
    ASSESSMENT_EMPTY_REVIEW_REASON,
    _normalize_evidence_text,
    generate_lesson_assessment,
)
from app.modules.ai.writer_schema import LessonContent


def _large_scoped_source() -> str:
    rows = [
        "| Характеристика | Nord | Classic |",
        "| --- | --- | --- |",
        "| Направляющие | шариковые системы | роликовые системы |",
    ]
    rows.extend(
        f"| Поверхности {index} | матовые покрытия, скрытые механизмы, бронзовые накладки | "
        "нейтральные покрытия, профильные механизмы, стальные накладки |"
        for index in range(120)
    )
    source = "\n".join(rows)
    assert len(source) > 8000
    return source


def _lesson() -> LessonContent:
    return LessonContent(
        title="Направляющие коллекции Nord",
        objectives=["Выбирать направляющие для коллекции Nord"],
        source_chunks=[_large_scoped_source()],
    )


def _valid_question() -> dict:
    return {
        "question": "Какие направляющие указаны для Nord?",
        "options": [
            {"text": "шариковые системы", "is_correct": True},
            {"text": "скрытые системы", "is_correct": False},
            {"text": "матовые системы", "is_correct": False},
            {"text": "бронзовые системы", "is_correct": False},
        ],
        "explanation": "Шариковые системы указаны для Nord.",
        "source_quote_id": "E01",
    }


def _off_source_question() -> dict:
    question = _valid_question()
    question["options"][1] = {"text": "Планета Марс для космических экспедиций", "is_correct": False}
    return question


class _ReplayLLM:
    def __init__(self, responses: list[list[dict]]) -> None:
        self.responses = responses
        self.calls = 0

    async def ainvoke(self, _messages, config=None, response_format=None):
        response = self.responses[self.calls]
        self.calls += 1
        return SimpleNamespace(content=json.dumps({"mcq": response, "true_false": [], "matching": []}))


@pytest.fixture(autouse=True)
def _disable_tabular_shortcut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.ai.assessment._generate_tabular_assessment", lambda **_kwargs: None)


@pytest.mark.asyncio
async def test_large_scoped_table_repairs_one_actionable_response_then_keeps_valid_question() -> None:
    llm = _ReplayLLM([[_off_source_question()], [_valid_question()]])

    assessment = await generate_lesson_assessment(llm, _lesson(), language="ru")

    assert llm.calls == 2
    assert [question.question for question in assessment.mcq] == ["Какие направляющие указаны для Nord?"]


@pytest.mark.asyncio
async def test_large_scoped_table_keeps_valid_partial_without_quota_repair() -> None:
    llm = _ReplayLLM([[_valid_question()]])

    assessment = await generate_lesson_assessment(llm, _lesson(), language="ru")

    assert llm.calls == 1
    assert len(assessment.mcq) == 1


@pytest.mark.asyncio
async def test_large_scoped_table_drops_duplicate_only_response_without_repair() -> None:
    llm = _ReplayLLM([[_valid_question()]])
    source_row = "| Направляющие | шариковые системы | роликовые системы |"
    already_assessed = frozenset(
        {(_normalize_evidence_text(source_row), _normalize_evidence_text("шариковые системы"))}
    )

    assessment = await generate_lesson_assessment(
        llm,
        _lesson(),
        language="ru",
        excluded_fact_keys=already_assessed,
    )

    assert llm.calls == 1
    assert assessment.mcq == []
    assert assessment.quality_policy_version == ASSESSMENT_DROP_ONLY_POLICY_VERSION
    assert assessment.omission_reason == ASSESSMENT_EMPTY_REVIEW_REASON


@pytest.mark.asyncio
async def test_large_scoped_table_stops_after_one_failed_quality_repair() -> None:
    llm = _ReplayLLM([[_off_source_question()], [_off_source_question()]])

    assessment = await generate_lesson_assessment(llm, _lesson(), language="ru")

    assert llm.calls == 2
    assert assessment.mcq == []
    assert assessment.quality_policy_version == ASSESSMENT_DROP_ONLY_POLICY_VERSION
    assert assessment.omission_reason == ASSESSMENT_EMPTY_REVIEW_REASON
