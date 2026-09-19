import asyncio
import json
from pathlib import Path

from scripts.dev.run_axis_owned_assessment_smoke import _CapturedReplay


def _trace(path: Path) -> None:
    path.write_text(json.dumps([
        {"task": "assessment_review", "responses": [{"raw": json.dumps({
            "reviews": [{"question_id": "question-a", "accepted": True}],
        })}]},
        {"task": "assessment_review", "responses": [{"raw": json.dumps({
            "reviews": [{"question_id": "question-a", "accepted": False}],
        })}]},
        {"task": "assessment_review", "responses": [{"raw": json.dumps({
            "reviews": [{"question_id": "question-b", "accepted": True}],
        })}]},
    ]), encoding="utf-8")


def test_captured_replay_routes_assessment_responses_by_question_identity(tmp_path: Path) -> None:
    trace = tmp_path / "trace.json"
    _trace(trace)
    replay = _CapturedReplay(trace)

    async def invoke(question_id: str) -> bool:
        request = {"task": "assessment_review", "questions": [{"question_id": question_id}]}
        response = await replay.ainvoke_validated(
            [{"role": "user", "content": json.dumps(request)}],
            lambda raw: json.loads(raw)["reviews"][0]["accepted"],
        )
        return response.value

    assert asyncio.run(invoke("question-b")) is True
    assert asyncio.run(invoke("question-a")) is True
    assert asyncio.run(invoke("question-a")) is False


def test_captured_replay_uses_live_fallback_only_for_missing_stage(tmp_path: Path) -> None:
    trace = tmp_path / "trace.json"
    _trace(trace)

    class Fallback:
        async def ainvoke_validated(self, messages, parser, **_kwargs):
            request = json.loads(messages[-1]["content"])
            raw = json.dumps({"reviews": [{
                "question_id": request["questions"][0]["question_id"],
                "accepted": "fallback",
            }]})
            return type("Result", (), {
                "value": parser(raw), "attempt_count": 1,
                "model_id": "live-fixture", "provider": "live-fixture",
            })()

    replay = _CapturedReplay(trace, fallback=Fallback())
    request = {"task": "assessment_constraints", "questions": [{"question_id": "question-c"}]}
    response = asyncio.run(replay.ainvoke_validated(
        [{"role": "user", "content": json.dumps(request)}],
        lambda raw: json.loads(raw)["reviews"][0]["accepted"],
    ))

    assert response.value == "fallback"
    assert replay.captured_calls == 0
    assert replay.live_fallback_calls == 1


def test_captured_replay_combines_successive_checkpoint_traces(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps([{
        "task": "assessment_review",
        "responses": [{"raw": json.dumps({
            "reviews": [{"question_id": "question-a", "accepted": "first"}],
        })}],
    }]), encoding="utf-8")
    second.write_text(json.dumps([{
        "task": "assessment_review",
        "responses": [{"raw": json.dumps({
            "reviews": [{"question_id": "question-b", "accepted": "second"}],
        })}],
    }]), encoding="utf-8")
    replay = _CapturedReplay((first, second))

    async def invoke(question_id: str) -> str:
        request = {"task": "assessment_review", "questions": [{"question_id": question_id}]}
        response = await replay.ainvoke_validated(
            [{"role": "user", "content": json.dumps(request)}],
            lambda raw: json.loads(raw)["reviews"][0]["accepted"],
        )
        return response.value

    assert asyncio.run(invoke("question-a")) == "first"
    assert asyncio.run(invoke("question-b")) == "second"
    assert replay.captured_calls == 2
