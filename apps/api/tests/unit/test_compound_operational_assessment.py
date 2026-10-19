import json
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.quality import MAX_ASSESSMENT_ANSWER_CHARS
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment


def _table_fixture(
    value: str,
    *,
    subject: str = "Категория Б",
    attribute: str = "Порядок согласования",
) -> tuple[LessonDraft, SourceFact]:
    fact = SourceFact(
        "synthetic-table-fact",
        subject,
        attribute,
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=rules;"
        "table=2;row=3;column=2",
    )
    lesson = LessonDraft(
        "synthetic-table-lesson",
        "Операционные правила",
        "Согласование операций",
        "Применять правила согласования",
        value,
        (fact.fact_id,),
        (),
        3,
    )
    return lesson, fact


def test_regulatory_ranges_keep_city_abbreviations_and_region_associations() -> None:
    value = (
        "От 500 100 до 900 000 тенге для РД г. Северный, г. Озерный, г. Степной "
        "от 500 100 до 1 200 000 тенге РД г. Центральный, г. Южный, г. Восточный"
    )
    lesson, fact = _table_fixture(
        value,
        subject="Категория Б",
        attribute="Лимит операции, тенге",
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-ranges")

    assert tuple(axis.correct_value for axis in axes) == (
        "От 500 100 до 900 000 тенге",
        "от 500 100 до 1 200 000 тенге",
    )
    assert all(axis.correct_value in value for axis in axes)
    assert all(len(axis.correct_value) <= MAX_ASSESSMENT_ANSWER_CHARS for axis in axes)
    assert "Категория Б" in axes[0].required_prompt
    assert "г. Северный" in axes[0].required_prompt
    assert "Категория Б" in axes[1].required_prompt
    assert "г. Центральный" in axes[1].required_prompt
    assert all(not axis.correct_value.endswith("РД г.") for axis in axes)


def test_long_operational_table_cell_derives_only_standalone_exact_source_clauses() -> None:
    value = (
        "Общий порядок включает предварительную сверку реквизитов и историю решений, "
        "которая используется только как справочный контекст для ответственного лица. "
        "Сотрудник обязан проверить документ и зафиксировать результат в журнале. "
        "Если обнаружено расхождение, остановить операцию и сообщить руководителю. "
        "В этом случае он оформляет дополнительную служебную запись, содержание которой "
        "определяется отдельным регламентом и не раскрывается в этой таблице."
    )
    lesson, fact = _table_fixture(value)

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-compound")

    assert tuple(axis.correct_value for axis in axes) == (
        "Сотрудник обязан проверить документ и зафиксировать результат в журнале.",
        "Если обнаружено расхождение, остановить операцию и сообщить руководителю.",
    )
    assert all(axis.correct_value in value for axis in axes)
    assert all(len(axis.correct_value) <= MAX_ASSESSMENT_ANSWER_CHARS for axis in axes)
    assert all("Категория Б" in axis.required_prompt for axis in axes)
    assert all("Порядок согласования" in axis.required_prompt for axis in axes)
    assert all(not axis.correct_value.startswith("В этом случае") for axis in axes)


def test_overlong_conditional_rule_keeps_full_condition_and_exact_action_span() -> None:
    condition = (
        "Если общая сумма заявок одного контрагента за один день в одном отделении, "
        "включая заявки по связанным операциям и повторным обращениям в течение смены, "
        "относится одновременно к первой и второй категориям внутреннего контроля"
    )
    action = "необходимо провести согласование по действующему стандарту."
    value = f"*{condition}, {action}"
    assert len(value) > MAX_ASSESSMENT_ANSWER_CHARS
    fact = SourceFact(
        "synthetic-aggregate-rule",
        "Совокупный лимит заявок",
        "правило согласования",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=rules;part=7",
    )
    lesson = LessonDraft(
        "synthetic-aggregate-lesson",
        "Операционные правила",
        "Совокупный лимит",
        "Применять совокупный лимит",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-aggregate")

    assert tuple(axis.correct_value for axis in axes) == (action,)
    assert axes[0].correct_value in value
    assert condition in axes[0].required_prompt
    assert "характеристике" not in axes[0].required_prompt
    assert "пункт" not in axes[0].required_prompt.casefold()


def test_conditional_action_does_not_detach_source_exception() -> None:
    condition = (
        "Если датчики фиксируют устойчивое задымление в рабочей зоне после повторной "
        "проверки ответственным сотрудником, подтверждения сигнала дежурным и "
        "сопоставления показаний двух независимых систем наблюдения за помещением"
    )
    action = "необходимо покинуть зону, кроме случаев учебной тревоги."
    value = f"{condition}, {action}"
    assert len(value) > MAX_ASSESSMENT_ANSWER_CHARS
    fact = SourceFact(
        "synthetic-exception-rule",
        "Действия при задымлении",
        "обязанность",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=safety;part=3",
    )
    lesson = LessonDraft(
        "synthetic-exception-lesson",
        "Безопасность",
        "Задымление",
        "Применять правило эвакуации",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-exception")

    assert tuple(axis.correct_value for axis in axes) == (action,)
    assert "кроме случаев учебной тревоги" in axes[0].correct_value
    assert condition in axes[0].required_prompt


def test_structured_condition_without_comma_keeps_trigger_and_action() -> None:
    value = (
        "Сотрудникам следует: - 1) в случае обнаружения дыма сообщить диспетчеру "
        "и принять меры к эвакуации людей; - 2) проверить свободный доступ к выходу."
    )
    fact = SourceFact(
        "synthetic-inline-condition",
        "Действия сотрудников",
        "обязанность",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=safety;part=5",
    )
    lesson = LessonDraft(
        "synthetic-inline-condition-lesson",
        "Безопасность",
        "Действия при дыме",
        "Применять порядок эвакуации",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-inline-condition")

    assert len(axes) == 2
    smoke_axis = next(axis for axis in axes if "обнаружения дыма" in axis.correct_value)
    assert "в случае обнаружения дыма" in smoke_axis.required_prompt
    assert "сообщить диспетчеру" in smoke_axis.correct_value
    assert "эвакуации людей" in smoke_axis.correct_value


def test_single_numbered_action_keeps_actor_and_complete_exceptions() -> None:
    action = (
        "отключить от сети все приборы за исключением разрешенного оборудования "
        "непрерывного действия, а также дежурного и аварийного освещения"
    )
    value = (
        "7.2. Сотрудник, закрывающий помещение последним, обязан: "
        f"4. — {action};"
    )
    fact = SourceFact(
        "synthetic-single-action",
        "Завершение смены",
        "обязанность",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=safety;part=12",
    )
    lesson = LessonDraft(
        "synthetic-single-action-lesson",
        "Безопасность",
        "Завершение смены",
        "Применять порядок завершения смены",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-single-action")

    assert tuple(axis.correct_value for axis in axes) == (action,)
    assert action in value
    assert "Сотрудник, закрывающий помещение последним, обязан" in axes[0].required_prompt
    assert "за исключением" in axes[0].correct_value
    assert "дежурного и аварийного освещения" in axes[0].correct_value
    assert "пункт" not in axes[0].required_prompt.casefold()


def test_compound_safety_paragraph_prefers_complete_deenergize_and_inspect_action() -> None:
    expected = (
        "Необходимо обесточить все приборы и осмотреть помещение на наличие "
        "признаков возгорания."
    )
    value = (
        "По окончании рабочей смены каждый сотрудник приводит в порядок рабочее "
        "место и проверяет сохранность документов. "
        f"{expected} "
        "Сотрудник, уходящий последним, должен проверить, закрыты ли окна, и "
        "выключить освещение в служебной зоне."
    )
    assert len(value) > MAX_ASSESSMENT_ANSWER_CHARS
    fact = SourceFact(
        "synthetic-end-of-day",
        "Окончание рабочего дня",
        "обязанность",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=safety;part=13",
    )
    lesson = LessonDraft(
        "synthetic-end-of-day-lesson",
        "Безопасность",
        "Окончание рабочего дня",
        "Применять порядок завершения работы",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-end-of-day")

    assert {axis.correct_value for axis in axes} == {
        expected,
        "должен проверить, закрыты ли окна, и выключить освещение в служебной зоне",
    }
    assert all(axis.correct_value in value for axis in axes)
    closing = next(axis for axis in axes if axis.correct_value != expected)
    assert "уходящий последним" in closing.required_prompt


def test_compound_safety_paragraph_prefers_explicit_network_disconnect_rule() -> None:
    expected = (
        "Неисправную сеть следует отключить до приведения ее в безопасное состояние."
    )
    value = (
        "Неисправности в аппаратуре, которые способны вызвать искрение, короткое "
        "замыкание, перегрев изоляции кабелей и повреждение защитных устройств, "
        "немедленно устраняются дежурным специалистом после регистрации события. "
        f"{expected}"
    )
    assert len(value) > MAX_ASSESSMENT_ANSWER_CHARS
    fact = SourceFact(
        "synthetic-network-disconnect",
        "Эксплуатация электрической сети",
        "обязанность",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=safety;part=14",
    )
    lesson = LessonDraft(
        "synthetic-network-disconnect-lesson",
        "Безопасность",
        "Неисправная сеть",
        "Отключать неисправную сеть",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-disconnect")

    assert tuple(axis.correct_value for axis in axes) == (expected,)
    assert axes[0].correct_value in value
    assert "Эксплуатация электрической сети" in axes[0].required_prompt


def test_table_deadlines_keep_actor_category_trigger_and_distinct_units() -> None:
    value = (
        "Порядок применяется после регистрации заявки и получения уведомления. "
        "Проверку категории А ответственный специалист производит в первый рабочий "
        "день с момента регистрации заявки. "
        "Проверку категории Б ответственный специалист производит в течение 24 часов "
        "с момента регистрации заявки. "
        "После получения уведомления ответственный специалист обязан при расположении "
        "пункта в пределах города выехать незамедлительно, а при расположении пункта "
        "вне города — в течении 2-х дней с момента получения уведомления, для проверки "
        "и составления акта. Если заявка поступила после 18:00, необходимо подтвердить "
        "получение по телефону."
    )
    lesson, fact = _table_fixture(value, subject="Категории А и Б")

    axes = derive_assessment_axes(lesson, [fact], block_id="synthetic-deadlines")
    by_value = {axis.correct_value: axis for axis in axes}

    expected = (
        "в первый рабочий день с момента регистрации заявки",
        "в течение 24 часов с момента регистрации заявки",
        "в течении 2-х дней с момента получения уведомления",
    )
    assert all(item in by_value for item in expected)
    assert "категории А" in by_value[expected[0]].required_prompt
    assert "ответственный специалист" in by_value[expected[0]].required_prompt
    assert "категории Б" in by_value[expected[1]].required_prompt
    assert "вне города" in by_value[expected[2]].required_prompt
    assert "для проверки и составления акта" in by_value[expected[2]].required_prompt
    assert all(item in value for item in expected)
    assert not any(axis.correct_value == "после 18:00" for axis in axes)


class _AcceptingAssessmentClient:
    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        if request["task"] == "assessment_generate":
            payload = {
                "questions": [
                    {
                        "axis_id": axis["axis_id"],
                        "prompt": axis["required_prompt"],
                        "distractors": [
                            "Продолжить операцию без проверки документа и не фиксировать результат в журнале.",
                            "Отложить проверку документа и запись результата до следующей смены.",
                        ],
                    }
                    for axis in request["axes"]
                ],
            }
        elif request["task"] == "assessment_review":
            payload = {
                "reviews": [
                    {
                        "question_id": question["question_id"],
                        "question_supported": True,
                        "educational": True,
                        "explanation_supported": True,
                        "options_distinct": True,
                        "options": [
                            {
                                "index": index,
                                "answers_question": True,
                                "correct": index == 0,
                                "plausible_error": index > 0,
                                "contradicted_by_source": index > 0,
                                "same_practical_task": True,
                            }
                            for index in range(len(question["options"]))
                        ],
                    }
                    for question in request["questions"]
                ],
            }
        else:
            fact = request["facts"][0]
            payload = {
                "rules": [{
                    "fact_id": fact["fact_id"],
                    "quote": fact["value"],
                    "kind": "required",
                }],
                "reviews": [
                    {
                        "question_id": question["question_id"],
                        "reason": "Synthetic source contract.",
                        "distinct_errors": True,
                        "options": [
                            {
                                "index": index,
                                "relation": "entailed" if index == 0 else "contradicted",
                                "invented_constraint": False,
                                "realistic_error": True,
                            }
                            for index in range(len(question["options"]))
                        ],
                    }
                    for question in request["questions"]
                ],
            }
        return SimpleNamespace(
            value=parser(json.dumps(payload, ensure_ascii=False)),
            attempt_count=1,
        )


@pytest.mark.asyncio
async def test_partial_long_table_atomization_keeps_unparsed_context_review_required() -> None:
    value = (
        "Общий порядок включает предварительную сверку реквизитов и историю решений, "
        "которая используется только как справочный контекст для ответственного лица. "
        "Сотрудник обязан проверить документ и зафиксировать результат в журнале. "
        "Если обнаружено расхождение, остановить операцию и сообщить руководителю. "
        "В этом случае он оформляет дополнительную служебную запись, содержание которой "
        "определяется отдельным регламентом и не раскрывается в этой таблице."
    )
    lesson, fact = _table_fixture(value)

    result = await generate_block_assessment(
        [lesson],
        {fact.fact_id: fact},
        _AcceptingAssessmentClient(),
    )

    assert len(result.questions) == 2
    assert all(question.correct_answer in value for question in result.questions)
    partial = [
        row for row in result.audit["axis_outcomes"]
        if row["reason"] == "partial_unatomized_source_contract"
    ]
    assert len(partial) == 1
    assert partial[0]["primary_fact_id"] == fact.fact_id
    assert result.audit["coverage"]["unatomizable_fact_ids"] == [fact.fact_id]
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["terminal_status"] == "review_required"


class _NoCallsClient:
    async def ainvoke_validated(self, *_args, **_kwargs):
        raise AssertionError("unatomizable source must not spend an assessment call")


@pytest.mark.asyncio
async def test_unatomizable_overlong_table_rule_is_review_required_without_author_call() -> None:
    value = (
        "Ответственный специалист рассматривает единое неделимое требование, "
        + "сохраняющее зависимый контекст без безопасной границы; " * 8
        + "после чего действует по отдельному закрытому регламенту."
    )
    lesson, fact = _table_fixture(value)

    result = await generate_block_assessment(
        [lesson],
        {fact.fact_id: fact},
        _NoCallsClient(),
    )

    assert result.questions == ()
    assert result.audit["attempt_counts"]["authored"] == 0
    assert result.audit["attempt_counts"]["model_repair"] == 0
    assert result.audit["unassessable_count"] == 1
    assert result.audit["coverage"]["unatomizable_fact_ids"] == [fact.fact_id]
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["coverage"]["audit_incomplete"] is True
    assert result.audit["terminal_status"] == "review_required"


@pytest.mark.asyncio
async def test_unatomizable_overlong_narrative_is_not_lost_before_axis_audit() -> None:
    value = (
        "Если суммарный показатель за рабочий период относится одновременно к двум "
        "категориям и требует единого решения без самостоятельной границы между "
        "условием и действием, ответственный сотрудник применяет полный действующий "
        "стандарт согласования без сокращения исходного требования."
    )
    assert len(value) > MAX_ASSESSMENT_ANSWER_CHARS
    fact = SourceFact(
        "synthetic-long-narrative",
        "Контроль совокупного показателя",
        "правило",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=rules;part=4",
    )
    lesson = LessonDraft(
        "synthetic-long-narrative-lesson",
        "Операционные правила",
        "Контроль совокупного показателя",
        "Применять порядок согласования",
        value,
        (fact.fact_id,),
        (),
        2,
    )

    result = await generate_block_assessment(
        [lesson],
        {fact.fact_id: fact},
        _NoCallsClient(),
    )

    assert result.questions == ()
    assert result.audit["attempt_counts"]["authored"] == 0
    assert result.audit["unassessable_count"] == 1
    assert result.audit["coverage"]["unatomizable_fact_ids"] == [fact.fact_id]
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["terminal_status"] == "review_required"


class _ImmutableExplanationRejectingClient:
    def __init__(self) -> None:
        self.tasks: list[str] = []

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        self.tasks.append(request["task"])
        if request["task"] == "assessment_generate":
            axis = request["axes"][0]
            payload = {
                "questions": [{
                    "axis_id": axis["axis_id"],
                    "prompt": axis["required_prompt"],
                    "distractors": [
                        "Продолжить операцию без проверки.",
                        "Отложить проверку до следующей смены.",
                    ],
                }],
            }
        elif request["task"] == "assessment_review":
            question = request["questions"][0]
            payload = {
                "reviews": [{
                    "question_id": question["question_id"],
                    "question_supported": True,
                    "educational": True,
                    "explanation_supported": False,
                    "options_distinct": True,
                    "options": [
                        {
                            "index": index,
                            "answers_question": True,
                            "correct": index == 0,
                            "plausible_error": index > 0,
                            "contradicted_by_source": index > 0,
                            "same_practical_task": True,
                        }
                        for index in range(len(question["options"]))
                    ],
                }],
            }
        else:
            raise AssertionError(f"unexpected immutable-defect call: {request['task']}")
        return SimpleNamespace(
            value=parser(json.dumps(payload, ensure_ascii=False)),
            attempt_count=1,
        )


@pytest.mark.asyncio
async def test_server_owned_explanation_rejection_does_not_spend_model_repair() -> None:
    value = "Если документ поврежден, сотрудник должен остановить операцию."
    fact = SourceFact(
        "synthetic-rule",
        "Проверка документа",
        "правило",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=rules;part=1",
    )
    lesson = LessonDraft(
        "synthetic-rule-lesson",
        "Операционные правила",
        "Проверка документа",
        "Действовать при повреждении документа",
        value,
        (fact.fact_id,),
        (),
        1,
    )
    client = _ImmutableExplanationRejectingClient()

    result = await generate_block_assessment(
        [lesson],
        {fact.fact_id: fact},
        client,
    )

    assert client.tasks == ["assessment_generate", "assessment_review"]
    assert result.questions == ()
    assert result.audit["attempt_counts"]["model_repair"] == 0
    outcome = next(
        row for row in result.audit["axis_outcomes"]
        if row["primary_fact_id"] == fact.fact_id
    )
    assert outcome["state"] == "omitted"
    assert outcome["reason"] == "explanation_supported;server_immutable_defect"


class _ImmutableKeyConstraintRejectingClient(_ImmutableExplanationRejectingClient):
    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        if request["task"] != "assessment_constraints":
            if request["task"] == "assessment_review":
                self.tasks.append(request["task"])
                question = request["questions"][0]
                payload = {
                    "reviews": [{
                        "question_id": question["question_id"],
                        "question_supported": True,
                        "educational": True,
                        "explanation_supported": True,
                        "options_distinct": True,
                        "options": [
                            {
                                "index": index,
                                "answers_question": True,
                                "correct": index == 0,
                                "plausible_error": index > 0,
                                "contradicted_by_source": index > 0,
                                "same_practical_task": True,
                            }
                            for index in range(len(question["options"]))
                        ],
                    }],
                }
                return SimpleNamespace(
                    value=parser(json.dumps(payload, ensure_ascii=False)),
                    attempt_count=1,
                )
            return await super().ainvoke_validated(messages, parser, **kwargs)
        self.tasks.append(request["task"])
        question = request["questions"][0]
        fact = request["facts"][0]
        payload = {
            "rules": [{
                "fact_id": fact["fact_id"],
                "quote": fact["value"],
                "kind": "required",
            }],
            "reviews": [{
                "question_id": question["question_id"],
                "reason": "Synthetic immutable key rejection.",
                "distinct_errors": True,
                "options": [
                    {
                        "index": index,
                        "relation": "undetermined" if index == 0 else "contradicted",
                        "invented_constraint": False,
                        "realistic_error": True,
                    }
                    for index in range(len(question["options"]))
                ],
            }],
        }
        return SimpleNamespace(
            value=parser(json.dumps(payload, ensure_ascii=False)),
            attempt_count=1,
        )


@pytest.mark.asyncio
async def test_correct_key_entailment_rejection_does_not_spend_model_repair() -> None:
    value = "Если документ поврежден, сотрудник должен остановить операцию."
    fact = SourceFact(
        "synthetic-key-rule",
        "Проверка документа",
        "правило",
        value,
        "doc_id=synthetic-policy;source_revision=synthetic-v1;section=rules;part=2",
    )
    lesson = LessonDraft(
        "synthetic-key-rule-lesson",
        "Операционные правила",
        "Проверка документа",
        "Действовать при повреждении документа",
        value,
        (fact.fact_id,),
        (),
        1,
    )
    client = _ImmutableKeyConstraintRejectingClient()

    result = await generate_block_assessment(
        [lesson],
        {fact.fact_id: fact},
        client,
    )

    assert client.tasks == [
        "assessment_generate",
        "assessment_review",
        "assessment_constraints",
    ]
    assert result.questions == ()
    assert result.audit["attempt_counts"]["model_repair"] == 0
    outcome = next(
        row for row in result.audit["axis_outcomes"]
        if row["primary_fact_id"] == fact.fact_id
    )
    assert outcome["reason"] == (
        "constraint_option_0:expected_entailed_got_undetermined;"
        "server_immutable_defect"
    )
