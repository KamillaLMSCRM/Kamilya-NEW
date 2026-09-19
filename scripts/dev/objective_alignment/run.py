"""Frozen, bounded A/B pilot. All mutations stay in a new local output directory."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from scripts.dev.run_evidence_course_application import _load_env  # noqa: E402
from scripts.dev.run_semantic_block_smoke import SOURCES, corpus_for  # noqa: E402


DEV_CASES = [
    {"id": "dev-policy", "split": "dev", "title": "Работа с обращениями",
     "source": SOURCES["independent-sections"], "expected_objectives": [
         {"id": "d1", "description": "Выбрать разрешённый канал даже при срочности"},
         {"id": "d2", "description": "Подтвердить получение и следующий шаг, не требуя финального решения"},
         {"id": "d3", "description": "Сохранять ответственность до явного подтверждения принимающей стороны"}]},
    {"id": "dev-table", "split": "dev", "title": "Консультация по коллекциям",
     "source": SOURCES["synthetic-collections"], "expected_objectives": [
         {"id": "d4", "description": "Выбрать коллекцию по комнате назначения"},
         {"id": "d5", "description": "Различать материалы фасада коллекций"},
         {"id": "d6", "description": "Правильно объяснить уход за каждой коллекцией"}]}]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint():
    paths = sorted((ROOT / "apps/api/app/modules/ai").rglob("*.py"))
    return {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in paths}


def experiment_fingerprint():
    paths = [Path(__file__), Path(__file__).with_name("engine.py"),
             Path(__file__).with_name("review.py"),
             Path(__file__).with_name("source.py"),
             ROOT / "scripts/dev/run_semantic_block_smoke.py"]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p) for p in paths}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_config(manifest):
    """Explicit DEV-only route; ASUS never reads a paid key or inherits failover."""
    from app.modules.ai.llm_client import LLMProviderConfig, _deepseek_llm_provider
    if manifest.get("provider") == "asus-glm":
        if manifest.get("thinking") not in {"native", "selective"}:
            raise ValueError("ASUS supports native or role-selective thinking in this experiment")
        extra = ({} if manifest.get("thinking") == "native"
                 else {"chat_template_kwargs": {"enable_thinking": False}})
        return LLMProviderConfig(name="asus-glm", base_url="http://10.66.66.28:8888/v1",
                                 api_key="local-no-key", model="GLM-5.3-Flash-EXL3",
                                 timeout=600, max_retries=0, extra_body=extra)
    if manifest.get("provider", "deepseek") != "deepseek":
        raise ValueError("Unknown provider; no ambient fallback")
    cfg = _deepseek_llm_provider()
    if cfg is None:
        raise ValueError("DeepSeek configuration missing; no alternate credential discovery")
    cfg = replace(cfg, max_retries=0, timeout=60)
    thinking = manifest.get("thinking", "disabled")
    if thinking == "native":
        raise ValueError("DeepSeek requires an explicit thinking policy")
    if thinking != "disabled":
        cfg = replace(cfg, timeout=120, extra_body={"thinking": {"type": "enabled"},
                      "reasoning_effort": "low" if thinking == "selective" else thinking})
    return cfg


def thinking_profile(provider_name, task, policy):
    """Return vendor-native request extras and bounded output for one DEV role."""
    if policy != "selective":
        return None
    if provider_name == "asus-glm":
        reasoned = (task in {"blind_audit", "captured_blind_audit"}
                    or task.endswith("_repair") or task.endswith("_contract_repair"))
        extra = {"chat_template_kwargs": {"enable_thinking": reasoned}}
        if reasoned:
            extra["reasoning_effort"] = "low"
        return extra, 8192 if reasoned else 4096
    mode = "disabled" if task == "objective_teaching" else "enabled"
    return ({"thinking": {"type": mode}, **(
        {"reasoning_effort": "high" if task == "blind_audit" else "low"}
        if mode == "enabled" else {})}, 16384)


class Recorder:
    """Instance-local capture; no runtime class monkeypatch and no secrets logged."""
    def __init__(self, client, max_calls=30, thinking=None):
        self.client = client
        self.trace = []
        self.calls = 0
        self.max_calls = max_calls
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.usage_responses = 0
        self.token_details = {"cache_hit_tokens": None, "cache_miss_tokens": None, "reasoning_tokens": None}
        self.requests = []
        self.thinking = thinking
        self.response_models = set()
        self.http_errors = []
        provider = client._clients[0]
        original = provider._request

        async def request(payload):
            if self.calls >= self.max_calls:
                raise RuntimeError("experiment_call_budget_exhausted")
            self.calls += 1
            record = {"call": self.calls,
                      "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
            self.requests.append(record)
            started = time.perf_counter()
            try:
                data = await original(payload)
            except Exception as error:
                underlying = getattr(error, "last_exc", error)
                status = getattr(getattr(underlying, "response", None), "status_code", None)
                if isinstance(status, int):
                    self.http_errors.append(status)  # No body, URL, header or credential.
                    record["http_error"] = status
                record["error"] = type(error).__name__
                raise
            finally:
                record["seconds"] = round(time.perf_counter() - started, 3)
            if data.get("model"):
                self.response_models.add(data["model"])
            if isinstance(data.get("usage"), dict):
                self.usage_responses += 1
                for name in self.usage:
                    self.usage[name] += data["usage"].get(name, 0)
                usage = data["usage"]
                details = {
                    "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", (usage.get("prompt_tokens_details") or {}).get("cached_tokens")),
                    "cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
                    "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                }
                record.update({name: usage.get(name) for name in self.usage}, **details)
                for name, value in details.items():
                    if type(value) is int and value >= 0:
                        self.token_details[name] = (self.token_details[name] or 0) + value
            return data

        provider._request = request

    async def ainvoke_validated(self, messages, parser, **kwargs):
        started = time.perf_counter()
        request = json.loads(messages[-1]["content"])
        request_sha256 = hashlib.sha256(json.dumps(
            request,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        entry = {"task": request.get("task", "realization"),
                 "request_sha256": request_sha256, "responses": []}
        provider = self.client._clients[0]
        profile = (thinking_profile(provider.config.name, entry["task"], self.thinking)
                   if self.thinking == "selective" else None)
        if profile:
            # Each recorder owns its provider instance; no global/provider config mutation.
            extra_body, max_tokens = profile
            provider.config = replace(provider.config, extra_body=extra_body)
            kwargs["config"] = {"max_tokens": max_tokens}
            entry["thinking"] = (
                "enabled" if extra_body.get("chat_template_kwargs", {}).get("enable_thinking")
                or extra_body.get("thinking", {}).get("type") == "enabled" else "disabled"
            )
            entry["reasoning_effort"] = extra_body.get("reasoning_effort")
        self.trace.append(entry)

        def capture(raw):
            response = {"raw": raw}
            entry["responses"].append(response)
            try:
                return parser(raw)
            except Exception as error:
                response["parser_error"] = type(error).__name__
                raise

        try:
            result = await self.client.ainvoke_validated(messages, parser=capture, **kwargs)
            entry["provider"], entry["model"] = result.provider, result.model_id
            return result
        except Exception as error:
            entry["error"] = type(error).__name__
            raise
        finally:
            entry["seconds"] = round(time.perf_counter() - started, 3)


def readable(case, result):
    lines = [f"# {case['title']}", "", "## Исходник", case["source"], "", "## Результат"]
    questions = result["realized_assessment"]["questions"]
    for lesson in result["realized_course"]["lessons"]:
        lines.extend([f"### {lesson['title']}", f"Цель: {lesson['objective']}", lesson["content"]])
        for q in questions:
            if q["lesson_id"] != lesson["lesson_id"]:
                continue
            lines.extend([f"#### {q['question_id']}", q["prompt"]])
            lines.extend(f"- {'[верно]' if o == q['correct_answer'] else '[неверно]'} {o}" for o in q["options"])
            lines.append(f"Пояснение: {q['explanation']}")
    return "\n\n".join(lines)


async def run(args):
    manifest_path = args.output_dir / "manifest.json"
    holdout = args.holdout_file or Path(__file__).with_name("holdout.json")
    if args.phase == "freeze":
        if args.output_dir.exists():
            raise ValueError("Use a new experiment output directory; never overwrite evidence")
        provider = getattr(args, "provider", "asus-glm")
        thinking = args.thinking or ("native" if provider == "asus-glm" else "disabled")
        if provider == "asus-glm":
            provider_config({"provider": provider, "thinking": thinking})
        manifest = {"runtime_sha256": fingerprint(), "experiment_sha256": experiment_fingerprint(),
                    "holdout_sha256": digest(holdout), "dev_cases": DEV_CASES,
                    "repeat_count": args.repeats, "arms": args.arms,
                    "provider": provider,
                    "model": "GLM-5.3-Flash-EXL3" if provider == "asus-glm" else "env_deepseek_only", "temperature": 0.2,
                    "thinking": thinking,
                    "max_tokens": 16384, "max_calls": 80,
                    "arm_timeout_seconds": 1800 if provider == "asus-glm" else 600,
                    "scope": "source-note preservation + objective packs; not end-to-end production acceptance",
                    "quality_gate": "0 factual/option defects; all answers taught; ceil(80% expected goals); no trivia",
                    "holdout_rule": "no prompt changes after freeze; failures retained"}
        save(manifest_path, manifest)
        for name in ("engine.py", "review.py", "source.py", "run.py"):
            (args.output_dir / f"frozen-{name}").write_bytes(Path(__file__).with_name(name).read_bytes())
        print(json.dumps({"frozen": True, "runtime_files": len(manifest["runtime_sha256"]),
                          "manifest_sha256": digest(manifest_path)}), flush=True)
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if fingerprint() != manifest["runtime_sha256"] or experiment_fingerprint() != manifest["experiment_sha256"]:
        raise ValueError("frozen_source_changed")
    if digest(holdout) != manifest["holdout_sha256"] or DEV_CASES != manifest["dev_cases"]:
        raise ValueError("frozen_fixtures_changed")
    if manifest.get("provider", "deepseek") == "deepseek":
        if not args.env_file:
            raise ValueError("--env-file required for explicitly authorized live local replay")
        _load_env(args.env_file)
    elif manifest["arms"] != "B":
        raise ValueError("ASUS experiment uses B only; no ambient embedding/provider routes")
    from app.modules.ai.evidence_engine.application import generate_evidence_course
    from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.llm_client import ResilientEmbeddingsClient, ResilientLLMClient
    from scripts.dev.objective_alignment.engine import generate
    from scripts.dev.objective_alignment.source import build_complete_source

    cfg = provider_config(manifest)
    cases = DEV_CASES if args.phase == "dev" else json.loads(holdout.read_text(encoding="utf-8"))
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            raise ValueError("Unknown frozen case ID")
    for case in cases:
        # Title/filename adapter preserves production worksheet metadata in both arms.
        label = "synthetic-collections" if "[Worksheet]" in case["source"] else case["id"]
        corpus = corpus_for(case["source"], label)
        source_plan = EvidenceCourseEngine().generate_from_document(build_complete_source(corpus).document)
        for repeat in range(1, manifest["repeat_count"] + 1):
            for arm in (manifest["arms"] if repeat % 2 else manifest["arms"][::-1]):
                folder = args.output_dir / args.phase / case["id"] / f"run-{repeat}" / arm
                if folder.exists():
                    raise ValueError("Attempt evidence exists; no hidden retries/overwrite")
                folder.mkdir(parents=True)
                save(folder / "input.json", case)
                save(folder / "source-plan.json", source_plan.to_dict())
                recorder = Recorder(ResilientLLMClient([cfg], temperature=0.2, max_tokens=manifest["max_tokens"]),
                                    max_calls=manifest["max_calls"], thinking=manifest.get("thinking"))
                started = time.perf_counter()
                metrics = {"arm": arm, "case": case["id"], "repeat": repeat, "model": cfg.model,
                           "thinking": manifest.get("thinking", "disabled"),
                           "status": "NOT_COMPLETED", "semantic_acceptance": "NOT_REVIEWED",
                           "embedding_work": "baseline_only_retrieval_metric_not_experimental_variable"}
                try:
                    async with asyncio.timeout(manifest["arm_timeout_seconds"]):
                        if arm == "A":
                            output = await generate_evidence_course(
                                corpus, intent=CourseIntent(), generation_client=recorder,
                                embedding_client=ResilientEmbeddingsClient.from_settings(max_retries_per_provider=0))
                            result = output.result.to_dict()
                        else:
                            result = await generate(list(source_plan.course.lessons),
                                {f.fact_id: f for f in source_plan.admitted_facts}, recorder,
                                checkpoint=lambda pack: save(folder / "checkpoints" / f"{pack['lesson_id']}.json", pack))
                        save(folder / "result.json", result)
                        (folder / "review.md").write_text(readable(case, result), encoding="utf-8")
                        metrics.update(status="COMPLETED", lessons=len(result["realized_course"]["lessons"]),
                                       questions=len(result["realized_assessment"]["questions"]),
                                       unresolved_packs=sum(any(p.get("unresolved", {}).values()) for p in result.get("packs", [])))
                        if metrics["unresolved_packs"]:
                            metrics["status"] = "COMPLETED_WITH_GAPS"
                except Exception as error:
                    metrics["error"] = type(error).__name__
                finally:
                    metrics.update(seconds=round(time.perf_counter() - started, 3), calls=recorder.calls,
                                   usage=recorder.usage if recorder.usage_responses else None,
                                   usage_responses=recorder.usage_responses,
                                   token_details=recorder.token_details,
                                   response_models=sorted(recorder.response_models),
                                   http_errors=recorder.http_errors,
                                   stages_seconds={task: round(sum(t["seconds"] for t in recorder.trace if t["task"] == task), 3)
                                                   for task in dict.fromkeys(t["task"] for t in recorder.trace)})
                    save(folder / "trace.json", recorder.trace)
                    save(folder / "requests.json", recorder.requests)
                    save(folder / "metrics.json", metrics)
                    print(json.dumps(metrics), flush=True)
                if any(status in (401, 402, 403) for status in recorder.http_errors):
                    raise RuntimeError("provider_auth_or_balance_unavailable_stop_batch")
        if fingerprint() != manifest["runtime_sha256"]:
            raise ValueError("runtime_changed_during_experiment")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--phase", required=True, choices=("freeze", "dev", "holdout"))
    cli.add_argument("--env-file", type=Path)
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--holdout-file", type=Path)
    cli.add_argument("--arms", choices=("AB", "B"), default="AB")
    cli.add_argument("--repeats", type=int, choices=(1, 2), default=2)
    cli.add_argument("--thinking", choices=("disabled", "low", "high", "selective", "native"))
    cli.add_argument("--provider", choices=("deepseek", "asus-glm"), default="asus-glm")
    cli.add_argument("--case", help="Run one frozen case; allows disjoint cases in separate processes")
    asyncio.run(run(cli.parse_args()))
