"""Behavior at the owner-approved lesson -> assessment -> checkpoint interface."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.ai.lesson_cycle import LearningTarget, LessonPacket, SourceExcerpt, run_lesson_cycles

RULE = "Обращение рассматривается не более 15 рабочих дней."


@pytest.mark.asyncio
async def test_fire_stop_all_except_and_stop_only_non_fire_are_not_exclusive_answers():
    source = "Прекратить все работы в здании, кроме работ, связанных с мероприятиями по ликвидации пожара."
    p = LessonPacket("qa", "fire", "Пожар", source, (SourceExcerpt("source-1", source),),
                     (LearningTarget("term", "Полный состав прекращаемых работ и исключение"),), "test")
    author = {"questions": [{"id": "q1", "target_ids": ["term"],
              "text": "Какие работы следует прекратить в здании и какое предусмотрено исключение?",
              "options": [source, "Прекратить только работы, не связанные с ликвидацией пожара, а работы по ликвидации продолжить"]}]}
    review = reviewed()
    review["reviews"][0].update(lesson_quote=source, explanation="Работы по ликвидации пожара исключены.")
    review["reviews"][0]["options"] = [{"index": i, "relation": "supported" if i == 0 else "contradicted",
                                         "source_id": "source-1", "quote": source} for i in range(2)]
    audit = audited()
    audit["audits"][0]["target_proofs"] = [{"target_id": "term", "question_quote": source,
                                            "source_id": "source-1", "quote": source}]
    result = (await run_lesson_cycles([p], client=Model([author, review, audit] * 2, []), store=Store([])))[0]
    assert not result.questions
    assert result.status == "review_required"


def packet(lesson_id="lesson-1"):
    return LessonPacket(
        tenant_id="qa",
        lesson_id=lesson_id,
        title="Обращения",
        content=RULE,
        sources=(SourceExcerpt("source-1", RULE),),
        targets=(LearningTarget("term", "Выбрать предельный срок рассмотрения обращения"),),
        policy_revision="test-policy",
    )


def authored():
    return {
        "questions": [
            {
                "id": "q1",
                "target_ids": ["term"],
                "text": "Какой предельный срок рассмотрения обращения?",
                "options": ["15 рабочих дней", "30 рабочих дней", "45 рабочих дней"],
            }
        ]
    }


def reviewed():
    return {
        "reviews": [
            {
                "question_id": "q1",
                "educational": True,
                "lesson_answerable": True,
                "unambiguous": True,
                "explanation_supported": True,
                "target_ids": ["term"],
                "explanation": "Предельный срок — 15 рабочих дней.",
                "lesson_quote": RULE,
                "options": [
                    {
                        "index": i,
                        "relation": "supported" if i == 0 else "contradicted",
                        "source_id": "source-1",
                        "quote": RULE,
                    }
                    for i in range(3)
                ],
            }
        ]
    }


def audited():
    return {
        "audits": [
            {
                "question_id": "q1",
                "admit": True,
                "modality_preserved": True,
                "conditions_complete": True,
                "no_other_valid_option": True,
                "reason": "The stated maximum is tested, not a stronger sufficient condition.",
                "target_proofs": [
                    {"target_id": "term", "question_quote": "15 рабочих дней", "source_id": "source-1", "quote": RULE}
                ],
            }
        ]
    }


class Model:
    """Script only the external provider; exercise the actual cycle and parsers."""

    def __init__(self, responses, events):
        self.responses = iter(responses)
        self.events = events

    async def ainvoke_validated(self, messages, parser, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.events.append((payload["task"], payload["lesson"]["id"]))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(value=parser(json.dumps(response, ensure_ascii=False)), attempt_count=1)


class Store:
    """External persistence adapter, retained across fresh invocations."""

    def __init__(self, events):
        self.rows = {}
        self.events = events

    async def load(self, tenant_id, identity):
        return self.rows.get((tenant_id, identity))

    async def save(self, tenant_id, identity, result):
        self.events.append(("save", result.lesson_id))
        self.rows[(tenant_id, identity)] = result


@pytest.mark.asyncio
async def test_complete_lesson_is_saved_before_next_is_generated_and_restart_reuses_it():
    events = []
    store = Store(events)
    packets = [packet(), packet("lesson-2")]
    model = Model([authored(), reviewed(), audited(), authored(), reviewed(), audited()], events)
    results = await run_lesson_cycles(packets, client=model, store=store)
    assert [r.status for r in results] == ["ready_for_methodologist"] * 2
    assert results[0].questions[0].correct_index == 0
    assert events == [
        ("lesson_assessment_author", "lesson-1"),
        ("lesson_assessment_review", "lesson-1"),
        ("lesson_assessment_counterexample", "lesson-1"),
        ("save", "lesson-1"),
        ("lesson_assessment_author", "lesson-2"),
        ("lesson_assessment_review", "lesson-2"),
        ("lesson_assessment_counterexample", "lesson-2"),
        ("save", "lesson-2"),
    ]
    before = list(events)
    restarted = await run_lesson_cycles(packets, client=Model([], events), store=store)
    assert restarted == results
    assert events == before


@pytest.mark.asyncio
async def test_restart_rejects_a_checkpoint_with_a_changed_answer_key():
    events = []
    store = Store(events)
    p = packet()
    saved = (await run_lesson_cycles([p], client=Model([authored(), reviewed(), audited()], events), store=store))[0]
    store.rows[(p.tenant_id, p.identity())] = replace(saved, questions=(replace(saved.questions[0], correct_index=1),))
    with pytest.raises(ValueError, match="checkpoint"):
        await run_lesson_cycles([p], client=Model([], events), store=store)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect",
    [
        "two_supported",
        "unknown",
        "invented_quote",
        "not_taught",
        "not_educational",
        "explanation",
        "missing_option",
        "wrong_target",
    ],
)
async def test_ambiguous_or_unsupported_questions_are_not_saved_as_ready(defect):
    response = reviewed()
    row = response["reviews"][0]
    if defect == "two_supported":
        row["options"][1]["relation"] = "supported"
    elif defect == "unknown":
        row["options"][1]["relation"] = "unknown"
    elif defect == "invented_quote":
        row["options"][1]["quote"] = "Несуществующее правило из другого документа"
    elif defect == "not_taught":
        row["lesson_quote"] = "Этому правилу данный урок не обучает"
    elif defect == "not_educational":
        row["educational"] = False
    elif defect == "explanation":
        row["explanation_supported"] = False
    elif defect == "missing_option":
        row["options"].pop()
    else:
        row["target_ids"] = ["unrelated"]
    events = []
    result = (
        await run_lesson_cycles(
            [packet()], client=Model([authored(), response, authored(), response], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions
    assert result.missing_target_ids == ("term",)
    assert result.logical_model_calls == 4


@pytest.mark.asyncio
async def test_failed_second_lesson_does_not_destroy_first_checkpoint():
    events = []
    store = Store(events)
    packets = [packet(), packet("lesson-2")]
    with pytest.raises(RuntimeError, match="network"):
        await run_lesson_cycles(
            packets, client=Model([authored(), reviewed(), audited(), RuntimeError("network")], events), store=store
        )
    assert len(store.rows) == 1
    resumed = await run_lesson_cycles(packets, client=Model([authored(), reviewed(), audited()], events), store=store)
    assert all(row.status == "ready_for_methodologist" for row in resumed)
    assert events.count(("lesson_assessment_author", "lesson-1")) == 1


@pytest.mark.asyncio
async def test_missing_target_cannot_be_masked_by_repeating_a_question():
    p = replace(packet(), targets=(*packet().targets, LearningTarget("extension", "Условия продления")))
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([authored(), reviewed(), audited(), authored(), reviewed()], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert result.missing_target_ids == ("extension",)
    assert len(result.questions) == 1


@pytest.mark.asyncio
async def test_blind_reviewer_derives_key_and_does_not_receive_author_key():
    events = []
    response = reviewed()
    response["reviews"][0]["options"][0]["relation"] = "contradicted"
    response["reviews"][0]["options"][2]["relation"] = "supported"
    candidate = authored()
    candidate["questions"][0]["options"] = ["45 рабочих дней", "30 рабочих дней", "15 рабочих дней"]
    result = (
        await run_lesson_cycles([packet()], client=Model([candidate, response, audited()], events), store=Store(events))
    )[0]
    assert result.questions[0].correct_index == 2


@pytest.mark.asyncio
async def test_changed_source_requires_new_generation_not_reuse():
    events = []
    store = Store(events)
    p = packet()
    await run_lesson_cycles([p], client=Model([authored(), reviewed(), audited()], events), store=store)
    changed = replace(p, policy_revision="different-model-policy")
    await run_lesson_cycles([changed], client=Model([authored(), reviewed(), audited()], events), store=store)
    assert len(store.rows) == 2


@pytest.mark.asyncio
async def test_checkpoint_error_prevents_starting_next_lesson():
    events = []

    class UnavailableStore(Store):
        async def save(self, *args):
            raise RuntimeError("database")

    with pytest.raises(RuntimeError, match="database"):
        await run_lesson_cycles(
            [packet(), packet("lesson-2")],
            client=Model([authored(), reviewed(), audited()], events),
            store=UnavailableStore(events),
        )
    assert ("lesson_assessment_author", "lesson-2") not in events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "correct,alternative",
    [
        (
            "Снижение дохода более тридцати процентов либо адресная социальная помощь",
            "Снижение дохода более пятидесяти процентов",
        ),
        ("Снижение дохода более чем на 30% либо адресная социальная помощь", "Снижение дохода более чем на 50%"),
    ],
)
async def test_a_review_cannot_mark_a_stronger_sufficient_income_condition_false(correct, alternative):
    rule = "Для указанной категории требуется снижение дохода более тридцати процентов либо адресная социальная помощь."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        text="При каком условии по доходу принимается решение о согласии?",
        options=[correct, alternative, "Рост дохода"],
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, response, candidate, response], events), store=Store(events)
        )
    )[0]
    # The reviewer falsely calls >50% contradicted, despite >50 implying >30.
    # The deterministic gate must reject this even when both LLM passes agree.
    assert result.status == "review_required"
    assert not result.questions
    assert all(task != "lesson_assessment_counterexample" for task, _ in events)


@pytest.mark.asyncio
async def test_a_separate_counterexample_audit_can_veto_a_blind_reviews_false_green():
    rule = "Ломбард принимает решение о согласии для указанных категорий. Право обратиться с заявлением имеют и другие заёмщики."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        text="Кто вправе обратиться?", options=["Только указанные категории", "Любой заёмщик", "Никто"]
    )
    response = reviewed()
    response["reviews"][0]["lesson_quote"] = rule
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    veto = {
        "audits": [
            {
                "question_id": "q1",
                "admit": False,
                "reason": "The stem confuses the lender's consent with the borrower's right to apply.",
            }
        ]
    }
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, response, veto, candidate, response, veto], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions
    assert result.logical_model_calls == 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "correct,alternative,accepted",
    [
        ("Более 30%", "Не более 30%", True),
        ("Не менее 30%", "Менее 30%", True),
        ("Не менее чем на 30%", "Не более 30%", False),
        (">30%", "≥50%", False),
        ("Более чем на 30%", "50%", False),
        ("Менее 30%", "Не более 20%", False),
    ],
)
async def test_percentage_boundary_intersections_do_not_depend_on_a_reviewer_verdict(correct, alternative, accepted):
    rule = f"При снижении дохода условие: {correct}."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        text="Какое снижение дохода соответствует условию?", options=[correct, alternative]
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule)
    response["reviews"][0]["options"] = response["reviews"][0]["options"][:2]
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote=correct, quote=rule)
    events = []
    replies = [candidate, response, audit] if accepted else [candidate, response, candidate, response]
    result = (await run_lesson_cycles([p], client=Model(replies, events), store=Store(events)))[0]
    assert result.status == ("ready_for_methodologist" if accepted else "review_required")
    assert len(result.questions) == int(accepted)
    if not accepted:
        assert all(task != "lesson_assessment_counterexample" for task, _ in events)


@pytest.mark.asyncio
async def test_semantic_approval_without_verbatim_target_proof_is_not_accepted():
    audit = audited()
    audit["audits"][0]["target_proofs"][0]["quote"] = "The source contains no such passage."
    events = []
    result = (
        await run_lesson_cycles(
            [packet()],
            client=Model([authored(), reviewed(), audit, authored(), reviewed(), audit], events),
            store=Store(events),
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions


@pytest.mark.asyncio
async def test_resume_rejects_removal_of_the_separate_semantic_proof():
    events = []
    store = Store(events)
    p = packet()
    saved = (await run_lesson_cycles([p], client=Model([authored(), reviewed(), audited()], events), store=store))[0]
    store.rows[(p.tenant_id, p.identity())] = replace(
        saved, questions=(replace(saved.questions[0], semantic_audit=None),)
    )
    with pytest.raises(ValueError, match="checkpoint"):
        await run_lesson_cycles([p], client=Model([], events), store=store)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule,stem,key,explanation",
    [
        (
            "При обнаружении пожара незамедлительно сообщить в противопожарную службу.",
            "Что сделать в первую очередь при пожаре?",
            "Сообщить в противопожарную службу",
            "Нужно незамедлительно сообщить о пожаре.",
        ),
        (
            "При необходимости отключить электроэнергию, выполнить другие мероприятия против развития пожара.",
            "Когда следует отключать электроэнергию?",
            "При необходимости",
            "Одновременно выполнить другие мероприятия против развития пожара.",
        ),
        (
            "В выходные дни требуется предварительное согласование по телефону.",
            "Микрокредит выдан в субботу. Как его согласовать?",
            "Предварительно согласовать по телефону",
            "В выходные требуется согласование по телефону.",
        ),
    ],
)
async def test_model_consensus_cannot_invent_temporal_applicability(rule, stem, key, explanation):
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(text=stem, options=[key, "Не выполнять указанное действие", "Ждать конца месяца"])
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation=explanation)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote=key, quote=rule)
    events = []
    # Consensus fixtures deliberately approve the exact captured failure pattern.
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, response, audit, candidate, response, audit], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions


@pytest.mark.asyncio
async def test_a_typed_exact_boundary_is_not_confused_with_overlapping_sufficient_conditions():
    rule = "При проверке дохода учитывают его снижение более чем на тридцать процентов."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        intent="threshold",
        numeric_rule={"operator": "gt", "unit": "percent"},
        text="Более какого процента должно составлять снижение дохода?",
        options=[30, 20, 40],
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation="Указанная в правиле граница — 30%.")
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote="30%", quote=rule)
    events = []
    store = Store(events)
    result = (await run_lesson_cycles([p], client=Model([candidate, response, audit], events), store=store))[0]
    assert result.status == "ready_for_methodologist"
    assert result.questions[0].options == ("30%", "20%", "40%")
    assert (await run_lesson_cycles([p], client=Model([], events), store=store))[0] == result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule,stem,key,explanation",
    [
        (
            "В первую очередь сообщить о пожаре по телефону.",
            "Что сделать в первую очередь?",
            "Сообщить о пожаре по телефону",
            "В первую очередь сообщить по телефону.",
        ),
        (
            "Одновременно с тушением организовать защиту ценностей.",
            "Когда организовать защиту ценностей?",
            "Одновременно с тушением",
            "Одновременно с тушением организовать защиту ценностей.",
        ),
        (
            "В выходные дни требуется предварительное согласование по телефону.",
            "Суббота — выходной день по графику. Как согласовать выдачу?",
            "Предварительно согласовать по телефону",
            "В выходные требуется согласование по телефону.",
        ),
    ],
)
async def test_explicit_temporal_predicates_and_scenario_conditions_remain_admissible(rule, stem, key, explanation):
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(text=stem, options=[key, "Не выполнять указанное действие", "Ждать конца месяца"])
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation=explanation)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote=key, quote=rule)
    events = []
    result = (await run_lesson_cycles([p], client=Model([candidate, response, audit], events), store=Store(events)))[0]
    assert result.status == "ready_for_methodologist"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stem,op,key_value",
    [
        ("При каком условии по доходу принимается решение?", "gt", 30),
        ("Более какого процента должно составлять снижение дохода?", "ge", 30),
        ("Более какого процента должно составлять снижение дохода?", "gt", 50),
    ],
)
async def test_threshold_intent_cannot_bypass_stem_operator_or_source_boundary(stem, op, key_value):
    rule = "При проверке дохода учитывают его снижение более чем на тридцать процентов."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        intent="threshold", numeric_rule={"operator": op, "unit": "percent"}, text=stem, options=[key_value, 20, 40]
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, response, candidate, response], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule,stem,options",
    [
        (
            "Отсрочка предусматривается по основному долгу и (или) вознаграждению.",
            "По каким платежам предусматривается отсрочка?",
            ["По основному долгу и (или) вознаграждению", "Только по основному долгу", "Только по вознаграждению"],
        ),
        (
            "Уведомление направляют в течение 15 календарных дней.",
            "В какой срок направляют уведомление?",
            ["В течение 15 календарных дней", "В течение 10 календарных дней", "В течение 30 календарных дней"],
        ),
        (
            "Решение о согласии принимается при назначении адресной социальной помощи.",
            "Вправе ли ломбард согласиться при назначении помощи?",
            [
                "Да, помощь является основанием",
                "Нет, помощь не является основанием",
                "Только при дополнительном условии",
            ],
        ),
    ],
)
async def test_allowed_branches_deadlines_and_modality_cannot_be_changed_by_consensus(rule, stem, options):
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(text=stem, options=options)
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation=rule)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote=options[0], quote=rule)
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, response, audit, candidate, response, audit], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule,stem,unit,op,values,rendered",
    [
        (
            "Направить уведомление в течение 15 (пятнадцати) календарных дней.",
            "Какой максимальный срок направления уведомления?",
            "calendar_days",
            "le",
            [15, 10, 30],
            "15 календарных дней",
        ),
        (
            "В правиле указан срок не менее трех месяцев.",
            "Какой минимальный срок назван в правиле?",
            "months",
            "ge",
            [3, 6, 12],
            "3 месяца",
        ),
    ],
)
async def test_typed_time_boundaries_remain_source_bound_and_resumable(rule, stem, unit, op, values, rendered):
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        intent="threshold", numeric_rule={"operator": op, "unit": unit}, text=stem, options=values
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation=rule)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote=rendered, quote=rule)
    events = []
    store = Store(events)
    result = (await run_lesson_cycles([p], client=Model([candidate, response, audit], events), store=store))[0]
    assert result.status == "ready_for_methodologist"
    assert result.questions[0].options[0] == rendered
    assert (await run_lesson_cycles([p], client=Model([], events), store=store))[0] == result


@pytest.mark.asyncio
async def test_two_exact_proofs_for_one_target_do_not_invalidate_it_or_count_as_two_targets():
    p = replace(packet(), targets=(*packet().targets, LearningTarget("extension", "Условия продления")))
    audit = audited()
    audit["audits"][0]["target_proofs"].append(
        {"target_id": "term", "question_quote": "предельный срок", "source_id": "source-1", "quote": RULE}
    )
    events = []
    result = (
        await run_lesson_cycles(
            [p],
            client=Model([authored(), reviewed(), audit, authored(), reviewed(), audit], events),
            store=Store(events),
        )
    )[0]
    assert len(result.questions) == 1
    assert result.questions[0].target_ids == ("term",)
    assert result.missing_target_ids == ("extension",)


@pytest.mark.asyncio
async def test_source_references_resolve_to_exact_owned_text_without_model_copying():
    response = reviewed()
    row = response["reviews"][0]
    del row["lesson_quote"]
    row["lesson_ref"] = "L1"
    for option in row["options"]:
        del option["quote"]
        del option["source_id"]
        option["source_ref"] = "S1P1"
    audit = {
        "audits": [
            {
                "question_id": "q1",
                "admit": True,
                "reason": "No other permitted outcome matches the maximum deadline.",
                "target_proofs": [{"target_id": "term", "source_ref": "S1P1", "question_part": "answer"}],
            }
        ]
    }
    events = []
    result = (
        await run_lesson_cycles([packet()], client=Model([authored(), response, audit], events), store=Store(events))
    )[0]
    assert result.status == "ready_for_methodologist"
    assert result.questions[0].lesson_quote == RULE
    assert result.questions[0].option_evidence[0]["quote"] == RULE


@pytest.mark.asyncio
async def test_an_ambiguous_amendment_duration_is_not_renamed_as_the_whole_loan_term():
    rule = "Ломбард принимает решение о согласии с изменениями в условия договора на срок не менее трех месяцев."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        intent="threshold",
        numeric_rule={"operator": "ge", "unit": "months"},
        text="Какой минимальный срок договора указан в правиле?",
        options=[3, 6, 12],
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation=rule)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote="3 месяца", quote=rule)
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, response, audit, candidate, response, audit], events), store=Store(events)
        )
    )[0]
    assert not result.questions


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["foreign_source_ref", "conflicting_quote", "explicit_veto"])
async def test_evidence_references_cannot_bypass_ownership_or_an_explicit_semantic_veto(defect):
    response = reviewed()
    audit = audited()
    if defect == "foreign_source_ref":
        response["reviews"][0]["options"][0]["source_ref"] = "S999P1"
    elif defect == "conflicting_quote":
        response["reviews"][0]["options"][0].update(
            source_ref="S1P1", quote="An unrelated rule, not the selected passage."
        )
    else:
        audit["audits"][0]["modality_preserved"] = False
    events = []

    # Repeat the external trace at repair, without changing the wrong proof.
    class InvalidProofModel(Model):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            task = json.loads(messages[-1]["content"])["task"]
            payload = (
                audit
                if task == "lesson_assessment_counterexample"
                else response
                if task == "lesson_assessment_review"
                else authored()
            )
            return SimpleNamespace(value=parser(json.dumps(payload, ensure_ascii=False)))

    result = (await run_lesson_cycles([packet()], client=InvalidProofModel([], events), store=Store(events)))[0]
    assert not result.questions
    assert result.status == "review_required"


@pytest.mark.asyncio
async def test_required_applicability_is_rendered_before_review_and_preserved_once_on_resume():
    context = "Пункт находится в том же населённом пункте, что и офис региональной директории."
    p = replace(packet(), targets=(LearningTarget("term", "Предельный срок", context=context),))
    events = []
    store = Store(events)
    result = (await run_lesson_cycles([p], client=Model([authored(), reviewed(), audited()], events), store=store))[0]
    assert result.status == "ready_for_methodologist"
    assert result.questions[0].text == "Условие: " + context + "\n" + authored()["questions"][0]["text"]
    resumed = (await run_lesson_cycles([p], client=Model([], events), store=store))[0]
    assert resumed == result


@pytest.mark.asyncio
async def test_typed_percent_unit_is_rendered_when_the_stem_omits_its_spelling():
    rule = "Изменение предусматривает уменьшение ежемесячного платежа не менее чем на пятьдесят процентов."
    p = replace(packet(), content=rule, sources=(SourceExcerpt("source-1", rule),))
    candidate = authored()
    candidate["questions"][0].update(
        intent="threshold",
        numeric_rule={"operator": "ge", "unit": "percent"},
        text="Какое минимальное уменьшение ежемесячного платежа требуется?",
        options=[50, 30, 40],
    )
    response = reviewed()
    response["reviews"][0].update(lesson_quote=rule, explanation=rule)
    for option in response["reviews"][0]["options"]:
        option["quote"] = rule
    audit = audited()
    audit["audits"][0]["target_proofs"][0].update(question_quote="50%", quote=rule)
    events = []
    store = Store(events)
    result = (await run_lesson_cycles([p], client=Model([candidate, response, audit], events), store=store))[0]
    assert result.status == "ready_for_methodologist"
    assert "в процентах" in result.questions[0].text
    assert (await run_lesson_cycles([p], client=Model([], events), store=store))[0] == result


@pytest.mark.asyncio
async def test_full_set_objective_renders_its_answer_contract_without_relying_on_author_wording():
    p = replace(packet(), targets=(LearningTarget("term", "Полный перечень", question_format="full_set"),))
    events = []
    store = Store(events)
    result = (await run_lesson_cycles([p], client=Model([authored(), reviewed(), audited()], events), store=store))[0]
    assert result.status == "ready_for_methodologist"
    assert result.questions[0].text.startswith("Укажите полный перечень допустимых вариантов.\n")
    assert (await run_lesson_cycles([p], client=Model([], events), store=store))[0] == result


@pytest.mark.asyncio
async def test_an_objective_is_not_covered_by_an_answer_missing_its_required_component():
    p = replace(
        packet(),
        targets=(LearningTarget("term", "Предельный срок", answer_requirements=(("15", "пятнадцать"), ("рабоч",))),),
    )
    candidate = authored()
    candidate["questions"][0]["options"][0] = "15 дней"
    audit = audited()
    audit["audits"][0]["target_proofs"][0]["question_quote"] = "15 дней"
    events = []
    result = (
        await run_lesson_cycles(
            [p], client=Model([candidate, reviewed(), audit, candidate, reviewed(), audit], events), store=Store(events)
        )
    )[0]
    assert result.status == "review_required"
    assert not result.questions


@pytest.mark.asyncio
async def test_context_full_set_and_component_contract_compose_once_on_resume():
    context = "Пункт находится в том же населённом пункте, что и региональный офис."
    p = replace(
        packet(),
        targets=(
            LearningTarget(
                "term",
                "Предельный срок",
                context=context,
                question_format="full_set",
                answer_requirements=(("15", "пятнадцать"), ("рабоч",)),
            ),
        ),
    )
    candidate = authored()
    candidate["questions"][0]["text"] += " Укажите полный перечень допустимых вариантов."
    events = []
    store = Store(events)
    result = (await run_lesson_cycles([p], client=Model([candidate, reviewed(), audited()], events), store=store))[0]
    assert result.status == "ready_for_methodologist"
    assert result.questions[0].text.count(context) == 1
    assert result.questions[0].text.count("Укажите полный перечень допустимых вариантов.") == 1
    assert (await run_lesson_cycles([p], client=Model([], events), store=store))[0] == result
