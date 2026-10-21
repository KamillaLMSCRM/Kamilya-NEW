"""Pre-rollout real-model diagnostic. Raw sources only; manual oracle not sent.

This local journal is NOT shared-worker/DB evidence. Normal DEV worker acceptance
must follow separately. Existing frozen lessons and source excerpts are read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT)]

from scripts.dev.lesson_cycle_compare import ProviderMeter, save  # noqa: E402


async def run(args):
    for key, value in dotenv_values("C:/Kamilya New/Kamilya-NEW/.env").items():
        if value is not None:
            os.environ[key] = value
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
    from app.modules.ai.llm_client import ResilientLLMClient, _deepseek_llm_provider
    from app.modules.ai.worker_lesson_cycle import WorkerLessonAssessor

    assert not args.output.exists()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    assert corpus["tenant_id"] == "a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"
    args.output.mkdir(parents=True)
    import hashlib
    save(args.output / "manifest.json", {"scope": "local diagnostic, not shared worker",
        "oracle_targets_sent": False, "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in [
            "apps/api/app/modules/ai/lesson_cycle.py", "apps/api/app/modules/ai/source_assessment_plan.py",
            "apps/api/app/modules/ai/worker_lesson_cycle.py", "scripts/dev/source_plan_probe.py"]}})

    class Journal:
        async def prepare(self, key, payload):
            path = args.output / (key.replace(":", "-") + ".json")
            return json.loads(path.read_text()) if path.exists() else None

        async def save_value(self, key, value):
            save(args.output / (key.replace(":", "-") + ".json"), value)

    async def checkpoint():
        pass

    from dataclasses import asdict
    cfg = _deepseek_llm_provider()
    assert cfg is not None
    report = []
    with ProviderMeter(cfg, args.output) as meter:
        for case in corpus["cases"]:
            if args.case and case["case_id"] not in args.case:
                continue
            facts = []
            primary_ids = []
            for source_index, source in enumerate(case["sources"]):
                for line_index, line in enumerate(source["text"].splitlines()):
                    if not line.strip():
                        continue
                    fid = f"source-{source_index}-line-{line_index}"
                    facts.append(SourceFact(fid, source["source_id"], "Исходное правило", line,
                                           "doc_id=" + source["source_id"]))
                    if source_index == 0:
                        primary_ids.append(fid)
            lesson = LessonDraft(case["lesson_id"], "QA", case["title"], "Рабочие решения",
                                 case["content"], tuple(primary_ids), (), 1)
            meter.label = case["case_id"]
            model = ResilientLLMClient([meter.provider()], temperature=0.1, max_retries_per_provider=0)
            assessor = WorkerLessonAssessor(tenant_id=str(UUID(corpus["tenant_id"])), client=model,
                                            journal=Journal(), checkpoint=checkpoint)
            result = await assessor(lesson, {f.fact_id: f for f in facts})
            save(args.output / (case["case_id"] + ".json"), asdict(result))
            row = {"case": case["case_id"], "questions": len(result.questions),
                   "coverage": result.audit.get("coverage"), "model_calls": result.audit.get("logical_model_calls")}
            report.append(row)
            save(args.output / "report.json", report)
            print(json.dumps(row, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case", action="append")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
