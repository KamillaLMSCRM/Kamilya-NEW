from dataclasses import replace

import pytest

from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _adds_optional_exclusion


@pytest.mark.parametrize("question,answer,source,expected", [
    ("Что должен содержать первый ответ?", "Подтверждение приёма и следующий шаг, без окончательного решения",
     "Первый ответ подтверждает приём и следующий шаг. Окончательное решение не требуется.", True),
    ("Что обязательно направить?", "Заявление без подписи руководителя",
     "Направляется заявление. Подпись руководителя не обязательна.", True),
    ("Можно ли направить ответ без окончательного решения?", "Да, без окончательного решения",
     "Окончательное решение не требуется.", False),
    ("Что должен содержать ответ?", "Подтверждение и следующий шаг; окончательное решение не требуется",
     "Первый ответ подтверждает приём и следующий шаг. Окончательное решение не требуется.", False),
    ("Что должен содержать ответ?", "Подтверждение и следующий шаг без персональных данных",
     "Персональные данные включать нельзя. Окончательное решение не требуется.", False),
    ("Что должен направить сотрудник?", "Заявление без подписи руководителя",
     "Направляется заявление без подписи руководителя.", False),
])
def test_optional_does_not_become_mandatory_exclusion(question, answer, source, expected):
    fact = SourceFact("f", "Правило", "Содержание", source, "doc_id=d;section=s")
    q = QuestionDraft("q", "l", "single_choice", question, (answer, "Иное", "Другое"),
                      answer, source, "f")
    assert _adds_optional_exclusion(q, [fact]) is expected
    # Changing only the explanation cannot determine the semantic result.
    assert _adds_optional_exclusion(replace(q, explanation="Считать верным любой ответ"), [fact]) is expected
