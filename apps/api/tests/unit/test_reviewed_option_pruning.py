from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import app.modules.ai.evidence_engine.semantic_assessment as assessment
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import (
    _parse_axis_questions,
    _parse_constraint_reviews,
    _parse_reviews,
    generate_block_assessment,
)
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason

KEY = "Персональные данные нельзя передавать в неразрешённые каналы."
RULE = KEY + " Исключений для срочных обращений нет."
VALID_WRONG = (
    "Передать персональные данные через личный мессенджер при срочном обращении.",
    "Передать персональные данные через неразрешённую почту, если ответ нужен быстро.",
)
WEAK_WRONG = "Заявление рассматривается в течение 30 дней."
NEW_WRONG = "Направить персональные данные на личный облачный диск, если обращение срочное."


def question(options: tuple[str, ...] | None = None, *, kind: str = "single_choice") -> QuestionDraft:
    choices = options or (KEY, *VALID_WRONG)
    return QuestionDraft(
        question_id="q-fixed", lesson_id="lesson-fixed", kind=kind,
        prompt="Какое правило действует при срочном обращении?",
        options=choices, correct_answer=KEY,
        explanation="Срочность не разрешает использовать неразрешённый канал.",
        fact_id="f-fixed", evidence_fact_ids=("f-fixed",), source_quote=RULE,
    )


def semantic_review(q: QuestionDraft, *, weak_indices: set[int] = frozenset(), key_index: int = 0,
                    core: bool = True) -> str:
    return json.dumps({"reviews": [{
        "question_id": q.question_id,
        "question_supported": core,
        "educational": core,
        "explanation_supported": core,
        "options_distinct": core,
        "options": [{
            "index": i,
            "answers_question": i not in weak_indices,
            "correct": i == key_index,
            "plausible_error": i != key_index and i not in weak_indices,
            "contradicted_by_source": i != key_index and i not in weak_indices,
            "same_practical_task": i not in weak_indices,
        } for i in range(len(q.options))],
    }]}, ensure_ascii=False)


def constraints_review(q: QuestionDraft, *, duplicate: bool = False,
                       unrealistic: set[int] = frozenset(), key_index: int = 0,
                       wrong_relation: dict[int, str] | None = None,
                       invented: set[int] = frozenset()) -> str:
    wrong_relation = wrong_relation or {}
    return json.dumps({
        "rules": [{"fact_id": "f-fixed", "quote": RULE, "kind": "forbidden"}],
        "reviews": [{
            "question_id": q.question_id,
            "reason": "Both wrong choices express the same misconception." if duplicate else "Independent errors.",
            "distinct_errors": not duplicate,
            "options": [{
                "index": i,
                "relation": "entailed" if i == key_index else wrong_relation.get(i, "contradicted"),
                "invented_constraint": i in invented,
                "realistic_error": i not in unrealistic,
            } for i in range(len(q.options))],
        }],
    }, ensure_ascii=False)


def fact_and_lesson():
    fact = SourceFact("f-fixed", "Защита данных", "правило", RULE,
                      "doc_id=d1;section=privacy;part=1")
    lesson = LessonDraft("lesson-fixed", "Работа", "Защита данных",
                         "Применять правила безопасной передачи", "",
                         (fact.fact_id,), (), 1)
    return lesson, {fact.fact_id: fact}


def test_semantic_review_prunes_one_weak_extra_but_keeps_authored_three_to_four_policy():
    authored = question((KEY, WEAK_WRONG, *VALID_WRONG))
    parsed = _parse_reviews(semantic_review(authored, weak_indices={1}), [authored])

    assert len(authored.options) == 4  # authoring contract is unchanged
    assert parsed[authored.question_id] is True
    assert parsed.option_removals[authored.question_id] == (1,)
    pruned = tuple(option for i, option in enumerate(authored.options)
                   if i not in parsed.option_removals[authored.question_id])
    assert pruned == (KEY, *VALID_WRONG)


def test_author_parser_keeps_three_to_four_choice_contract_before_any_review_pruning():
    lesson, facts = fact_and_lesson()
    axis = derive_assessment_axes(lesson, list(facts.values()), block_id="block")[0]
    one_distractor = {"questions": [{"axis_id": axis.axis_id, "prompt": axis.required_prompt,
                                    "distractors": [VALID_WRONG[0]]}]}
    three_distractors = {"questions": [{"axis_id": axis.axis_id, "prompt": axis.required_prompt,
                                       "distractors": [WEAK_WRONG, *VALID_WRONG]}]}

    assert _parse_axis_questions(json.dumps(one_distractor), axes=(axis,), maximum=1) == []
    authored = _parse_axis_questions(json.dumps(three_distractors), axes=(axis,), maximum=1)
    assert len(authored) == 1
    assert len(authored[0].options) == 4


def _option_evidence(result, question_id: str):
    evidence = getattr(result, "option_evidence", None)
    assert evidence is not None, "review parser must retain option-level evidence even on ordinary rejection"
    assert question_id in evidence
    return evidence[question_id]


def test_duplicate_only_constraint_rejection_retains_evidence_for_last_resort_helper():
    original = question((KEY, WEAK_WRONG, *VALID_WRONG))
    semantic = _parse_reviews(semantic_review(original, weak_indices={1}), [original])
    assert semantic[original.question_id] is True
    sem_ev = _option_evidence(semantic, original.question_id)
    assert sem_ev.question_valid is True
    assert sem_ev.valid_wrong_indices == (2, 3)

    sem_options = tuple(option for i, option in enumerate(original.options)
                        if i not in semantic.option_removals[original.question_id])
    sem_question = replace(original, options=sem_options, semantic_reviewed=True)
    constraint = _parse_constraint_reviews(
        constraints_review(sem_question, duplicate=True,
                           wrong_relation={2: "undetermined"}), [sem_question],
        [SourceFact("f-fixed", "Защита данных", "правило", RULE,
                    "doc_id=d1;section=privacy;part=1")],
    )
    # Normal acceptance stays strict: single choice still needs two distinct wrong options.
    assert constraint[original.question_id] is False
    con_ev = _option_evidence(constraint, original.question_id)
    assert con_ev.question_valid is True
    assert con_ev.valid_wrong_indices == (1,)

    helper = getattr(assessment, "_post_review_pruned_candidate", None)
    assert callable(helper), "last-resort option pruning helper is not implemented"
    salvaged = helper(
        sem_ev, con_ev,
        facts=[SourceFact("f-fixed", "Защита данных", "правило", RULE,
                          "doc_id=d1;section=privacy;part=1")],
        accepted=[],
    )
    assert salvaged is not None
    assert salvaged.question_id == original.question_id
    assert salvaged.kind == "single_choice"
    assert salvaged.correct_answer == original.correct_answer
    assert len(salvaged.options) == 2
    assert salvaged.correct_answer in salvaged.options
    assert salvaged.options == (KEY, VALID_WRONG[0])
    assert all(option in original.options for option in salvaged.options)


def test_successful_normal_repair_wins_over_post_review_pruning():
    original = question((KEY, WEAK_WRONG, *VALID_WRONG))
    semantic = _parse_reviews(semantic_review(original, weak_indices={1}), [original])
    sem_options = tuple(option for i, option in enumerate(original.options)
                        if i not in semantic.option_removals[original.question_id])
    sem_question = replace(original, options=sem_options, semantic_reviewed=True)
    constraint = _parse_constraint_reviews(
        constraints_review(sem_question, duplicate=True), [sem_question],
        [SourceFact("f-fixed", "Защита данных", "правило", RULE,
                    "doc_id=d1;section=privacy;part=1")],
    )
    helper = getattr(assessment, "_post_review_pruned_candidate", None)
    assert callable(helper), "last-resort option pruning helper is not implemented"
    normal_repair = replace(original, options=(KEY, VALID_WRONG[1], VALID_WRONG[0]))
    salvaged = helper(
        _option_evidence(semantic, original.question_id),
        _option_evidence(constraint, original.question_id),
        facts=[SourceFact("f-fixed", "Защита данных", "правило", RULE,
                          "doc_id=d1;section=privacy;part=1")],
        accepted=[normal_repair],
    )
    assert salvaged is None


@pytest.mark.parametrize("field", ["prompt", "correct_answer", "fact_id"])
def test_last_resort_rejects_constraint_evidence_bound_to_changed_immutable_field(field: str):
    original = question((KEY, WEAK_WRONG, *VALID_WRONG))
    semantic = _parse_reviews(semantic_review(original, weak_indices={1}), [original])
    sem_options = tuple(option for i, option in enumerate(original.options)
                        if i not in semantic.option_removals[original.question_id])
    reviewed = replace(original, options=sem_options, semantic_reviewed=True)
    source = SourceFact("f-fixed", "Защита данных", "правило", RULE,
                        "doc_id=d1;section=privacy;part=1")
    constraints = _parse_constraint_reviews(
        constraints_review(reviewed, duplicate=True), [reviewed], [source],
    )
    evidence = _option_evidence(constraints, original.question_id)
    changed = {
        "prompt": "Different question with broader scope?",
        "correct_answer": "An invented answer not in the source.",
        "fact_id": "different-source-fact",
    }[field]
    bad_evidence = replace(evidence, question=replace(evidence.question, **{field: changed}))
    helper = getattr(assessment, "_post_review_pruned_candidate", None)
    assert callable(helper)
    assert helper(_option_evidence(semantic, original.question_id), bad_evidence,
                  facts=[source], accepted=[]) is None


def test_last_resort_does_not_keep_locally_contained_key_distractor():
    contained = KEY + " Но при срочном обращении можно использовать иной канал."
    original = question((KEY, WEAK_WRONG, contained, VALID_WRONG[1]))
    semantic = _parse_reviews(semantic_review(original, weak_indices={1, 3}), [original])
    sem_options = tuple(option for i, option in enumerate(original.options)
                        if i not in semantic.option_removals[original.question_id])
    reviewed = replace(original, options=sem_options, semantic_reviewed=True)
    constraint = _parse_constraint_reviews(
        constraints_review(reviewed, duplicate=True,
                           wrong_relation={2: "undetermined"}),
        [reviewed],
        [SourceFact("f-fixed", "Защита данных", "правило", RULE,
                    "doc_id=d1;section=privacy;part=1")],
    )
    helper = getattr(assessment, "_post_review_pruned_candidate", None)
    assert callable(helper)
    result = helper(
        _option_evidence(semantic, original.question_id),
        _option_evidence(constraint, original.question_id),
        facts=[SourceFact("f-fixed", "Защита данных", "правило", RULE,
                          "doc_id=d1;section=privacy;part=1")], accepted=[],
    )
    assert result is None


@pytest.mark.parametrize("bad_case", [
    "semantic_core", "wrong_key", "semantic_wrong_task", "constraint_key",
    "invented_key", "undetermined", "unrealistic", "optional_exclusion", "missing_evidence",
])
def test_last_resort_helper_rejects_any_invalid_or_incomplete_review_evidence(bad_case: str):
    q = question((KEY, WEAK_WRONG, *VALID_WRONG))
    if bad_case == "semantic_core":
        sem_raw = semantic_review(q, core=False)
    elif bad_case == "wrong_key":
        sem_raw = semantic_review(q, key_index=1)
    elif bad_case == "semantic_wrong_task":
        sem_raw = semantic_review(q, weak_indices={1, 2, 3})
    else:
        sem_raw = semantic_review(q, weak_indices={1})
    semantic = _parse_reviews(sem_raw, [q])
    sem_ev = _option_evidence(semantic, q.question_id)
    sem_options = tuple(option for i, option in enumerate(q.options)
                        if i not in semantic.option_removals[q.question_id])
    reviewed = replace(q, options=sem_options, semantic_reviewed=True)

    source = SourceFact("f-fixed", "Защита данных", "правило", RULE,
                        "doc_id=d1;section=privacy;part=1")
    if bad_case == "optional_exclusion":
        source = SourceFact("f-fixed", "Защита данных", "правило",
            RULE + " Дополнительный журнал не требуется.", "doc_id=d1;section=privacy;part=1")
        optional_key = "Персональные данные нельзя передавать в неразрешённые каналы без дополнительного журнала."
        reviewed = replace(reviewed, prompt="Что обязательно сделать без дополнительного журнала?",
                           options=(optional_key, *reviewed.options[1:]), correct_answer=optional_key)
        sem_ev = _option_evidence(_parse_reviews(semantic_review(reviewed), [reviewed]), reviewed.question_id)

    if bad_case == "constraint_key":
        con_raw = constraints_review(reviewed, key_index=1)
    elif bad_case == "invented_key":
        con_raw = constraints_review(reviewed, invented={0})
    elif bad_case == "undetermined":
        con_raw = constraints_review(reviewed, wrong_relation={i: "undetermined"
            for i in range(1, len(reviewed.options))})
    elif bad_case == "unrealistic":
        con_raw = constraints_review(reviewed, unrealistic={1, 2})
    else:
        con_raw = constraints_review(reviewed)
    constraint = _parse_constraint_reviews(con_raw, [reviewed], [source])
    con_ev = _option_evidence(constraint, reviewed.question_id)
    helper = getattr(assessment, "_post_review_pruned_candidate", None)
    assert callable(helper), "last-resort option pruning helper is not implemented"
    result = helper(
        None if bad_case == "missing_evidence" else sem_ev,
        con_ev,
        facts=[source], accepted=[],
    )
    assert result is None


@pytest.mark.parametrize("bad_case", [
    "later_core_invalid", "later_explanation_invalid", "later_semantic_key_invalid",
    "later_semantic_one_wrong", "later_key_invalid", "later_invented_key",
    "later_constraint_unavailable", "later_constraint_malformed",
])
@pytest.mark.asyncio
async def test_pipeline_binds_last_resort_to_latest_valid_reviews(bad_case: str):
    lesson, facts = fact_and_lesson()
    calls: list[dict] = []
    actual_key = derive_assessment_axes(lesson, list(facts.values()), block_id="stale-pair")[0].correct_value

    class ScriptedClient:
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            calls.append(request)
            task = request["task"]
            if task == "assessment_generate":
                axis = request["axes"][0]
                raw = {"questions": [{"axis_id": axis["axis_id"],
                    "prompt": "Какое правило действует при срочном обращении?",
                    "distractors": [WEAK_WRONG, *VALID_WRONG]}]}
            elif task == "assessment_repair":
                axis = request["axes"][0]
                raw = {"questions": [{"axis_id": axis["axis_id"],
                    "prompt": request["rejected"][0]["prompt"],
                    "distractors": [VALID_WRONG[0], NEW_WRONG]}]}
            elif task == "assessment_review":
                item = request["questions"][0]
                key_index = item["options"].index(actual_key)
                weak_index = item["options"].index(WEAK_WRONG) if WEAK_WRONG in item["options"] else -1
                latest = "assessment_repair" in [call["task"] for call in calls[:-1]]
                wrong_indices = [i for i in range(len(item["options"])) if i != key_index]
                classified_key = (wrong_indices[0] if latest and bad_case == "later_semantic_key_invalid"
                                  else key_index)
                raw = {"reviews": [{
                    "question_id": item["question_id"],
                    "question_supported": not (latest and bad_case == "later_core_invalid"),
                    "educational": True,
                    "explanation_supported": not (latest and bad_case == "later_explanation_invalid"),
                    "options_distinct": True,
                    "options": [{"index": i, "answers_question": i != weak_index and not (
                            latest and bad_case == "later_semantic_one_wrong" and i == wrong_indices[-1]),
                        "correct": i == classified_key,
                        "plausible_error": i != key_index and i != weak_index and not (
                            latest and bad_case == "later_semantic_one_wrong" and i == wrong_indices[-1]),
                        "contradicted_by_source": i != key_index and i != weak_index and not (
                            latest and bad_case == "later_semantic_one_wrong" and i == wrong_indices[-1]),
                        "same_practical_task": i != weak_index}
                        for i in range(len(item["options"]))],
                }]}
            elif task == "assessment_constraints":
                item = request["questions"][0]
                qid = item["question_id"]
                key_index = item["options"].index(actual_key)
                latest = "assessment_repair" in [call["task"] for call in calls[:-1]]
                if latest and bad_case == "later_constraint_unavailable":
                    raise AllProvidersFailedError(
                        "fixture", [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE],
                    )
                if latest and bad_case == "later_constraint_malformed":
                    try:
                        parser(json.dumps({"rules": [], "reviews": []}))
                    except (ValueError, KeyError, TypeError) as exc:
                        raise AllProvidersFailedError(
                            "fixture", [ValidatedCallFailureReason.VALIDATION_BLOCKED],
                        ) from exc
                if latest and bad_case == "later_key_invalid":
                    option_rows = [{"index": i, "relation": "contradicted" if i == key_index else
                                    ("entailed" if i == next(j for j in range(len(item["options"])) if j != key_index)
                                     else "contradicted"),
                                    "invented_constraint": False, "realistic_error": True}
                                   for i in range(len(item["options"]))]
                    distinct = True
                else:
                    option_rows = [{"index": i, "relation": "entailed" if i == key_index else "contradicted",
                                    "invented_constraint": latest and bad_case == "later_invented_key"
                                        and i == key_index, "realistic_error": True}
                                   for i in range(len(item["options"]))]
                    distinct = latest
                raw = {"rules": [{"fact_id": "f-fixed", "quote": RULE, "kind": "forbidden"}],
                    "reviews": [{"question_id": qid, "reason": "same misconception",
                        "distinct_errors": distinct, "options": option_rows}]}
            else:
                pytest.fail(f"unexpected provider stage {task}")
            result = parser(json.dumps(raw, ensure_ascii=False))
            return SimpleNamespace(value=result, attempt_count=1, failure_reasons=(), model_id="fixture")

    result = await generate_block_assessment([lesson], facts, ScriptedClient())

    if bad_case == "later_semantic_one_wrong":
        # This is legitimately salvageable only AFTER the second role has
        # independently checked the latest, changed candidate.
        assert len(result.questions) == 1 and len(result.questions[0].options) == 2
        assert set(result.questions[0].options) == {actual_key, VALID_WRONG[0]}
        event = result.audit["post_review_pruned"][0]
        latest = [call for call in calls if call["task"] == "assessment_review"][-1]
        assert len(latest["questions"][0]["options"]) == 3
        assert event["removed_original_indices"] == [2]
    else:
        assert result.questions == ()
    expected_calls = [
        "assessment_generate", "assessment_review", "assessment_constraints",
        "assessment_repair", "assessment_review",
    ]
    if bad_case not in {"later_core_invalid", "later_explanation_invalid", "later_semantic_key_invalid"}:
        expected_calls.append("assessment_constraints")
    if bad_case == "later_constraint_malformed":
        expected_calls.append("assessment_constraints")  # Existing bounded contract retry.
    assert [call["task"] for call in calls] == expected_calls


def test_single_choice_two_options_still_requires_realistic_error():
    reviewed = question((KEY, VALID_WRONG[0]))
    parsed = _parse_constraint_reviews(
        constraints_review(reviewed, unrealistic={1}), [reviewed],
        [SourceFact("f-fixed", "Защита данных", "правило", RULE, "doc_id=d1;section=privacy;part=1")],
    )

    assert parsed[reviewed.question_id] is False
    assert parsed.option_removals[reviewed.question_id] == ()


@pytest.mark.parametrize("bad_review", [
    "wrong_key", "unknown_key", "invented_key", "optional_exclusion", "all_undetermined",
    "all_unrealistic", "unavailable", "invalid",
])
def test_pruning_never_repairs_immutable_or_unproven_failures(bad_review: str):
    q = question((KEY, WEAK_WRONG, *VALID_WRONG))
    if bad_review == "wrong_key":
        raw = semantic_review(q, key_index=1)
        parsed = _parse_reviews(raw, [q])
        assert parsed[q.question_id] is False
        return
    if bad_review == "unknown_key":
        payload = json.loads(semantic_review(q))
        payload["reviews"][0]["options"][0]["correct"] = False
        payload["reviews"][0]["options"][1]["correct"] = True
        parsed = _parse_reviews(json.dumps(payload), [q])
        assert parsed[q.question_id] is False
        return
    if bad_review == "unavailable":
        with pytest.raises(ValueError, match="assessment_review_count"):
            _parse_reviews('{"reviews":[]}', [q])
        return
    if bad_review == "invalid":
        payload = json.loads(semantic_review(q))
        payload["reviews"][0]["options"][0]["answers_question"] = "yes"
        with pytest.raises(ValueError, match="assessment_review_option_contract"):
            _parse_reviews(json.dumps(payload), [q])
        return

    source = SourceFact("f-fixed", "Защита данных", "правило", RULE,
                        "doc_id=d1;section=privacy;part=1")
    kwargs = {}
    options = q.options
    if bad_review == "invented_key":
        payload = json.loads(constraints_review(q))
        payload["reviews"][0]["options"][0]["invented_constraint"] = True
        raw = json.dumps(payload)
    elif bad_review == "optional_exclusion":
        optional_source = SourceFact("f-fixed", "Защита данных", "правило",
            RULE + " Дополнительный журнал не требуется.", "doc_id=d1;section=privacy;part=1")
        optional_key = "Использовать только разрешённый канал без дополнительного журнала."
        q = QuestionDraft(
            question_id=q.question_id, lesson_id=q.lesson_id, kind=q.kind,
            prompt="Что обязательно сделать без дополнительного журнала?",
            options=(optional_key, *VALID_WRONG), correct_answer=optional_key,
            explanation=q.explanation, fact_id=q.fact_id,
            evidence_fact_ids=q.evidence_fact_ids, source_quote=q.source_quote,
        )
        parsed = _parse_constraint_reviews(constraints_review(q), [q], [optional_source])
        assert parsed[q.question_id] is False
        return
    elif bad_review == "all_undetermined":
        kwargs["wrong_relation"] = {i: "undetermined" for i in range(1, len(options))}
        raw = constraints_review(q, **kwargs)
    elif bad_review == "all_unrealistic":
        kwargs["unrealistic"] = set(range(1, len(options)))
        raw = constraints_review(q, **kwargs)
    else:
        raw = constraints_review(q)
    parsed = _parse_constraint_reviews(raw, [q], [source])
    assert parsed[q.question_id] is False
    assert parsed.option_removals[q.question_id] == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_succeeds", [False, True])
async def test_scripted_author_review_repair_then_last_resort_pruning(repair_succeeds: bool):
    lesson, facts = fact_and_lesson()
    calls: list[dict] = []
    actual_key = derive_assessment_axes(lesson, list(facts.values()), block_id="test")[0].correct_value

    class ScriptedClient:
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            calls.append(request)
            task = request["task"]
            if task == "assessment_generate":
                assert len(request["axes"]) == 1
                axis = request["axes"][0]
                raw = {"questions": [{"axis_id": axis["axis_id"],
                    "prompt": "Какое правило действует при срочном обращении?",
                    "distractors": [WEAK_WRONG, *VALID_WRONG]}]}
            elif task == "assessment_review":
                item = request["questions"][0]
                assert len(item["options"]) in {3, 4}
                key_index = item["options"].index(actual_key)
                weak_index = item["options"].index(WEAK_WRONG) if WEAK_WRONG in item["options"] else -1
                raw = {"reviews": [{
                    "question_id": item["question_id"],
                    "question_supported": True, "educational": True,
                    "explanation_supported": True, "options_distinct": True,
                    "options": [{"index": i, "answers_question": i != weak_index,
                        "correct": i == key_index, "plausible_error": i != key_index and i != weak_index,
                        "contradicted_by_source": i != key_index and i != weak_index,
                        "same_practical_task": i != weak_index}
                        for i in range(len(item["options"]))],
                }]}
            elif task == "assessment_constraints":
                item = request["questions"][0]
                assert len(item["options"]) == 3
                qid = item["question_id"]
                key_index = item["options"].index(actual_key)
                raw = {"rules": [{"fact_id": "f-fixed", "quote": RULE, "kind": "forbidden"}],
                    "reviews": [{"question_id": qid, "reason": "same misconception",
                        "distinct_errors": repair_succeeds and len(calls) > 3,
                        "options": [{"index": i, "relation": "entailed" if i == key_index else "contradicted",
                            "invented_constraint": False, "realistic_error": True}
                            for i in range(len(item["options"]))]}]}
            elif task == "assessment_repair":
                if repair_succeeds:
                    axis = request["axes"][0]
                    raw = {"questions": [{"axis_id": axis["axis_id"],
                        "prompt": request["rejected"][0]["prompt"],
                        "distractors": list(VALID_WRONG)}]}
                else:
                    raw = {"questions": []}
            else:
                pytest.fail(f"unexpected provider stage {task}")
            result = parser(json.dumps(raw, ensure_ascii=False))
            return SimpleNamespace(value=result, attempt_count=1, failure_reasons=(), model_id="fixture")

    result = await generate_block_assessment([lesson], facts, ScriptedClient())

    assert len(result.questions) == 1
    final = result.questions[0]
    authored_question_id = next(call for call in calls if call["task"] == "assessment_review")["questions"][0]["question_id"]
    assert final.question_id == authored_question_id
    assert final.kind == "single_choice"
    assert final.correct_answer == actual_key
    assert final.fact_id == "f-fixed" and final.evidence_fact_ids == ("f-fixed",)
    assert final.source_quote in RULE
    assert WEAK_WRONG not in final.options
    assert all(option in calls[1]["questions"][0]["options"] for option in final.options)
    if repair_succeeds:
        assert len(final.options) == 3
        assert [call["task"] for call in calls] == [
            "assessment_generate", "assessment_review", "assessment_constraints",
            "assessment_repair", "assessment_review", "assessment_constraints",
        ]
        assert not result.audit.get("post_review_pruned")
    else:
        assert len(final.options) == 2
        assert [call["task"] for call in calls] == [
            "assessment_generate", "assessment_review", "assessment_constraints", "assessment_repair",
        ]
        pruning = result.audit.get("post_review_pruned")
        assert pruning, "salvage audit must record the original option indices"
        assert any(record.get("question_id") == final.question_id
                   and record.get("original_option_indices") for record in pruning)


def test_true_false_keeps_its_existing_one_wrong_option_contract():
    q = question((KEY, VALID_WRONG[0]), kind="true_false")
    semantic = _parse_reviews(semantic_review(q), [q])
    source = SourceFact("f-fixed", "Защита данных", "правило", RULE,
                        "doc_id=d1;section=privacy;part=1")
    constraint = _parse_constraint_reviews(
        constraints_review(q, duplicate=True, unrealistic={1}), [q], [source],
    )
    assert semantic[q.question_id] is True
    assert constraint[q.question_id] is True
