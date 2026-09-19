"""One local assessment request from saved plan/teaching; never a whole-course retry."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from scripts.dev.objective_alignment.run import Recorder, digest, provider_config, save
from scripts.dev.objective_alignment.engine import Plan, Teaching, QUIZ_PROMPT, parse_quiz


def restored_payload(folder):
    trace = json.loads((folder / "trace.json").read_text(encoding="utf-8"))
    # This diagnostic is intentionally restricted to the first, unrepaired lesson.
    if [t["task"] for t in trace] != ["objective_plan", "objective_teaching", "objective_assessment"]:
        raise ValueError("Requires exactly the captured initial plan/teaching/failed-assessment sequence")
    if not trace[-1].get("error") or trace[-1]["responses"]:
        raise ValueError("Expected failed assessment without a returned response")
    plan = Plan.model_validate_json(trace[0]["responses"][-1]["raw"])
    teaching = Teaching.model_validate_json(trace[1]["responses"][-1]["raw"])
    source = json.loads((folder / "source-plan.json").read_text(encoding="utf-8"))
    ids = source["course"]["lessons"][0]["fact_ids"]
    facts = [f for f in source["admitted_facts"] if f["fact_id"] in ids]
    blocks = []
    for objective in plan.objectives:
        block = next(b for b in teaching.blocks if b.objective_id == objective.id)
        quotes = "\n".join(f"> {c.quote}" for c in objective.evidence)
        blocks.append(f"## {block.heading}\n\n{block.explanation}\n\n{block.application}\n\nОснование:\n{quotes}")
    content = "\n\n".join(blocks)
    return plan, content, {"task": "objective_assessment", "facts": facts,
                           "plan": plan.model_dump(), "lesson": content, "repair_feedback": ""}


async def main(args):
    if args.output_dir.exists():
        raise ValueError("Never overwrite attempt evidence")
    plan, content, payload = restored_payload(args.attempt)
    from app.modules.ai.llm_client import ResilientLLMClient
    cfg = provider_config({"provider": "asus-glm", "thinking": "native"})
    recorder = Recorder(ResilientLLMClient([cfg], temperature=0.2, max_tokens=8192), max_calls=1)
    save(args.output_dir / "manifest.json", {
        "model": cfg.model, "provider": cfg.name, "timeout_seconds": cfg.timeout, "max_tokens": 8192,
        "runner_sha256": digest(Path(__file__)), "prior_trace_sha256": digest(args.attempt / "trace.json"),
        "scope": "one failed stage only; native thinking; no paid fallback; no automatic repair"})
    started = time.perf_counter()
    status = "NOT_COMPLETED"
    try:
        answer = await recorder.ainvoke_validated(
            [{"role": "system", "content": QUIZ_PROMPT},
             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            parser=lambda raw: parse_quiz(raw, plan, content),
            response_format={"type": "json_object"}, repair_json_syntax=False)
        save(args.output_dir / "assessment.json", answer.value.model_dump())
        status = "COMPLETED_REQUIRES_SEMANTIC_REVIEW"
    except Exception as error:
        status = type(error).__name__
    finally:
        metrics = {"status": status, "seconds": round(time.perf_counter() - started, 3),
                   "calls": recorder.calls, "usage": recorder.usage if recorder.usage_responses else None,
                   "usage_responses": recorder.usage_responses, "token_details": recorder.token_details,
                   "response_models": sorted(recorder.response_models)}
        save(args.output_dir / "metrics.json", metrics)
        save(args.output_dir / "trace.json", recorder.trace)
        save(args.output_dir / "requests.json", recorder.requests)
        print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--attempt", type=Path, required=True)
    cli.add_argument("--output-dir", type=Path, required=True)
    asyncio.run(main(cli.parse_args()))
