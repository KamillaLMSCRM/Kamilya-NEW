"""Evaluate completed synthetic pilot artifacts only; not a runtime dependency."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("experiment", type=Path)
    cli.add_argument("--env-file", type=Path)
    cli.add_argument("--typesafe-live", action="store_true")
    args = cli.parse_args()
    manifest = json.loads((args.experiment / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("scope") not in {
        "common source-plan packs; not an end-to-end production acceptance",
        "source-note preservation + objective packs; not end-to-end production acceptance",
    }:
        raise ValueError("Only this frozen synthetic experiment is authorized")
    reports = []
    for path in sorted(args.experiment.glob("*/*/run-*/*/metrics.json")):
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if metrics["case"] not in {"dev-policy", "dev-table", "h-policy", "h-table",
                                    "h2-small", "h2-policy", "h2-matrix", "h2-procedure",
                                    "h3-manufacturing", "h3-booking"}:
            raise ValueError("Unexpected/non-synthetic case")
        reports.append(metrics)
    destination = args.experiment / "typesafe"
    if args.typesafe_live:
        from scripts.dev.course_quality_eval.adapters import CachedEvaluator, TypeSafeHTTPAdapter
        from scripts.dev.course_quality_eval.artifact import load_artifact
        from scripts.dev.course_quality_eval.cli import _load_env_value
        from scripts.dev.course_quality_eval.evaluator import evaluate_generation
        from scripts.dev.course_quality_eval.report import write_report
        from scripts.dev.course_quality_eval.rubric import DEFAULT_RUBRIC

        if not args.env_file:
            raise ValueError("Explicit canonical env required")
        evaluator = CachedEvaluator(TypeSafeHTTPAdapter(
            api_key=_load_env_value(args.env_file, "TYPESAFE_API_KEY") or ""), destination / "cache")
        for path in sorted(args.experiment.glob("*/*/run-*/*/result.json")):
            relative = path.relative_to(args.experiment)
            output = destination / relative.parent
            if output.exists():
                raise ValueError("TypeSafe evidence exists; do not overwrite")
            try:
                report = evaluate_generation(load_artifact(path), evaluator=evaluator, rubric=DEFAULT_RUBRIC)
                write_report(report, output)
                print(json.dumps({"artifact": str(relative), "decision": report.decision,
                                  "usage": asdict(report.usage)}), flush=True)
            except Exception as error:
                output.mkdir(parents=True, exist_ok=True)
                (output / "error.json").write_text(json.dumps({"error": type(error).__name__}), encoding="utf-8")
                print(json.dumps({"artifact": str(relative), "error": type(error).__name__}), flush=True)
                raise  # No hidden retries, alternate credentials or ignored evaluator failures.
    print(json.dumps({"arms": len(reports), "completed": sum(r["status"] == "COMPLETED" for r in reports),
                      "seconds_sum": round(sum(r["seconds"] for r in reports), 3),
                      "calls": sum(r["calls"] for r in reports)}))


if __name__ == "__main__":
    main()
