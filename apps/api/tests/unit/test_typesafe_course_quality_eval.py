from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.dev.course_quality_eval import (  # noqa: E402
    DEFAULT_RUBRIC,
    AdapterResult,
    CachedEvaluator,
    CacheMissError,
    EvaluationRequest,
    PrivacyViolation,
    TypeSafeHTTPAdapter,
    evaluate_generation,
    load_artifact,
    render_markdown,
    write_report,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "course_quality_eval_synthetic.json"


class ScenarioEvaluator:
    def __init__(self) -> None:
        self.calls: list[EvaluationRequest] = []

    def evaluate(self, request: EvaluationRequest) -> AdapterResult:
        self.calls.append(request)
        if request.state["kind"] == "lesson":
            answers: dict[str, dict[str, Any]] = {
                "claims_supported": {"type": "noul", "noul": 0.94},
                "objective_alignment": {"type": "noul", "noul": 0.91},
                "coherent_focus": {"type": "noul", "noul": 0.88},
                "mostly_source_repetition": {"type": "noul", "noul": 0.10},
                "practical_value": {
                    "type": "score",
                    "score": 2.4,
                    "confidence": 0.77,
                    "legend": {"0": "none", "1": "limited", "2": "useful", "3": "strong"},
                    "probabilities": {"0": 0.02, "1": 0.12, "2": 0.32, "3": 0.54},
                },
            }
        else:
            ambiguous = "Плавно и тихо" in request.state["options"]
            answers = {
                "source_support": {"type": "noul", "noul": 0.96},
                "exactly_one_correct": {"type": "noul", "noul": 0.91 if not ambiguous else 0.58},
                "distractors_distinct": {"type": "noul", "noul": 0.89 if not ambiguous else 0.11},
                "distractors_plausible": {"type": "noul", "noul": 0.71},
                "atomic": {"type": "noul", "noul": 0.93},
                "explanation_grounded": {"type": "noul", "noul": 0.90},
                "educational_value": {
                    "type": "score",
                    "score": 2.1,
                    "confidence": 0.72,
                    "legend": {"0": "none", "1": "weak", "2": "useful", "3": "strong"},
                    "probabilities": {"0": 0.03, "1": 0.18, "2": 0.45, "3": 0.34},
                },
            }
        return AdapterResult(model="jev-1.13.0", answers=answers, input_tokens=120, output_tokens=0, latency_ms=15)


def test_public_seam_parses_artifact_and_composes_policy_in_code() -> None:
    artifact = load_artifact(FIXTURE)
    evaluator = ScenarioEvaluator()

    report = evaluate_generation(artifact, evaluator=evaluator, rubric=DEFAULT_RUBRIC)

    assert report.artifact.course_title == "Синтетический курс по мебели"
    assert len(report.lessons) == 1
    assert len(report.questions) == 2
    assert report.questions[0].decision == "pass"
    assert report.questions[1].decision == "reject"
    assert "exactly_one_correct" in report.questions[1].reasons
    assert "distractors_distinct" in report.questions[1].reasons
    assert report.decision == "reject"
    assert report.enforcement == "report_only"
    assert report.usage.input_tokens == 360
    assert report.usage.live_calls == 3
    assert report.usage.cache_hits == 0
    assert len(evaluator.calls) == 3


def test_loader_accepts_provider_backed_evidence_result(tmp_path: Path) -> None:
    payload = {
        "evidence_result": {
            "document_plan": {"source_sha256": "b" * 64},
            "admitted_facts": [
                {
                    "fact_id": "fact-1",
                    "subject": "Коллекция Север",
                    "attribute": "Помещение",
                    "value": "Предназначена для прихожей",
                    "source_locator": "Лист Коллекции, строка 2",
                }
            ],
        },
        "realized_course": {
            "title": "Синтетический evidence-курс",
            "description": "",
            "lessons": [
                {
                    "lesson_id": "lesson-1",
                    "module_title": "Коллекции",
                    "title": "Коллекция Север",
                    "objective": "Определить назначение",
                    "content": "Коллекция Север предназначена для прихожей.",
                    "fact_ids": ["fact-1"],
                    "supporting_fact_ids": [],
                    "duration_minutes": 5,
                }
            ],
        },
        "realized_assessment": {
            "questions": [
                {
                    "question_id": "question-1",
                    "lesson_id": "lesson-1",
                    "kind": "single_choice",
                    "prompt": "Для какого помещения предназначена коллекция Север?",
                    "options": ["Для прихожей", "Для кухни", "Для ванной"],
                    "correct_answer": "Для прихожей",
                    "explanation": "Это прямо указано в источнике.",
                    "fact_id": "fact-1",
                }
            ]
        },
    }
    path = tmp_path / "provider-result.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    artifact = load_artifact(path)

    assert artifact.identity.course_title == "Синтетический evidence-курс"
    assert artifact.identity.source_sha256 == "b" * 64
    assert artifact.lessons[0].source == (
        "Раздел: Коллекция Север\nАтрибут: Помещение\nФакт: Предназначена для прихожей"
    )
    assert artifact.questions[0].correct_indexes == (0,)
    assert artifact.questions[0].source == artifact.lessons[0].source


def test_privacy_preflight_blocks_customer_identifiers_before_adapter_call(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["course"]["modules"][0]["lessons"][0]["content"] += " Автор: person@example.kz"
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    evaluator = ScenarioEvaluator()

    with pytest.raises(PrivacyViolation, match="email"):
        evaluate_generation(load_artifact(unsafe), evaluator=evaluator, rubric=DEFAULT_RUBRIC)

    assert evaluator.calls == []


def test_cache_replays_without_sending_state_or_calling_live_adapter(tmp_path: Path) -> None:
    live = ScenarioEvaluator()
    cached = CachedEvaluator(live, tmp_path / "cache")
    artifact = load_artifact(FIXTURE)

    first = evaluate_generation(artifact, evaluator=cached, rubric=DEFAULT_RUBRIC)
    call_count = len(live.calls)
    replay = evaluate_generation(
        artifact,
        evaluator=CachedEvaluator(None, tmp_path / "cache"),
        rubric=DEFAULT_RUBRIC,
    )

    assert replay.decision == first.decision
    assert len(live.calls) == call_count
    assert replay.usage.live_calls == 0
    assert replay.usage.cache_hits == 3
    assert replay.usage.estimated_cost_usd == 0.0
    assert replay.usage.provider_latency_ms == first.usage.provider_latency_ms
    cache_text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "cache").glob("*.json"))
    assert "Коллекция Север" not in cache_text


def test_cache_only_mode_fails_closed_on_miss(tmp_path: Path) -> None:
    request = EvaluationRequest(model="jev-1.13.0", state={"kind": "lesson"}, questions={})

    with pytest.raises(CacheMissError):
        CachedEvaluator(None, tmp_path / "cache").evaluate(request)


def test_http_adapter_uses_documented_wire_shape_and_retries_overload() -> None:
    calls: list[dict[str, Any]] = []
    responses: list[tuple[int, dict[str, Any], dict[str, str]]] = [
        (529, {"detail": "overloaded"}, {"Retry-After": "0"}),
        (
            200,
            {
                "model": "jev-1.13.0",
                "answers": {"supported": {"type": "noul", "noul": 0.87}},
                "usage": {"input_tokens": 42, "output_tokens": 0},
            },
            {},
        ),
    ]

    def transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any], dict[str, str]]:
        calls.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return responses.pop(0)

    adapter = TypeSafeHTTPAdapter(api_key="secret-value", transport=transport, sleep=lambda _seconds: None)
    result = adapter.evaluate(
        EvaluationRequest(
            model="jev-1.13.0",
            state={"source": "Synthetic fact", "claim": "Synthetic claim"},
            questions={"supported": {"type": "noul", "instructions": "Is the claim supported?"}},
        )
    )

    assert len(calls) == 2
    assert calls[0]["url"] == "https://api.typesafe.ai/v1/systemone"
    assert calls[0]["payload"]["questions"]["supported"]["type"] == "noul"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-value"
    assert result.answers["supported"]["noul"] == 0.87
    assert result.input_tokens == 42


def test_reports_are_machine_readable_and_human_readable(tmp_path: Path) -> None:
    report = evaluate_generation(load_artifact(FIXTURE), evaluator=ScenarioEvaluator(), rubric=DEFAULT_RUBRIC)

    json_path, markdown_path = write_report(report, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert payload["rubric_version"] == "typesafe-course-quality-v1"
    assert payload["enforcement"] == "report_only"
    assert "## Вопросы" in markdown
    assert "Плавно и тихо" not in markdown
    assert render_markdown(report) == markdown


def test_typesafe_is_absent_from_real_client_runtime() -> None:
    forbidden = ("TYPESAFE_API_KEY", "api.typesafe.ai", "course_quality_eval")
    violations: list[str] = []
    for root in (REPO_ROOT / "apps" / "api" / "app", REPO_ROOT / "apps" / "web" / "src"):
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                text = path.read_text(encoding="utf-8")
                if any(marker in text for marker in forbidden):
                    violations.append(str(path.relative_to(REPO_ROOT)))
    assert violations == []
