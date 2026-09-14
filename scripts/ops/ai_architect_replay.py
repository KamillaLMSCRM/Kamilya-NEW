"""Private capture and offline replay for direct-source architect calls.

This utility intentionally stops at architecture.  It converts an explicitly
named local original through the product converter, creates the normal source
passport/sizing result, then runs ``run_direct_architect``.  Capture files are
private evidence: they contain complete prompts and responses. They may be
stored outside the checkout or in the owner-authorized release-evidence scope.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
DEFAULT_GUIDANCE = (
    "Compare Phoenix, Chicago Neo, and Chicago Street. Treat the primary worksheet "
    "Коллекции as the course subject; use auxiliary nomenclature only as examples."
)
TRACE_VERSION = 1
AUTHORIZED_RELEASE_EVIDENCE = REPOSITORY_ROOT / ".release-evidence"
OFFLINE_REPLAY_JWT_SECRET = "offline-replay-jwt-secret-not-for-deployment"


def _sha256(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _prepare_offline_replay_environment(mode: str) -> None:
    """Supply the minimum process-local config needed to import offline replay code.

    This is deliberately limited to no-network replay modes. Capture continues to
    require the operator's approved environment and never receives this fallback.
    """

    if mode in {"replay", "replay-architecture"}:
        os.environ.setdefault("JWT_SECRET", OFFLINE_REPLAY_JWT_SECRET)


def _private_output_path(path: Path) -> Path:
    """Allow external private evidence or the owner-authorized ignored scope only."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        return resolved
    authorized_relative = AUTHORIZED_RELEASE_EVIDENCE.relative_to(REPOSITORY_ROOT).parts
    if relative.parts[: len(authorized_relative)] == authorized_relative and resolved.suffix == ".json":
        return resolved
    raise ValueError("private_evidence_path_not_authorized")


def _write_private_json(path: Path, value: dict[str, Any], *, create_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if create_only:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    else:
        path.write_text(serialized, encoding="utf-8")
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


class _LocalStorage:
    def __init__(self, source: Path) -> None:
        self._source = source

    def get_bytes(self, key: str) -> bytes:
        if key != "original":
            raise ValueError("unexpected_local_source_key")
        return self._source.read_bytes()


class _LocalConverter:
    async def convert(self, path: str) -> dict[str, Any]:
        from app.modules.ai.ingestion import _local_convert

        return await _local_convert(path)


class _CaptureLLM:
    def __init__(self, inner: Any, trace: dict[str, Any], trace_path: Path) -> None:
        self._inner = inner
        self._trace = trace
        self._trace_path = trace_path

    async def ainvoke(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        request = {"messages": messages, "kwargs": kwargs}
        entry: dict[str, Any] = {
            "index": len(self._trace["calls"]),
            "request": request,
            "request_sha256": _sha256(json.dumps(request, ensure_ascii=False, sort_keys=True)),
        }
        # Map calls run concurrently. Reserve the sequence before awaiting so
        # response-completion timing can never duplicate or reorder call IDs.
        self._trace["calls"].append(entry)
        _write_private_json(self._trace_path, self._trace)
        started = time.perf_counter()
        try:
            response = await self._inner.ainvoke(messages, **kwargs)
        except BaseException as exc:
            entry["exception"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
            entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            _write_private_json(self._trace_path, self._trace)
            raise
        content = str(response.content or "")
        entry["response"] = {"content": content}
        entry["response_sha256"] = _sha256(content)
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        _write_private_json(self._trace_path, self._trace)
        return response


class _ReplayLLM:
    def __init__(self, trace: dict[str, Any]) -> None:
        self._calls = trace["calls"]
        self._index = 0

    async def ainvoke(self, messages: list[dict[str, Any]], **kwargs: Any) -> SimpleNamespace:
        if self._index >= len(self._calls):
            raise AssertionError("replay_trace_exhausted_before_architect_completed")
        entry = self._calls[self._index]
        request = {"messages": messages, "kwargs": kwargs}
        actual_hash = _sha256(json.dumps(request, ensure_ascii=False, sort_keys=True))
        if actual_hash != entry.get("request_sha256"):
            raise AssertionError(f"replay_request_hash_mismatch_at_call_{self._index}")
        if "exception" in entry:
            self._index += 1
            raise RuntimeError(f"replayed_provider_exception:{entry['exception']['type']}")
        self._index += 1
        return SimpleNamespace(content=entry["response"]["content"])

    def assert_consumed(self) -> None:
        if self._index != len(self._calls):
            raise AssertionError(f"replay_unconsumed_calls:{len(self._calls) - self._index}")


def _architecture_stage(trace: dict[str, Any], *, response_limit: int | None = None) -> tuple[list[dict[str, Any]], str]:
    """Extract only ordered architect calls and the completed map context they used.

    This is deliberately not a full replay: legacy concurrent source-map entries
    may have been persisted in response-completion order. The returned architect
    calls remain strict because their request hashes are replayed in sequence.
    """

    calls = trace.get("calls")
    if not isinstance(calls, list):
        raise ValueError("replay_trace_calls_missing")
    architecture_calls = [
        entry for entry in calls
        if isinstance(entry, dict)
        and isinstance(entry.get("request"), dict)
        and isinstance(entry["request"].get("messages"), list)
        and entry["request"]["messages"]
        and isinstance(entry["request"]["messages"][0], dict)
        and "You are the course architect" in str(entry["request"]["messages"][0].get("content", ""))
    ]
    if not architecture_calls:
        raise ValueError("replay_architecture_stage_missing")
    if response_limit is not None:
        if response_limit < 1:
            raise ValueError("replay_architecture_response_limit_invalid")
        architecture_calls = architecture_calls[:response_limit]
    messages = architecture_calls[0]["request"]["messages"]
    user_messages = [message for message in messages if isinstance(message, dict) and message.get("role") == "user"]
    if not user_messages:
        raise ValueError("replay_architecture_user_prompt_missing")
    prefix = "SELECTED SOURCES:\n"
    prompt = str(user_messages[-1].get("content", ""))
    if prefix not in prompt:
        raise ValueError("replay_architecture_context_missing")
    # ``user_prompt`` adds one newline after ``{context}``; the captured prompt
    # therefore contains that template delimiter, not part of the map context.
    context = prompt.split(prefix, 1)[1]
    if context.endswith("\n"):
        context = context[:-1]
    return architecture_calls, context


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("capture", "replay", "replay-architecture", "capture-architecture"), required=True)
    parser.add_argument("--source", required=True, type=Path, help="Original local XLSX; never copied into evidence.")
    parser.add_argument("--trace", required=True, type=Path, help="Private complete request/response JSON.")
    parser.add_argument("--capture-trace", type=Path, help="New trace for --mode capture-architecture.")
    parser.add_argument("--result", type=Path, help="Private structural result JSON.")
    parser.add_argument("--architecture-response-limit", type=int, help="Strict replay subset of architect responses.")
    parser.add_argument("--document-id", default="local-replay-source")
    parser.add_argument("--document-title", default="Local architect replay source")
    parser.add_argument("--tenant-id", default="local-replay")
    parser.add_argument("--job-options", type=Path, help="Exported worker job options JSON.")
    parser.add_argument("--job-id", help="Exact job id in --job-options; inferred only from document id when unique.")
    parser.add_argument("--guidance", default=DEFAULT_GUIDANCE)
    parser.add_argument("--target-audience", default="")
    parser.add_argument("--goals-json", default="[]")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--course-hours", type=float)
    parser.add_argument("--num-modules", type=int)
    parser.add_argument("--lessons-per-module", type=int)
    parser.add_argument("--max-total-lessons", type=int)
    parser.add_argument("--source-strategy", default="single_topic")
    parser.add_argument("--combination-goal", default="")
    parser.add_argument("--model-max-tokens", type=int, default=8192)
    return parser


def _parse_goals(raw: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("goals_json_must_be_a_json_array_of_strings")
    return value


def _selected_job_params(path: Path, *, job_id: str | None, document_id: str) -> tuple[str, dict[str, Any]]:
    """Return one exported job's params without accepting an ambiguous selection."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("job_options_jobs_missing")
    matches = [
        job for job in jobs
        if isinstance(job, dict)
        and isinstance(job.get("id"), str)
        and isinstance(job.get("params"), dict)
        and (job["id"] == job_id if job_id else document_id in job["params"].get("documents", ()))
    ]
    if len(matches) != 1:
        raise ValueError("job_options_selection_ambiguous_or_missing")
    return matches[0]["id"], dict(matches[0]["params"])


async def _build_corpus(source: Path, *, document_id: str, document_title: str, tenant_id: str) -> Any:
    from app.modules.ai.direct_source import build_direct_source_corpus

    blob = source.read_bytes()
    digest = _sha256(blob)
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        lifecycle_status="active",
        content_sha256=digest,
        s3_key="original",
        size=len(blob),
        filename=source.name,
        title=document_title,
        category="general",
    )
    return await build_direct_source_corpus(
        [document], tenant_id=tenant_id, storage=_LocalStorage(source), converter=_LocalConverter()
    )


def _model_identity(llm: Any) -> dict[str, Any]:
    clients = getattr(llm, "_clients", ())
    return {
        "provider_names": list(getattr(llm, "provider_names", ())),
        "models": [str(client.config.model) for client in clients],
        "route_fingerprint": llm.cache_fingerprint(),
    }


def _primary_resilient_client_from_settings(*, max_tokens: int) -> Any:
    """Keep the production ``ainvoke`` adapter but bind capture to one explicit route.

    ``ResilientLLMClient`` owns provider-specific response-format conversion.  We
    intentionally derive the first configured provider from its synchronous
    settings path, then create a single-provider client with that exact config.
    This never consults the async DB routing/provider-key factory.
    """

    from app.modules.ai.llm_client import ResilientLLMClient

    configured = ResilientLLMClient.from_settings(max_tokens=max_tokens)
    primary_config = configured._clients[0].config
    return ResilientLLMClient([primary_config], max_tokens=max_tokens)


def _course_structure_schema_hash() -> str:
    """Hash the dataclass wire shape without assuming a Pydantic schema API."""

    schema = {
        "CourseStructure": {"title": "str", "description": "str", "modules": "list[Module]"},
        "Module": {"title": "str", "description": "str", "lessons": "list[Lesson]"},
        "Lesson": {
            "title": "str", "description": "str", "objectives": "list[LearningObjective]",
            "source_doc_ids": "list[str]", "relevant_headings": "list[str]",
        },
        "LearningObjective": {"text": "str"},
    }
    return _sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")))


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    _prepare_offline_replay_environment(args.mode)
    if not args.source.is_file():
        raise ValueError("source_file_not_found")
    trace_path = _private_output_path(args.trace)
    if args.mode == "capture-architecture":
        if args.capture_trace is None:
            raise ValueError("capture_architecture_trace_required")
        capture_trace_path = _private_output_path(args.capture_trace)
    else:
        if args.capture_trace is not None:
            raise ValueError("capture_trace_only_valid_for_capture_architecture")
        capture_trace_path = trace_path
    result_default = capture_trace_path.with_suffix(".result.json")
    result_path = _private_output_path(args.result or result_default)
    if capture_trace_path == result_path:
        raise ValueError("trace_and_result_paths_must_differ")
    if args.mode in {"capture", "capture-architecture"} and (capture_trace_path.exists() or result_path.exists()):
        raise FileExistsError("capture_evidence_already_exists")
    goals = _parse_goals(args.goals_json)
    selected_job_id: str | None = None
    selected_job_params: dict[str, Any] | None = None
    if args.job_options is not None:
        selected_job_id, selected_job_params = _selected_job_params(
            args.job_options, job_id=args.job_id, document_id=args.document_id
        )
        if selected_job_params.get("documents") != [args.document_id]:
            raise ValueError("job_options_document_identity_mismatch")
    elif args.job_id is not None:
        raise ValueError("job_id_requires_job_options")
    corpus = await _build_corpus(
        args.source, document_id=args.document_id, document_title=args.document_title, tenant_id=args.tenant_id
    )
    from app.modules.ai import direct_source as direct_source_module
    from app.modules.ai.direct_source import DirectSourceError, run_direct_architect
    from app.modules.ai.document_passport import build_document_passport
    from app.modules.ai.pipeline import _direct_source_structure_plan
    from app.modules.ai.source_analysis import recommend_course_structure

    passport = build_document_passport(corpus)
    run_options = {
        "goals": goals, "course_hours": args.course_hours, "num_modules": args.num_modules,
        "lessons_per_module": args.lessons_per_module, "max_total_lessons": args.max_total_lessons,
        "language": args.language, "guidance": args.guidance, "target_audience": args.target_audience,
        "source_strategy": args.source_strategy, "combination_goal": args.combination_goal,
    }
    worker_plan: Any | None = None
    if selected_job_params is not None:
        source_analysis = selected_job_params.get("source_analysis")
        if not isinstance(source_analysis, dict):
            raise ValueError("job_options_source_analysis_missing")
        course_intent = selected_job_params.get("course_intent")
        target_audience = selected_job_params.get("target_audience")
        if not isinstance(course_intent, str) or not isinstance(target_audience, str):
            raise ValueError("job_options_architect_inputs_missing")
        worker_plan = _direct_source_structure_plan(corpus, source_analysis)
        if worker_plan is None:
            raise ValueError("job_options_worker_structure_plan_missing")
        run_options.update(
            language=str(selected_job_params.get("language") or "ru"),
            guidance=course_intent,
            target_audience=target_audience,
            source_strategy=str(selected_job_params.get("source_strategy") or "single_topic"),
            combination_goal=str(selected_job_params.get("combination_goal") or ""),
            num_modules=worker_plan.module_count,
            lessons_per_module=worker_plan.lessons_per_module,
            max_total_lessons=worker_plan.hard_max_total_lessons,
        )
        sizing = worker_plan
    else:
        sizing = recommend_course_structure(
            total_chunks=corpus.total_chunks, document_count=len(corpus.documents), source_passport=passport
        )
    base_evidence = {
        "version": TRACE_VERSION,
        "source": {"sha256": _sha256(args.source.read_bytes()), "bytes": args.source.stat().st_size},
        "document": {"id": args.document_id, "title": args.document_title, "tenant_id": args.tenant_id},
        "passport": asdict(passport),
        "sizing": asdict(sizing),
        "worker_structure_plan": asdict(worker_plan) if worker_plan is not None else None,
        "job_options": (
            {"id": selected_job_id, "params": selected_job_params} if selected_job_params is not None else None
        ),
        "run_options": run_options,
        "schema_hashes": {
            "course_structure": _course_structure_schema_hash(),
            "captured_request": _sha256("messages+kwargs:v1"),
            "captured_response": _sha256("content:v1"),
        },
    }
    replay_scope = "full"
    original_architect_context: Any | None = None
    if args.mode == "capture":
        inner = _primary_resilient_client_from_settings(max_tokens=args.model_max_tokens)
        trace = {**base_evidence, "mode": "capture", "model_identity": _model_identity(inner), "calls": []}
        _write_private_json(capture_trace_path, trace, create_only=True)
        llm: Any = _CaptureLLM(inner, trace, capture_trace_path)
    else:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        if trace.get("version") != TRACE_VERSION or trace.get("source") != base_evidence["source"]:
            raise ValueError("replay_trace_source_or_version_mismatch")
        if trace.get("document") != base_evidence["document"]:
            raise ValueError("replay_trace_document_identity_mismatch")
        if trace.get("job_options") != base_evidence["job_options"]:
            raise ValueError("replay_trace_job_options_mismatch")
        if trace.get("run_options") != run_options:
            raise ValueError("replay_trace_options_mismatch")
        if args.mode in {"replay-architecture", "capture-architecture"}:
            architecture_calls, captured_context = _architecture_stage(
                trace, response_limit=args.architecture_response_limit
            )

            async def _captured_architect_context(*_args: Any, **_kwargs: Any) -> str:
                return captured_context

            original_architect_context = direct_source_module._architect_context
            direct_source_module._architect_context = _captured_architect_context
            if args.mode == "capture-architecture":
                inner = _primary_resilient_client_from_settings(max_tokens=args.model_max_tokens)
                fresh_trace = {
                    **base_evidence,
                    "mode": "capture-architecture",
                    "prefix_trace": str(trace_path),
                    "prefix_architecture_call_count": len(architecture_calls),
                    "model_identity": _model_identity(inner),
                    "calls": [],
                }
                _write_private_json(capture_trace_path, fresh_trace, create_only=True)
                trace = fresh_trace
                llm = _CaptureLLM(inner, trace, capture_trace_path)
                replay_scope = "cached_map_prefix_fresh_architecture_capture"
            else:
                llm = _ReplayLLM({"calls": architecture_calls})
                replay_scope = (
                    "architecture_first_response_strict"
                    if args.architecture_response_limit == 1
                    else "architecture_only_strict_requests"
                )
        else:
            llm = _ReplayLLM(trace)
    result: dict[str, Any] = {
        **base_evidence, "mode": args.mode, "trace": str(capture_trace_path), "replay_scope": replay_scope,
    }
    try:
        structure = await run_direct_architect(llm, corpus, **run_options)
        result["structure"] = asdict(structure)
        result["outcome"] = "success"
    except DirectSourceError as exc:
        result["outcome"] = "direct_source_error"
        result["exception"] = {"code": exc.code, "document_ids": list(exc.document_ids)}
    except BaseException as exc:
        result["outcome"] = "exception"
        result["exception"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
    finally:
        if args.mode in {"replay", "replay-architecture"}:
            llm.assert_consumed()
        if original_architect_context is not None:
            direct_source_module._architect_context = original_architect_context
    _write_private_json(result_path, result, create_only=args.mode in {"capture", "capture-architecture"})
    print(json.dumps({
        "mode": args.mode, "outcome": result["outcome"], "captured_calls": len(trace["calls"]),
        "replay_scope": replay_scope,
        "source_sha256": base_evidence["source"]["sha256"], "result_sha256": _sha256(json.dumps(result, ensure_ascii=False, sort_keys=True)),
    }, ensure_ascii=False))
    return result


def main() -> int:
    sys.path.insert(0, str(API_ROOT))
    try:
        result = asyncio.run(_run(_parser().parse_args()))
    except (AssertionError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"outcome": "harness_error", "error": type(exc).__name__, "detail": str(exc)[:500]}))
        return 2
    return 0 if result["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
