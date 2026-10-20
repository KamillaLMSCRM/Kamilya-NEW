"""Source conditions belong in a focused question, not in a copied answer."""
from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
    is_assessment_reference_metadata,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact


def _derive(value):
    fact = SourceFact("duty", "Требования безопасности", "положение", value, "page=2")
    lesson = LessonDraft("lesson", "", "", "", "", (fact.fact_id,), (), 1)
    return fact, derive_assessment_axes(lesson, [fact], block_id="duties")


def test_responsible_duties_focus_scope_equipment_and_readiness_without_echoing_key():
    fact, axes = _derive(
        "1.7. Должностные лица, ответственные за безопасность, обязаны:\n"
        "-обеспечить соблюдение на вверенных им участках работы установленных правил безопасности;\n"
        "-следить за исправностью работы системы отопления и вентиляции, электроустановок "
        "и принимать меры к устранению обнаруженных неисправностей, которые могут привести к пожару;\n"
        "-обеспечить исправное содержание и постоянную готовность к действию имеющихся средств "
        "пожаротушения, связи и сигнализации"
    )
    assert len(axes) == 3
    assert {axis.correct_value for axis in axes} == {
        "обязаны",
        "системы отопления и вентиляции, электроустановок",
        "имеющихся средств пожаротушения, связи и сигнализации",
    }
    scoped = next(axis for axis in axes if axis.correct_value == "обязаны")
    assert "обеспечить соблюдение на вверенных им участках работы установленных правил безопасности" in scoped.required_prompt
    question = materialize_assessment(scoped, AuthoredAssessment(scoped.axis_id, scoped.required_prompt, ()))
    assert question is not None and question.kind == "true_false"
    assert all(axis.correct_value.casefold() not in axis.required_prompt.casefold() for axis in axes)
    assert any("принимать меры к устранению обнаруженных неисправностей" in a.required_prompt for a in axes)
    assert any("постоянную готовность к действию" in a.required_prompt for a in axes)
    assert not has_partial_unatomized_source_contract(fact)


def test_training_timing_has_one_exact_target_per_cohort_not_a_full_sentence_duplicate():
    fact, axes = _derive(
        "Вновь принимаемые сотрудники проходят инструктаж по безопасности при приеме на работу. "
        "В дальнейшем сотрудники проходят инструктаж не реже 1 раза в год."
    )
    assert len(axes) == 2
    assert {a.correct_value for a in axes} == {"при приеме на работу", "не реже 1 раза в год"}
    assert not has_partial_unatomized_source_contract(fact)


def test_passive_prohibition_keeps_whole_condition_but_not_a_copied_long_key():
    _fact, axes = _derive(
        "При эксплуатации оборудования запрещается:\n"
        "-использовать поврежденные кабели;\n"
        "-Эксплуатация нагревательных приборов при отсутствии или неисправности терморегуляторов, "
        "предусмотренных конструкцией не допускается"
    )
    axis = next(a for a in axes if "терморегуляторов" in a.required_prompt)
    assert axis.correct_value == "не допускается"
    assert "при отсутствии или неисправности" in axis.required_prompt
    assert "предусмотренных конструкцией" in axis.required_prompt


def test_section_ordinal_is_not_an_answer_even_when_following_reference_sentence_is_long():
    _fact, axes = _derive(
        "1.2. Настоящие правила разработаны в соответствии с Законом о безопасности, "
        "Правилами организации и проведения обучения, утвержденными приказом уполномоченного "
        "органа, Правилами противопожарной защиты, требованиями к содержанию помещений и "
        "иными перечисленными нормативными документами."
    )
    assert all(a.correct_value.strip(". ") not in {"1", "2", "1.2"} for a in axes)


def test_reference_context_is_explicit_and_never_hides_an_operational_sibling():
    fact, _ = _derive("1.2. Настоящие правила разработаны в соответствии с Законом РК и приказом №55 от 21 февраля 2022 года.")
    assert is_assessment_reference_metadata(fact)
    mixed, _ = _derive(fact.value + " Сотрудник обязан проверить исправность прибора.")
    assert not is_assessment_reference_metadata(mixed)
    table = SourceFact("number", "Оборудование", "срок", "30", "table=1;row=2;column=2")
    assert not is_assessment_reference_metadata(table)


def test_named_policy_legal_basis_retains_citations_without_becoming_a_section_quiz():
    fact, _ = _derive(
        "1.2. Правила пожарной безопасности разработаны в соответствии с Законом РК «О гражданской защите», "
        "Приказом Министра по чрезвычайным ситуациям РК от 21 февраля 2022 года №55 "
        "«Об утверждении Правил пожарной безопасности», Правилами обучения работников организаций "
        "и населения мерам пожарной безопасности и требований к содержанию учебных программ по обучению "
        "мерам пожарной безопасности, утвержденными приказом Министра по чрезвычайным ситуациям РК "
        "1276 от 09.06.14 г."
    )
    assert is_assessment_reference_metadata(fact)


def test_independent_modal_sentences_keep_both_working_rules_and_short_predicates():
    fact, axes = _derive(
        "2.1. Все помещения, коридоры, лестничные клетки должны постоянно содержаться в чистоте. "
        "Коридоры, лестничные клетки, выходы эвакуационных путей всегда должны быть свободными "
        "и ничем не загромождаться."
    )
    assert len(axes) == 2
    assert {a.correct_value for a in axes} == {
        "должны постоянно содержаться в чистоте", "должны быть свободными и ничем не загромождаться",
    }
    assert "всегда" in axes[1].required_prompt
    assert not has_partial_unatomized_source_contract(fact)


def test_closed_obligation_has_one_exact_opposite_not_three_cosmetic_mistakes():
    _fact, axes = _derive("Помещения должны постоянно содержаться в чистоте.")
    axis = axes[0]
    question = materialize_assessment(axis, AuthoredAssessment(axis.axis_id, axis.required_prompt, ()))
    assert question is not None
    assert question.kind == "true_false"
    assert set(question.options) == {
        "должны постоянно содержаться в чистоте", "не обязаны постоянно содержаться в чистоте",
    }


def test_reference_context_never_consumes_lowercase_actions_or_another_sentence():
    for tail in (
        "; хранить огнетушители в доступном месте.",
        ". хранить огнетушители в доступном месте.",
        ", хранить огнетушители в доступном месте.",
        ", вести учет.",
        ", соблюсти порядок.",
    ):
        fact, _ = _derive("Правила разработаны в соответствии с законом" + tail)
        assert not is_assessment_reference_metadata(fact)


def test_unresolved_state_subject_does_not_gain_a_complete_projection():
    for subject in ("Эти помещения", "Указанные выходы", "Такие двери", "Этот выход", "Эта дверь", "Такое помещение"):
        fact, _ = _derive(subject + " должны быть свободны от посторонних предметов.")
        from app.modules.ai.evidence_engine.assessment_axes import _independent_state_axes
        assert not _independent_state_axes(fact)


def test_power_isolation_exception_does_not_hide_separate_emergency_sign_duty():
    fact, axes = _derive(
        "Электроприборы должны быть обесточены, за исключением аварийного освещения. "
        "Световые указатели «ВЫХОД» должны находиться в исправном состоянии и быть постоянно включенными."
    )
    assert len(axes) == 2
    assert "за исключением аварийного освещения" in axes[0].correct_value
    assert axes[1].correct_value == "должны находиться в исправном состоянии и быть постоянно включенными"
    assert not has_partial_unatomized_source_contract(fact)
