"""Summarize one or more local Evidence V2 replay artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))

from app.modules.ai.evidence_engine.replay_diagnostics import (  # noqa: E402
    summarize_assessment_replay,
)


def compare_replay_artifacts(
    artifacts: Sequence[Path],
    *,
    question_cap: int,
    same_source_permutations: bool = False,
) -> dict[str, object]:
    """Compare local artifacts without assuming unrelated sources are permutations."""

    runs = [
        {
            "artifact": str(path.resolve()),
            "diagnostics": summarize_assessment_replay(
                json.loads(path.read_text(encoding="utf-8")),
                question_cap=question_cap,
            ),
        }
        for path in artifacts
    ]
    fingerprints = {
        run["diagnostics"]["question_fingerprint"]  # type: ignore[index]
        for run in runs
    }
    fingerprints_equal = len(fingerprints) <= 1
    return {
        "policy": "evidence-v2-replay-comparison-v1",
        "run_count": len(runs),
        "same_source_permutations": same_source_permutations,
        "fingerprints_equal": fingerprints_equal,
        "permutation_stable": (
            fingerprints_equal if same_source_permutations else None
        ),
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--question-cap", type=int, default=3)
    parser.add_argument(
        "--same-source-permutations",
        action="store_true",
        help="Declare that all artifacts are order variants of the same source.",
    )
    args = parser.parse_args()
    if args.question_cap < 1:
        raise ValueError("question cap must be positive")

    result = compare_replay_artifacts(
        args.artifact,
        question_cap=args.question_cap,
        same_source_permutations=args.same_source_permutations,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
