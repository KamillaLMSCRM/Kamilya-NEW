"""Run the native application/assessor on a local original with a USD5 API ledger.

This is local semantic evaluation, not a deployed worker, DB/RLS or UI acceptance.
No live job, route setting, customer course or embedding provider is used.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "api")]

from scripts.dev.generation_quality_api import QualityAPISession  # noqa: E402


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
                      default=lambda item: item.model_dump(mode="json")).encode()


def save(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("wb") as handle:
        handle.write(encoded(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def local_progress(folder):
    lessons = []
    pending = []
    for path in folder.glob("worker-cycle-*.json"):
        row = json.loads(path.read_bytes())
        value = row.get("value")
        if row["key"].startswith("lesson-realization:") and value:
            audit = value["assessment"]["audit"]
            surface = value.get("surface_review") or {}
            lessons.append({"lesson_id": value["lesson"]["lesson_id"],
                "content_chars": len(value["lesson"]["content"]), "questions": len(value["questions"]),
                "review_required": audit.get("coverage", {}).get("requires_review"),
                "source_prerequisite": audit.get("source_prerequisite"),
                "teaching_status": audit.get("final_teaching", {}).get("current_catalog_status"),
                "surface_ready": surface.get("surface_ready"),
                "surface_unproved_groups": surface.get("unproved_groups"),
                "surface_gap_codes": [gap["code"] for gap in (surface.get("block_custody") or {}).get("gaps", [])],
                "result_statuses": [item.get("status") for item in audit.get("results", [])],
                "cycle_issues": [item.get("issues", []) for item in audit.get("results", [])],
                "teaching_diagnostics": [item.get("teaching_diagnostics", []) for item in audit.get("results", [])],
                "missing_target_ids": audit.get("coverage", {}).get("missing_target_ids", [])})
        elif row["key"].startswith("source-plan:") and value is None:
            pending.append("source-plan")
    return {"committed_lessons": lessons, "incomplete_source_plans": len(pending)}


class LocalJournal:
    """Local immutable JSON wire; no claim of authenticated DB ownership."""

    def __init__(self, folder: Path, tenant: str, job: str):
        self.folder, self.tenant_id, self.job_id = folder, tenant, job

    def _owned_key(self, key):
        return "worker-cycle:" + hashlib.sha256(encoded([self.tenant_id, self.job_id, key])).hexdigest()

    def _path(self, key):
        return self.folder / (self._owned_key(key).replace(":", "-") + ".json")

    async def prepare(self, key, payload):
        path = self._path(key)
        if not path.exists():
            save(path, {"key": key, "plan": payload, "value": None})
            return None
        row = json.loads(path.read_bytes())
        if encoded(row["plan"]) != encoded(payload) or row["key"] != key:
            raise ValueError("local_quality_journal_input_changed")
        return row["value"]

    async def save_value(self, key, value):
        path = self._path(key)
        row = json.loads(path.read_bytes())
        if row["value"] is not None and encoded(row["value"]) != encoded(value):
            raise ValueError("local_quality_journal_value_changed")
        row["value"] = value
        save(path, row)

    async def read_value(self, key):
        path = self._path(key)
        return json.loads(path.read_bytes())["value"] if path.exists() else None

    async def read_owned_value(self, key, expected):
        path = self._path(key)
        if not path.exists():
            return None
        row = json.loads(path.read_bytes())
        if row["key"] != key or encoded(row["plan"]) != encoded(expected):
            raise ValueError("local_quality_journal_input_changed")
        return row["value"]

    async def read_owned_realization(self, key, expected):
        if not self._path(key).exists():
            return None
        value = await self.read_owned_value(key, expected)
        if value is None or encoded(value.get("realization_plan")) != encoded(expected):
            raise ValueError("local_quality_realization_incomplete")
        return value

    async def inventory_versions(self, key):
        from app.modules.ai.lesson_cycle import POLICY_VERSION
        from app.modules.ai.source_assessment_plan import PLAN_POLICY

        result = []
        for path in self.folder.glob("worker-cycle-*.json"):
            row = json.loads(path.read_bytes())
            if row["plan"].get("inventory_base_key") == key:
                result.append({"generation_key": self._owned_key(row["key"]),
                    "plan_revision": f"{PLAN_POLICY}/{POLICY_VERSION}", "plan_payload": row["plan"],
                    "module_key": "cycle", "lesson_key": "lesson", "assessment_status": "completed",
                    "assessment_payload": row["value"]})
        return result

    async def append_inventory_version(self, key, plan, value):
        await self.prepare(key, plan)
        await self.save_value(key, value)


class NoEmbeddings:
    async def embed_documents_with_provenance(self, *args, **kwargs):
        from app.modules.ai.llm_client import AllProvidersFailedError
        raise AllProvidersFailedError("No embedding provider in this local quality evaluation", [])


async def run(args):
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("JWT_SECRET", "local-quality-control-synthetic-not-a-secret")
    os.environ["DOCLING_URL"] = ""
    from app.modules.admin.runtime_configuration.catalog import default_snapshot
    from app.modules.admin.runtime_configuration.runtime import runtime_settings_scope
    from app.modules.ai.direct_source import build_direct_source_corpus
    from app.modules.ai.evidence_engine.application import generate_evidence_course, to_generation_artifacts
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.ingestion import DocumentConverter
    from app.modules.ai.worker_lesson_cycle import WorkerLessonAssessor

    if not args.evidence.parent.is_dir() or args.evidence.is_symlink():
        raise ValueError("local_quality_evidence_parent_invalid")
    args.evidence.mkdir(exist_ok=True)
    source = args.source.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest != args.sha256:
        raise ValueError("local_quality_original_hash_mismatch")
    tenant = "a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"
    document = SimpleNamespace(id=uuid5(NAMESPACE_URL, "local-quality:" + digest), tenant_id=tenant,
        lifecycle_status="active", content_sha256=digest, s3_key="local-original", size=len(source),
        filename=args.source.name, title=args.case, category="general")

    class Storage:
        def get_bytes(self, key):
            if key != "local-original":
                raise ValueError("local_quality_source_key_changed")
            return source

    async def checkpoint():
        return None

    async def progress(stage, current, total, provider, attempt):
        if stage in {"evidence_plan", "lesson_cycle", "quality"}:
            print(json.dumps({"stage": stage, "completed": current, "total": total}), flush=True)

    with runtime_settings_scope(default_snapshot()):
        corpus = await build_direct_source_corpus([document], tenant_id=tenant, storage=Storage(),
                                                converter=DocumentConverter())
        save(args.evidence / "corpus.json", asdict(corpus))
        if args.preflight_only:
            from app.modules.ai.evidence_engine.application import build_evidence_source
            from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
            prepared = EvidenceCourseEngine().generate_from_document(build_evidence_source(corpus).document)
            source_preview = ["# Native source units and lesson ownership", ""]
            for lesson in prepared.course.lessons:
                source_preview.extend(["## " + lesson.lesson_id, lesson.title,
                                       "Facts: " + ", ".join(lesson.fact_ids), ""])
            for fact in prepared.admitted_facts:
                source_preview.extend(["## " + fact.fact_id, fact.source_locator, "", fact.value, ""])
            (args.evidence / "source-review.md").write_text("\n".join(source_preview), encoding="utf-8")
            committed = []
            for path in args.evidence.glob("worker-cycle-*.json"):
                row = json.loads(path.read_bytes())
                if row["key"].startswith("lesson-realization:") and row.get("value"):
                    value = row["value"]
                    committed.extend(["# " + value["lesson"]["lesson_id"], value["lesson"]["title"],
                                      value["lesson"]["content"], ""])
            (args.evidence / "committed-review.md").write_text("\n".join(committed), encoding="utf-8")
            print(json.dumps({"status": "SOURCE_PREFLIGHT", "case": args.case, "source_sha256": digest,
                "lessons": len(prepared.course.lessons), "facts": len(prepared.admitted_facts), "inference_calls": 0}))
            return
        replay = set(args.replay_request_sha256)
        if args.replay_completed:
            old = json.loads(args.budget.read_bytes())
            replay.update(row["request_sha256"] for row in old["calls"]
                          if row.get("status") == "completed" and row.get("response_sha256"))
        client = QualityAPISession(key_file=args.key_file, ledger=args.budget, model=args.model,
                                   output_tokens=32_768, replay_requests=frozenset(replay))
        try:
            assessor = WorkerLessonAssessor(tenant_id=tenant, client=client,
                journal=LocalJournal(args.evidence, tenant, "local-quality:" + args.case),
                checkpoint=checkpoint, learner_language_gate=True)
            generated = await generate_evidence_course(corpus, intent=CourseIntent(),
                generation_client=client, embedding_client=NoEmbeddings(), lesson_assessor=assessor,
                progress_callback=progress)
            save(args.evidence / "application.json", asdict(generated))
            save(args.evidence / "artifacts.json", asdict(to_generation_artifacts(generated)))
            preview = []
            for lesson in generated.result.realized_course.lessons:
                preview.extend(["# " + lesson.title, "", lesson.content, "", "## Questions", ""])
                for question in generated.result.realized_assessment.questions:
                    if question.lesson_id == lesson.lesson_id:
                        preview.extend([question.prompt, *["- " + option for option in question.options],
                                        "Key: " + question.correct_answer, question.explanation, ""])
            (args.evidence / "preview.md").write_text("\n".join(preview), encoding="utf-8")
            summary = {"status": "COMPLETED_NOT_SEMANTIC_ACCEPTANCE", "case": args.case,
                "lessons": len(generated.result.realized_course.lessons),
                "questions": len(generated.result.realized_assessment.questions),
                "publishable": generated.result.publishability.publishable,
                "review_required": generated.result.assessment_review.get("coverage", {}).get("requires_review"),
                "chat_attempt_count": generated.result.chat_attempt_count,
                "prompt_tokens": generated.result.prompt_tokens,
                "completion_tokens": generated.result.completion_tokens,
                "timings": {timing.stage: round(timing.seconds, 3) for timing in generated.result.timings},
                "physical_calls_total": len(client.state["calls"]),
                "explicit_saved_response_replays": client.replayed,
                "budget_charge_usd": client.charged_micro_usd / 1_000_000,
                "estimated_cost_usd": sum(row.get("estimated_cost_micro_usd", 0) for row in client.state["calls"]) / 1_000_000}
            save(args.evidence / "summary.json", summary)
            print(json.dumps(summary))
        finally:
            await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--replay-request-sha256", action="append", default=[])
    parser.add_argument("--replay-completed", action="store_true", help="Explicit same-candidate interrupted-run replay; never a fresh audit claim.")
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args()
    try:
        if args.background:
            if not args.evidence.parent.is_dir():
                raise ValueError("local_quality_evidence_parent_invalid")
            args.evidence.mkdir(exist_ok=True)
            command = [sys.executable, str(Path(__file__).resolve()),
                       *[argument for argument in sys.argv[1:] if argument != "--background"]]
            log = args.evidence / "runner.log"
            with log.open("ab", buffering=0) as output:
                options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
                child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=output, **options)
            save(args.evidence / "runner.json", {"pid": child.pid,
                "command_sha256": hashlib.sha256(encoded(command)).hexdigest(), "log": log.name})
            print(json.dumps({"status": "STARTED", "pid": child.pid, "log": str(log)}))
            return 0
        asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
