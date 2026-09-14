from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import (
    ASSESSMENT_DROP_ONLY_POLICY_VERSION,
    ASSESSMENT_EMPTY_REVIEW_REASON,
    _restored_assessment_is_valid,
    _validate_direct_lesson_topic_scope,
    generate_lesson_assessment,
)
from app.modules.ai.assessment_schema import LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.lesson_quality import LESSON_QUALITY_POLICY_VERSION
from app.modules.ai.writer_schema import LessonContent


def _mcq(
    *, question: str, correct: str, distractors: tuple[str, str, str], quote_id: str,
) -> dict[str, object]:
    return {
        "question": question,
        "options": [
            {"text": correct, "is_correct": True},
            {"text": distractors[0], "is_correct": False},
            {"text": distractors[1], "is_correct": False},
            {"text": distractors[2], "is_correct": False},
        ],
        "explanation": correct,
        "source_quote_id": quote_id,
    }


class _OneResponseLLM:
    def __init__(self, question: dict[str, object]) -> None:
        self.question = question

    async def ainvoke(self, messages, config=None, response_format=None):
        return SimpleNamespace(content=json.dumps({"mcq": [self.question]}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_direct_lesson_drops_grounded_question_from_neighboring_topic() -> None:
    source = (
        "Заявка рассматривается в течение 15 рабочих дней. "
        "Жалоба рассматривается в течение 30 календарных дней."
    )
    lesson = LessonContent(
        title="Рассмотрение заявления и проверка через ГКБ",
        objectives=[
            "Определять срок рассмотрения заявления.",
            "Описывать проверку сведений через Государственное кредитное бюро.",
        ],
        content="Заявка рассматривается в течение 15 рабочих дней.",
        source_chunks=[source],
        quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
    )

    result = await generate_lesson_assessment(
        _OneResponseLLM(
            _mcq(
                question="В какой срок рассматривается жалоба?",
                correct="30 календарных дней",
                distractors=("15 рабочих дней", "10 календарных дней", "5 рабочих дней"),
                quote_id="E02",
            )
        ),
        lesson,
        language="ru",
        compact=True,
    )

    assert result.mcq == []
    assert result.quality_policy_version == ASSESSMENT_DROP_ONLY_POLICY_VERSION
    assert result.omission_reason == ASSESSMENT_EMPTY_REVIEW_REASON


@pytest.mark.asyncio
async def test_direct_lesson_keeps_question_bound_to_its_topic() -> None:
    source = (
        "Заявка рассматривается в течение 15 рабочих дней. "
        "Жалоба рассматривается в течение 30 календарных дней."
    )
    lesson = LessonContent(
        title="Рассмотрение заявления и проверка через ГКБ",
        objectives=["Определять срок рассмотрения заявления."],
        content="Заявка рассматривается в течение 15 рабочих дней.",
        source_chunks=[source],
        quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
    )

    result = await generate_lesson_assessment(
        _OneResponseLLM(
            _mcq(
                question="В какой срок рассматривается заявка?",
                correct="15 рабочих дней",
                distractors=("30 календарных дней", "10 календарных дней", "5 рабочих дней"),
                quote_id="E01",
            )
        ),
        lesson,
        language="ru",
        compact=True,
    )

    assert len(result.mcq) == 1
    assert result.mcq[0].question == "В какой срок рассматривается заявка?"


@pytest.mark.parametrize(
    ("lesson", "question", "quote", "correct"),
    [
        (
            LessonContent(
                title="Годовая эффективная ставка вознаграждения (АРК)",
                objectives=["Описывать формулу расчёта и правила округления АРК."],
                content="АРК рассчитывается по установленной формуле и округляется до сотых.",
                quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
            ),
            "Когда выплачивается вознаграждение?",
            "Вознаграждение выплачивается в дату погашения микрокредита.",
            "В дату погашения",
        ),
        (
            LessonContent(
                title="Права клиента",
                objectives=["Разъяснять порядок обращения к микрофинансовому омбудсману."],
                content="Клиент вправе обратиться к микрофинансовому омбудсману.",
                quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
            ),
            "Какую обязанность выполняет ломбард?",
            "Ломбард обязан предоставить клиенту полную информацию.",
            "Предоставить информацию клиенту",
        ),
    ],
)
def test_direct_lesson_rejects_other_known_neighbor_topics(
    lesson: LessonContent,
    question: str,
    quote: str,
    correct: str,
) -> None:
    issues = _validate_direct_lesson_topic_scope(
        {
            "mcq": [
                {
                    "question": question,
                    "source_quote": quote,
                    "options": [{"text": correct, "is_correct": True}],
                }
            ]
        },
        lesson,
    )

    assert issues == ["MCQ #1: source fact is outside the authored lesson topic"]


def test_direct_lesson_accepts_paraphrased_quote_with_explicit_topic_binding() -> None:
    lesson = LessonContent(
        title="Обязанности ломбарда",
        objectives=["Описывать защиту персональных данных клиента."],
        content="Ломбард обеспечивает конфиденциальность сведений о клиенте.",
        quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
    )

    assert _validate_direct_lesson_topic_scope(
        {
            "mcq": [
                {
                    "question": "Какая обязанность ломбарда касается персональных данных?",
                    "source_quote": "Организация защищает персональные данные заёмщика.",
                    "options": [
                        {"text": "Защищать персональные данные", "is_correct": True}
                    ],
                }
            ]
        },
        lesson,
    ) == []


def test_non_direct_lesson_keeps_existing_assessment_contract() -> None:
    lesson = LessonContent(
        title="Права клиента",
        objectives=["Разъяснять права клиента."],
        content="Generated prose is not evidence.",
    )

    assert _validate_direct_lesson_topic_scope(
        {
            "mcq": [
                {
                    "question": "Какую обязанность выполняет ломбард?",
                    "source_quote": "Ломбард обязан предоставить информацию.",
                    "options": [{"text": "Предоставить информацию", "is_correct": True}],
                }
            ]
        },
        lesson,
    ) == []


def test_restored_checkpoint_rejects_neighboring_topic_question() -> None:
    source = (
        "Заявка рассматривается в течение 15 рабочих дней. "
        "Жалоба рассматривается в течение 30 календарных дней."
    )
    lesson = LessonContent(
        title="Рассмотрение заявления и проверка через ГКБ",
        objectives=["Определять срок рассмотрения заявления."],
        content="Заявка рассматривается в течение 15 рабочих дней.",
        source_chunks=[source],
        quality_policy_version=LESSON_QUALITY_POLICY_VERSION,
    )
    restored = LessonAssessment(
        lesson_title=lesson.title,
        mcq=[
            MCQQuestion(
                question="В какой срок рассматривается жалоба?",
                options=[
                    MCQOption(text="30 календарных дней", is_correct=True),
                    MCQOption(text="15 рабочих дней", is_correct=False),
                    MCQOption(text="10 календарных дней", is_correct=False),
                    MCQOption(text="5 рабочих дней", is_correct=False),
                ],
                explanation="Жалоба рассматривается в течение 30 календарных дней.",
                source_quote="Жалоба рассматривается в течение 30 календарных дней.",
            )
        ],
    )

    assert not _restored_assessment_is_valid(
        restored,
        lesson,
        language="ru",
        compact=True,
        excluded_fact_keys=frozenset(),
    )
