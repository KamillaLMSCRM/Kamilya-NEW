from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ops" / "ai_assessment_replay.py"
SPEC = importlib.util.spec_from_file_location("ai_assessment_replay", SCRIPT)
assert SPEC and SPEC.loader
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def _export() -> dict:
    return {
        "plan": {"structure": {}},
        "checkpoints": [
            {
                "module_order": 0,
                "lesson_order": 1,
                "module_key": "module-000",
                "lesson_key": "lesson-000-001",
                "content_status": "completed",
                "content_payload": {"title": "Synthetic lesson", "objectives": ["Apply a rule"], "content": "Fact A."},
            },
            {"module_order": 0, "lesson_order": 2, "content_status": "pending", "content_payload": None},
        ],
    }


def _assessment_payload(title: str = "Synthetic lesson") -> dict:
    return {
        "lesson_title": title,
        "mcq": [
            {
                "question": "Which fact applies?",
                "options": [
                    {"text": "Fact A", "is_correct": True},
                    {"text": "Fact B", "is_correct": False},
                ],
                "source_quote": "Fact A.",
            }
        ],
    }


def test_selects_only_completed_exact_lesson() -> None:
    selected = replay.select_lessons(_export(), module_order=0, lesson_order=1, all_completed=False)

    assert len(selected) == 1
    assert selected[0]["lesson"].title == "Synthetic lesson"


def test_selects_checkpointed_course_for_final_audit() -> None:
    exported = _export()
    exported["checkpoints"][0].update(
        assessment_status="completed",
        assessment_payload=_assessment_payload(),
    )

    course, assessment = replay.select_course_for_audit(exported)

    assert [[lesson.title for lesson in module.lessons] for module in course.modules] == [["Synthetic lesson"]]
    assert [item.lesson_title for item in assessment.assessments] == ["Synthetic lesson"]
    assert assessment.assessments[0].mcq[0].options[0].text == "Fact A"


def test_final_audit_replay_rejects_completed_lesson_without_assessment() -> None:
    with pytest.raises(replay.ReplayTraceError, match="completed_lesson_missing_assessment"):
        replay.select_course_for_audit(_export())


def test_final_audit_replay_rejects_duplicate_checkpoint_coordinates() -> None:
    exported = _export()
    first = exported["checkpoints"][0]
    first.update(assessment_status="completed", assessment_payload=_assessment_payload())
    exported["checkpoints"].append(dict(first))

    with pytest.raises(replay.ReplayTraceError, match="duplicate_completed_lesson_coordinate"):
        replay.select_course_for_audit(exported)


def test_final_audit_stage_records_filtered_assessment_and_gap_coordinates(monkeypatch) -> None:
    exported = _export()
    exported["checkpoints"][0].update(
        assessment_status="completed",
        assessment_payload=_assessment_payload(),
    )
    course, assessment = replay.select_course_for_audit(exported)
    output: dict = {}
    flush_calls: list[bool] = []

    async def finalize(llm, course_content, course_assessment, **kwargs):
        assert llm == "replay-llm"
        assert course_content is course
        assert course_assessment is assessment
        return SimpleNamespace(
            assessment=assessment,
            uncovered_objectives=[(0, 0)],
            uncovered_content_objectives=[],
            decisions=[{"question_id": "L0Q0", "decision": "keep", "reason": "valid"}],
        )

    monkeypatch.setattr(replay, "finalize_course_assessment", finalize)

    asyncio.run(
        replay.run_final_audit(
            course,
            assessment,
            llm="replay-llm",
            language="ru",
            compact=False,
            output=output,
            flush=lambda: flush_calls.append(True),
        )
    )

    assert output["uncovered_objectives"] == [[0, 0]]
    assert output["assessment"]["assessments"][0]["lesson_title"] == "Synthetic lesson"
    assert output["decisions"][0]["decision"] == "keep"
    assert flush_calls == [True]


def test_replay_rejects_exhausted_and_unconsumed_responses() -> None:
    calls = [{"request": {"messages": "one", "config": None, "response_format": None}, "response": {"content": "answer"}}]
    llm = replay.ReplayingLLM(calls)

    assert asyncio.run(llm.ainvoke("one")).content == "answer"
    with pytest.raises(replay.ReplayTraceError, match="exhausted"):
        asyncio.run(llm.ainvoke("two"))

    leftover = replay.ReplayingLLM(calls)
    with pytest.raises(replay.ReplayTraceError, match="unconsumed_1"):
        leftover.assert_consumed()


def test_capture_records_full_call_and_redacts_secret_values() -> None:
    class Inner:
        async def ainvoke(self, messages, config=None, response_format=None):
            return SimpleNamespace(content="Bearer public-response")

    calls: list[dict] = []
    captured = replay.CapturingLLM(Inner(), calls, lambda: None)

    response = asyncio.run(captured.ainvoke("prompt", config={"api_key": "never-store", "max_tokens": 4096}))

    assert response.content == "Bearer public-response"
    assert calls[0]["request"]["config"]["api_key"] == "[REDACTED]"
    assert calls[0]["request"]["config"]["max_tokens"] == 4096
    assert calls[0]["response"]["content"] == "Bearer [REDACTED]"
    assert calls[0]["response"]["attributes"] == {"content": "Bearer [REDACTED]"}
    assert calls[0]["elapsed_ms"] >= 0


def test_replay_requires_the_captured_request_shape() -> None:
    llm = replay.ReplayingLLM(
        [{"request": {"messages": "expected", "config": None, "response_format": None}, "response": {"content": "ok"}}]
    )

    with pytest.raises(replay.ReplayTraceError, match="request_mismatch"):
        asyncio.run(llm.ainvoke("different"))


def test_failing_generator_preserves_incrementally_captured_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "private-export.json"
    output_path = tmp_path / "private-capture.json"
    input_path.write_text(json.dumps(_export()), encoding="utf-8")

    class SyntheticClient:
        provider_names = ["synthetic"]

        def __init__(self, providers, temperature, max_tokens):
            assert temperature == 0.2
            assert max_tokens == 4096

        async def ainvoke(self, messages, config=None, response_format=None):
            return SimpleNamespace(content="captured synthetic response")

    async def failing_generator(llm, lesson, language="ru", compact=False):
        response = await llm.ainvoke("synthetic request", config={"max_tokens": 4096})
        assert response.content == "captured synthetic response"
        raise RuntimeError("synthetic generator failure")

    monkeypatch.setattr(replay, "_deepseek_llm_provider", lambda: object())
    monkeypatch.setattr(replay, "ResilientLLMClient", SyntheticClient)
    monkeypatch.setattr(replay, "generate_lesson_assessment", failing_generator)

    assert replay.main([
        "capture", "--input", str(input_path), "--output", str(output_path), "--lesson", "0", "1"
    ]) == 1

    trace = json.loads(output_path.read_text(encoding="utf-8"))
    assert trace["failure"]["type"] == "RuntimeError"
    assert trace["calls"][0]["request"]["config"]["max_tokens"] == 4096
    assert trace["calls"][0]["response"]["content"] == "captured synthetic response"
    assert trace["results"] == []


def test_refuses_to_overwrite_private_trace(tmp_path: Path) -> None:
    output_path = tmp_path / "existing-private-trace.json"
    output_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        replay.parse_args([
            "capture", "--input", str(tmp_path / "input.json"), "--output", str(output_path), "--lesson", "0", "1"
        ])


def test_final_audit_cli_requires_all_completed_checkpoint_set(tmp_path: Path) -> None:
    common = [
        "replay",
        "--stage",
        "final-audit",
        "--input",
        str(tmp_path / "input.json"),
        "--output",
        str(tmp_path / "output.json"),
        "--replay",
        str(tmp_path / "capture.json"),
    ]

    with pytest.raises(SystemExit, match="2"):
        replay.parse_args([*common, "--lesson", "0", "1"])

    args = replay.parse_args([*common, "--all-completed"])
    assert args.stage == "final-audit"
    assert args.all_completed is True


def test_final_audit_capture_uses_production_audit_token_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exported = _export()
    exported["checkpoints"][0].update(
        assessment_status="completed",
        assessment_payload=_assessment_payload(),
    )
    input_path = tmp_path / "private-export.json"
    output_path = tmp_path / "private-capture.json"
    input_path.write_text(json.dumps(exported), encoding="utf-8")

    class SyntheticClient:
        provider_names = ["synthetic"]

        def __init__(self, providers, temperature, max_tokens):
            assert temperature == 0.2
            assert max_tokens == 8192

    async def final_audit(*args, **kwargs):
        kwargs["output"].update(assessment={"assessments": []})

    monkeypatch.setattr(replay, "_deepseek_llm_provider", lambda: object())
    monkeypatch.setattr(replay, "ResilientLLMClient", SyntheticClient)
    monkeypatch.setattr(replay, "run_final_audit", final_audit)

    assert replay.main([
        "capture", "--stage", "final-audit", "--input", str(input_path),
        "--output", str(output_path), "--all-completed",
    ]) == 0
    trace = json.loads(output_path.read_text(encoding="utf-8"))
    assert trace["client"]["max_tokens"] == 8192


def test_all_completed_uses_course_generator_for_cross_lesson_fact_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = replay.select_lessons(_export(), module_order=None, lesson_order=None, all_completed=True)
    results: list[dict] = []
    class Assessment:
        def to_dict(self):
            return {"lesson_title": "Synthetic lesson", "mcq": []}

    async def course_generator(*, llm, course_content, language, compact, on_assessment_complete):
        assert [[lesson.title for lesson in module.lessons] for module in course_content.modules] == [["Synthetic lesson"]]
        await on_assessment_complete(0, 0, Assessment())

    monkeypatch.setattr(replay, "generate_course_assessment", course_generator)
    asyncio.run(replay.run_course_assessments(
        selected, llm=object(), language="ru", compact=False, results=results, flush=lambda: None
    ))

    assert results == [{
        "module_order": 0, "lesson_order": 1, "module_key": "module-000", "lesson_key": "lesson-000-001",
        "assessment": {"lesson_title": "Synthetic lesson", "mcq": []},
    }]


def test_all_completed_replay_skips_only_assessment_interlesson_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = replay.select_lessons(_export(), module_order=None, lesson_order=None, all_completed=True)
    original_asyncio = replay.assessment_module.asyncio

    async def course_generator(*, llm, course_content, language, compact, on_assessment_complete):
        await replay.assessment_module.asyncio.sleep(5)

    monkeypatch.setattr(replay, "generate_course_assessment", course_generator)
    started = time.perf_counter()
    asyncio.run(replay.run_course_assessments(
        selected, llm=object(), language="ru", compact=False, results=[], flush=lambda: None,
        skip_interlesson_pacing=True,
    ))

    assert time.perf_counter() - started < 0.1
    assert replay.assessment_module.asyncio is original_asyncio
