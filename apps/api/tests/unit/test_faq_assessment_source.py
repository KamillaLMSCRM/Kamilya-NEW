"""FAQ source questions provide context, never immutable answer keys."""

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    _source_owned_faq_pair,
    derive_assessment_axes,
)
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


@pytest.mark.parametrize(("prompt", "answer"), [
    ("Можно ли получить сертификат, если пропущен один урок?",
     "Да, пропуск не блокирует сертификат, если все обязательные задания сданы до даты окончания курса."),
    ("Когда появляется сертификат?",
     "Обычно в течение 24 часов после выполнения последнего обязательного задания; в выходной день обработка переносится на следующий рабочий день."),
    ("Нужно ли проходить необязательный опрос?",
     "Нет, опрос улучшает программу, но его результат не влияет на выдачу сертификата."),
    ("Что делать при ошибке в фамилии?",
     "Не скачивайте документ повторно: сообщите методисту номер курса и правильное написание, после чего исправленная версия будет доступна в течение двух рабочих дней."),
    ("Можно ли передать сертификат другому человеку?",
     "Нет, сертификат именной и не переносится между учетными записями."),
])
def test_faq_axis_uses_answer_and_preserves_original_question_context(prompt, answer):
    value = f"{prompt} {answer}"
    fact = SourceFact("faq-rule", "Сертификат", "положение", value,
                      "doc_id=faq;source_revision=revision;section=faq;part=1")
    lesson = LessonDraft("faq-lesson", "FAQ", "Сертификат", "Применять правила",
                         value, (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id="faq-block")
    assert len(axes) == 1
    assert axes[0].correct_value == answer
    assert axes[0].required_prompt == prompt
    assert axes[0].evidence_fact_ids == (fact.fact_id,)
    assert axes[0].correct_value in fact.value


def test_question_without_source_answer_is_not_an_assessment_axis():
    fact = SourceFact("unanswered", "Сертификат", "положение", "Когда появляется сертификат?",
                      "doc_id=faq;section=faq;part=1")
    lesson = LessonDraft("faq-lesson", "FAQ", "Сертификат", "Применять правила",
                         fact.value, (fact.fact_id,), (), 1)
    assert derive_assessment_axes(lesson, [fact], block_id="faq-block") == ()


@pytest.mark.parametrize("value", [
    'Нажмите «Когда появляется сертификат?» и дождитесь ответа методиста.',
    'Когда появляется сертификат? Обычно за сутки. Что делать при ошибке? Обратитесь к методисту.',
    'Когда появляется сертификат? Да.',
])
def test_embedded_ambiguous_or_truncated_question_is_not_split_as_faq(value):
    assert _source_owned_faq_pair(value) is None
