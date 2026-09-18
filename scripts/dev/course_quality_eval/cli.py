from __future__ import annotations

import argparse
import os
from pathlib import Path

from .adapters import CachedEvaluator, TypeSafeHTTPAdapter
from .artifact import load_artifact
from .evaluator import evaluate_generation
from .report import write_report
from .rubric import DEFAULT_RUBRIC


def _load_env_value(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Development-only TypeSafe evaluation of a frozen Kamilya course artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/course-quality-eval"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".codex/tmp/course-quality-eval-cache"))
    parser.add_argument("--live", action="store_true", help="Explicitly allow TypeSafe network calls on cache misses.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached answers; valid only with --live.")
    parser.add_argument("--env-file", type=Path, help="Optional local .env path; the key is loaded process-locally.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.refresh and not args.live:
        raise SystemExit("--refresh requires --live")
    delegate = None
    if args.live:
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key and args.env_file:
            api_key = _load_env_value(args.env_file, "TYPESAFE_API_KEY")
        delegate = TypeSafeHTTPAdapter(api_key=api_key or "")
    evaluator = CachedEvaluator(delegate, args.cache_dir, refresh=args.refresh)
    report = evaluate_generation(load_artifact(args.artifact), evaluator=evaluator, rubric=DEFAULT_RUBRIC)
    json_path, markdown_path = write_report(report, args.output_dir)
    print(f"decision={report.decision} enforcement={report.enforcement}")
    print(f"json={json_path.resolve()}")
    print(f"markdown={markdown_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
