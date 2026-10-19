"""An irreducible source prohibition needs one real opposite, not padded MCQ."""
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _course_question_identity


def axes(value):
    fact = SourceFact("ban", "Безопасность", "положение", value,
                      "doc_id=synthetic;source_revision=v1;section=rules;part=1")
    lesson = LessonDraft("l", "", "", "", "", (fact.fact_id,), (), 1)
    return derive_assessment_axes(lesson, [fact], block_id="ban")


def test_simple_list_prohibition_has_a_source_bound_binary_contrast():
    items = axes("Сотрудникам запрещается: 1) курить в помещении; 2) применять открытый огонь.")
    assert len(items) == 2
    assert len({item.axis_id for item in items}) == 2
    smoking = next(item for item in items if "курить в помещении" in item.required_prompt)
    question = materialize_assessment(smoking, AuthoredAssessment(smoking.axis_id, smoking.required_prompt, ()))
    assert question is not None
    assert question.kind == "true_false"
    assert question.options == ("запрещается", "Разрешается")
    assert "сотрудникам" in question.prompt
    assert "запрещается" not in question.prompt
    assert question.source_quote == smoking.correct_value
    assert smoking.required_prompt == question.prompt
    other = next(item for item in items if item.axis_id != smoking.axis_id)
    other_question = materialize_assessment(other, AuthoredAssessment(other.axis_id, other.required_prompt, ()))
    assert other_question is not None
    assert _course_question_identity(question, {}) != _course_question_identity(other_question, {})


def test_whole_qualified_proposition_is_never_distributed_or_stripped():
    for clause in (
        "хранить и применять горючие жидкости",
        "оставлять оборудование без присмотра, кроме сигнализации",
        "покидать помещение в случае пожара",
        "покидать помещение во время тревоги",
        "покидать помещение после завершения проверки",
        "покидать помещение в течение проверки",
        "покидать помещение с момента тревоги",
        "покидать помещение по завершении проверки",
    ):
        value = f"Сотрудникам запрещается: 1) {clause}; 2) курить в помещении."
        items = axes(value)
        assert len(items) == 2
        compound = next(item for item in items if clause in item.required_prompt)
        question = materialize_assessment(compound, AuthoredAssessment(compound.axis_id, compound.required_prompt, ()))
        assert question is not None
        assert clause in question.prompt
        assert question.options == ("запрещается", "Разрешается")
        assert compound.correct_value in value


def test_a_bare_non_list_predicate_cannot_grant_a_binary_answer():
    item = axes("Запрещается")[0]
    assert materialize_assessment(item, AuthoredAssessment(item.axis_id, "Что указано?", ())) is None


def test_negated_or_scoped_prohibition_is_never_turned_into_a_prohibition():
    for predicate in ("не запрещается", "не запрещено", "не всегда запрещается", "не было запрещено"):
        assert axes(f"Сотрудникам {predicate}: 1) курить в помещении; 2) применять открытый огонь.") == ()
    assert axes("Сотрудникам не во всех случаях, предусмотренных правилами, запрещается: "
                "1) курить в помещении; 2) применять открытый огонь.") == ()


def test_closed_negative_actor_qualifier_is_not_a_negated_prohibition():
    items = axes("Лицам, не прошедшим инструктаж, запрещается: 1) входить в хранилище; 2) применять оборудование.")
    assert len(items) == 2
    assert all(item.correct_value == "запрещается" for item in items)
    assert all("не прошедшим инструктаж" in item.required_prompt for item in items)
