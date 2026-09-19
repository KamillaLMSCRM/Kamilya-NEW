from __future__ import annotations

import json

import pytest

from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import _parse_constraint_reviews


def question(
    question_id: str,
    options: tuple[str, ...],
    correct_index: int = 0,
    *,
    fact_id: str = "duty",
) -> QuestionDraft:
    return QuestionDraft(
        question_id=question_id,
        lesson_id="lesson-1",
        kind="single_choice",
        prompt="What is required when handling the request?",
        options=options,
        correct_answer=options[correct_index],
        explanation="Source-supported answer.",
        fact_id=fact_id,
        evidence_fact_ids=(fact_id,),
    )


def payload(questions: list[QuestionDraft], *, rules: list[dict] | None = None) -> dict:
    return {
        "rules": rules if rules is not None else [
            {"fact_id": "duty", "quote": "Register the request and state the response deadline.", "kind": "required"}
        ],
        "reviews": [
            {
                "question_id": q.question_id,
                "reason": "Each option was checked against the supplied rule.",
                "distinct_errors": True,
                "options": [
                    {"index": i, "relation": "entailed" if i == q.options.index(q.correct_answer) else "contradicted",
                     "invented_constraint": False, "realistic_error": True}
                    for i in range(len(q.options))
                ],
            }
            for q in questions
        ],
    }


def test_valid_minimum_duty_accepts_only_entailed_key_and_contradicted_wrong_options():
    facts = [SourceFact(
        "duty", "Request", "handling",
        "Register the request and state the response deadline. Manager notification is not required.",
        "doc_id=d1;section=handling",
    )]
    q = question("q-duty", (
        "Register the request and state the response deadline; manager notification is optional.",
        "Only notify the manager; registering the request is unnecessary.",
        "Register the request but do not state the response deadline.",
    ))
    raw = payload([q])
    raw["rules"][0]["quote"] = "Register the request and state the response deadline."

    assert _parse_constraint_reviews(json.dumps(raw), [q], facts) == {"q-duty": True}


def test_optional_not_prohibited_rejects_key_that_invents_a_ban():
    facts = [SourceFact("duty", "Request", "handling", "Register the request. Manager notification is not required.", "doc_id=d1;section=handling")]
    q = question("q-optional", (
        "Register the request without notifying the manager.",
        "Register the request and notify the manager if useful.",
        "Ignore the request until a manager is available.",
    ))
    raw = payload([q], rules=[{"fact_id": "duty", "quote": "Manager notification is not required.", "kind": "optional"}])
    raw["reviews"][0]["options"][0].update(relation="undetermined", invented_constraint=True)

    assert _parse_constraint_reviews(json.dumps(raw), [q], facts) == {"q-optional": False}


def test_two_entailed_options_rejects_the_question():
    facts = [SourceFact("duty", "Request", "handling", "Register the request and state the response deadline.", "doc_id=d1;section=handling")]
    q = question("q-two-true", (
        "Register the request and state the response deadline.",
        "State the response deadline and register the request.",
        "Discard the request.",
    ))
    raw = payload([q])
    raw["reviews"][0]["options"][1]["relation"] = "entailed"

    assert _parse_constraint_reviews(json.dumps(raw), [q], facts) == {"q-two-true": False}


def test_unknown_wrong_option_cannot_be_counted_as_false():
    facts = [SourceFact("duty", "Request", "handling", "Register the request and state the response deadline.", "doc_id=d1;section=handling")]
    q = question("q-unknown", (
        "Register the request and state the response deadline.",
        "Register the request in a blue folder before stating the deadline.",
        "Discard the request.",
    ))
    raw = payload([q])
    raw["reviews"][0]["options"][1]["relation"] = "undetermined"

    assert _parse_constraint_reviews(json.dumps(raw), [q], facts) == {"q-unknown": False}


def test_realistic_wrong_option_may_express_an_invented_exception() -> None:
    facts = [SourceFact(
        "duty",
        "Personal data",
        "channel rule",
        "Use only an approved channel; urgency and customer consent are not exceptions.",
        "doc_id=d1;section=privacy",
    )]
    q = question("q-exception", (
        "Use only an approved channel.",
        "Use a personal messenger when the request is urgent.",
        "Use a personal messenger after receiving written customer consent.",
    ))
    raw = payload([q], rules=[{
        "fact_id": "duty",
        "quote": facts[0].value,
        "kind": "required",
    }])
    raw["reviews"][0]["options"][2]["invented_constraint"] = True

    assert _parse_constraint_reviews(json.dumps(raw), [q], facts) == {"q-exception": True}


def test_constraint_audit_removes_one_weak_extra_when_two_strong_distractors_remain() -> None:
    facts = [SourceFact(
        "duty", "Personal data", "channel rule",
        "Use only an approved channel; urgency is not an exception.",
        "doc_id=d1;section=privacy",
    )]
    q = question("q-trim", (
        "Use only an approved channel.",
        "Use a personal messenger when urgent.",
        "Use a personal messenger after customer consent.",
        "Wait until a personal messenger becomes available.",
    ))
    raw = payload([q], rules=[{"fact_id": "duty", "quote": facts[0].value,
                              "kind": "required"}])
    raw["reviews"][0]["options"][3].update(
        relation="undetermined", realistic_error=False,
    )

    result = _parse_constraint_reviews(json.dumps(raw), [q], facts)

    assert result[q.question_id] is True
    assert result.option_removals[q.question_id] == (3,)


def test_true_false_inverse_does_not_require_multiple_distinct_realistic_errors() -> None:
    facts = [SourceFact(
        "duty", "First response", "rule",
        "A final decision is not required in the first response.",
        "doc_id=d1;section=reply",
    )]
    q = question("q-binary", (
        "A final decision is not required in the first response.",
        "A final decision is required in the first response.",
    ))
    q = QuestionDraft(
        question_id=q.question_id,
        lesson_id=q.lesson_id,
        kind="true_false",
        prompt="Is a final decision required in the first response?",
        options=q.options,
        correct_answer=q.correct_answer,
        explanation=q.explanation,
        fact_id=q.fact_id,
        evidence_fact_ids=q.evidence_fact_ids,
    )
    raw = payload([q], rules=[{"fact_id": "duty", "quote": facts[0].value,
                              "kind": "optional"}])
    raw["reviews"][0]["distinct_errors"] = False
    raw["reviews"][0]["options"][1]["realistic_error"] = False

    assert _parse_constraint_reviews(json.dumps(raw), [q], facts) == {"q-binary": True}


def test_attribute_replacement_is_a_grounded_contradiction():
    fact = SourceFact("facade", "Cabinet", "Facade material", "Chipboard", "doc_id=d1;section=catalog")
    q = question("q-attribute", ("Chipboard", "MDF", "Glass"), fact_id="facade")
    raw = payload([q], rules=[{"fact_id": "facade", "quote": "Chipboard", "kind": "attribute"}])

    assert _parse_constraint_reviews(json.dumps(raw), [q], [fact]) == {"q-attribute": True}


def test_distinct_attribute_values_are_not_rejected_as_one_broad_misconception() -> None:
    fact = SourceFact(
        "style",
        "Chicago Street",
        "Style",
        "Urban minimalism with smooth facades and no exterior hardware.",
        "doc_id=d1;section=catalog",
    )
    q = question(
        "q-style",
        (
            "Urban minimalism with smooth facades and no exterior hardware.",
            "Classic style with carved facades.",
            "Loft style with exposed hardware.",
            "Provence style with framed facades.",
        ),
        fact_id="style",
    )
    raw = payload([q], rules=[{
        "fact_id": "style",
        "quote": fact.value,
        "kind": "attribute",
    }])
    # A model can collapse every wrong category into the broad statement
    # "not minimalism".  The concrete values are nevertheless different
    # misconceptions and remain useful distractors for an attribute question.
    raw["reviews"][0]["distinct_errors"] = False

    assert _parse_constraint_reviews(json.dumps(raw), [q], [fact]) == {"q-style": True}


def test_known_same_fact_attribute_label_is_a_grounded_rule_quote():
    fact = SourceFact("facade", "Cabinet", "Facade material", "Chipboard", "doc_id=d1;section=catalog")
    q = question("q-labelled-rule", ("Chipboard", "MDF", "Glass"), fact_id="facade")
    raw = payload([q], rules=[
        {"fact_id": "facade", "quote": "facade material: chipboard", "kind": "attribute"}
    ])

    assert _parse_constraint_reviews(json.dumps(raw), [q], [fact]) == {"q-labelled-rule": True}


@pytest.mark.parametrize(
    "mutate",
    ["missing-index", "duplicate-index", "duplicate-question-id", "non-boolean-invented-constraint"],
)
def test_missing_or_duplicate_question_and_option_identity_is_rejected(mutate: str):
    facts = [SourceFact("duty", "Request", "handling", "Register the request and state the response deadline.", "doc_id=d1;section=handling")]
    questions = [
        question("q-one", ("Register the request and state the response deadline.", "Discard it.")),
        question("q-two", ("Register the request and state the response deadline.", "Discard it.")),
    ]
    raw = payload(questions)
    if mutate == "missing-index":
        raw["reviews"][0]["options"].pop()
    elif mutate == "duplicate-index":
        raw["reviews"][0]["options"][1]["index"] = 0
    elif mutate == "non-boolean-invented-constraint":
        raw["reviews"][0]["options"][0]["invented_constraint"] = 1
    else:
        raw["reviews"][1]["question_id"] = "q-one"

    with pytest.raises(ValueError):
        _parse_constraint_reviews(json.dumps(raw), questions, facts)


@pytest.mark.parametrize(
    "rules",
    [
        [],
        [{"fact_id": "unknown", "quote": "Register the request", "kind": "required"}],
        [{"fact_id": "duty", "quote": "Invented restriction", "kind": "forbidden"}],
        [{"fact_id": "facade", "quote": "Cabinet material: Chipboard", "kind": "attribute"}],
        [{"fact_id": "facade", "quote": "Facade material: MDF", "kind": "attribute"}],
        [{"fact_id": "duty", "quote": "Register the request", "kind": "mandatory"}],
    ],
)
def test_rules_require_grounded_fact_references_and_valid_kinds(rules: list[dict]):
    facts = [
        SourceFact("duty", "Request", "handling", "Register the request and state the response deadline.", "doc_id=d1;section=handling"),
        SourceFact("facade", "Cabinet", "Facade material", "Chipboard", "doc_id=d1;section=catalog"),
    ]
    q = question("q-rule", ("Register the request and state the response deadline.", "Discard it."))

    with pytest.raises(ValueError):
        _parse_constraint_reviews(json.dumps(payload([q], rules=rules)), [q], facts)
