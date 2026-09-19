"""Bounded full-source local replay after synthetic acceptance. No DB or deploy."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from scripts.dev.objective_alignment.run import (  # noqa: E402
    Recorder, digest, experiment_fingerprint, fingerprint, provider_config, readable, save,
)
from scripts.dev.run_evidence_course_application import (  # noqa: E402
    _converted_pdf_corpus, _load_env, _xlsx_corpus,
)


def validate_inputs(args):
    if args.output_dir.exists():
        raise ValueError("New output directory required; preserve previous evidence")
    if not args.source.is_file() or args.source.suffix.lower() not in (".xlsx", ".pdf"):
        raise ValueError("An existing XLSX/PDF source file is required")
    if args.source.suffix.lower() == ".pdf" and (not args.converter_json or not args.converter_json.is_file()):
        raise ValueError("PDF requires an existing local production converter capture")


async def main(args):
    validate_inputs(args)
    provider = getattr(args, "provider", "asus-glm")
    thinking = "native" if provider == "asus-glm" else "selective"
    if provider == "deepseek":
        if not args.env_file:
            raise ValueError("Explicit --env-file required for DeepSeek")
        _load_env(args.env_file)
    from scripts.dev.objective_alignment.source import build_complete_source
    from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
    from app.modules.ai.llm_client import ResilientLLMClient
    from scripts.dev.objective_alignment.engine import generate

    cfg = provider_config({"provider": provider, "thinking": thinking})
    lesson_timeout = 1800 if provider == "asus-glm" else 480
    course_timeout = 7200 if provider == "asus-glm" else 2400
    manifest = {"runtime": fingerprint(), "experiment": experiment_fingerprint(),
                "runner_sha256": digest(Path(__file__)), "input_sha256": digest(args.source),
                "converter_capture_sha256": digest(args.converter_json) if args.converter_json else None,
                "scope": "local full source; captured production PDF conversion; no persistence or embeddings",
                "provider": provider, "model": cfg.model, "thinking": thinking, "repeats": args.repeats,
                "concurrency": 3, "per_lesson_calls": 18, "per_lesson_seconds": lesson_timeout,
                "per_course_seconds": course_timeout, "semantic_acceptance": "REQUIRES_REVIEW"}
    save(args.output_dir / "manifest.json", manifest)
    started = time.perf_counter()
    corpus = (await _xlsx_corpus(args.source) if args.source.suffix.lower() == ".xlsx"
              else await _converted_pdf_corpus(args.source, args.converter_json))
    source = build_complete_source(corpus)
    plan = EvidenceCourseEngine().generate_from_document(source.document)
    preparation = round(time.perf_counter() - started, 3)
    save(args.output_dir / "source-plan.json", plan.to_dict())
    facts = {f.fact_id: f for f in plan.admitted_facts}
    lessons = list(plan.course.lessons)
    print(json.dumps({"source_preparation_seconds": preparation, "lessons": len(lessons),
                      "facts": len(facts), "input_sha256": manifest["input_sha256"]}), flush=True)
    if args.prepare_only:
        print(json.dumps({"generation": "NOT_RUN", "provider_calls": 0}), flush=True)
        return
    for repeat in range(1, args.repeats + 1):
        folder = args.output_dir / f"run-{repeat}"
        semaphore = asyncio.Semaphore(3)
        fatal_status = []

        async def lesson_run(index, lesson):
            async with semaphore:
                if fatal_status:
                    skipped = {"index": index, "lesson_id": lesson.lesson_id, "title": lesson.title,
                               "status": "NOT_STARTED_PROVIDER_UNAVAILABLE", "seconds": 0, "calls": 0,
                               "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
                    save(folder / "lessons" / f"{index:02d}" / "metrics.json", skipped)
                    return skipped, None
                recorder = Recorder(ResilientLLMClient([cfg], temperature=0.2, max_tokens=16384),
                                    max_calls=18, thinking=thinking)
                leaf = folder / "lessons" / f"{index:02d}"
                start = time.perf_counter()
                metrics = {"index": index, "lesson_id": lesson.lesson_id, "title": lesson.title,
                           "status": "NOT_COMPLETED"}
                result = None
                try:
                    async with asyncio.timeout(lesson_timeout):
                        result = await generate([lesson], facts, recorder,
                            checkpoint=lambda pack: save(leaf / "checkpoint.json", pack))
                        save(leaf / "result.json", result)
                        unresolved = any(result["packs"][0].get("unresolved", {}).values())
                        metrics.update(status="COMPLETED_WITH_GAPS" if unresolved else "COMPLETED",
                                       questions=len(result["realized_assessment"]["questions"]))
                except Exception as error:
                    metrics["error"] = type(error).__name__
                finally:
                    metrics.update(seconds=round(time.perf_counter() - start, 3), calls=recorder.calls,
                                   usage=recorder.usage,
                                   token_details=recorder.token_details,
                                   response_models=sorted(recorder.response_models),
                                   http_errors=recorder.http_errors,
                                   stages_seconds={task: round(sum(t["seconds"] for t in recorder.trace if t["task"] == task), 3)
                                                   for task in dict.fromkeys(t["task"] for t in recorder.trace)})
                    save(leaf / "trace.json", recorder.trace)
                    save(leaf / "requests.json", recorder.requests)
                    save(leaf / "metrics.json", metrics)
                    fatal_status.extend(status for status in recorder.http_errors if status in (401, 402, 403))
                    print(json.dumps(metrics, ensure_ascii=False), flush=True)
                return metrics, result

        start = time.perf_counter()
        async with asyncio.timeout(course_timeout):
            outcomes = await asyncio.gather(*(lesson_run(i, lesson) for i, lesson in enumerate(lessons, 1)))
        combined = {"mode": "experimental_full_source_requires_review",
                    "evidence_result": plan.to_dict(), "realized_course": {"lessons": []},
                    "realized_assessment": {"questions": []}, "packs": []}
        for _, result in outcomes:
            if result:
                combined["realized_course"]["lessons"].extend(result["realized_course"]["lessons"])
                combined["realized_assessment"]["questions"].extend(result["realized_assessment"]["questions"])
                combined["packs"].extend(result["packs"])
        save(folder / "result.json", combined)
        case = {"title": args.source.stem, "source": "Полный источник: " + args.source.name}
        (folder / "review.md").write_text(readable(case, combined), encoding="utf-8")
        metrics = {"repeat": repeat, "seconds": round(time.perf_counter() - start, 3),
                   "preparation_seconds": preparation, "planned_lessons": len(lessons),
                   "completed_lessons": len(combined["realized_course"]["lessons"]),
                   "questions": len(combined["realized_assessment"]["questions"]),
                   "failures": [m for m, _ in outcomes if m["status"] != "COMPLETED"],
                   "calls": sum(m["calls"] for m, _ in outcomes),
                   "usage": {key: sum(m["usage"][key] for m, _ in outcomes)
                             for key in ("prompt_tokens", "completion_tokens")}}
        save(folder / "metrics.json", metrics)
        print(json.dumps({"course_summary": metrics}, ensure_ascii=False), flush=True)
        if fingerprint() != manifest["runtime"] or experiment_fingerprint() != manifest["experiment"]:
            raise ValueError("source_changed_during_full_replay")
        if fatal_status:
            print(json.dumps({"stopped": "provider_auth_or_balance_unavailable", "http_status": fatal_status[0]}), flush=True)
            break


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", required=True, type=Path)
    cli.add_argument("--converter-json", type=Path)
    cli.add_argument("--env-file", type=Path)
    cli.add_argument("--provider", choices=("asus-glm", "deepseek"), default="asus-glm")
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--repeats", type=int, choices=(1, 2), default=2)
    cli.add_argument("--prepare-only", action="store_true", help="Source preparation only, zero model requests")
    options = cli.parse_args()
    if options.source.suffix.lower() not in (".xlsx", ".pdf"):
        cli.error("Only the existing XLSX/PDF seams are supported")
    if options.source.suffix.lower() == ".pdf" and not options.converter_json:
        cli.error("Explicit captured production conversion is required; no remote converter invocation")
    asyncio.run(main(options))
