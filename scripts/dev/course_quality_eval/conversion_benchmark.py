"""Measure local fallback extraction only, never represent it as production OCR."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from scripts.dev.course_quality_eval.benchmark import DEFAULT_SUITE, ROOT, digest, load_suite, normalize


async def run(source_dir: Path, output: Path) -> None:
    sys.path.insert(0, str(ROOT / "apps/api"))
    from app.modules.ai.ingestion import _local_convert

    rows = []
    for case in load_suite(DEFAULT_SUITE):
        for path in [source_dir / case["filename"], source_dir / f"{case['id']}.pdf"]:
            start = time.perf_counter()
            converted = await _local_convert(str(path))
            elapsed = time.perf_counter() - start
            matched = [claim["id"] for claim in case["required_claims"]
                       if normalize(claim["quote"]) in normalize(converted["markdown"])]
            rows.append({"case": case["id"], "format": path.suffix, "file_sha256": digest(path),
                         "seconds": round(elapsed, 6), "engine": converted["metadata"]["engine"],
                         "extracted_characters": len(converted["markdown"]),
                         "gold_quote_denominator": len(case["required_claims"]),
                         "exact_quotes_present": len(matched),
                         "missing_exact_quotes": [claim["id"] for claim in case["required_claims"]
                                                  if claim["id"] not in matched]})
    with output.open("x", encoding="utf-8") as target:
        json.dump({"scope": "LOCAL_FALLBACK_EXTRACTION_NOT_PRODUCTION_DOCLING_OR_END_TO_END",
                   "suite_sha256": digest(DEFAULT_SUITE), "rows": rows}, target, ensure_ascii=False, indent=2)
    print(json.dumps({"conversions": len(rows), "rows_with_missing_literal_quotes":
                      sum(bool(row["missing_exact_quotes"]) for row in rows)}))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source-dir", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    asyncio.run(run(args.source_dir, args.output))
