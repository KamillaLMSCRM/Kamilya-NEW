"""Prepare a local source-only assessment fixture with production conversion.

Does not generate teaching prose, touch DB or pretend to be full-course acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from scripts.dev.run_evidence_course_application import _converted_pdf_corpus, _load_env, _pdf_corpus, _xlsx_corpus  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ocr-json", type=Path, help="Local OCR replay, NOT production converter evidence")
    parser.add_argument("--converter-json", type=Path, help="Hash-bound capture from deployed application converter")
    args = parser.parse_args()
    if args.ocr_json and args.converter_json:
        parser.error("Choose one conversion input")
    _load_env(args.env_file)
    from app.modules.ai.evidence_engine.application import build_evidence_source
    from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine

    started = time.perf_counter()
    if args.ocr_json:
        corpus = _pdf_corpus(args.source, args.ocr_json)
        conversion_mode = "local_ocr_replay_not_production_converter"
    else:
        corpus = await (_xlsx_corpus(args.source) if args.source.suffix.lower() == ".xlsx"
                        else _converted_pdf_corpus(args.source, args.converter_json))
        conversion_mode = "deployed_converter_capture" if args.converter_json else "application_converter"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "corpus.json").write_text(json.dumps(asdict(corpus), ensure_ascii=False, indent=2), encoding="utf-8")
    result = EvidenceCourseEngine().generate_from_document(build_evidence_source(corpus).document)
    artifact = {"mode": "source_only_plan_not_generated_course", "conversion_mode": conversion_mode,
                "evidence_result": result.to_dict(),
                "realized_course": asdict(result.course), "realized_assessment": {"questions": []}}
    (args.output_dir / "result.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": artifact["mode"], "seconds": round(time.perf_counter() - started, 3),
                      "chunks": corpus.total_chunks, "facts": len(result.admitted_facts),
                      "lessons": len(result.course.lessons)}))


if __name__ == "__main__":
    asyncio.run(main())
