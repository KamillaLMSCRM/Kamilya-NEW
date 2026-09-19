"""Offline validation replay. Never fills missing stages or promotes a failed run."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from app.modules.ai.evidence_engine.models import SourceFact  # noqa: E402
from scripts.dev.objective_alignment.engine import parse_plan, parse_quiz, parse_teaching  # noqa: E402


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("experiment", type=Path)
    args = cli.parse_args()
    cases = []
    for path in sorted(args.experiment.glob("*/*/run-*/B/trace.json")):
        source = json.loads(path.with_name("source-plan.json").read_text(encoding="utf-8"))
        all_facts = {f["fact_id"]: SourceFact(**f) for f in source["admitted_facts"]}
        groups = iter(source["course"]["lessons"])
        events = []
        plan, content = None, ""
        for event in json.loads(path.read_text(encoding="utf-8")):
            if not event["responses"]:
                continue
            raw = event["responses"][-1]["raw"]
            try:
                if event["task"] == "objective_plan":
                    group = next(groups)
                    plan = parse_plan(raw, {fid: all_facts[fid] for fid in group["fact_ids"]})
                elif event["task"] == "objective_teaching":
                    teaching = parse_teaching(raw, plan)
                    by_id = {b.objective_id: b for b in teaching.blocks}
                    blocks = []
                    for objective in plan.objectives:
                        block = by_id[objective.id]
                        quotes = "\n".join(f"> {c.quote}" for c in objective.evidence)
                        blocks.append(f"## {block.heading}\n\n{block.explanation}\n\n{block.application}\n\nОснование:\n{quotes}")
                    content = "\n\n".join(blocks)
                elif event["task"] == "objective_assessment":
                    parse_quiz(raw, plan, content)
                events.append({"task": event["task"], "validation": "PASS_NOT_SEMANTIC_ACCEPTANCE"})
            except ValueError as error:
                events.append({"task": event["task"], "validation": "REJECT", "reason": str(error)})
                break
        cases.append({"trace": str(path.relative_to(args.experiment)), "events": events,
                      "original_metrics_unchanged": True, "missing_stages_not_generated": True})
    report = {"mode": "offline_existing_responses_only", "calls": 0, "cases": cases,
              "current_engine_sha256": hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()}
    destination = args.experiment / "offline-validator-replay.json"
    if destination.exists():
        raise ValueError("replay evidence exists")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(cases), "provider_calls": 0, "report": str(destination)}))


if __name__ == "__main__":
    main()
