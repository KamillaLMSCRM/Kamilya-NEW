from __future__ import annotations

import json
from argparse import Namespace

import pytest
from scripts.dev.course_quality_eval.benchmark import DEFAULT_SUITE, inspect_result, load_suite


def case():
    return {
        "id": "guard", "source": "Ответить в течение 2 рабочих часов. Срочность не является исключением.",
        "filename": "guard.txt", "split": "development", "expected": "draft",
        "required_claims": [
            {"id": "deadline", "quote": "в течение 2 рабочих часов", "critical": True},
            {"id": "exception", "quote": "Срочность не является исключением.", "critical": True},
        ],
        "forbidden_claims": ["Срочность отменяет срок ответа."],
    }


def result(content: str):
    return {
        "realized_course": {"lessons": [{"lesson_id": "one", "content": content}]},
        "realized_assessment": {"questions": [{
            "question_id": "q1", "lesson_id": "one", "prompt": "Каков срок?",
            "correct_answer": "2 рабочих часа", "options": ["2 рабочих часа", "1 час"],
            "explanation": "Соблюдайте срок.",
        }]},
        "publishability": {"publishable": True},
    }


def test_presence_is_not_semantic_acceptance():
    signals = inspect_result(case(), result(case()["source"]))
    assert signals["exact_quote_recall"] == 1
    assert signals["semantic_accuracy"] is None
    assert signals["marketing_ready"] is False
    assert signals["independent_review"] == "NOT_REVIEWED"


def test_exception_omission_cannot_hide_in_answer_or_source_metadata():
    candidate = result("Ответить в течение 2 рабочих часов.")
    candidate["realized_assessment"]["questions"][0]["explanation"] = case()["source"]
    signals = inspect_result(case(), candidate)
    assert signals["missing_critical_exact_claims"] == ["exception"]
    assert signals["exact_quote_recall"] == 0.5


def test_negation_reversal_is_detected_as_forbidden_not_counted_as_correct():
    signals = inspect_result(case(), result(case()["source"] + " Срочность отменяет срок ответа."))
    assert signals["forbidden_exact_claims_found"] == ["Срочность отменяет срок ответа."]
    assert signals["marketing_ready"] is False


def test_question_structure_longest_and_foreign_lesson():
    candidate = result(case()["source"])
    question = candidate["realized_assessment"]["questions"][0]
    question["options"] = ["2 рабочих часа", "2 рабочих часа"]
    question["lesson_id"] = "other"
    signals = inspect_result(case(), candidate)
    assert {defect["reason"] for defect in signals["structural_defects"]} == {
        "invalid_unique_key", "duplicate_options", "foreign_lesson",
    }
    assert signals["longest_answer_heuristic_hits"] == 0
    assert inspect_result(case(), result(case()["source"]))["longest_answer_heuristic_hits"] == 1


def test_conflicting_source_publishability_is_not_success():
    source = case()
    source["expected"] = "review"
    assert inspect_result(source, result(source["source"]))["expected_review_but_generator_publishable"]


@pytest.mark.parametrize("mutation", ["invalid_gold", "duplicate_case", "unsafe_name"])
def test_fixture_identity_preflight(tmp_path, mutation):
    source = case()
    if mutation == "invalid_gold":
        source["required_claims"][0]["quote"] = "Несуществующая норма"
    elif mutation == "unsafe_name":
        source["filename"] = "../guard.txt"
    cases = [source, source] if mutation == "duplicate_case" else [source]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"schema_version": 1, "cases": cases}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_suite(path)


def test_frozen_synthetic_suite_is_source_first_and_has_holdout():
    cases = load_suite(DEFAULT_SUITE)
    assert len(cases) >= 8
    assert len({item["type"] for item in cases}) >= 5
    assert len({item["level"] for item in cases}) >= 3
    assert sum(item["split"] == "holdout" for item in cases) >= 3
    assert sum(item["expected"] == "review" for item in cases) >= 2


@pytest.mark.asyncio
async def test_benchmark_rejects_custom_source_suite_changed_during_run(tmp_path, monkeypatch):
    from scripts.dev.course_quality_eval import benchmark

    source = {**case(), "title": "Guard", "type": "policy", "level": "high"}
    suite = tmp_path / "custom-suite.json"
    suite.write_text(json.dumps({"schema_version": 1, "cases": [source]}), encoding="utf-8")
    original_save = benchmark.save

    def mutate_after_planning(path, value):
        original_save(path, value)
        if path.name == "source-plan.json":
            suite.write_text(suite.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    monkeypatch.setattr(benchmark, "save", mutate_after_planning)
    args = Namespace(suite=suite, output_dir=tmp_path / "output", case=None,
                     live=False, replay_dir=None, env_file=None, max_calls=30, timeout=360)
    with pytest.raises(ValueError, match="suite_changed_during_benchmark"):
        await benchmark.run(args)
