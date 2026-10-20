"""Every explicit normative list child must survive or remain visibly partial."""

from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
)
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact


def _fixture(value: str):
    fact = SourceFact("list", "Безопасность", "обязанность", value, "section=safety;part=1")
    lesson = LessonDraft("lesson", "", "", "", "", (fact.fact_id,), (), 1)
    return fact, derive_assessment_axes(lesson, [fact], block_id="inventory")


def test_normative_list_keeps_nominal_passive_adverb_and_comma_children():
    children = (
        "организовать обучение сотрудников",
        "обеспечение исправного состояния средств пожаротушения",
        "сотрудники допускаются к работе только после инструктажа",
        "четко знать план эвакуации и обеспечить изучение его сотрудниками",
        "систематически контролировать исправность аппаратов защиты",
        "проверить, удалены ли из помещения горючие материалы",
    )
    fact, axes = _fixture("Руководитель обязан:\n" + ";\n".join("- " + c for c in children))
    assert {axis.correct_value for axis in axes} == set(children)
    assert all(axis.correct_value.casefold() not in axis.required_prompt.casefold() for axis in axes)
    assert not has_partial_unatomized_source_contract(fact)


def test_long_prohibition_keeps_whole_condition_in_question_without_long_key():
    action = ("использовать оборудование в условиях, не соответствующих рекомендациям изготовителя, "
              "или имеющее неисправности, способные привести к пожару, а также эксплуатировать "
              "провода с поврежденной изоляцией, исключающей защиту от воздействия опасных факторов")
    fact, axes = _fixture("Сотрудникам запрещается:\n- " + action + ";\n- применять открытый огонь")
    assert len(axes) == 2
    assert all(axis.correct_value == "запрещается" for axis in axes)
    assert any(action in axis.required_prompt for axis in axes)
    assert not has_partial_unatomized_source_contract(fact)


def test_long_duty_can_assess_exact_responsible_actor_without_cutting_the_action():
    action = ("обеспечить организацию и своевременное проведение профилактических осмотров и "
              "планово-предупредительных ремонтов электрооборудования, аппаратов защиты и "
              "электросетей, а также своевременно устранять нарушения, которые могут привести "
              "к пожарам и возгораниям")
    fact, axes = _fixture("Ответственные за электроустановки сотрудники обязаны:\n- " + action
                          + ";\n- контролировать исправность аппаратов защиты")
    assert len(axes) == 2
    actor_axis = next(axis for axis in axes if action in axis.required_prompt)
    assert actor_axis.correct_value == "Ответственные за электроустановки сотрудники"
    assert not has_partial_unatomized_source_contract(fact)


def test_unprojectable_child_cannot_hide_behind_two_supported_siblings():
    fact, axes = _fixture("Руководитель обязан:\n- организовать обучение сотрудников;\n"
                          "- проверить свободный выход;\n- обеспечить " + "сохранность " * 110)
    assert len(axes) == 2
    assert has_partial_unatomized_source_contract(fact)


def test_non_normative_list_does_not_invent_obligations():
    _fact, axes = _fixture("Параметры оборудования:\n- рабочее напряжение 220 В;\n"
                           "- номинальная мощность 100 Вт;\n- материал корпуса сталь")
    assert not any("обязан" in axis.required_prompt for axis in axes)


def test_unbounded_prohibition_stem_is_not_a_completed_source_target():
    fact, axes = _fixture("Сотрудникам запрещается:\n- применять открытый огонь;\n"
                          "- хранить горючие материалы;\n- использовать " + "оборудование " * 100)
    assert len(axes) == 2
    assert has_partial_unatomized_source_contract(fact)


def test_list_inventory_precedes_specialized_schedule_shortcut():
    fact, _axes = _fixture("Руководитель обязан:\n- организовать обучение сотрудников;\n"
                           "- проверить свободный выход;\n"
                           "- сотрудники проходят инструктаж не реже 1 раза в год;\n"
                           "- обеспечить " + "сохранность " * 110)
    assert has_partial_unatomized_source_contract(fact)


def test_overlong_child_with_two_rules_keeps_both_source_statements():
    first = ("пользоваться электронагревательными приборами без подставок из негорючих "
             "теплоизоляционных материалов, исключающих опасность возникновения пожара, "
             "а также оставлять такие приборы включенными без присмотра")
    second = "Эксплуатация приборов при неисправности предусмотренных конструкцией терморегуляторов не допускается"
    fact, axes = _fixture("При эксплуатации оборудования запрещается:\n- " + first + ". "
                          + second + ";\n- применять открытый огонь")
    assert len(axes) == 3
    assert any(first.lower() in axis.required_prompt.lower() for axis in axes)
    assert any(second in axis.correct_value for axis in axes)
    assert not has_partial_unatomized_source_contract(fact)
