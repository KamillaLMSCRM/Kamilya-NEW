"""Local assessment-only replay of an existing artifact; never writes courses."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import asdict
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from scripts.dev.run_evidence_course_application import _load_env  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--regenerate-assessment", action="store_true")
    args = parser.parse_args()
    _load_env(args.env_file)
    from app.modules.ai.evidence_engine.models import LessonDraft, QuestionDraft, SourceFact
    from app.modules.ai.evidence_engine.semantic_assessment import (
        CONSTRAINT_PROMPT, REVIEW_PROMPT, _constraint_request, _parse_constraint_reviews,
        _parse_reviews, _review_request, generate_block_assessment,
    )
    from app.modules.ai.llm_client import ResilientLLMClient

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    facts = {f["fact_id"]: f for f in artifact["evidence_result"]["admitted_facts"]}
    client = await ResilientLLMClient.from_settings_async(temperature=0.2)
    trace = []

    class CapturedClient:
        async def ainvoke_validated(self, messages, parser, **kwargs):
            def captured(raw):
                entry = {"task": json.loads(messages[-1]["content"]).get("task"), "response": raw}
                trace.append(entry)
                try:
                    return parser(raw)
                except (ValueError, TypeError, KeyError) as error:
                    entry["validation_error"] = str(error)
                    raise
                finally:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.with_suffix(".trace.json").write_text(
                        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            return await client.ainvoke_validated(messages, parser=captured, **kwargs)

    captured_client = CapturedClient()
    if args.regenerate_assessment:
        fingerprint_paths = ["apps/api/app/modules/ai/evidence_engine/semantic_assessment.py",
                             "apps/api/app/modules/ai/evidence_engine/assessment_coverage.py",
                             "apps/api/app/modules/ai/llm_client.py",
                             "apps/api/app/modules/ai/evidence_engine/source_blocks.py",
                             "apps/api/app/modules/ai/evidence_engine/application.py"]
        fingerprints = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                        for path in fingerprint_paths}
        started = time.perf_counter()
        async def progress(done, total):
            print(json.dumps({"blocks_done": done, "blocks_total": total,
                              "seconds": round(time.perf_counter() - started, 3)}), flush=True)
        result = await generate_block_assessment(
            [LessonDraft(**lesson) for lesson in artifact["realized_course"]["lessons"]],
            {fid: SourceFact(**fact) for fid, fact in facts.items()}, captured_client, on_progress=progress)
        report = {"mode": "assessment_only", "seconds": round(time.perf_counter() - started, 3),
                  "candidate_sha256": fingerprints,
                  "source_artifact_sha256": hashlib.sha256(args.artifact.read_bytes()).hexdigest(),
                  **asdict(result)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"seconds": report["seconds"], "audit": {
            key: result.audit[key] for key in ("candidates", "accepted", "repaired", "dropped", "failures", "coverage")}}))
        return
    reports = []
    for raw in artifact["realized_assessment"]["questions"]:
        for field in ("options", "evidence_fact_ids", "distractor_fact_ids"):
            if field in raw:
                raw[field] = tuple(raw[field])
        q = QuestionDraft(**raw)
        request = {"task": "assessment_review", "block_id": q.semantic_block_id,
                   "facts": [facts[fid] for fid in q.evidence_fact_ids or (q.fact_id,)],
                   "questions": [{"question_id": q.question_id, "prompt": q.prompt,
                                  "options": q.options, "explanation": q.explanation,
                                  "source_quote": q.source_quote,
                                  "evidence_fact_ids": q.evidence_fact_ids}]}
        review = _review_request(q.semantic_block_id, [q], [SourceFact(**f) for f in request["facts"]])
        result = await captured_client.ainvoke_validated(
            [{"role": "system", "content": REVIEW_PROMPT},
             {"role": "user", "content": json.dumps(review, ensure_ascii=False)}],
            parser=partial(_parse_reviews, questions=[q]), response_format={"type": "json_object"})
        constraints = await captured_client.ainvoke_validated(
            [{"role": "system", "content": CONSTRAINT_PROMPT},
             {"role": "user", "content": json.dumps(_constraint_request(request, [q]), ensure_ascii=False)}],
            parser=partial(_parse_constraint_reviews, questions=[q],
                           facts=[SourceFact(**f) for f in request["facts"]]),
            response_format={"type": "json_object"})
        reports.append({"question_id": q.question_id,
                        "general_review": result.value[q.question_id],
                        "constraint_review": constraints.value[q.question_id],
                        "accepted": result.value[q.question_id] and constraints.value[q.question_id]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"reviewed": len(reports), "accepted": sum(row["accepted"] for row in reports)}))


if __name__ == "__main__":
    asyncio.run(main())
