"""One bounded production-seam assessment smoke against the private ASUS GLM.

The source is synthetic, embeddings are deterministic and local, and no database,
tenant, deployment, paid provider or production setting is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api"))

from app.modules.ai.evidence_engine.application import generate_evidence_course  # noqa: E402
from app.modules.ai.evidence_engine.models import CourseIntent  # noqa: E402
from app.modules.ai.llm_client import LLMProviderConfig, ResilientLLMClient  # noqa: E402
from scripts.dev.objective_alignment.run import Recorder  # noqa: E402
from scripts.dev.run_evidence_course_application import _render  # noqa: E402
from scripts.dev.run_semantic_block_smoke import SOURCES, corpus_for  # noqa: E402


class _DeterministicEmbeddings:
    """No-cost retrieval adapter; assessment quality is the variable under test."""

    @staticmethod
    def _vectors(texts: list[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple((byte + 1) / 256 for byte in hashlib.sha256(text.encode()).digest()[:8])
                     for text in texts)

    async def embed_documents_with_provenance(self, texts: list[str], *, on_progress=None):
        if on_progress is not None:
            await on_progress(len(texts), len(texts), "deterministic-local")
        return SimpleNamespace(vectors=self._vectors(texts), model="deterministic-local",
                               space="deterministic-local-v1")

    async def embed_queries_with_provenance(self, texts: list[str], *, on_progress=None):
        if on_progress is not None:
            await on_progress(len(texts), len(texts), "deterministic-local")
        return SimpleNamespace(vectors=self._vectors(texts), model="deterministic-local",
                               space="deterministic-local-v1")


class _CapturedReplay:
    """Replay immutable raw model responses by task without another provider call."""

    def __init__(self, trace_path: Path | Sequence[Path], *, fallback=None) -> None:
        trace_paths = (trace_path,) if isinstance(trace_path, Path) else tuple(trace_path)
        if not trace_paths:
            raise ValueError("captured_replay_requires_trace")
        self._responses: dict[str, deque[str]] = defaultdict(deque)
        self._identified_responses: dict[tuple[str, str], deque[str]] = defaultdict(deque)
        self._request_responses: dict[tuple[str, str], deque[str]] = defaultdict(deque)
        for path in trace_paths:
            trace = json.loads(path.read_text(encoding="utf-8"))
            for entry in trace:
                task = str(entry.get("task") or "realization")
                request_sha256 = entry.get("request_sha256")
                for response in entry.get("responses") or []:
                    raw = response.get("raw")
                    if isinstance(raw, str):
                        if task == "realization":
                            # A lesson response is safe to reuse only for the exact
                            # source/evidence request that produced it. Legacy traces
                            # without this fingerprint deliberately miss and fall back.
                            if isinstance(request_sha256, str) and request_sha256:
                                self._request_responses[(task, request_sha256)].append(raw)
                            continue
                        identity = self._response_identity(task, raw)
                        if identity is None:
                            self._responses[task].append(raw)
                        else:
                            self._identified_responses[(task, identity)].append(raw)
        self.calls = 0
        self.captured_calls = 0
        self.live_fallback_calls = 0
        self._fallback = fallback
        self.response_models = {"captured-replay"}
        self.trace: list[dict[str, object]] = []

    @staticmethod
    def _response_identity(task: str, raw: str) -> str | None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if task in {"assessment_generate", "assessment_repair"}:
            items = payload.get("questions") or []
            key = "axis_id"
        elif task in {"assessment_review", "assessment_constraints"}:
            items = payload.get("reviews") or []
            key = "question_id"
        else:
            return None
        identities = [str(item[key]) for item in items if isinstance(item, dict) and item.get(key)]
        return identities[0] if identities else None

    @staticmethod
    def _request_sha256(request: dict[str, object]) -> str:
        canonical = json.dumps(
            request,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _request_identity(task: str, request: dict[str, object]) -> str | None:
        if task in {"assessment_generate", "assessment_repair"}:
            items = request.get("axes") or []
            key = "axis_id"
        elif task in {"assessment_review", "assessment_constraints"}:
            items = request.get("questions") or []
            key = "question_id"
        else:
            return None
        identities = [str(item[key]) for item in items if isinstance(item, dict) and item.get(key)]
        return identities[0] if identities else None

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        task = str(request.get("task") or "realization")
        identity = self._request_identity(task, request)
        request_sha256 = self._request_sha256(request)
        if task == "realization":
            identified = self._request_responses[(task, request_sha256)]
        else:
            identified = (
                self._identified_responses[(task, identity)] if identity is not None else None
            )
        queues = [queue for queue in (identified, self._responses[task]) if queue is not None]
        rejected = False
        while queue := next((candidate for candidate in queues if candidate), None):
            raw = queue.popleft()
            self.calls += 1
            self.captured_calls += 1
            record = {
                "task": task,
                "identity": identity,
                "request_sha256": request_sha256,
                "captured_response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            }
            self.trace.append(record)
            try:
                value = parser(raw)
            except (ValueError, KeyError, TypeError):
                rejected = True
                record["captured_validation"] = "rejected"
                continue
            record["captured_validation"] = "accepted"
            return SimpleNamespace(value=value, attempt_count=1, failure_reasons=(),
                                   model_id="captured-replay", provider="captured-replay")
        return await self._live_fallback(
            messages,
            parser,
            task=task,
            identity=identity,
            reason="captured_validation_rejected" if rejected else "missing",
            **_kwargs,
        )

    async def _live_fallback(self, messages, parser, *, task, identity, reason, **kwargs):
        if self._fallback is None:
            raise RuntimeError(f"captured_response_{reason}:{task}:{identity or 'unidentified'}")
        self.calls += 1
        self.live_fallback_calls += 1
        self.trace.append({"task": task, "identity": identity,
                           "request_sha256": self._request_sha256(
                               json.loads(messages[-1]["content"])
                           ), "live_fallback_reason": reason})
        result = await self._fallback.ainvoke_validated(messages, parser=parser, **kwargs)
        self.response_models.add(result.model_id)
        return result

async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=tuple(SOURCES), default="single-rule")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-trace", type=Path, action="append")
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("Use a new output directory; evidence is append-only")

    config = LLMProviderConfig(
        name="asus-glm",
        base_url="http://10.66.66.28:8888/v1",
        api_key="local-no-key",
        model="GLM-5.3-Flash-EXL3",
        timeout=600,
        max_retries=0,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    recorder = (
        _CapturedReplay(args.replay_trace)
        if args.replay_trace is not None
        else Recorder(
            ResilientLLMClient([config], temperature=0.2, max_tokens=8192),
            max_calls=24,
            thinking="native",
        )
    )
    started = time.perf_counter()
    output = await generate_evidence_course(
        corpus_for(SOURCES[args.source], args.source),
        intent=CourseIntent(),
        generation_client=recorder,
        embedding_client=_DeterministicEmbeddings(),
    )
    elapsed = round(time.perf_counter() - started, 3)
    result = output.result.to_dict()
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "course-and-assessment.md").write_text(_render(output), encoding="utf-8")
    metrics = {
        "source": args.source,
        "provider": "captured-replay" if args.replay_trace is not None else config.name,
        "requested_model": "captured-replay" if args.replay_trace is not None else config.model,
        "returned_models": sorted(recorder.response_models),
        "seconds": elapsed,
        "calls": recorder.calls,
        "lessons": len(output.result.realized_course.lessons),
        "questions": len(output.result.realized_assessment.questions),
        "publishable": output.result.publishability.publishable,
        "publishability_reasons": output.result.publishability.reasons,
        "assessment_review": output.result.assessment_review,
        "stages": {timing.stage: round(timing.seconds, 3) for timing in output.result.timings},
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "trace.json").write_text(
        json.dumps(recorder.trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
