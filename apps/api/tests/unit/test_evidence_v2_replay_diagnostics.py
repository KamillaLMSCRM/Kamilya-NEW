from __future__ import annotations

import json
from copy import deepcopy

from scripts.dev.analyze_evidence_v2_replay import compare_replay_artifacts

from app.modules.ai.evidence_engine.replay_diagnostics import summarize_assessment_replay


def _artifact() -> dict:
    questions = [
        {
            "question_id": f"q-{index}",
            "lesson_id": "lesson-dense",
            "prompt": f"Question {index}?",
            "correct_answer": f"Answer {index}",
            "evidence_fact_ids": [f"fact-{index}"],
        }
        for index in range(1, 4)
    ]
    axes = [
        {
            "axis_id": f"axis-{index}",
            "lesson_id": "lesson-dense",
            "state": "retained" if index <= 3 else "omitted",
            "reason": "" if index <= 3 else "assessment_question_limit",
        }
        for index in range(1, 6)
    ]
    return {
        "realized_course": {
            "lessons": [
                {
                    "lesson_id": "lesson-dense",
                    "content": "Коллекция Север описана кратко. Коллекция Север описана кратко.",
                }
            ]
        },
        "realized_assessment": {"questions": questions},
        "assessment_review": {
            "axis_outcomes": axes,
            "block_outcomes": [{"outcome": "accepted"}],
            "coverage": {"requires_review": False},
            "contract_coverage": {"audit_incomplete": False},
        },
    }


def test_replay_summary_exposes_density_cap_and_omission_reasons() -> None:
    result = summarize_assessment_replay(_artifact())

    assert result["cap_saturated_lesson_ids"] == ["lesson-dense"]
    assert result["high_density_lesson_ids"] == ["lesson-dense"]
    assert result["high_density_cap_saturated_lesson_ids"] == ["lesson-dense"]
    assert result["axis_states"] == {"omitted": 2, "retained": 3}
    assert result["omission_reasons"] == {"assessment_question_limit": 2}
    assert result["review_diagnostics_available"] is True


def test_question_fingerprint_is_independent_of_replay_order() -> None:
    first = _artifact()
    second = deepcopy(first)
    second["realized_assessment"]["questions"].reverse()
    second["assessment_review"]["axis_outcomes"].reverse()

    assert (
        summarize_assessment_replay(first)["question_fingerprint"]
        == summarize_assessment_replay(second)["question_fingerprint"]
    )


def test_missing_review_diagnostics_are_explicit() -> None:
    artifact = _artifact()
    del artifact["assessment_review"]

    result = summarize_assessment_replay(artifact)

    assert result["review_diagnostics_available"] is False


def test_permutation_stability_requires_same_source_declaration(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(_artifact()), encoding="utf-8")
    changed = _artifact()
    changed["realized_assessment"]["questions"][0]["prompt"] = "Different question?"
    second.write_text(json.dumps(changed), encoding="utf-8")

    unrelated = compare_replay_artifacts((first, second), question_cap=3)
    permutations = compare_replay_artifacts(
        (first, second), question_cap=3, same_source_permutations=True
    )

    assert unrelated["fingerprints_equal"] is False
    assert unrelated["permutation_stable"] is None
    assert permutations["permutation_stable"] is False
