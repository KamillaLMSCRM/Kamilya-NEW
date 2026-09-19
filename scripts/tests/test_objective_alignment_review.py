"""Contract tests for blind review payloads and selective audit filtering."""
from __future__ import annotations

import json

import pytest

from scripts.dev.objective_alignment.engine import Quiz
from scripts.dev.objective_alignment.review import (
    blind_items,
    feedback,
    filter_quiz,
    parse_audit,
)


def make_quiz(option_texts: list[str] | None = None) -> Quiz:
    texts = option_texts or ["Keep the seal covered", "Expose the seal", "Remove the seal"]
    return Quiz.model_validate({
        "items": [{
            "objective_id": "o1",
            "prompt": "Which action preserves the seal during storage?",
            "options": [
                {
                    "text": text,
                    "correct": index == 0,
                    "action_or_property": f"action {index}",
                    "error_mechanism": "" if index == 0 else f"error {index}",
                }
                for index, text in enumerate(texts)
            ],
            "taught_quote": "Keep the seal covered",
            "explanation": "The covered seal is the required storage condition.",
        }],
        "unassessable": [],
    })


def make_audit(*, supported_answers=None, remove_options=None,
               duplicate_groups=None, status="usable", plan_issues=None):
    raw = {
        "plan_issues": [] if plan_issues is None else plan_issues,
        "teaching_issues": [],
        "missing_decisions": [],
        "items": [{
            "objective_id": "o1",
            "supported_answers": [0] if supported_answers is None else supported_answers,
            "remove_options": [] if remove_options is None else remove_options,
            "duplicate_groups": [] if duplicate_groups is None else duplicate_groups,
            "status": status,
            "reason": "synthetic structural audit",
        }],
    }
    return parse_audit(json.dumps(raw), make_quiz())


def audit_raw(*, objective_id="o1", supported_answers=None,
              remove_options=None, duplicate_groups=None):
    return {
        "plan_issues": [],
        "teaching_issues": [],
        "missing_decisions": [],
        "items": [{
            "objective_id": objective_id,
            "supported_answers": [0] if supported_answers is None else supported_answers,
            "remove_options": [] if remove_options is None else remove_options,
            "duplicate_groups": [] if duplicate_groups is None else duplicate_groups,
            "status": "usable",
            "reason": "synthetic structural audit",
        }],
    }


def test_blind_items_removes_key_labels_and_explanation():
    payload = blind_items(make_quiz())

    assert payload == [{
        "objective_id": "o1",
        "prompt": "Which action preserves the seal during storage?",
        "options": ["Keep the seal covered", "Expose the seal", "Remove the seal"],
    }]
    assert all("correct" not in option for option in payload[0]["options"])
    assert "action_or_property" not in payload[0]
    assert "explanation" not in payload[0]


def test_parse_audit_accepts_and_normalizes_flat_duplicate_group():
    raw = audit_raw(duplicate_groups=[1, 2])

    audit = parse_audit(json.dumps(raw), make_quiz())

    assert audit.items[0].duplicate_groups == [[1, 2]]


@pytest.mark.parametrize("items", [
    [audit_raw(objective_id="unknown")["items"][0]],
    [],
])
def test_parse_audit_rejects_unknown_or_missing_objective_ids(items):
    raw = audit_raw()
    raw["items"] = items

    with pytest.raises(ValueError, match="audit_objective_mismatch"):
        parse_audit(json.dumps(raw), make_quiz())


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("remove_options", [3], "audit_option_index_out_of_range"),
        ("duplicate_groups", [[1, 1]], "invalid_duplicate_group"),
    ],
)
def test_parse_audit_rejects_out_of_range_and_duplicate_indices(field, value, error):
    raw = {
        "teaching_issues": [],
        "missing_decisions": [],
        "items": [{
            "objective_id": "o1",
            "supported_answers": [0],
            "remove_options": value if field == "remove_options" else [],
            "duplicate_groups": value if field == "duplicate_groups" else [],
            "status": "usable",
            "reason": "synthetic structural audit",
        }],
    }

    with pytest.raises(ValueError, match=error):
        parse_audit(json.dumps(raw), make_quiz())


@pytest.mark.parametrize(
    ("supported_answers", "remove_options", "error"),
    [
        ([True], [], "int_type"),
        ([0], [3], "audit_option_index_out_of_range"),
    ],
)
def test_parse_audit_rejects_boolean_or_out_of_range_indices(
    supported_answers, remove_options, error
):
    raw = audit_raw(supported_answers=supported_answers, remove_options=remove_options)

    with pytest.raises(ValueError, match=error):
        parse_audit(json.dumps(raw), make_quiz())


def test_parse_audit_rejects_duplicated_supported_answers():
    raw = audit_raw(supported_answers=[0, 0])

    with pytest.raises(ValueError, match="duplicate_supported_answer"):
        parse_audit(json.dumps(raw), make_quiz())


def test_feedback_preserves_plan_issues_without_generating_correction():
    audit = make_audit(plan_issues=["source decision is not represented"])

    result = json.loads(feedback(audit, []))

    assert result["plan_issues"] == ["source decision is not represented"]
    assert "correction" not in result


def test_filter_drops_one_duplicate_wrong_action_and_retains_valid_question():
    quiz = make_quiz(["Keep the seal covered", "Expose the seal", "Open the cover", "Remove the seal"])
    audit = make_audit(duplicate_groups=[[1, 2]])

    filtered, rejected, removed = filter_quiz(quiz, audit)

    assert not rejected
    assert [option.text for option in filtered.items[0].options] == [
        "Keep the seal covered", "Expose the seal", "Remove the seal"
    ]
    assert removed[0]["indices"] == [2]


@pytest.mark.parametrize(
    ("supported_answers", "status"),
    [([1], "usable"), ([0], "rewrite")],
)
def test_filter_rejects_invalid_or_key_disagreeing_review(supported_answers, status):
    quiz = make_quiz()
    audit = make_audit(supported_answers=supported_answers, status=status)

    filtered, rejected, removed = filter_quiz(quiz, audit)

    assert filtered.items == []
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "blind_answer_or_item_disagreement"
    assert removed == []


def test_filter_rejects_when_removing_all_distractors():
    quiz = make_quiz()
    audit = make_audit(remove_options=[1, 2])

    filtered, rejected, removed = filter_quiz(quiz, audit)

    assert filtered.items == []
    assert rejected[0]["reason"] == "no_meaningful_contrast"
    assert removed == []


def test_filter_keeps_valid_two_choice_question():
    quiz = make_quiz(["Keep the seal covered", "Expose the seal"])
    audit = make_audit()

    filtered, rejected, removed = filter_quiz(quiz, audit)

    assert not rejected
    assert not removed
    assert len(filtered.items[0].options) == 2


def test_filter_retains_distinct_values_of_one_property_without_duplicate_group():
    quiz = make_quiz(["Set temperature to 10 C", "Set temperature to 20 C", "Set temperature to 30 C"])
    audit = make_audit()

    filtered, rejected, removed = filter_quiz(quiz, audit)

    assert not rejected
    assert not removed
    assert [option.text for option in filtered.items[0].options] == [
        "Set temperature to 10 C", "Set temperature to 20 C", "Set temperature to 30 C"
    ]
