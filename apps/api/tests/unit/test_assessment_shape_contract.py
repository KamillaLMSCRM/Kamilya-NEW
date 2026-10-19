from dataclasses import replace

from app.modules.ai.evidence_engine.models import AssessmentAxis, QuestionDraft
from app.modules.ai.evidence_engine.quality import (
    answer_length_contract,
    answer_length_repair_targets,
)
from app.modules.ai.evidence_engine.semantic_assessment import _axis_author_payload


def _question(identity: str, correct: str) -> QuestionDraft:
    return QuestionDraft(
        identity, "lesson", "single_choice", identity,
        (correct, "wrong", "another wrong"), correct,
        "Source-owned explanation", identity,
    )


def test_answer_length_contract_has_exact_boundary_and_rounding_arithmetic() -> None:
    assert answer_length_contract("x" * 23) == {
        "at_least_one_distractor_min_chars": None,
        "distractor_max_chars": None,
    }
    assert answer_length_contract("x" * 24)["distractor_max_chars"] == 36
    assert answer_length_contract("x" * 79)["at_least_one_distractor_min_chars"] is None
    assert answer_length_contract("x" * 80)["at_least_one_distractor_min_chars"] == 54
    assert answer_length_contract("x" * 81)["at_least_one_distractor_min_chars"] == 54
    assert answer_length_contract("x" * 82)["at_least_one_distractor_min_chars"] == 55
    assert answer_length_contract("x" * 25)["distractor_max_chars"] == 37


def test_shared_contract_preserves_severe_target_verdicts() -> None:
    long_key = "x" * 80
    assert answer_length_repair_targets([
        replace(_question("long", long_key),
            options=(long_key, "x" * 53, "x" * 53),
        )
    ]) == ("long",)
    short_key = "x" * 24
    assert answer_length_repair_targets([
        replace(_question("short", short_key),
            options=(short_key, "x" * 36, "x" * 36),
        )
    ]) == ()


def test_quiz_level_logic_and_author_payload_are_unchanged_except_contract() -> None:
    questions = [
        _question(str(index), "one two three four")
        for index in range(5)
    ]
    questions[-1] = replace(
        questions[-1], options=(questions[-1].correct_answer, "a b c d e", "wrong"),
    )
    assert len(answer_length_repair_targets(questions)) == 1

    axis = AssessmentAxis(
        axis_id="axis-1", lesson_id="lesson", semantic_block_id="block",
        primary_fact_id="fact-1", evidence_fact_ids=("fact-1",),
        subject="subject", attribute="attribute", required_prompt="",
        correct_value="x" * 80, normalized_correct_value="x" * 80,
        eligible_distractor_fact_ids=(), axis_kind="rule_value",
    )
    payload = _axis_author_payload(axis)
    assert payload["answer_length_contract"] == {
        "at_least_one_distractor_min_chars": 54,
        "distractor_max_chars": 120,
    }
    assert payload["distractor_token_limit"] is None
