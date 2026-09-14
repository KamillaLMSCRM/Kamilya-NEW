from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import (
    _build_evidence_bank,
    _recover_valid_assessment,
    _validate_question_evidence,
    generate_lesson_assessment,
)
from app.modules.ai.writer_schema import LessonContent


def _question(question: str, correct: str, evidence_id: str, options: list[str]) -> dict[str, object]:
    return {
        "question": question,
        "options": [{"text": text, "is_correct": text == correct} for text in options],
        "explanation": "Provider-authored explanation is replaced by server evidence.",
        "source_quote_id": evidence_id,
    }


def test_overlong_sentence_is_skipped_instead_of_losing_its_governing_action() -> None:
    source = "Заемщик вправе отказаться от отсрочки " + ("при наличии документов " * 20) + "."

    evidence = _build_evidence_bank(source)

    assert evidence == {}


def test_ordinal_priority_question_is_not_treated_as_ambiguous_list_membership() -> None:
    source = "Приоритеты:\n1. основной долг\n2. начисленное вознаграждение\n3. пеня"
    data = {
        "mcq": [
            _question(
                "Какая категория вторая в списке приоритетов?",
                "начисленное вознаграждение",
                "E01",
                ["основной долг", "начисленное вознаграждение", "пеня", "следующий договор"],
            )
        ]
    }

    issues = _validate_question_evidence(data, _build_evidence_bank(source), source, "ru")

    assert "MCQ #1: list evidence supports an incorrect option" not in issues


def test_unqualified_covered_debt_question_is_rejected_when_list_items_compete() -> None:
    source = "Покрываемая задолженность:\n- основной долг\n- начисленное вознаграждение\n- пеня"
    data = {
        "mcq": [
            _question(
                "Какая задолженность покрывается?",
                "основной долг",
                "E01",
                ["основной долг", "начисленное вознаграждение", "пеня", "будущая задолженность"],
            )
        ]
    }

    issues = _validate_question_evidence(data, _build_evidence_bank(source), source, "ru")

    assert "MCQ #1: list evidence supports an incorrect option" in issues


@pytest.mark.asyncio
async def test_public_russian_replay_drops_request_question_that_reverses_refusal_action() -> None:
    source = (
        "Заемщик вправе отказаться от отсрочки по договору путем подачи письменного обращения "
        "по юридическому адресу. "
        "Подпись заемщика подтверждает отказ в заявлении."
    )
    refusal_options = [
        "письменного обращения по юридическому адресу",
        "отказаться от отсрочки по договору",
        "Заемщик вправе отказаться от отсрочки",
        "Подпись заемщика подтверждает отказ",
    ]
    invalid = _question(
        "Как заемщику запросить отсрочку по договору?",
        "письменного обращения по юридическому адресу",
        "E01",
        refusal_options,
    )
    valid_refusal = _question(
        "Как заемщик вправе отказаться от отсрочки по договору?",
        "письменного обращения по юридическому адресу",
        "E01",
        refusal_options,
    )
    valid_signature = _question(
        "Что подтверждает подпись заемщика?",
        "отказ в заявлении",
        "E02",
        [
            "отказ в заявлении",
            "заемщик вправе отказаться",
            "подачи письменного обращения",
            "по юридическому адресу",
        ],
    )

    class ReplayLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(content=json.dumps({"mcq": [invalid, valid_refusal, valid_signature]}))

    llm = ReplayLLM()
    assessment = await generate_lesson_assessment(
        llm,
        LessonContent(title="Отказ от отсрочки", content=source),
        language="ru",
        compact=True,
    )

    assert llm.calls == 1
    assert [question.question for question in assessment.mcq] == [
        valid_refusal["question"],
        valid_signature["question"],
    ]


def test_prose_recovery_drops_russian_duplicate_rate_but_keeps_distinct_conditions_and_subjects() -> None:
    source = (
        "Пеня по основному долгу составляет 0,5% в день в первые 90 дней. "
        "Размер пени по основному долгу равен 0,5% в первые 90 дней. "
        "Пеня по основному долгу составляет 0,03% в день после первых 90 дней. "
        "Страховой взнос составляет 0,5% в день в первые 90 дней."
    )
    evidence = _build_evidence_bank(source)
    assert list(evidence) == ["E01", "E02", "E03", "E04"]
    questions = [
        _question("Какой размер пени по основному долгу вначале?", "0,5% в день", "E01", ["0,5% в день", "0,03% в день", "Страховой взнос", "основному долгу"]),
        _question("Какой размер пени по основному долгу в первые 90 дней?", "0,5%", "E02", ["0,5%", "0,03% в день", "Страховой взнос", "основному долгу"]),
        _question("Какой размер пени по основному долгу после 90 дней?", "0,03% в день", "E03", ["0,03% в день", "0,5% в день", "Страховой взнос", "основному долгу"]),
        _question("Какой размер страхового взноса в первые 90 дней?", "0,5% в день", "E04", ["0,5% в день", "0,03% в день", "Пеня по основному долгу", "первые 90 дней"]),
    ]

    recovered = _recover_valid_assessment(
        {"mcq": questions}, evidence_bank=evidence, bounded_source=source,
        lesson_title="Пеня", language="ru", minimum_questions=1, maximum_questions=4,
    )

    assert recovered is not None
    assert [question.question for question in recovered.mcq] == [
        questions[0]["question"], questions[2]["question"], questions[3]["question"],
    ]
