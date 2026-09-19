"""Re-audit saved DEV artifacts without regenerating their lessons or questions."""
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

from scripts.dev.objective_alignment.run import Recorder, digest, provider_config, save  # noqa: E402
from scripts.dev.run_evidence_course_application import _load_env  # noqa: E402


async def main(args):
    if args.output_dir.exists():
        raise ValueError("Never overwrite previous audit")
    provider = getattr(args, "provider", "asus-glm")
    if provider == "deepseek":
        if not args.env_file:
            raise ValueError("Explicit --env-file required for DeepSeek")
        _load_env(args.env_file)
    from app.modules.ai.llm_client import ResilientLLMClient
    from scripts.dev.objective_alignment.engine import Quiz
    from scripts.dev.objective_alignment.review import REVIEW_PROMPT, audit_payload, filter_quiz, parse_audit

    source = json.loads(args.artifact.read_text(encoding="utf-8"))
    cfg = provider_config({"provider": provider, "thinking": "native" if provider == "asus-glm" else args.effort})
    recorder = Recorder(ResilientLLMClient([cfg], temperature=0.2, max_tokens=16384), max_calls=6)
    facts = {f["fact_id"]: f for f in source["evidence_result"]["admitted_facts"]}
    lessons = {lesson["lesson_id"]: lesson for lesson in source["realized_course"]["lessons"]}
    start = time.perf_counter()
    results = []
    try:
        for pack in source["packs"]:
            quiz = Quiz.model_validate(pack["assessment"])
            lesson = lessons[pack["lesson_id"]]
            payload = audit_payload({"facts": [facts[fid] for fid in lesson["fact_ids"]],
                                     "plan": pack["plan"]}, lesson["content"], quiz)
            result = await recorder.ainvoke_validated(
                [{"role": "system", "content": REVIEW_PROMPT},
                 {"role": "user", "content": json.dumps({"task": "captured_blind_audit", **payload}, ensure_ascii=False)}],
                parser=lambda raw: parse_audit(raw, quiz), response_format={"type": "json_object"},
                repair_json_syntax=False)
            filtered, rejected, removed = filter_quiz(quiz, result.value)
            results.append({"lesson_id": lesson["lesson_id"], "audit": result.value.model_dump(),
                            "rejected": rejected, "removed": removed, "retained": len(filtered.items)})
    finally:
        save(args.output_dir / "trace.json", recorder.trace)
        save(args.output_dir / "requests.json", recorder.requests)
        save(args.output_dir / "result.json", {"artifact_sha256": digest(args.artifact), "results": results,
                                               "provider": provider, "model": cfg.model,
                                               "token_details": recorder.token_details,
                                               "response_models": sorted(recorder.response_models),
                                               "calls": recorder.calls, "usage": recorder.usage,
                                               "seconds": round(time.perf_counter() - start, 3)})
    print(json.dumps({"packs": len(results), "calls": recorder.calls,
                      "seconds": round(time.perf_counter() - start, 3)}), flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--artifact", required=True, type=Path)
    cli.add_argument("--env-file", type=Path)
    cli.add_argument("--provider", choices=("asus-glm", "deepseek"), default="asus-glm")
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--effort", choices=("low", "high"), default="low")
    asyncio.run(main(cli.parse_args()))
