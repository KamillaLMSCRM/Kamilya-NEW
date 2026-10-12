"""Source-first synthetic benchmark; no DB, queue, deployment or external judge.

Default is offline planning, NOT a generation speed measurement. Live mode uses
the existing explicitly configured DeepSeek route with no provider failover.
Embedding retrieval is intentionally unavailable in this algorithm-only pilot.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUITE = ROOT / "apps/api/tests/fixtures/course_benchmark_v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def load_suite(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported_suite_schema")
    cases = payload["cases"]
    ids: set[str] = set()
    for case in cases:
        case_id = case["id"]
        if not re.fullmatch(r"[a-z0-9-]+", case_id) or case_id in ids:
            raise ValueError("invalid_or_duplicate_case_id")
        ids.add(case_id)
        if case["expected"] not in {"draft", "review"}:
            raise ValueError("invalid_expected_outcome")
        if case["split"] not in {"development", "holdout"}:
            raise ValueError("invalid_split")
        claim_ids = [claim["id"] for claim in case["required_claims"]]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("duplicate_claim_id")
        if any(not claim["quote"] or claim["quote"] not in case["source"]
               for claim in case["required_claims"]):
            raise ValueError("gold_quote_not_in_source")
        if any(not text or normalize(text) in normalize(case["source"])
               for text in case["forbidden_claims"]):
            raise ValueError("invalid_forbidden_claim")
        if Path(case["filename"]).name != case["filename"]:
            raise ValueError("unsafe_fixture_filename")
    return cases


def inspect_result(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Exact preservation and structural signals, never a semantic accuracy score.

    Missing exact text may be a valid paraphrase; a quote's presence cannot prove
    no contradiction elsewhere. Independent review is always required.
    """
    lessons = result["realized_course"]["lessons"]
    questions = result["realized_assessment"]["questions"]
    taught = normalize("\n".join(lesson["content"] for lesson in lessons))
    visible = normalize("\n".join([
        *(lesson["content"] for lesson in lessons),
        *(question.get("explanation", "") for question in questions),
        *(question.get("correct_answer", "") for question in questions),
        *(question.get("prompt", "") for question in questions),
    ]))
    matched = [claim["id"] for claim in case["required_claims"]
               if normalize(claim["quote"]) in taught]
    missing = [claim["id"] for claim in case["required_claims"] if claim["id"] not in matched]
    critical_missing = [claim["id"] for claim in case["required_claims"]
                        if claim["critical"] and claim["id"] in missing]
    defects: list[dict[str, str]] = []
    longest_keys = 0
    lesson_ids = {lesson["lesson_id"] for lesson in lessons}
    for question in questions:
        qid = question["question_id"]
        options = question["options"]
        key = question["correct_answer"]
        if len(options) < 2 or options.count(key) != 1:
            defects.append({"question_id": qid, "reason": "invalid_unique_key"})
        if len({normalize(option) for option in options}) != len(options):
            defects.append({"question_id": qid, "reason": "duplicate_options"})
        if question["lesson_id"] not in lesson_ids:
            defects.append({"question_id": qid, "reason": "foreign_lesson"})
        if options and key in options:
            lengths = [len(normalize(option)) for option in options]
            if lengths.count(max(lengths)) == 1 and len(normalize(key)) == max(lengths):
                longest_keys += 1
    forbidden = [claim for claim in case["forbidden_claims"] if normalize(claim) in visible]
    publishable = result.get("publishability", {}).get("publishable", False)
    return {
        "lessons": len(lessons), "questions": len(questions),
        "gold_claims": len(case["required_claims"]), "exact_quotes_present": len(matched),
        "exact_quote_recall": len(matched) / len(case["required_claims"])
        if case["required_claims"] else None,
        "missing_exact_claims": missing, "missing_critical_exact_claims": critical_missing,
        "structural_defects": defects, "forbidden_exact_claims_found": forbidden,
        "longest_answer_heuristic_hits": longest_keys,
        "longest_answer_heuristic_denominator": len(questions),
        "generator_publishable": publishable,
        "expected_review_but_generator_publishable": case["expected"] == "review" and publishable,
        "semantic_accuracy": None, "human_review_minutes": None,
        "independent_review": "NOT_REVIEWED", "marketing_ready": False,
        "scope": "literal preservation and structure only; not factual accuracy or learner effectiveness",
    }


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def runtime_identity() -> str:
    paths = sorted((ROOT / "apps/api/app/modules/ai").rglob("*.py"))
    paths += [Path(__file__), DEFAULT_SUITE]
    value = "\n".join(f"{path.relative_to(ROOT).as_posix()}:{digest(path)}" for path in paths)
    return hashlib.sha256(value.encode()).hexdigest()


def corpus_for_case(case: dict[str, Any]):
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.ingestion import DocumentChunker

    revision = "document:" + hashlib.sha256(case["source"].encode()).hexdigest()
    chunks = tuple(DirectSourceChunk(
        chunk_id=f"{case['id']}:{index}", doc_id=case["id"], doc_name=case["filename"],
        title=case["title"], headings=tuple(json.loads(chunk["metadata"].get("headings", "[]"))),
        text=chunk["text"], source_revision=revision, chunk_index=index,
        table_fragment=chunk["metadata"].get("worksheet_table_fragment"),
    ) for index, chunk in enumerate(DocumentChunker().chunk_markdown(
        case["source"], case["id"], case["filename"],
    )))
    return DirectSourceCorpus(
        tenant_id="synthetic-benchmark-no-database",
        documents=(DirectSourceDocument(
            doc_id=case["id"], title=case["title"], filename=case["filename"],
            category="training_material", source_revision=revision, chunks=chunks,
        ),), total_chars=len(case["source"]), total_chunks=len(chunks),
    )


async def run(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(ROOT / "apps/api"))
    if args.live:
        if args.env_file is None:
            raise ValueError("explicit_env_file_required")
        from scripts.dev.run_evidence_course_application import _load_env
        _load_env(args.env_file)
    from app.modules.ai.evidence_engine.application import build_evidence_source, generate_evidence_course
    from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.llm_client import AllProvidersFailedError, ResilientLLMClient

    suite_identity = digest(args.suite)
    cases = load_suite(args.suite)
    if args.case:
        cases = [case for case in cases if case["id"] in args.case]
        if {case["id"] for case in cases} != set(args.case):
            raise ValueError("unknown_case")
    if args.replay_dir:
        origin = json.loads((args.replay_dir / "manifest.json").read_text(encoding="utf-8"))
        if origin["suite_sha256"] != digest(args.suite):
            raise ValueError("replay_suite_identity_mismatch")
    provider = None
    if args.live:
        from app.modules.ai.llm_client import _deepseek_llm_provider
        provider = _deepseek_llm_provider()
        if provider is None:
            raise ValueError("configured_project_provider_missing")
        provider = replace(provider, max_retries=0, timeout=60)

    identity = runtime_identity()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    save(args.output_dir / "manifest.json", {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "suite_sha256": suite_identity, "runtime_sha256": identity,
        "case_ids": [case["id"] for case in cases],
        "mode": ("LIVE_GENERATION_ALGORITHM_ONLY" if args.live else
                 "CAPTURED_REPLAY_NOT_LIVE" if args.replay_dir else "OFFLINE_SOURCE_PLAN_ONLY"),
        "replay_origin_manifest_sha256": digest(args.replay_dir / "manifest.json") if args.replay_dir else None,
        "provider": provider.name if provider else None,
        "model_requested": provider.model if provider else None,
        "max_http_calls_per_case": args.max_calls, "case_timeout_seconds": args.timeout,
        "embedding_retrieval": "NOT_MEASURED", "conversion": "NOT_MEASURED",
        "queue_database_browser": "NOT_MEASURED", "human_comparison": "NOT_MEASURED",
        "gold_not_sent_to_provider": True, "external_judge": False,
    })

    class NoEmbedding:
        async def embed_documents_with_provenance(self, *_args, **_kwargs):
            raise AllProvidersFailedError("benchmark intentionally excludes retrieval")

    rows = []
    for case in cases:
        if digest(args.suite) != suite_identity:
            raise ValueError("suite_changed_during_benchmark")
        folder = args.output_dir / case["id"]
        folder.mkdir()
        (folder / case["filename"]).write_text(case["source"], encoding="utf-8")
        save(folder / "input.json", case)
        started, cpu_started = time.perf_counter(), time.process_time()
        row = {"case": case["id"], "split": case["split"], "level": case["level"],
               "type": case["type"], "expected": case["expected"],
               "source_words": len(case["source"].split()), "status": "NOT_COMPLETED",
               "mode": "live" if args.live else "captured_replay" if args.replay_dir else "offline_plan", "attempt": 1}
        recorder = None
        replay = None
        try:
            corpus = corpus_for_case(case)
            plan = EvidenceCourseEngine().generate_from_document(build_evidence_source(corpus).document)
            save(folder / "source-plan.json", plan.to_dict())
            row.update(planned_lessons=len(plan.course.lessons), admitted_facts=len(plan.admitted_facts))
            if not args.live and not args.replay_dir:
                row["status"] = "PLANNED_NOT_GENERATED"
            else:
                from scripts.dev.objective_alignment.run import Recorder, readable
                if args.replay_dir:
                    from scripts.dev.run_axis_owned_assessment_smoke import _CapturedReplay
                    replay = _CapturedReplay(args.replay_dir / case["id"] / "trace.json")
                    generation_client = replay
                else:
                    recorder = Recorder(ResilientLLMClient([provider], temperature=0.2, max_tokens=8192),
                                        max_calls=args.max_calls)
                    generation_client = recorder
                async with asyncio.timeout(args.timeout):
                    output = await generate_evidence_course(
                        corpus, intent=CourseIntent(), generation_client=generation_client,
                        embedding_client=NoEmbedding(),
                    )
                result = output.result.to_dict()
                save(folder / "result.json", result)
                save(folder / "signals.json", inspect_result(case, result))
                (folder / "review.md").write_text(readable(case, result), encoding="utf-8")
                row.update(status="GENERATED_PENDING_INDEPENDENT_REVIEW",
                           stages_seconds={timing.stage: round(timing.seconds, 3)
                                           for timing in output.result.timings})
        except Exception as error:
            row.update(status="FAILED", error_type=type(error).__name__)
            # Only closed application reasons, never provider bodies, credentials or URLs.
            if isinstance(error, ValueError) and str(error).startswith("evidence_"):
                row["application_reason"] = str(error)
        finally:
            row.update(wall_seconds=round(time.perf_counter() - started, 3),
                       cpu_seconds=round(time.process_time() - cpu_started, 3))
            if recorder:
                row.update(http_calls=recorder.calls, usage=recorder.usage if recorder.usage_responses else None,
                           usage_responses=recorder.usage_responses,
                           resolved_models=sorted(recorder.response_models), http_errors=recorder.http_errors,
                           token_details=recorder.token_details, actual_cost_usd=None)
                save(folder / "trace.json", recorder.trace)
                save(folder / "requests.json", recorder.requests)
            if replay:
                row.update(captured_calls=replay.captured_calls, http_calls=0,
                           live_fallback_calls=replay.live_fallback_calls, actual_cost_usd=0,
                           resolved_models=["captured-replay"])
                save(folder / "replay-trace.json", replay.trace)
            save(folder / "metrics.json", row)
            rows.append(row)
            save(args.output_dir / "metrics.json", rows)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        if digest(args.suite) != suite_identity:
            raise ValueError("suite_changed_during_benchmark")
        if runtime_identity() != identity:
            raise ValueError("runtime_changed_during_benchmark")
        if recorder and any(status in {401, 402, 403, 429} for status in recorder.http_errors):
            raise RuntimeError("provider_gate_failed_stop_batch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", action="append")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay-dir", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--max-calls", type=int, choices=range(1, 81), default=30)
    parser.add_argument("--timeout", type=int, choices=range(30, 901), default=360)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
