"""Shared DEV acceptance on retained Lombard QA documents; no production URLs.

Nonrepeatable submission is journaled first. Unknown outcomes must be reconciled,
never retried. Existing documents, courses, enrollments and history stay intact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.dev.lesson_cycle_compare import APIClient, TENANT, save  # noqa: E402


async def run(args):
    env = dotenv_values("C:/Kamilya New/Kamilya-NEW/.env")
    api = APIClient(env, args.sha)
    await api.open()
    try:
        jobs = await api.request("GET", "/ai/jobs?scope=mine")
        active = [{"id": j["id"], "status": j["status"], "stage": j.get("stage")}
                  for j in jobs if j["status"] in {"pending", "running"}]
        if args.mode == "preflight":
            source_state = json.loads(args.sources.read_text(encoding="utf-8"))
            inventory = []
            for row in source_state["sources"]:
                if row["case"] not in {"microcredit", "standards", "fire"}:
                    continue
                doc = await api.request("GET", "/documents/" + row["document"]["id"])
                # Ordinary tenant-scoped GET DTO deliberately omits tenant_id;
                # APIClient verifies the normal QA role and tenant at login.
                assert doc["id"] == row["document"]["id"] and doc["embedding_status"] == "success"
                inventory.append({"case": row["case"], "document_id": doc["id"], "source_sha256": row["sha256"]})
            assert len(inventory) == 3
            assert not args.state.exists()
            save(args.state, {"tenant_id": TENANT, "preflight_sha": args.sha,
                              "active_jobs": active, "sources": inventory, "at": datetime.now(UTC).isoformat()})
            print(json.dumps({"active_jobs": active, "sources": inventory}), flush=True)
            return
        state = json.loads(args.state.read_text(encoding="utf-8"))
        assert state["tenant_id"] == TENANT
        selected = [row for row in state["sources"] if not args.case or row["case"] in args.case]
        assert selected
        for row in selected:
            if args.mode == "start":
                assert not active and not row.get("job_id") and not row.get("outcome_unknown")
                row.update(outcome_unknown=True, started_at=datetime.now(UTC).isoformat(), release_sha=args.sha)
                save(args.state, state)
                response = await api.request("POST", "/ai/generate-course", json={
                    "documents": [row["document_id"]], "target_audience": "Сотрудники компании",
                    "language": "ru", "tone": "professional", "course_format": "automatic", "reuse_reason": "other"})
                row.update(job_id=response["id"], outcome_unknown=False)
                save(args.state, state)
                print(json.dumps({"case": row["case"], "job_id": row["job_id"]}), flush=True)
                # Never submit the next full course without reviewing this result.
                return
            if not row.get("job_id"):
                continue
            job = await api.request("GET", "/ai/jobs/" + row["job_id"])
            row["job"] = job
            if args.mode == "capture" and job.get("course_id"):
                course = await api.request("GET", "/courses/" + job["course_id"])
                assert course["tenant_id"] == TENANT and course["status"] == "draft"
                assert course["source_document_ids"] == [row["document_id"]]
                preview = await api.request("GET", "/courses/" + job["course_id"] + "/preview?max_chars=2000")
                lessons = []
                for module in preview["modules"]:
                    for lesson in module["lessons"]:
                        lessons.append({"lesson": await api.request("GET", "/lessons/" + lesson["id"]),
                                        "quiz": await api.request("GET", "/quizzes/" + lesson["quiz_id"]) if lesson.get("quiz_id") else None})
                save(args.state.with_name(args.state.stem + "-" + row["case"] + "-capture.json"),
                     {"course": course, "lessons": lessons, "job": job, "release_sha": args.sha})
            save(args.state, state)
            print(json.dumps({"case": row["case"], "job_id": row["job_id"], "status": job["status"],
                              "stage": job.get("stage"), "progress": job.get("progress"),
                              "course_id": job.get("course_id"), "errors": job.get("errors")}), flush=True)
    finally:
        await api.client.aclose()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["preflight", "start", "poll", "capture"])
    p.add_argument("--sha", required=True)
    p.add_argument("--state", required=True, type=Path)
    p.add_argument("--sources", type=Path)
    p.add_argument("--case", action="append")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
