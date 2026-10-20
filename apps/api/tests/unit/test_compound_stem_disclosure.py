"""A coordinated duty belongs in the answer, never in the neutral stem."""
import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


@pytest.mark.parametrize(("clause", "neutral", "hidden", "context"), [
    ("соблюдать требования пожарной безопасности, а также выполнять предписания и иные законные требования органов противопожарной службы",
     "требования пожарной безопасности", "выполнять предписания", ""),
    ("разрабатывать и осуществлять меры по обеспечению пожарной безопасности",
     "меры по обеспечению пожарной безопасности", "осуществлять меры", ""),
    ("проводить противопожарную пропаганду, а также обучать своих работников мерам пожарной безопасности",
     "противопожарную пропаганду", "обучать своих работников", ""),
    ("четко знать план эвакуации людей и документов на случай возникновения пожара и Обеспечить изучение его всеми сотрудниками",
     "план эвакуации людей и документов на случай возникновения пожара", "Обеспечить изучение", "четко"),
    ("в случае обнаружения пожара сообщить о нем в подразделение противопожарной службы и принять возможные меры к спасению людей, имущества и ликвидации пожара",
     "оповещение и меры реагирования", "сообщить о нем", "в случае обнаружения пожара"),
    ("при необходимости отключить электроэнергию, выполнить другие мероприятия, способствующие предотвращению развития пожара и задымления помещений здания",
     "электроэнергию", "отключить электроэнергию", "при необходимости"),
    ("организовать встречу подразделений противопожарной службы и оказать помощь в выборе кратчайшего пути для подъезда пожарных машин к месту пожара и источникам противопожарного водоснабжения",
     "встречу подразделений противопожарной службы", "оказать помощь", ""),
])
def test_compound_rule_stem_keeps_context_and_key_without_revealing_actions(clause, neutral, hidden, context):
    fact = SourceFact("f", "Безопасность", "обязанность",
                      "1.6. Работникам следует:\n— " + clause + ";\n— проверять помещение.",
                      "doc_id=synthetic;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Обязанности сотрудников", "Применять правила", "", ("f",), (), 1)
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id="b") if a.correct_value == clause)
    assert f"«{neutral}»" in axis.required_prompt
    assert hidden.casefold() not in axis.required_prompt.casefold()
    assert not context or f"«{context}»" in axis.required_prompt
    assert axis.correct_value == clause


@pytest.mark.parametrize("objects", ["мощность и вместимость оборудования", "двери и окна помещения", "право и возможность обращения"])
def test_object_conjunction_is_not_mistaken_for_a_second_verb(objects):
    fact = SourceFact("f", "Безопасность", "обязанность",
                      f"Работникам следует:\n— проверять {objects};\n— осматривать помещение.",
                      "doc_id=synthetic;section=rules;part=1")
    lesson = LessonDraft("l", "Правила", "Проверка", "Применять правила", "", ("f",), (), 1)
    axis = next(a for a in derive_assessment_axes(lesson, [fact], block_id="b") if a.correct_value == f"проверять {objects}")
    assert f"«{objects}»" in axis.required_prompt


def test_shared_primary_object_is_disambiguated_by_source_secondary_objects():
    from app.modules.ai.evidence_engine.assessment_axes import _structured_operational_axes

    clauses = ["проверять оборудование и выполнять требования по техническому обслуживанию",
               "проверять оборудование и выполнять требования по пожарной безопасности"]
    fact = SourceFact("f", "Проверка", "обязанность", "Работникам следует:\n— " + ";\n— ".join(clauses) + ".",
                      "doc_id=synthetic;section=rules;part=1")
    rows = _structured_operational_axes(fact)
    assert len(rows) == 2 and len({p for _, p in rows}) == 2
    assert {key for key, _ in rows} == set(clauses)
    assert all("выполнять требования" not in p for _, p in rows)
    assert "техническому обслуживанию" in rows[0][1] and "пожарной безопасности" in rows[1][1]


def test_indistinguishable_compound_topics_fail_closed_without_leaking_the_key():
    from app.modules.ai.evidence_engine.assessment_axes import _structured_operational_axes

    fact = SourceFact("f", "Проверка", "обязанность",
                      "Работникам следует:\n— проверять оборудование и выполнять требования безопасности;\n"
                      "— осматривать оборудование и выполнять требования безопасности.",
                      "doc_id=synthetic;section=rules;part=1")
    with pytest.raises(ValueError, match="assessment_compound_topic_collision"):
        _structured_operational_axes(fact)
