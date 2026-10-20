"""Source-exact operational projections keep each rule's complete scope."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import (
    AuthoredAssessment,
    LessonDraft,
    SourceFact,
)
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment


def _fixture(
    value: str,
    *,
    fact_id: str = "synthetic-operational-rule",
    subject: str = "Операционная процедура",
    attribute: str = "обязанность",
    tabular: bool = False,
) -> tuple[LessonDraft, SourceFact]:
    locator = "doc_id=synthetic-policy;source_revision=v1;section=rules;part=1"
    if tabular:
        locator += ";table=2;row=3;column=2"
    fact = SourceFact(fact_id, subject, attribute, value, locator)
    lesson = LessonDraft(
        "synthetic-operational-lesson",
        "Операционные правила",
        "Рабочая процедура",
        "Применять правила процедуры",
        value,
        (fact.fact_id,),
        (),
        3,
    )
    return lesson, fact


def test_conditional_negative_right_asks_for_the_rule_in_its_source_scenario() -> None:
    value = (
        "Оператор не вправе продлевать договор, если обязательное согласование "
        "отсутствует."
    )
    lesson, fact = _fixture(value, attribute="запрет")

    axes = derive_assessment_axes(lesson, [fact], block_id="conditional-prohibition")

    assert len(axes) == 1
    axis = axes[0]
    assert axis.correct_value == "не вправе продлевать договор"
    assert axis.correct_value in value
    assert "если обязательное согласование отсутствует" in axis.required_prompt
    assert "Оператор" in axis.required_prompt

    question = materialize_assessment(
        axis,
        AuthoredAssessment(
            axis_id=axis.axis_id,
            prompt="Какое правило применяется?",
            distractors=(
                "вправе продлевать договор без согласования",
                "должен продлевать договор до получения согласования",
            ),
        ),
    )
    assert question is not None
    assert question.kind == "single_choice"
    assert question.prompt == axis.required_prompt


def test_conditional_negative_right_keeps_an_explicit_exception_in_the_key() -> None:
    value = (
        "Оператор не вправе отключать защиту, кроме аварийного режима, если "
        "обязательное согласование отсутствует."
    )
    lesson, fact = _fixture(value, attribute="запрет")

    axes = derive_assessment_axes(lesson, [fact], block_id="qualified-prohibition")

    assert tuple(axis.correct_value for axis in axes) == (
        "не вправе отключать защиту, кроме аварийного режима",
    )
    assert "если обязательное согласование отсутствует" in axes[0].required_prompt
    assert axes[0].correct_value in value


@pytest.mark.parametrize("conditional_first", [True, False])
def test_plain_and_condition_scoped_rule_survive_in_both_source_orders(conditional_first):
    lesson, conditional = _fixture(
        "Оператор не вправе продлевать договор, если согласование отсутствует.",
        fact_id="conditional", attribute="запрет",
    )
    plain = replace(conditional, fact_id="plain", value="не вправе продлевать договор")
    facts = [conditional, plain] if conditional_first else [plain, conditional]
    lesson = replace(lesson, fact_ids=tuple(fact.fact_id for fact in facts))
    axes = derive_assessment_axes(lesson, facts, block_id="plain-and-conditional")
    assert len(axes) == 2
    reverse = derive_assessment_axes(
        replace(lesson, fact_ids=tuple(reversed(lesson.fact_ids))), list(reversed(facts)),
        block_id="plain-and-conditional",
    )
    assert {axis.primary_fact_id: axis.axis_id for axis in axes} == {
        axis.primary_fact_id: axis.axis_id for axis in reverse
    }


def test_equal_scenario_actions_keep_distinct_conditions_but_dedup_same_scope() -> None:
    action = "не вправе продлевать договор"
    values = (
        f"Оператор {action}, если обязательное согласование отсутствует.",
        f"Оператор {action}, если срок разрешения истек.",
        f"Оператор {action}, если обязательное согласование отсутствует.",
    )
    facts = tuple(
        _fixture(value, fact_id=f"scenario-{index}", attribute="запрет")[1]
        for index, value in enumerate(values)
    )
    lesson = LessonDraft(
        "scenario-scope",
        "Сценарные ограничения",
        "Рабочая процедура",
        "Применять ограничения",
        " ".join(values),
        tuple(fact.fact_id for fact in facts),
        (),
        3,
    )

    axes = derive_assessment_axes(lesson, facts, block_id="scenario-scope")

    assert len(axes) == 2
    assert {axis.correct_value for axis in axes} == {action}
    assert {
        axis.required_prompt for axis in axes
    } == {
        "Какое ограничение действует для «Оператор» при условии "
        "«если обязательное согласование отсутствует»?",
        "Какое ограничение действует для «Оператор» при условии "
        "«если срок разрешения истек»?",
    }
    assert len({axis.axis_id for axis in axes}) == 2


def test_numbered_prohibition_does_not_hide_a_conditional_marking_sibling() -> None:
    prohibition = (
        "Операторам категорически запрещается продлевать договор, в случае если "
        "операция не согласована контролером."
    )
    exception_condition = (
        "В случае если на момент проверки обязательство погашено и имущество "
        "возвращено владельцу"
    )
    marking_rule = "отметка о согласовании не проставляется."
    unprojected_sibling = (
        "Материалы проверки передаются в архив после завершения процедуры."
    )
    value = (
        f"3. {prohibition} {exception_condition}, то {marking_rule} "
        f"{unprojected_sibling}"
    )
    lesson, fact = _fixture(value, attribute="запрет")

    axes = derive_assessment_axes(lesson, [fact], block_id="numbered-siblings")

    assert {axis.correct_value for axis in axes} == {
        prohibition,
        marking_rule,
    }
    by_value = {axis.correct_value: axis for axis in axes}
    assert "операция не согласована контролером" in prohibition
    assert exception_condition in by_value[marking_rule].required_prompt
    assert "погашено и имущество возвращено" in by_value[marking_rule].required_prompt
    assert all(axis.correct_value in value for axis in axes)
    assert has_partial_unatomized_source_contract(fact) is True


def test_long_shared_modal_rule_keeps_responsibility_and_each_obligation() -> None:
    scope = (
        "за ошибочную проверку оборудования, включая отступление от утвержденных "
        "инструкций, контрольных значений и порядка документирования результатов, "
        "которая причинила организации прямой действительный ущерб"
    )
    value = (
        "Согласно договору о коллективной ответственности, рабочая группа и ее "
        f"участники несут солидарную ответственность {scope}, а также обязаны "
        "бережно относиться к вверенному группе имуществу и принимать меры по "
        "предотвращению ущерба."
    )
    assert len(value) > 240
    lesson, fact = _fixture(value, subject="Коллективная ответственность")

    axes = derive_assessment_axes(lesson, [fact], block_id="shared-obligations")

    assert tuple(axis.correct_value for axis in axes) == (
        "солидарную ответственность",
        "бережно относиться к вверенному группе имуществу",
        "принимать меры по предотвращению ущерба",
    )
    assert all(axis.correct_value in value for axis in axes)
    assert scope in axes[0].required_prompt
    assert all("рабочая группа и ее участники" in axis.required_prompt for axis in axes)


def test_long_consequence_rule_keeps_complete_trigger_and_actors_in_prompt() -> None:
    trigger_and_actors = (
        "За неисполнение или ненадлежащее исполнение стандарта специалистом и "
        "руководителем подразделения"
    )
    value = (
        f"{trigger_and_actors} предусмотрена дисциплинарная ответственность в "
        "соответствии с трудовым законодательством, а также внутренним положением "
        "о категориях нарушений, влияющих на переменную часть оплаты труда."
    )
    assert len(value) > 240
    lesson, fact = _fixture(value, subject="Ответственность за нарушение")

    axes = derive_assessment_axes(lesson, [fact], block_id="disciplinary-consequence")

    assert tuple(axis.correct_value for axis in axes) == (
        "дисциплинарная ответственность",
    )
    assert axes[0].correct_value in value
    assert trigger_and_actors in axes[0].required_prompt
    assert "внутренним положением" not in axes[0].correct_value


def test_numbered_consequence_does_not_claim_to_be_the_only_other_liability() -> None:
    value = ("5. За неисполнение стандарта специалистом предусмотрена дисциплинарная "
             "ответственность в соответствии с трудовым законодательством и внутренними правилами.")
    lesson, fact = _fixture(value, subject="Ответственность")
    item = next(axis for axis in derive_assessment_axes(lesson, [fact], block_id="consequence")
                if axis.correct_value == "дисциплинарная ответственность")
    assert "пунктом «5»" in item.required_prompt
    assert "прямо" in item.required_prompt
    assert "За неисполнение стандарта специалистом" in item.required_prompt


def test_passive_responsibility_and_appointed_functions_remain_distinct() -> None:
    qualification = (
        "по занимаемой должности или по характеру выполняемых работ в силу "
        "действующих нормативных правовых и иных актов"
    )
    functions = (
        "выполняют соответствующие правила безопасности, либо обеспечивают их "
        "соблюдение на определенных участках работ"
    )
    value = (
        "Обеспечение безопасности и реагирование на инциденты возлагается на "
        "руководителя организации. Руководитель организации назначает лиц, которые "
        f"{qualification} {functions}."
    )
    assert len(value) > 240
    lesson, fact = _fixture(value, subject="Распределение ответственности")

    axes = derive_assessment_axes(lesson, [fact], block_id="assigned-responsibility")

    assert tuple(axis.correct_value for axis in axes) == (
        "руководителя организации",
        "Руководитель организации",
        functions,
    )
    assert all(axis.correct_value in value for axis in axes)
    assert "Обеспечение безопасности и реагирование на инциденты" in axes[0].required_prompt
    assert "назначает" in axes[1].required_prompt
    assert functions in axes[1].required_prompt
    assert qualification in axes[1].required_prompt
    assert "варианты функций" in axes[2].required_prompt
    assert "назначенных лиц" in axes[2].required_prompt
    assert "выполняют «лиц»" not in axes[2].required_prompt
    assert qualification in axes[2].required_prompt
    assert "либо" in axes[2].correct_value


def test_narrative_specialized_projection_does_not_hide_an_operational_sibling() -> None:
    value = (
        "Обеспечение безопасности и реагирование на инциденты возлагается на "
        "руководителя организации. Руководитель организации назначает лиц, которые "
        "по занимаемой должности или по характеру выполняемых работ в силу "
        "действующих нормативных правовых и иных актов выполняют соответствующие "
        "правила безопасности, либо обеспечивают их соблюдение на участках работ. "
        "Оператор принимает журнал в начале смены. "
        "Дежурный регистрирует все выявленные неисправности перед закрытием."
    )
    lesson, fact = _fixture(value)
    axes = derive_assessment_axes(lesson, [fact], block_id="hidden-sibling")
    assert axes
    assert not all(any(clause in axis.correct_value for axis in axes) for clause in (
        "Оператор принимает журнал в начале смены",
        "Дежурный регистрирует все выявленные неисправности перед закрытием",
    ))
    assert has_partial_unatomized_source_contract(fact) is True


@pytest.mark.parametrize("first_rule", [
    "Оператор не вправе продлевать договор, если согласование отсутствует.",
    "Если контролер согласовывает операцию, то ответственное лицо подписывает "
    "карточку с отметкой о согласовании, а также проставляет отметку в учетной системе.",
])
def test_each_new_conditional_family_accounts_for_independent_siblings(first_rule):
    value = (
        first_rule + " Оператор принимает журнал в начале смены. "
        "Дежурный регистрирует все выявленные неисправности перед закрытием."
    )
    lesson, fact = _fixture(value)
    assert derive_assessment_axes(lesson, [fact], block_id="conditional-siblings")
    assert has_partial_unatomized_source_contract(fact) is True


def test_overlong_modal_action_keeps_all_named_governing_sources_as_scope() -> None:
    governing_sources = (
        "в соответствии с Правилами эксплуатации оборудования, Правилами устройства "
        "оборудования, Правилами безопасности при эксплуатации оборудования и "
        "другими обязательными нормативными документами"
    )
    value = (
        "Технические установки должны монтироваться и эксплуатироваться "
        f"{governing_sources}."
    )
    assert len(value) > 240
    lesson, fact = _fixture(value, subject="Технические установки")

    axes = derive_assessment_axes(lesson, [fact], block_id="governed-modal-action")

    assert tuple(axis.correct_value for axis in axes) == (
        "должны монтироваться и эксплуатироваться",
    )
    assert axes[0].correct_value in value
    assert governing_sources in axes[0].required_prompt
    assert "и эксплуатироваться" in axes[0].correct_value


def test_overlong_modal_rule_keeps_exception_and_all_applicable_times() -> None:
    source_scope = (
        "Все помещения, независимо от их назначения, по окончании в них работы, "
        "а также перед закрытием на ночное время, на выходные и праздничные дни"
    )
    action = (
        "должны быть проверены по вопросу устранения причин, способных вызвать в "
        "помещении возгорание в нерабочее время"
    )
    value = f"{source_scope} {action}."
    assert len(value) > 240
    lesson, fact = _fixture(value, subject="Закрытие помещений")

    axes = derive_assessment_axes(lesson, [fact], block_id="time-qualified-modal")

    assert tuple(axis.correct_value for axis in axes) == (action,)
    assert axes[0].correct_value in value
    assert source_scope in axes[0].required_prompt
    assert "независимо от их назначения" in axes[0].required_prompt
    assert "ночное время" in axes[0].required_prompt
    assert "выходные и праздничные дни" in axes[0].required_prompt


def test_last_person_leaving_rule_is_not_lost_after_general_end_of_day_duties() -> None:
    value = (
        "6.3. По окончании рабочего дня каждый сотрудник обязан проверить и привести в порядок рабочее место. "
        "Необходимо обесточить оборудование и осмотреть на наличие признаков возгорания. "
        "Уходящий последним из помещения должен проверить, закрыты ли форточки и окна, выключить свет."
    )
    lesson, fact = _fixture(value, subject="Окончание работы")
    axes = derive_assessment_axes(lesson, [fact], block_id="closing")
    assert len(axes) == 3
    last = next(axis for axis in axes if "закрыты ли форточки и окна" in axis.correct_value)
    assert "выключить свет" in last.correct_value
    assert "Уходящий последним из помещения" in last.required_prompt
    assert not has_partial_unatomized_source_contract(fact)


def test_conditional_coordinated_actions_get_distinct_source_scoped_axes() -> None:
    condition = "Если контролер согласовывает операцию"
    value = (
        "Общий порядок включает предварительную сверку реквизитов, истории решений "
        "и полномочий ответственного лица до начала документирования. "
        f"{condition}, то ответственное лицо подписывает карточку с отметкой о "
        "согласовании, а также проставляет отметку в учетной системе."
    )
    assert len(value) > 240
    lesson, fact = _fixture(value, tabular=True)

    axes = derive_assessment_axes(lesson, [fact], block_id="coordinated-condition")

    assert tuple(axis.correct_value for axis in axes) == (
        "подписывает карточку с отметкой о согласовании",
        "проставляет отметку в учетной системе",
    )
    assert all(axis.correct_value in value for axis in axes)
    assert all(condition in axis.required_prompt for axis in axes)
    assert all("ответственное лицо" in axis.required_prompt for axis in axes)
    assert axes[0].required_prompt != axes[1].required_prompt
    assert has_partial_unatomized_source_contract(fact) is True


def test_coordinated_recording_step_keeps_its_explicit_approval_context() -> None:
    value = (
        "Общий порядок включает предварительную сверку реквизитов и полномочий "
        "ответственного лица до начала документирования. Если контролер "
        "согласовывает операцию, то ответственное лицо подписывает карточку "
        "с отметкой о согласовании, а также об этом проставляет отметку в "
        "учетной системе."
    )
    lesson, fact = _fixture(value, tabular=True)
    axes = derive_assessment_axes(lesson, [fact], block_id="coordinated-recording")
    recording = next(axis for axis in axes if axis.correct_value ==
                     "проставляет отметку в учетной системе")
    assert "Если контролер согласовывает операцию" in recording.required_prompt
    assert "ответственное лицо" in recording.required_prompt
    assert "подписывает карточку с отметкой о согласовании" in {
        axis.correct_value for axis in axes
    }


def test_flattened_local_and_remote_branches_keep_their_own_conditions() -> None:
    local_condition = "при расположении пункта в пределах города"
    remote_condition = "при расположении пункта вне города"
    local_action = (
        "проверка проводится во время комплексной или оперативной проверки."
    )
    remote_action = "проверка проводится во время комплексной проверки."
    value = (
        "Ответственный проводит проверку по правилам категории: "
        f"- {local_condition} - {local_action} "
        f"- {remote_condition} - {remote_action} "
        "Дальнейшее документирование регулируется отдельной процедурой, которая "
        "не входит в это правило и не изменяет условия двух указанных ветвей."
    )
    assert len(value) > 240
    lesson, fact = _fixture(value, subject="Категория Б", tabular=True)

    axes = derive_assessment_axes(lesson, [fact], block_id="location-branches")

    assert tuple(axis.correct_value for axis in axes) == (
        local_action,
        remote_action,
    )
    assert local_condition in axes[0].required_prompt
    assert remote_condition not in axes[0].required_prompt
    assert remote_condition in axes[1].required_prompt
    assert local_condition not in axes[1].required_prompt
    assert all("Категория Б" in axis.required_prompt for axis in axes)
    assert all("Ответственный" in axis.required_prompt for axis in axes)
    assert all(axis.correct_value in value for axis in axes)
    assert has_partial_unatomized_source_contract(fact) is True


def test_handover_suspicion_rule_keeps_checks_notification_and_branch_timing() -> None:
    value = (
        "Сменный специалист во время приема-передачи участка (если операция не "
        "согласована руководителем) обязан визуально проверить соответствие объекта "
        "выданной сумме. В случае своего согласия поставить свою подпись в карточке. "
        "Если объект вызывает подозрения в отношении качественных или количественных "
        "характеристик, то сменный специалист обязан сразу уведомить руководителя. "
        "После получения такой информации, руководитель обязан при расположении "
        "участка в пределах города выехать незамедлительно, а при расположении участка "
        "вне города - в течение 2-х дней с момента получения информации, для проверки "
        "и составления акта."
    )
    lesson, fact = _fixture(value, subject="Категория Б", tabular=True)

    axes = derive_assessment_axes(lesson, [fact], block_id="handover-response")
    by_value = {axis.correct_value: axis for axis in axes}

    expected = (
        "обязан визуально проверить соответствие объекта выданной сумме",
        "поставить свою подпись в карточке",
        "сменный специалист обязан сразу уведомить руководителя.",
        "выехать незамедлительно",
        "в течение 2-х дней с момента получения информации",
    )
    assert tuple(axis.correct_value for axis in axes) == expected
    assert all(item in value for item in expected)
    visual = by_value[expected[0]].required_prompt
    assert "во время приема-передачи участка" in visual
    assert "если операция не согласована руководителем" in visual
    signature = by_value[expected[1]].required_prompt
    assert "сменный специалист" in signature.casefold()
    assert "В случае своего согласия" in signature
    notification = by_value[expected[2]].required_prompt
    assert "объект вызывает подозрения" in notification
    local = by_value[expected[3]].required_prompt
    remote = by_value[expected[4]].required_prompt
    assert "объект вызывает подозрения" in local
    assert "в пределах города" in local
    assert "вне города" not in local
    assert "объект вызывает подозрения" in remote
    assert "вне города" in remote
    assert "в пределах города" not in remote
    assert "для проверки и составления акта" in remote
    assert by_value[expected[3]].axis_kind == "rule_value"
    assert by_value[expected[4]].axis_kind == "numeric_value"
    assert has_partial_unatomized_source_contract(fact) is True


def test_handover_signature_does_not_inherit_actor_across_an_intervening_rule() -> None:
    signature = "поставить свою подпись в карточке"
    value = (
        "Сменный специалист во время приема-передачи участка (если операция не "
        "согласована руководителем) обязан визуально проверить объект. "
        "Руководитель отдельно проверяет журнал и фиксирует результат проверки. "
        f"В случае своего согласия {signature}. "
        "Дальнейший порядок регулируется отдельным документом и здесь не указан."
    )
    lesson, fact = _fixture(value, subject="Категория Б", tabular=True)

    axes = derive_assessment_axes(lesson, [fact], block_id="separated-handover")

    assert signature not in {axis.correct_value for axis in axes}
    assert has_partial_unatomized_source_contract(fact) is True


def test_shared_modal_projection_preserves_negation_and_or_scope() -> None:
    scope = (
        "за применение средств контроля без обязательной сверки журналов, "
        "показаний и подтверждающих документов по установленной процедуре"
    )
    value = (
        "Согласно соглашению, группа и ее участники несут совместную "
        f"ответственность {scope}, а также обязаны не отключать защиту и "
        "проверять основной или резервный канал связи."
    )
    lesson, fact = _fixture(value)

    axes = derive_assessment_axes(lesson, [fact], block_id="negative-shared-modal")

    assert tuple(axis.correct_value for axis in axes) == (
        "совместную ответственность",
        "не отключать защиту",
        "проверять основной или резервный канал связи",
    )
    assert "не отключать" in axes[1].correct_value
    assert "основной или резервный" in axes[2].correct_value


def test_numeric_date_and_clause_number_do_not_split_consequence_scope() -> None:
    trigger = (
        "За нарушение стандарта 2.1 от 09.06.2026 специалистом и руководителем"
    )
    value = (
        f"{trigger} предусмотрена дисциплинарная ответственность в соответствии "
        "с внутренними правилами и обязательным порядком документирования."
    )
    lesson, fact = _fixture(value)

    axes = derive_assessment_axes(lesson, [fact], block_id="numbered-consequence")

    consequence = next(
        axis for axis in axes
        if axis.correct_value == "дисциплинарная ответственность"
    )
    assert trigger in consequence.required_prompt


def test_overlong_time_scope_stays_unsupported_instead_of_being_truncated() -> None:
    long_scope = " ".join(["после подтверждения каждого контрольного признака"] * 20)
    value = (
        f"Все помещения, независимо от их назначения, {long_scope} должны быть "
        "проверены перед закрытием."
    )
    assert len(long_scope) > 700
    lesson, fact = _fixture(value)

    axes = derive_assessment_axes(lesson, [fact], block_id="unbounded-time-scope")

    assert axes == ()


def test_time_qualified_action_does_not_emit_an_overlapping_deadline_axis() -> None:
    scope = (
        "Все помещения, независимо от их назначения, после завершения основной и "
        "контрольной смены, перед закрытием на выходные и праздничные дни"
    )
    action = (
        "должны быть проверены в течение 2 дней с момента окончания работы для "
        "устранения причин возможного возгорания"
    )
    value = f"{scope} {action}. Дополнительные пояснения " + "контроля " * 20
    lesson, fact = _fixture(value)

    axes = derive_assessment_axes(lesson, [fact], block_id="qualified-action-deadline")

    assert [axis.correct_value for axis in axes if "в течение 2 дней" in axis.correct_value] == [
        action,
    ]


@pytest.mark.asyncio
async def test_source_owned_short_answer_domain_is_disclosed_to_the_author() -> None:
    value = (
        "Обеспечение безопасности и реагирование на инциденты возлагается на "
        "руководителя организации. Руководитель организации назначает лиц, которые "
        "по занимаемой должности или по характеру выполняемых работ в силу "
        "действующих нормативных правовых и иных актов выполняют соответствующие "
        "правила безопасности, либо обеспечивают их соблюдение на участках работ."
    )
    lesson, fact = _fixture(value)
    requests = []

    class CaptureEmptyAuthor:
        async def ainvoke_validated(self, messages, parser, **_kwargs):
            request = json.loads(messages[-1]["content"])
            assert request["task"] == "assessment_generate"
            requests.append(request)
            return SimpleNamespace(value=parser('{"questions": []}'), attempt_count=1)

    await generate_block_assessment([lesson], {fact.fact_id: fact}, CaptureEmptyAuthor())
    by_claim = {axis["source_claim"]: axis for request in requests for axis in request["axes"]}
    assert by_claim["руководителя организации"]["distractor_token_limit"] == 5
    assert by_claim["Руководитель организации"]["distractor_token_limit"] == 5
    assert next(axis for claim, axis in by_claim.items()
                if claim.startswith("выполняют"))["distractor_token_limit"] is None

    axes = derive_assessment_axes(lesson, [fact], block_id="short-domain")
    owner = next(axis for axis in axes if axis.correct_value == "руководителя организации")
    assert materialize_assessment(owner, AuthoredAssessment(
        owner.axis_id, owner.required_prompt,
        ("начальника смены", "ответственного инженера"),
    )) is not None
    assert materialize_assessment(owner, AuthoredAssessment(
        owner.axis_id, owner.required_prompt,
        ("На всех сотрудников организации, независимо от должности и характера работ",
         "начальника смены"),
    )) is None
