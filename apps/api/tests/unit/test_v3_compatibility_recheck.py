"""Compatibility rechecks preserve source, prior findings and fail closed."""

import json
from pathlib import Path

import pytest

from app.modules.ai.v3.compatibility_recheck import recheck_compatibility
from app.modules.ai.v3.service import _validate_question_entailment


FIXTURE = Path(__file__).with_name("fixtures") / "v3_compatibility_report_case3_case4.json"


def persisted_case_review(case_id):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return fixture["flags"][case_id], fixture["source"], fixture["responses"][case_id]["compatibility"]


def response(correct_index=0):
    statuses = ["CONTRADICTED"] * 4
    statuses[correct_index] = "SUPPORTED"
    return {
        "options": [
            {
                "index": i,
                "verdict": status,
                "claims": [{"claim": "action", "status": status, "reason": "source"}],
                "summary": "checked",
                "omitted_required_elements": [],
            }
            for i, status in enumerate(statuses)
        ]
    }


class Pipeline:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def review_question_compatibility(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_shape", ["blank_omission", "mixed_status"])
async def test_saved_malformed_shapes_rechecked_with_original_and_source(bad_shape):
    original = response()
    row = original["options"][3]
    if bad_shape == "blank_omission":
        row["omitted_required_elements"] = ["required", ""]
    else:
        row.update(verdict="UNCERTAIN", claims=[{"claim": "action", "status": "CONTRADICTED", "reason": "source"}])
    evidence = {}
    pipeline = Pipeline(response())
    ok, recheck_error = await recheck_compatibility(
        pipeline,
        "scenario",
        "question",
        ["a", "b", "c", "d"],
        [True, False, False, False],
        ["exact source"],
        (),
        original,
        evidence,
    )
    assert evidence["compatibility"] == original
    if bad_shape == "blank_omission":
        assert ok and evidence["compatibility_recheck"]["result"] == response()
        assert (pipeline.calls[0][0][3] == ["exact source"]
                and "Предыдущий ответ" in pipeline.calls[0][1]["consistency_feedback"])
    else:
        assert not ok and not pipeline.calls
        assert "ожидался CONTRADICTED" in recheck_error


@pytest.mark.asyncio
async def test_recheck_cannot_clear_a_contradiction_or_unknown():
    original = response()
    original["options"][3]["omitted_required_elements"] = [""]
    conflicting = response()
    conflicting["options"][0].update(
        verdict="UNCERTAIN", claims=[{"claim": "a", "status": "UNCERTAIN", "reason": "unclear"}]
    )
    record = {}
    ok, _ = await recheck_compatibility(
        Pipeline(conflicting),
        "s",
        "q",
        ["a", "b", "c", "d"],
        [True, False, False, False],
        ["source"],
        (),
        original,
        record,
    )
    assert not ok and record["compatibility"] == original and record["compatibility_recheck"]["result"] == conflicting
    record = {}
    with pytest.raises(TimeoutError):
        await recheck_compatibility(
            Pipeline(TimeoutError()),
            "s",
            "q",
            ["a", "b", "c", "d"],
            [True, False, False, False],
            ["source"],
            (),
            original,
            record,
        )
    assert record["compatibility"] == original and record["compatibility_recheck"]["result"] is None


@pytest.mark.asyncio
async def test_substantive_uncertainty_is_not_retried():
    original = response()
    original["options"][0].update(
        verdict="UNCERTAIN", claims=[{"claim": "a", "status": "UNCERTAIN", "reason": "unclear"}]
    )
    pipeline = Pipeline(response())
    record = {}
    ok, _ = await recheck_compatibility(
        pipeline, "s", "q", ["a", "b", "c", "d"], [True, False, False, False], ["source"], (), original, record
    )
    assert not ok and not pipeline.calls and record["compatibility"] == original


@pytest.mark.asyncio
async def test_recheck_checkpoint_replays_exact_result_without_second_call():
    from app.modules.ai.v3.engine import V3GenerationPipeline
    from app.modules.ai.v3.stage_checkpoint import stage_once

    class Journal:
        tenant_id = "t"
        job_id = "j"

        def __init__(self):
            self.plans, self.values = {}, {}

        async def prepare(self, key, plan):
            if key in self.plans and self.plans[key] != plan:
                raise ValueError("conflict")
            self.plans[key] = plan
            return self.values.get(key)

        async def save_value(self, key, value):
            if key in self.values and self.values[key] != value:
                raise ValueError("conflict")
            self.values[key] = value

        async def read_owned_value(self, key, plan):
            return self.values.get(key) if self.plans.get(key) == plan else None

    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        async def physical():
            calls.append(1)
            return response()

        return await stage_once(
            journal,
            stage="review",
            group_id="g",
            source_sha256="a" * 64,
            route_fingerprint="b" * 64,
            messages=messages,
            response_format=response_format,
            invoke=physical,
        )

    original = response()
    original["options"][3]["omitted_required_elements"] = [""]
    pipeline = V3GenerationPipeline(invoke)
    for _ in range(2):
        evidence = {}
        valid, _ = await recheck_compatibility(
            pipeline, "s", "q", ["a", "b", "c", "d"], [True, False, False, False], ["source"], (), original, evidence
        )
        assert valid and evidence["compatibility"] == original
    assert calls == [1]


@pytest.mark.asyncio
async def test_recheck_untrusted_inputs_are_only_in_user_message():
    from app.modules.ai.v3.engine import V3GenerationPipeline

    captured = []

    async def invoke(messages, response_format):
        captured.extend(messages)
        return response()

    original = response()
    original["options"][3]["omitted_required_elements"] = [""]
    original["untrusted"] = "MODEL_SENTINEL"
    await recheck_compatibility(
        V3GenerationPipeline(invoke), "SCENARIO_SENTINEL", "QUESTION_SENTINEL",
        ["OPTION_SENTINEL", "b", "c", "d"], [True, False, False, False],
        ["SOURCE_SENTINEL"], ("CONTEXT_SENTINEL",), original, {},
    )
    system = next(message["content"] for message in captured if message["role"] == "system")
    user = next(message["content"] for message in captured if message["role"] == "user")
    for value in ("MODEL_SENTINEL", "SOURCE_SENTINEL", "SCENARIO_SENTINEL", "QUESTION_SENTINEL", "OPTION_SENTINEL", "CONTEXT_SENTINEL"):
        assert value not in system and value in user
    assert "<UNTRUSTED_PREVIOUS_REVIEW>" in user and "</UNTRUSTED_PREVIOUS_REVIEW>" in user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "expected_error", "rechecked"),
    [("case-3-var-a", "нет корректной проверки полноты ответа", True),
     ("case-4-var-a", "вердикт проверки ответа противоречит статусам утверждений", False)],
)
async def test_exact_persisted_synthetic_report_shapes_recheck_failures(case_id, expected_error, rechecked):
    flags, source, original = persisted_case_review(case_id)
    valid, error = _validate_question_entailment(original, flags)
    assert not valid and expected_error in error

    evidence = {}
    pipeline = Pipeline(response(flags.index(True)))
    ok, recheck_error = await recheck_compatibility(
        pipeline, "Передача смены", "Что сделать?", ["a", "b", "c", "d"],
        flags, source, (), original, evidence,
    )
    assert evidence["compatibility"] == original
    if rechecked:
        assert ok
        assert evidence["compatibility_recheck"]["original_error"] == error
        assert evidence["compatibility_recheck"]["result"] == response(flags.index(True))
    else:
        assert not ok and not pipeline.calls
        assert ("вердикт проверки ответа противоречит статусам утверждений" in recheck_error
                or "ожидался CONTRADICTED" in recheck_error)
        assert "compatibility_recheck" not in evidence


@pytest.mark.asyncio
async def test_later_substantive_mismatch_is_not_hidden_by_earlier_shape_error():
    original = response(1)
    original["options"][0]["omitted_required_elements"] = [""]
    original["options"][2]["verdict"] = "SUPPORTED"
    original["options"][2]["claims"][0]["status"] = "SUPPORTED"
    pipeline = Pipeline(response(1))
    evidence = {}
    ok, error = await recheck_compatibility(
        pipeline, "s", "q", ["a", "b", "c", "d"], [False, True, False, False],
        ["source"], (), original, evidence,
    )
    assert not ok and "ожидался CONTRADICTED" in error
    assert not pipeline.calls
    assert "compatibility_recheck" not in evidence


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [("distractor_bad_summary", "ожидался CONTRADICTED"),
     ("correct_bad_claim", "ожидался SUPPORTED")],
)
async def test_nonrepairable_mixed_failure_is_held_before_recheck(failure, expected_error):
    original = response(1)
    original["options"][0]["omitted_required_elements"] = [""]
    if failure == "distractor_bad_summary":
        original["options"][2].update(verdict="SUPPORTED", summary="")
    else:
        original["options"][1].update(
            verdict="CONTRADICTED", claims=[{"claim": "", "status": "CONTRADICTED", "reason": ""}]
        )
    pipeline = Pipeline(response(1))
    evidence = {}
    ok, error = await recheck_compatibility(
        pipeline, "s", "q", ["a", "b", "c", "d"], [False, True, False, False],
        ["source"], (), original, evidence,
    )
    assert not ok and not pipeline.calls
    assert expected_error in error
    assert "compatibility_recheck" not in evidence


@pytest.mark.asyncio
async def test_unhashable_verdict_is_structured_hold_not_type_error():
    original = response(1)
    original["options"][0]["omitted_required_elements"] = [""]
    original["options"][2]["verdict"] = []
    pipeline = Pipeline(response(1))
    evidence = {}
    ok, error = await recheck_compatibility(
        pipeline, "s", "q", ["a", "b", "c", "d"], [False, True, False, False],
        ["source"], (), original, evidence,
    )
    assert not ok and error == "вариант 2: невалидный вердикт проверки ответа"
    assert not pipeline.calls and "compatibility_recheck" not in evidence
