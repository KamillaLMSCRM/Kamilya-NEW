#!/usr/bin/env python3
"""Privately capture or deterministically replay lesson-assessment model calls.

The input and capture files can contain lesson and generated model content. Keep
them outside the repository and do not attach them to tickets or test fixtures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Protocol

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.modules.ai import assessment as assessment_module
from app.modules.ai.assessment import generate_course_assessment, generate_lesson_assessment
from app.modules.ai.assessment_completion import finalize_course_assessment
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.llm_client import ResilientLLMClient, _deepseek_llm_provider
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent

TRACE_VERSION = 1
_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token)(?:$|[_-])",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]+")


class AssessmentLLM(Protocol):
    async def ainvoke(
        self,
        messages: str | list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Any: ...


class ReplayTraceError(RuntimeError):
    """A capture file cannot reproduce exactly the calls assessment requested."""


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"trace value is not JSON serializable: {type(value).__name__}")


def _redact(value: Any, *, key: str | None = None) -> Any:
    """Retain complete request/response shape while removing credential values."""
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): _redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", value)
    return value


def _error_detail(exc: BaseException) -> str:
    return _BEARER.sub("Bearer [REDACTED]", "".join(traceback.format_exception(exc)))


def _checkpoint_complete(checkpoint: Mapping[str, Any]) -> bool:
    return checkpoint.get("content_status", "completed") == "completed" and isinstance(
        checkpoint.get("content_payload"), Mapping
    )


def select_lessons(
    exported: Mapping[str, Any],
    *,
    module_order: int | None,
    lesson_order: int | None,
    all_completed: bool,
) -> list[dict[str, Any]]:
    checkpoints = exported.get("checkpoints")
    if not isinstance(checkpoints, list):
        raise ReplayTraceError("invalid_export_checkpoints")
    if all_completed == (module_order is not None or lesson_order is not None):
        raise ReplayTraceError("choose_all_completed_or_exact_lesson")
    if (module_order is None) != (lesson_order is None):
        raise ReplayTraceError("lesson_selector_requires_module_and_lesson_order")

    selected: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, Mapping):
            raise ReplayTraceError("invalid_export_checkpoint")
        if not _checkpoint_complete(checkpoint):
            continue
        if not all_completed and (
            checkpoint.get("module_order") != module_order or checkpoint.get("lesson_order") != lesson_order
        ):
            continue
        content_payload = checkpoint["content_payload"]
        assert isinstance(content_payload, Mapping)
        try:
            lesson = LessonContent.from_dict(dict(content_payload))
        except (TypeError, ValueError) as exc:
            raise ReplayTraceError("invalid_lesson_content_payload") from exc
        selected.append(
            {
                "module_order": checkpoint.get("module_order"),
                "lesson_order": checkpoint.get("lesson_order"),
                "module_key": checkpoint.get("module_key"),
                "lesson_key": checkpoint.get("lesson_key"),
                "lesson": lesson,
            }
        )
    if not selected:
        raise ReplayTraceError("no_completed_lesson_matches_selector")
    if not all_completed and len(selected) != 1:
        raise ReplayTraceError("lesson_selector_is_ambiguous")
    return selected


def select_course_for_audit(exported: Mapping[str, Any]) -> tuple[CourseContent, CourseAssessment]:
    """Rebuild the exact completed checkpoint set needed by the final audit.

    Pending and intentionally omitted lessons are outside the audit. A lesson
    whose content completed without a persisted assessment is not replayable and
    fails closed instead of silently changing the course under test.
    """
    checkpoints = exported.get("checkpoints")
    if not isinstance(checkpoints, list):
        raise ReplayTraceError("invalid_export_checkpoints")
    grouped: dict[int, list[tuple[int, LessonContent, LessonAssessment]]] = {}
    coordinates: set[tuple[int, int]] = set()
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, Mapping):
            raise ReplayTraceError("invalid_export_checkpoint")
        content_status = checkpoint.get("content_status", "completed")
        if content_status in {"pending", "omitted"}:
            continue
        if content_status != "completed" or not isinstance(checkpoint.get("content_payload"), Mapping):
            raise ReplayTraceError("invalid_completed_lesson_content")
        if checkpoint.get("assessment_status") != "completed" or not isinstance(
            checkpoint.get("assessment_payload"), Mapping
        ):
            raise ReplayTraceError("completed_lesson_missing_assessment")
        module_order = checkpoint.get("module_order")
        lesson_order = checkpoint.get("lesson_order")
        if not isinstance(module_order, int) or not isinstance(lesson_order, int):
            raise ReplayTraceError("completed_lesson_missing_stable_order")
        coordinate = (module_order, lesson_order)
        if coordinate in coordinates:
            raise ReplayTraceError("duplicate_completed_lesson_coordinate")
        coordinates.add(coordinate)
        try:
            lesson = LessonContent.from_dict(dict(checkpoint["content_payload"]))
            assessment = LessonAssessment.from_dict(dict(checkpoint["assessment_payload"]))
        except (TypeError, ValueError) as exc:
            raise ReplayTraceError("invalid_audit_checkpoint_payload") from exc
        if assessment.lesson_title != lesson.title:
            raise ReplayTraceError("audit_checkpoint_lesson_title_mismatch")
        grouped.setdefault(module_order, []).append((lesson_order, lesson, assessment))
    if not grouped:
        raise ReplayTraceError("no_completed_assessments_for_audit")
    course_modules: list[ModuleContent] = []
    assessments: list[LessonAssessment] = []
    for module_order, items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda item: item[0])
        course_modules.append(
            ModuleContent(title=f"module-{module_order}", lessons=[lesson for _order, lesson, _item in ordered])
        )
        assessments.extend(item for _order, _lesson, item in ordered)
    return (
        CourseContent(title="Private final-audit replay", modules=course_modules),
        CourseAssessment(assessments=assessments),
    )


class CapturingLLM:
    def __init__(self, inner: AssessmentLLM, calls: list[dict[str, Any]], flush: Callable[[], None]):
        self._inner = inner
        self._calls = calls
        self._flush = flush

    async def ainvoke(self, messages: str | list[dict[str, Any]], config: dict[str, Any] | None = None,
                      response_format: dict[str, Any] | None = None) -> Any:
        started = time.perf_counter()
        call: dict[str, Any] = {
            "request": _redact(_json_value({"messages": messages, "config": config, "response_format": response_format})),
        }
        self._calls.append(call)
        try:
            response = await self._inner.ainvoke(messages, config=config, response_format=response_format)
            content = getattr(response, "content", None)
            if not isinstance(content, str):
                raise ReplayTraceError("llm_response_content_is_not_string")
            attributes = vars(response) if hasattr(response, "__dict__") else {"content": content}
            response_attributes = _redact(_json_value(attributes))
            if not isinstance(response_attributes, Mapping):  # Defensive: the trace contract is an object.
                raise ReplayTraceError("llm_response_attributes_are_not_object")
            call["response"] = {
                "type": type(response).__name__,
                "attributes": dict(response_attributes),
                "content": _redact(content),
            }
            return response
        except BaseException as exc:
            call["exception"] = {"type": type(exc).__name__, "detail": _error_detail(exc)}
            raise
        finally:
            call["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            self._flush()


class ReplayingLLM:
    def __init__(self, calls: list[Mapping[str, Any]]):
        self._calls = calls
        self._index = 0

    async def ainvoke(self, messages: str | list[dict[str, Any]], config: dict[str, Any] | None = None,
                      response_format: dict[str, Any] | None = None) -> Any:
        if self._index >= len(self._calls):
            raise ReplayTraceError("replay_responses_exhausted")
        call = self._calls[self._index]
        self._index += 1
        expected = call.get("request")
        actual = _redact(_json_value({"messages": messages, "config": config, "response_format": response_format}))
        if expected != actual:
            raise ReplayTraceError(f"replay_request_mismatch_at_call_{self._index}")
        exception = call.get("exception")
        if isinstance(exception, Mapping):
            raise ReplayTraceError(f"captured_call_failed_{self._index}_{exception.get('type', 'unknown')}")
        response = call.get("response")
        if not isinstance(response, Mapping) or not isinstance(response.get("content"), str):
            raise ReplayTraceError(f"invalid_replay_response_at_call_{self._index}")
        attributes = response.get("attributes", {"content": response["content"]})
        if not isinstance(attributes, Mapping) or not isinstance(attributes.get("content"), str):
            raise ReplayTraceError(f"invalid_replay_response_attributes_at_call_{self._index}")
        return SimpleNamespace(**dict(attributes))

    def assert_consumed(self) -> None:
        if self._index != len(self._calls):
            raise ReplayTraceError(f"replay_responses_unconsumed_{len(self._calls) - self._index}")


async def run_assessments(
    lessons: list[dict[str, Any]],
    *,
    llm: AssessmentLLM,
    language: str,
    compact: bool,
    results: list[dict[str, Any]],
    flush: Callable[[], None],
) -> list[dict[str, Any]]:
    for item in lessons:
        assessment = await generate_lesson_assessment(
            llm, item["lesson"], language=language, compact=compact
        )
        results.append(
            {
                "module_order": item["module_order"],
                "lesson_order": item["lesson_order"],
                "module_key": item["module_key"],
                "lesson_key": item["lesson_key"],
                "assessment": assessment.to_dict(),
            }
        )
        flush()
    return results


async def run_course_assessments(
    lessons: list[dict[str, Any]], *, llm: AssessmentLLM, language: str, compact: bool,
    results: list[dict[str, Any]], flush: Callable[[], None], skip_interlesson_pacing: bool = False,
) -> None:
    """Use production's sequential course flow so tested facts cross lessons."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in lessons:
        module_order = item["module_order"]
        if not isinstance(module_order, int):
            raise ReplayTraceError("completed_lesson_missing_module_order")
        grouped.setdefault(module_order, []).append(item)
    ordered_groups = [(order, sorted(items, key=lambda item: item["lesson_order"])) for order, items in sorted(grouped.items())]
    course = CourseContent(
        title="Private assessment replay",
        modules=[ModuleContent(title=f"module-{order}", lessons=[item["lesson"] for item in items]) for order, items in ordered_groups],
    )

    async def record(module_index: int, lesson_index: int, assessment: Any) -> None:
        item = ordered_groups[module_index][1][lesson_index]
        results.append({
            "module_order": item["module_order"], "lesson_order": item["lesson_order"],
            "module_key": item["module_key"], "lesson_key": item["lesson_key"],
            "assessment": assessment.to_dict(),
        })
        flush()

    if not skip_interlesson_pacing:
        await generate_course_assessment(
            llm=llm, course_content=course, language=language, compact=compact,
            on_assessment_complete=record,
        )
        return

    async def no_pacing_sleep(_delay: float) -> None:
        return None

    original_asyncio = assessment_module.asyncio
    assessment_module.asyncio = SimpleNamespace(sleep=no_pacing_sleep)
    try:
        await generate_course_assessment(
            llm=llm, course_content=course, language=language, compact=compact,
            on_assessment_complete=record,
        )
    finally:
        assessment_module.asyncio = original_asyncio


async def run_final_audit(
    course: CourseContent,
    assessment: CourseAssessment,
    *,
    llm: AssessmentLLM,
    language: str,
    compact: bool,
    output: dict[str, Any],
    flush: Callable[[], None],
) -> None:
    """Run only the production final-audit/supplement seam from checkpoints."""
    result = await finalize_course_assessment(
        llm,
        course,
        assessment,
        language=language,
        compact=compact,
    )
    output.update(
        {
            "assessment": result.assessment.to_dict(),
            "decisions": _json_value(result.decisions),
            "uncovered_objectives": _json_value(result.uncovered_objectives),
            "uncovered_content_objectives": _json_value(result.uncovered_content_objectives),
        }
    )
    flush()


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, Mapping):
        raise ReplayTraceError("export_must_be_json_object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(value, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")


def _summary(mode: str, results: list[dict[str, Any]], calls: list[dict[str, Any]], elapsed_ms: float) -> dict[str, Any]:
    return {
        "status_code": "ok",
        "mode": mode,
        "lesson_count": len(results),
        "call_count": len(calls),
        "assessment_types": [type(item["assessment"]).__name__ for item in results],
        "response_types": [
            call["response"].get("type", "unknown")
            for call in calls
            if isinstance(call.get("response"), Mapping)
        ],
        "error_types": [
            call["exception"].get("type", "unknown")
            for call in calls
            if isinstance(call.get("exception"), Mapping)
        ],
        "elapsed_ms": round(elapsed_ms, 3),
    }


async def _main_async(args: argparse.Namespace, trace: dict[str, Any], flush: Callable[[], None]) -> dict[str, Any]:
    exported = _read_json(args.input)
    if args.stage == "final-audit":
        course, assessment = select_course_for_audit(exported)
        lessons: list[dict[str, Any]] = []
        selected = [
            {
                "module_order": module_index,
                "lesson_order": lesson_index,
                "lesson_title": lesson.title,
            }
            for module_index, module in enumerate(course.modules)
            for lesson_index, lesson in enumerate(module.lessons)
        ]
    else:
        lessons = select_lessons(
            exported, module_order=args.module_order, lesson_order=args.lesson_order, all_completed=args.all_completed
        )
        selected = [
            {key: item[key] for key in ("module_order", "lesson_order", "module_key", "lesson_key")}
            for item in lessons
        ]
    started = time.perf_counter()
    trace.update(
        {
            "stage": args.stage,
            "selected": selected,
            "calls": [],
            "results": [],
            **({"audit": {}} if args.stage == "final-audit" else {}),
        }
    )
    flush()
    calls: list[dict[str, Any]] = trace["calls"]
    results: list[dict[str, Any]] = trace["results"]
    if args.mode == "capture":
        # Keep the assessment's production wrapper so provider-specific response
        # format conversion remains identical, but avoid the tenant/DB factory.
        # The operator must establish the authorized process-local provider
        # settings before starting this offline checkpoint harness.
        provider = _deepseek_llm_provider()
        if provider is None:
            raise ReplayTraceError("deepseek_provider_not_configured")
        max_tokens = 8192 if args.stage == "final-audit" else 4096
        inner = ResilientLLMClient(providers=[provider], temperature=0.2, max_tokens=max_tokens)
        trace["client"] = {
            "type": "ResilientLLMClient",
            "provider_names": inner.provider_names,
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        flush()
        llm: AssessmentLLM = CapturingLLM(inner, calls, flush)
        if args.stage == "final-audit":
            await run_final_audit(
                course,
                assessment,
                llm=llm,
                language=args.language,
                compact=args.compact,
                output=trace["audit"],
                flush=flush,
            )
        else:
            runner = run_course_assessments if args.all_completed else run_assessments
            await runner(lessons, llm=llm, language=args.language,
                         compact=args.compact, results=results, flush=flush)
    else:
        replay = _read_json(args.replay)
        raw_calls = replay.get("calls")
        if not isinstance(raw_calls, list) or not all(isinstance(call, Mapping) for call in raw_calls):
            raise ReplayTraceError("invalid_replay_calls")
        calls.extend(dict(call) for call in raw_calls)
        llm = ReplayingLLM(calls)
        trace["client"] = {"type": "replay", "provider_names": ["replay"]}
        flush()
        if args.stage == "final-audit":
            await run_final_audit(
                course,
                assessment,
                llm=llm,
                language=args.language,
                compact=args.compact,
                output=trace["audit"],
                flush=flush,
            )
        else:
            runner = run_course_assessments if args.all_completed else run_assessments
            await runner(lessons, llm=llm, language=args.language, compact=args.compact, results=results, flush=flush,
                         **({"skip_interlesson_pacing": True} if args.all_completed else {}))
        llm.assert_consumed()
    elapsed_ms = (time.perf_counter() - started) * 1000
    trace["summary"] = _summary(args.mode, results, calls, elapsed_ms)
    trace["summary"]["stage"] = args.stage
    if args.stage == "final-audit":
        trace["summary"]["lesson_count"] = len(selected)
    flush()
    return trace


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "replay"))
    parser.add_argument("--stage", choices=("assessment", "final-audit"), default="assessment")
    parser.add_argument("--input", required=True, type=Path, help="Private exported checkpoint JSON")
    parser.add_argument("--output", required=True, type=Path, help="Private capture/replay output JSON")
    parser.add_argument("--replay", type=Path, help="Private capture JSON; required for replay")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--all-completed", action="store_true")
    selector.add_argument("--lesson", nargs=2, type=int, metavar=("MODULE_ORDER", "LESSON_ORDER"))
    parser.add_argument("--language", default="ru")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    args.module_order, args.lesson_order = (args.lesson if args.lesson else (None, None))
    if args.mode == "replay" and args.replay is None:
        parser.error("replay requires --replay PRIVATE_CAPTURE.json")
    if args.mode == "capture" and args.replay is not None:
        parser.error("capture does not accept --replay")
    if args.stage == "final-audit" and not args.all_completed:
        parser.error("final-audit requires --all-completed")
    if args.output.exists():
        parser.error("refusing to overwrite existing private output; choose a distinct --output path")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    trace: dict[str, Any] = {
        "trace_version": TRACE_VERSION,
        "mode": args.mode,
        "stage": args.stage,
        "calls": [],
        "results": [],
    }
    started = time.perf_counter()

    def flush() -> None:
        _write_json(args.output, trace)

    try:
        trace = asyncio.run(_main_async(args, trace, flush))
    except BaseException as exc:
        trace["failure"] = {"type": type(exc).__name__, "detail": _error_detail(exc)}
        trace["summary"] = {
            "status_code": "failed",
            "mode": args.mode,
            "stage": args.stage,
            "call_count": len(trace["calls"]),
            "lesson_count": len(trace["results"]),
            "error_types": [type(exc).__name__],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        flush()
        print(f"FAILED mode={args.mode} error_type={type(exc).__name__}", file=sys.stderr)
        return 1
    _write_json(args.output, trace)
    print(json.dumps(trace["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
