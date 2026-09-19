"""Practical distractor quality is independent from being factually false."""
import json

import pytest

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _parse_questions, _parse_reviews


def candidate():
    fact = SourceFact("f1", "Storage", "scope", "The range contains cabinets, not beds.", "doc_id=d;section=s")
    return _parse_questions(json.dumps({"questions": [{
        "prompt": "What should be offered to a buyer who needs a bed?",
        "options": ["A bed from a different range.", "A nonexistent bed from this range.",
                    "A cabinet to sleep in instead of a bed."],
        "correct_index": 0, "explanation": "The range does not include beds.",
        "evidence": [{"fact_id": "f1", "quote": fact.value}],
    }]}), lesson_id="l", facts=[fact], maximum=1, block_id="b")[0]


def verdict(q):
    return {"reviews": [{"question_id": q.question_id,
        "question_supported": True, "educational": True, "explanation_supported": True,
        "options_distinct": True,
        "options": [{"index": i, "answers_question": True, "correct": i == 0,
            "plausible_error": i != 0, "contradicted_by_source": i != 0,
            "same_practical_task": True} for i in range(len(q.options))]}]}


def test_false_but_functionally_absurd_alternative_is_not_accepted():
    q = candidate()
    raw = verdict(q)
    raw["reviews"][0]["options"][2]["same_practical_task"] = False
    result = _parse_reviews(json.dumps(raw), [q])
    assert result[q.question_id] is False
    assert "option_2:wrong_practical_task" in result.reasons[q.question_id]


def test_same_action_with_different_excuses_is_not_distinct_knowledge():
    q = candidate()
    raw = verdict(q)
    raw["reviews"][0]["options_distinct"] = False
    result = _parse_reviews(json.dumps(raw), [q])
    assert result[q.question_id] is False
    assert "options_distinct" in result.reasons[q.question_id]


def test_one_weak_extra_distractor_is_removed_when_two_strong_ones_remain():
    fact = SourceFact(
        "f1", "Privacy", "rule", "Use only an approved channel.",
        "doc_id=d;section=privacy",
    )
    q = _parse_questions(json.dumps({"questions": [{
        "prompt": "How should personal data be sent?",
        "options": [
            "Use only an approved channel.",
            "Use any channel when urgent.",
            "Use a personal messenger after verbal consent.",
            "Do not offer any approved alternative.",
        ],
        "correct_index": 0,
        "explanation": fact.value,
        "evidence": [{"fact_id": "f1", "quote": fact.value}],
    }]}), lesson_id="l", facts=[fact], maximum=1, block_id="b")[0]
    raw = verdict(q)
    raw["reviews"][0]["options"][3]["contradicted_by_source"] = False

    result = _parse_reviews(json.dumps(raw), [q])

    assert result[q.question_id] is True
    assert result.option_removals[q.question_id] == (3,)


def test_relevance_reviewer_defers_contradiction_truth_to_constraint_audit():
    q = candidate()
    raw = verdict(q)
    for option in raw["reviews"][0]["options"]:
        if not option["correct"]:
            option["contradicted_by_source"] = False

    result = _parse_reviews(json.dumps(raw), [q])

    assert result[q.question_id] is True
    assert result.option_removals[q.question_id] == ()


@pytest.mark.parametrize("field", ["options_distinct", "same_practical_task"])
def test_missing_new_quality_judgment_does_not_silently_pass(field):
    q = candidate()
    raw = verdict(q)
    row = raw["reviews"][0]
    del (row if field == "options_distinct" else row["options"][1])[field]
    with pytest.raises(ValueError):
        _parse_reviews(json.dumps(raw), [q])


def test_review_context_contains_only_each_questions_own_cited_evidence():
    from app.modules.ai.evidence_engine.semantic_assessment import _review_request
    q = candidate()
    facts = [SourceFact("f1", "Storage", "scope", "The range contains cabinets, not beds.", "doc_id=d;section=s"),
             SourceFact("f2", "Storage", "other", "Uncited supplementary claim.", "doc_id=d;section=s")]
    request = _review_request("b", [q], facts)
    assert "facts" not in request
    assert [f["fact_id"] for f in request["questions"][0]["cited_facts"]] == ["f1"]
    assert "Uncited supplementary" not in json.dumps(request)
    assert "correct_answer" not in request["questions"][0]


@pytest.mark.parametrize("fault", ["unrealistic", "duplicate"])
def test_independent_constraint_check_can_veto_rubber_stamped_practical_errors(fault):
    from app.modules.ai.evidence_engine.semantic_assessment import _parse_constraint_reviews
    q = candidate()
    facts = [SourceFact("f1", "Storage", "scope", "The range contains cabinets, not beds.", "doc_id=d;section=s")]
    raw = {"rules": [{"fact_id": "f1", "quote": facts[0].value, "kind": "attribute"}],
           "reviews": [{"question_id": q.question_id, "reason": "Independent judgement",
                        "distinct_errors": fault != "duplicate",
                        "options": [{"index": i, "relation": "entailed" if i == 0 else "contradicted",
                                     "invented_constraint": False,
                                     "realistic_error": not (fault == "unrealistic" and i == 2)}
                                    for i in range(3)]}]}
    assert _parse_constraint_reviews(json.dumps(raw), [q], facts)[q.question_id] is False


@pytest.mark.parametrize("option", ["Replace a bed with a cabinet.", "Кровать можно заменить шкафом."])
def test_unmentioned_replacement_advice_is_not_a_safe_distractor(option):
    from app.modules.ai.evidence_engine.semantic_assessment import _unsupported_replacement_advice
    q = candidate()
    from dataclasses import replace
    q = replace(q, options=(q.options[0], q.options[1], option))
    facts = [SourceFact("f1", "Storage", "scope", "The range contains cabinets, not beds.", "doc_id=d;section=s")]
    assert _unsupported_replacement_advice(q, facts)


def test_documented_substitution_context_and_normal_attribute_values_are_not_blocked():
    from dataclasses import replace

    from app.modules.ai.evidence_engine.semantic_assessment import _unsupported_replacement_advice
    q = candidate()
    q = replace(q, options=(q.options[0], "Replace the approved item with an unapproved item.", q.options[2]))
    facts = [SourceFact("f1", "Procedure", "scope", "Do not replace the approved item.", "doc_id=d;section=s")]
    assert not _unsupported_replacement_advice(q, facts)
    assert not _unsupported_replacement_advice(candidate(), facts)


def test_explanation_is_built_from_verified_quotes_not_authors_extra_claims():
    fact = SourceFact("f1", "Range", "mechanism", "Doors open with a handle.", "doc_id=d;section=s")
    q = _parse_questions(json.dumps({"questions": [{
        "prompt": "How do doors open?", "options": ["Handle", "Push", "Key"], "correct_index": 0,
        "explanation": "Doors use a handle. Drawers are free and beds are included.",
        "evidence": [{"fact_id": "f1", "quote": fact.value}],
    }]}), lesson_id="l", facts=[fact], maximum=1, block_id="b")[0]
    assert q.explanation == fact.value
