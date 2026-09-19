"""Bounded local review of frozen known failures and one valid control."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from functools import partial
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/api")]
from scripts.dev.run_evidence_course_application import _load_env  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _load_env(args.env_file)
    from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact
    from app.modules.ai.evidence_engine.semantic_assessment import (
        REVIEW_PROMPT, CONSTRAINT_PROMPT, _parse_reviews, _review_request,
        _constraint_request, _parse_constraint_reviews,
        _unsupported_replacement_advice, _parse_questions,
    )
    from app.modules.ai.llm_client import ResilientLLMClient

    base = ROOT / "outputs/semantic-repair-20260918"
    source = json.loads((ROOT / "outputs/semantic-block-real-excel-final-20260918/plus-excel/run-1/result.json").read_text(encoding="utf-8"))
    first = json.loads((base / "final-plus-1.json").read_text(encoding="utf-8"))
    second = json.loads((base / "final-plus-2.json").read_text(encoding="utf-8"))
    synthetic = json.loads((base / "synthetic/independent-sections/run-1/result.json").read_text(encoding="utf-8"))
    cases = [("unsupported_explanation_removed", first["questions"][0], source, True),
             ("absurd_function_substitution", second["questions"][0], source, False),
             ("duplicate_misconception", synthetic["realized_assessment"]["questions"][0], synthetic, False),
             ("valid_mechanism_control", first["questions"][4], source, True)]
    client = await ResilientLLMClient.from_settings_async(temperature=0.2)
    report = []
    trace = []
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def persist(error=None):
        args.output.write_text(json.dumps({
            "candidate_sha256": hashlib.sha256((ROOT / "apps/api/app/modules/ai/evidence_engine/semantic_assessment.py").read_bytes()).hexdigest(),
            "cases": report, "error": error,
            "passed": len(report) == len(cases) and error is None
                and all(r["expected_accept"] == r["accepted"] for r in report),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    async def invoke(messages, parser):
        def captured(raw):
            entry = {"task": json.loads(messages[-1]["content"])["task"], "response": raw}
            try:
                return parser(raw)
            except (ValueError, TypeError, KeyError) as error:
                entry["validation_error"] = str(error)
                raise
            finally:
                trace.append(entry)
                args.output.with_suffix(".trace.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            return await client.ainvoke_validated(messages, parser=captured,
                response_format={"type": "json_object"}, repair_json_syntax=True)
        except Exception as error:
            persist(type(error).__name__)
            raise

    for label, raw, artifact, expected in cases:
        q = QuestionDraft(**raw)
        facts = [SourceFact(**f) for f in artifact["evidence_result"]["admitted_facts"]]
        # Replay the actual parsing boundary, not merely an already persisted
        # historical object. Canonical explanations must be checked evidence.
        q = _parse_questions(json.dumps({"questions": [{
            "prompt": q.prompt, "options": q.options,
            "correct_index": list(q.options).index(q.correct_answer),
            "explanation": q.explanation,
            "evidence": [{"fact_id": fid, "quote": next(f.value for f in facts if f.fact_id == fid)}
                         for fid in q.evidence_fact_ids],
        }]}), lesson_id=q.lesson_id, facts=facts, maximum=1, block_id=q.semantic_block_id)[0]
        assert q.explanation == q.source_quote
        request = _review_request(q.semantic_block_id, [q], facts)
        started = time.perf_counter()
        response = await invoke(
            [{"role": "system", "content": REVIEW_PROMPT},
             {"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
            parser=partial(_parse_reviews, questions=[q]))
        checked = response.value[q.question_id]
        reasons = list(response.value.reasons[q.question_id])
        if checked:
            block_ids = next(lesson["fact_ids"] for lesson in artifact["realized_course"]["lessons"] if lesson["lesson_id"] == q.lesson_id)
            block_facts = [f for f in facts if f.fact_id in block_ids]
            block = {"block_id": q.semantic_block_id, "facts": [
                {"fact_id": f.fact_id, "subject": f.subject, "attribute": f.attribute, "value": f.value}
                for f in block_facts]}
            constraints = await invoke(
                [{"role": "system", "content": CONSTRAINT_PROMPT},
                 {"role": "user", "content": json.dumps(_constraint_request(block, [q]), ensure_ascii=False)}],
                parser=partial(_parse_constraint_reviews, questions=[q], facts=block_facts))
            checked = constraints.value[q.question_id]
            reasons.extend(constraints.value.reasons[q.question_id])
            if _unsupported_replacement_advice(q, block_facts):
                checked = False
                reasons.append("unsupported_replacement_advice")
        report.append({"case": label, "question_id": q.question_id, "expected_accept": expected,
                       "accepted": checked, "reasons": reasons,
                       "explanation": q.explanation,
                       "seconds": round(time.perf_counter()-started, 3)})
        print(json.dumps(report[-1]), flush=True)
        persist()


if __name__ == "__main__":
    asyncio.run(main())
