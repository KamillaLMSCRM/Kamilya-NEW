"""Bounded opt-in DEV A/B. Existing QA sources read only; new QA drafts only.

The experiment runs local candidate code against the canonical DEV provider
configuration and normal DEV APIs. It is not a shared-worker deployment claim.
No credentials, headers, URLs with secrets or raw provider errors are persisted.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT)]
TENANT = "a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"
API = "https://kamilya-lms-api.onrender.com/api/v1"
ORIGIN = "https://kamilya-lms-dev.vercel.app"


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class ProviderMeter:
    """Loopback-only transparent forwarder counts every actual provider HTTP POST.

    This also sees low-reasoning client instances and retries. No shared client
    monkeypatch, credential capture, thinking change or production proxy occurs.
    """

    def __init__(self, config, output):
        self.config, self.output = config, output
        self.label = "none"
        self.rows = []
        self.server = None

    def __enter__(self):
        meter = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if self.path != meter.config.endpoint:
                    self.send_error(404)
                    return
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(raw)
                record = {
                    "label": meter.label,
                    "call": len(meter.rows) + 1,
                    "request_sha256": sha(payload),
                    "at": datetime.now(UTC).isoformat(),
                }
                if sum(row["label"] == meter.label for row in meter.rows) >= 40:
                    self.send_error(429)
                    return
                meter.rows.append(record)
                started = time.perf_counter()
                try:
                    with httpx.Client(
                        timeout=meter.config.timeout, trust_env=False
                    ) as client:
                        response = client.post(
                            meter.config.base_url + meter.config.endpoint,
                            json=payload,
                            headers={"Authorization": "Bearer " + meter.config.api_key},
                        )
                    record["status"] = response.status_code
                    if response.status_code == 200:
                        data = response.json()
                        record.update(model=data.get("model"), usage=data.get("usage"))
                        save(
                            meter.output / (f"provider-{record['call']:03}.json"),
                            {
                                "label": meter.label,
                                "request": payload,
                                "response": data,
                            },
                        )
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(response.content)))
                    self.end_headers()
                    self.wfile.write(response.content)
                except (httpx.HTTPError, OSError) as exc:
                    record["error_class"] = type(exc).__name__
                    self.send_error(502)
                finally:
                    record["seconds"] = round(time.perf_counter() - started, 3)
                    save(meter.output / "provider-http.json", meter.rows)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def provider(self):
        return replace(
            self.config,
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            trust_env=False,
        )

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class APIClient:
    def __init__(self, env, expected_sha):
        self.env = env
        self.client = httpx.AsyncClient(
            base_url=API, timeout=60, headers={"Origin": ORIGIN}
        )
        self.expected_sha = expected_sha
        self.last_refresh = time.monotonic()
        self.last_quiz_write = {}

    async def open(self):
        health = await self.request("GET", "/health", auth=False)
        assert health["release_sha"] == self.expected_sha
        response = await self.client.post(
            "/auth/login",
            json={
                "email": "methodologist@kamilya-dev-qa.example.com",
                "password": self.env["DEV_QA_METHODOLOGIST_PASSWORD"],
            },
        )
        if response.status_code != 200:
            raise RuntimeError("normal_dev_login_status_" + str(response.status_code))
        self.client.headers["Authorization"] = (
            "Bearer " + response.json()["access_token"]
        )
        me = await self.request("GET", "/users/me")
        assert me["tenant_id"] == TENANT and me["role"] == "methodologist"

    async def request(self, method, path, auth=True, **kwargs):
        if method == "POST" and path.endswith("/questions"):
            # Existing quiz bucket permits10requests/10s. Respect it; do not
            # weaken the server limiter or blindly retry nonrepeatable writes.
            pause = 1.1 - (time.monotonic() - self.last_quiz_write.get(path, 0))
            if pause > 0:
                await asyncio.sleep(pause)
            self.last_quiz_write[path] = time.monotonic()
        if auth and time.monotonic() - self.last_refresh > 600:
            refreshed = await self.client.post("/auth/refresh")
            if refreshed.status_code != 200:
                raise RuntimeError(
                    "normal_dev_refresh_status_" + str(refreshed.status_code)
                )
            self.client.headers["Authorization"] = (
                "Bearer " + refreshed.json()["access_token"]
            )
            self.last_refresh = time.monotonic()
        response = await self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError("dev_api_" + str(response.status_code) + "_" + method)
        return response.json() if response.content else None


class APIStore:
    """Save only new QA lesson copies; read back every persisted key on resume.

    A receipt is written BEFORE each non-repeatable POST. Unknown outcomes stop;
    they are never retried or resolved by creating another course/lesson.
    """

    def __init__(self, api, output, manifest, module_id, mode):
        self.api, self.output, self.manifest = api, output, manifest
        self.module_id, self.mode = module_id, mode

    async def load(self, tenant_id, identity):
        from app.modules.ai.lesson_cycle import LessonCycleResult, ReviewedQuestion

        assert tenant_id == TENANT
        entry = self.manifest["saved"].get(identity)
        if entry is None:
            return None
        if entry.get("outcome_unknown"):
            raise RuntimeError("reconcile_nonrepeatable_post_before_resume")
        lesson = await self.api.request("GET", "/lessons/" + entry["lesson_id"])
        assert (
            sha(lesson["content"]) == entry["content_sha256"]
            and lesson["tenant_id"] == TENANT
        )
        if entry.get("quiz_id"):
            quiz = await self.api.request("GET", "/quizzes/" + entry["quiz_id"])
            expected = entry["result"]["questions"]
            assert len(quiz["questions"]) == len(expected)
            for live, saved in zip(quiz["questions"], expected, strict=True):
                assert (
                    live["text"] == saved["text"]
                    and live["explanation"] == saved["explanation"]
                )
                assert [(c["text"], c["is_correct"]) for c in live["choices"]] == [
                    (option, i == saved["correct_index"])
                    for i, option in enumerate(saved["options"])
                ]
        row = dict(entry["result"])
        row["questions"] = tuple(
            ReviewedQuestion(
                **{
                    **q,
                    "target_ids": tuple(q["target_ids"]),
                    "options": tuple(q["options"]),
                    "option_evidence": tuple(q["option_evidence"]),
                }
            )
            for q in row["questions"]
        )
        row["missing_target_ids"], row["issues"] = (
            tuple(row["missing_target_ids"]),
            tuple(row["issues"]),
        )
        return LessonCycleResult(**row)

    async def save(self, tenant_id, identity, result):
        assert tenant_id == TENANT
        packet = self.packet
        entry = {
            "outcome_unknown": True,
            "result": asdict(result),
            "content_sha256": sha(packet.content),
        }
        assert identity not in self.manifest["saved"]
        self.manifest["saved"][identity] = entry
        save(self.output / "receipt.json", self.manifest)
        lesson = await self.api.request(
            "POST",
            "/modules/" + self.module_id + "/lessons",
            json={
                "title": packet.title[:245],
                "content": packet.content,
                "content_type": "text",
                "order_index": len(self.manifest["saved"]) - 1,
            },
        )
        entry["lesson_id"] = lesson["id"]
        save(self.output / "receipt.json", self.manifest)
        if result.questions:
            quiz = await self.api.request(
                "POST",
                "/quizzes",
                json={"lesson_id": lesson["id"], "title": packet.title[:245]},
            )
            entry["quiz_id"] = quiz["id"]
            save(self.output / "receipt.json", self.manifest)
            for i, question in enumerate(result.questions):
                await self.api.request(
                    "POST",
                    "/quizzes/" + quiz["id"] + "/questions",
                    json={
                        "text": question.text,
                        "type": "MCQ",
                        "explanation": question.explanation,
                        "order_index": i,
                        "choices": [
                            {
                                "text": option,
                                "is_correct": j == question.correct_index,
                                "order_index": j,
                            }
                            for j, option in enumerate(question.options)
                        ],
                    },
                )
        entry["outcome_unknown"] = False
        save(self.output / "receipt.json", self.manifest)
        assert await self.load(tenant_id, identity) == result


async def run(args):
    env = dotenv_values("C:/Kamilya New/Kamilya-NEW/.env")
    for key, value in env.items():
        if value is not None:
            os.environ[key] = value
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.ai.lesson_cycle import (
        LessonPacket,
        LearningTarget,
        SourceExcerpt,
        run_lesson_cycles,
    )
    from app.modules.ai.llm_client import ResilientLLMClient, _deepseek_llm_provider
    from app.modules.ai.regeneration_assessment import prepare_lesson_assessment
    from scripts.ops.kb_rag_isolated_dev_gate import same_supabase_project

    assert same_supabase_project(
        env.get("DATABASE_URL", ""), env.get("SUPABASE_URL", "")
    )
    assert (
        args.execute and not args.output.exists()
    ), "new exact experiment directory required"
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    assert corpus["tenant_id"] == TENANT and len(corpus["cases"]) == 3
    selected = [
        case
        for case in corpus["cases"]
        if not args.case or case["case_id"] in args.case
    ]
    assert selected and (
        not args.case or set(args.case) <= {case["case_id"] for case in corpus["cases"]}
    )
    args.output.mkdir(parents=True)
    api = APIClient(env, corpus["release_sha"])
    receipt = {
        "tenant_id": TENANT,
        "created_at": datetime.now(UTC).isoformat(),
        "release_sha": corpus["release_sha"],
        "corpus_sha256": sha(corpus),
        "saved": {},
        "courses": {},
        "baseline_saved": {},
        "scope": "local_candidate_connected_to_shared_DEV_API;not_shared_worker_deployment",
        "production_mutations": 0,
        "selected_cases": [case["case_id"] for case in selected],
    }
    receipt["code_sha256"] = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__),
            ROOT / "apps/api/app/modules/ai/lesson_cycle.py",
            ROOT / "apps/api/app/modules/ai/regeneration_assessment.py",
            ROOT / "apps/api/app/modules/ai/evidence_engine/semantic_assessment.py",
        )
    }
    modes = ("lesson_cycle",) if args.candidate_only else ("current", "lesson_cycle")
    if args.candidate_only:
        assert args.baseline is not None, "frozen baseline lineage required"
        baseline = json.loads(
            (args.baseline / "receipt.json").read_text(encoding="utf-8")
        )
        baseline_results = json.loads(
            (args.baseline / "results-private.json").read_text(encoding="utf-8")
        )
        baseline["code_sha256"] = {
            key.replace("\\", "/"): value
            for key, value in baseline["code_sha256"].items()
        }
        assert (
            baseline["tenant_id"] == TENANT
            and baseline["release_sha"] == corpus["release_sha"]
        )
        for path in (
            "apps/api/app/modules/ai/regeneration_assessment.py",
            "apps/api/app/modules/ai/evidence_engine/semantic_assessment.py",
        ):
            assert baseline["code_sha256"][path] == receipt["code_sha256"][path]
        frozen = [row for row in baseline_results if row["mode"] == "current"]
        assert len(frozen) == len(corpus["cases"])
        for case in corpus["cases"]:
            assert any(
                row["case"] == case["case_id"]
                and row["lesson_sha256"] == sha(case["content"])
                for row in frozen
            )
        receipt["baseline_reuse"] = {
            "receipt_sha256": sha(baseline),
            "results_sha256": sha(baseline_results),
            "qualification": "unchanged frozen lesson-only baseline reused; corrected candidate oracle/context; not a new paired replicate",
            "rows": frozen,
        }
    save(args.output / "receipt.json", receipt)
    try:
        await api.open()
        # Canonical DEV-owned source lessons must still match the frozen input.
        for case in corpus["cases"]:
            lesson = await api.request("GET", "/lessons/" + case["lesson_id"])
            assert (
                lesson["tenant_id"] == TENANT and lesson["content"] == case["content"]
            )
        cfg = _deepseek_llm_provider()
        assert cfg is not None and cfg.base_url.startswith("https://api.deepseek.com")
        # Controlled paired provider, same settings in both arms. No route write.
        cfg = replace(cfg, max_retries=0)
        receipt["provider"] = {
            "name": cfg.name,
            "model": cfg.model,
            "temperature": 0.1,
            "transport_retries": 0,
            "qualification": "matched single-provider experiment, not live failover-chain acceptance",
        }
        if args.candidate_only:
            assert receipt["provider"] == baseline["provider"]
        for mode in modes:
            receipt["courses"][mode] = {"outcome_unknown": True}
            save(args.output / "receipt.json", receipt)
            course = await api.request(
                "POST",
                "/courses",
                json={
                    "title": "QA LC21 " + mode + " " + args.output.name,
                    "description": "Owned synthetic QA comparison only. Not approved for publication.",
                    "status": "draft",
                },
            )
            assert course["tenant_id"] == TENANT and course["status"] == "draft"
            receipt["courses"][mode].update(id=course["id"])
            save(args.output / "receipt.json", receipt)
            module = await api.request(
                "POST",
                "/courses/" + course["id"] + "/modules",
                json={"title": "Сравнение уроков"},
            )
            receipt["courses"][mode].update(
                module_id=module["id"], outcome_unknown=False
            )
            save(args.output / "receipt.json", receipt)
        results = []
        with ProviderMeter(cfg, args.output) as meter:
            for index, case in enumerate(selected):
                packet = LessonPacket(
                    TENANT,
                    case["lesson_id"],
                    case["title"],
                    case["content"],
                    tuple(SourceExcerpt(**source) for source in case["sources"]),
                    tuple(LearningTarget(**target) for target in case["targets"]),
                    "paired-" + sha(receipt["provider"]),
                )
                order = (
                    modes
                    if len(modes) == 1 or index % 2 == 0
                    else tuple(reversed(modes))
                )
                for mode in order:
                    meter.label = case["case_id"] + ":" + mode
                    start, before = time.perf_counter(), len(meter.rows)
                    client = ResilientLLMClient(
                        [meter.provider()], temperature=0.1, max_retries_per_provider=0
                    )
                    row = {
                        "case": case["case_id"],
                        "mode": mode,
                        "lesson_sha256": sha(packet.content),
                    }
                    try:
                        async with asyncio.timeout(480):
                            if mode == "current":
                                questions = await prepare_lesson_assessment(
                                    lesson=SimpleNamespace(
                                        id=packet.lesson_id,
                                        tenant_id=TENANT,
                                        title=packet.title,
                                        content=packet.content,
                                        source_validation_status="verified",
                                        source_document_ids=case["source_document_ids"],
                                    ),
                                    client=client,
                                )
                                row.update(status="completed", questions=questions)
                                receipt["baseline_saved"][case["case_id"]] = {
                                    "outcome_unknown": True
                                }
                                save(args.output / "receipt.json", receipt)
                                entry = receipt["baseline_saved"][case["case_id"]]
                                copied = await api.request(
                                    "POST",
                                    "/modules/"
                                    + receipt["courses"][mode]["module_id"]
                                    + "/lessons",
                                    json={
                                        "title": packet.title[:245],
                                        "content": packet.content,
                                        "order_index": index,
                                    },
                                )
                                entry["lesson_id"] = copied["id"]
                                save(args.output / "receipt.json", receipt)
                                quiz = await api.request(
                                    "POST",
                                    "/quizzes",
                                    json={
                                        "lesson_id": copied["id"],
                                        "title": packet.title[:245],
                                    },
                                )
                                entry["quiz_id"] = quiz["id"]
                                save(args.output / "receipt.json", receipt)
                                for order, question in enumerate(questions):
                                    await api.request(
                                        "POST",
                                        "/quizzes/" + quiz["id"] + "/questions",
                                        json={
                                            "text": question["text"],
                                            "type": "MCQ",
                                            "explanation": question["explanation"],
                                            "order_index": order,
                                            "choices": [
                                                {
                                                    "text": option,
                                                    "is_correct": i
                                                    == question["correct_index"],
                                                    "order_index": i,
                                                }
                                                for i, option in enumerate(
                                                    question["choices"]
                                                )
                                            ],
                                        },
                                    )
                                readback = await api.request(
                                    "GET", "/quizzes/" + quiz["id"]
                                )
                                assert len(readback["questions"]) == len(questions)
                                entry["outcome_unknown"] = False
                                save(args.output / "receipt.json", receipt)
                            else:
                                store = APIStore(
                                    api,
                                    args.output,
                                    receipt,
                                    receipt["courses"][mode]["module_id"],
                                    mode,
                                )
                                store.packet = packet
                                result = (
                                    await run_lesson_cycles(
                                        [packet], client=client, store=store
                                    )
                                )[0]
                                row.update(status=result.status, result=asdict(result))
                                network_before_resume = len(meter.rows)
                                # Fresh adapter, server readback: no model invocation or new rows.
                                restarted = APIStore(
                                    api, args.output, receipt, store.module_id, mode
                                )
                                resumed = (
                                    await run_lesson_cycles(
                                        [packet], client=client, store=restarted
                                    )
                                )[0]
                                assert (
                                    resumed == result
                                    and len(meter.rows) == network_before_resume
                                )
                                row["resume_without_model_calls"] = True
                    except (ValueError, TimeoutError, RuntimeError) as exc:
                        row.update(status="failed", error_class=type(exc).__name__)
                        code = str(exc)
                        if code.startswith("dev_api_") and len(code) <= 30:
                            row["error_code"] = code
                    row.update(
                        seconds=round(time.perf_counter() - start, 3),
                        http_calls=len(meter.rows) - before,
                    )
                    results.append(row)
                    save(args.output / "results-private.json", results)
                    print(
                        json.dumps(
                            {
                                k: v
                                for k, v in row.items()
                                if k not in {"questions", "result"}
                            }
                        ),
                        flush=True,
                    )
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        save(args.output / "receipt.json", receipt)
    finally:
        await api.client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-only", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
