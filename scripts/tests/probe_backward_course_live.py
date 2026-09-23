"""Bounded, database-free live probe for synthetic course-quality fixtures.

This is deliberately not a release test: embeddings are disabled to isolate the
lesson/assessment seams and the source corpus contains no customer data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from dotenv import dotenv_values


class BudgetStop(BaseException):
    """Escape application fallbacks when the external-call budget is exhausted."""


class BudgetLedger:
    """Durably reserve peak-price worst-case cost *before* each external call.

    Reservations are never refunded: a timeout or crash may still be billable.
    An exclusive lock fails closed if another probe (or a crashed probe) exists.
    """

    def __init__(self, path: Path, *, cap_micro_usd: int, prior_micro_usd: int):
        self.path = path
        self.cap_micro_usd = cap_micro_usd
        self.prior_micro_usd = prior_micro_usd
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write({"cap_micro_usd": cap_micro_usd,
                         "prior_micro_usd": prior_micro_usd,
                         "reserved_micro_usd": prior_micro_usd, "requests": 0})
        self._load()

    def _load(self) -> dict[str, int]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value["cap_micro_usd"] != self.cap_micro_usd or value["prior_micro_usd"] != self.prior_micro_usd:
                raise ValueError("approval changed")
            if not self.prior_micro_usd <= value["reserved_micro_usd"] <= self.cap_micro_usd:
                raise ValueError("invalid reservation")
            if not isinstance(value["requests"], int) or value["requests"] < 0:
                raise ValueError("invalid count")
            return value
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise BudgetStop("missing, changed or corrupt paid-experiment ledger") from exc

    @property
    def reserved_micro_usd(self) -> int:
        return self._load()["reserved_micro_usd"]

    @property
    def requests(self) -> int:
        return self._load()["requests"]

    def _write(self, value: dict[str, int]) -> None:
        temporary = self.path.with_suffix(".pending")
        temporary.write_text(
            json.dumps(value, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
        )
        os.replace(temporary, self.path)

    def reserve(self, *, input_bytes: int, max_output_tokens: int) -> int:
        # Official 2026-09-23 peak rates: $0.30/M cache-miss input, $1.20/M output.
        # UTF-8 bytes plus 4096 serialization overhead conservatively bound input.
        if input_bytes > 100_000 or max_output_tokens > 8192:
            raise BudgetStop("request exceeds synthetic probe size bound")
        micro_usd = ((input_bytes + 4096) * 30 + max_output_tokens * 120 + 99) // 100
        lock = self.path.with_suffix(".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError as exc:
            raise BudgetStop("paid-experiment ledger is locked") from exc
        try:
            os.close(descriptor)
            value = self._load()
            if value["reserved_micro_usd"] + micro_usd > self.cap_micro_usd:
                raise BudgetStop("approved $2 experiment cap exhausted")
            value["reserved_micro_usd"] += micro_usd
            value["requests"] += 1
            self._write(value)
        finally:
            lock.unlink(missing_ok=True)
        return micro_usd


class NoEmbedding:
    async def embed_documents_with_provenance(self, _texts: list[str], *, on_progress=None):
        from app.modules.ai.llm_client import AllProvidersFailedError

        raise AllProvidersFailedError("embeddings intentionally excluded from seam probe")

    async def embed_queries_with_provenance(self, _texts: list[str], *, on_progress=None):
        raise AssertionError("query embeddings must not run after document failure")


class BoundedDeepSeek:
    def __init__(self, key: str, *, max_calls: int, ledger: BudgetLedger):
        self.key = key
        self.max_calls = max_calls
        self.ledger = ledger
        self.calls = 0
        self.failures: list[str] = []
        self.call_details: list[dict[str, Any]] = []

    async def _request_raw(self, messages: list[dict[str, Any]]) -> str:
        from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason
        input_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        max_output_tokens = 8192
        if self.calls >= self.max_calls:
            raise BudgetStop("run call budget exhausted")
        self.ledger.reserve(input_bytes=input_bytes, max_output_tokens=max_output_tokens)
        self.calls += 1
        payload = {
            "model": "deepseek-flash",
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json=payload,
                )
            if response.status_code != 200:
                self.failures.append(f"http_{response.status_code}")
                raise AllProvidersFailedError(
                    "live probe provider HTTP failure",
                    reasons=(ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,),
                )
            data = response.json()
            content = data["choices"][0]["message"].get("content") or ""
            task = "lesson"
            try:
                task = json.loads(messages[-1]["content"]).get("task", "lesson")
            except (KeyError, TypeError, ValueError):
                pass
            self.call_details.append({
                "task": task, "finish_reason": data["choices"][0].get("finish_reason"),
                "content_chars": len(content), "completion_tokens": data.get("usage", {}).get("completion_tokens"),
            })
            usage = data.get("usage", {})
            # Peak prices, intentionally conservative; cache hits are counted
            # as misses and no discount is assumed.
            self.call_details[-1]["peak_price_usage_usd"] = round((
                int(usage.get("prompt_tokens", 0)) * 0.30
                + int(usage.get("completion_tokens", 0)) * 1.20
            ) / 1_000_000, 6)
            return content
        except BudgetStop:
            raise
        except AllProvidersFailedError:
            raise
        except Exception as exc:
            self.failures.append(type(exc).__name__)
            raise AllProvidersFailedError(
                "live probe transport failure",
                reasons=(ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,),
            ) from exc

    async def ainvoke_validated(
        self, messages: list[dict[str, Any]], parser, config=None,
        response_format=None, repair_json_syntax=False,
    ):
        from app.modules.ai.llm_client import (
            AllProvidersFailedError, ValidatedCallFailureReason, ValidatedLLMResult,
            _json_syntax_correction_messages,
        )

        content = await self._request_raw(messages)
        attempts = 1
        reasons: tuple[ValidatedCallFailureReason, ...] = ()
        try:
            value = parser(content)
        except json.JSONDecodeError as exc:
            self.failures.append(type(exc).__name__)
            reasons = (ValidatedCallFailureReason.PROVIDER_OUTPUT_UNPARSEABLE,)
            if not repair_json_syntax:
                raise AllProvidersFailedError("probe JSON rejected", reasons=reasons) from exc
            corrected = await self._request_raw(_json_syntax_correction_messages(messages, content))
            attempts += 1
            try:
                value = parser(corrected)
            except json.JSONDecodeError as correction_exc:
                self.failures.append(type(correction_exc).__name__)
                raise AllProvidersFailedError("probe JSON correction rejected", reasons=reasons) from correction_exc
            except Exception as correction_exc:
                self.failures.append(type(correction_exc).__name__)
                raise AllProvidersFailedError(
                    "probe contract correction rejected",
                    reasons=(ValidatedCallFailureReason.CONTRACT_VIOLATION,),
                ) from correction_exc
        except Exception as exc:
            self.failures.append(type(exc).__name__)
            raise AllProvidersFailedError(
                "probe contract rejected",
                reasons=(ValidatedCallFailureReason.CONTRACT_VIOLATION,),
            ) from exc
        return ValidatedLLMResult(
            provider="deepseek-bounded-probe", model_id="deepseek-flash",
            value=value, attempt_count=attempts, failure_reasons=reasons,
        )


class LocalGLM(BoundedDeepSeek):
    """The same validation path against the existing, non-billable Asus model."""

    MODEL_ID = "GLM-5.3-Flash-EXL3"
    BASE_URL = "http://10.66.66.28:8888/v1"

    def __init__(self, *, max_calls: int, reasoning: str = "off"):
        if reasoning not in {"off", "low"}:
            raise ValueError("unsupported local GLM reasoning mode")
        self.max_calls = max_calls
        self.reasoning = reasoning
        self.calls = 0
        self.failures: list[str] = []
        self.call_details: list[dict[str, Any]] = []

    async def _request_raw(self, messages: list[dict[str, Any]]) -> str:
        from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason

        if self.calls >= self.max_calls:
            raise BudgetStop("local GLM run call budget exhausted")
        self.calls += 1
        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    json={
                        "model": self.MODEL_ID,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 8192,
                        "response_format": {"type": "json_object"},
                        "chat_template_kwargs": (
                            {"enable_thinking": False} if self.reasoning == "off"
                            else {"reasoning_effort": "low"}
                        ),
                    },
                )
            if response.status_code != 200:
                self.failures.append(f"http_{response.status_code}")
                raise AllProvidersFailedError(
                    "local GLM HTTP failure",
                    reasons=(ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,),
                )
            data = response.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            task = "unknown"
            try:
                task = json.loads(messages[-1]["content"]).get("task", "unknown")
            except (KeyError, TypeError, ValueError):
                pass
            self.call_details.append({
                "task": task,
                "seconds": round(perf_counter() - started, 3),
                "finish_reason": data["choices"][0].get("finish_reason"),
                "content_chars": len(content),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "raw_content_preview": content[:2000] if self.calls <= 2 else None,
            })
            print(
                f"GLM_CALL|number={self.calls}|seconds={self.call_details[-1]['seconds']}|"
                f"finish={self.call_details[-1]['finish_reason']}",
                file=sys.stderr, flush=True,
            )
            return content
        except (BudgetStop, AllProvidersFailedError):
            raise
        except Exception as exc:
            self.failures.append(type(exc).__name__)
            raise AllProvidersFailedError(
                "local GLM transport failure",
                reasons=(ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,),
            ) from exc

    async def ainvoke_validated(self, messages, parser, config=None, response_format=None,
                                repair_json_syntax=False):
        result = await super().ainvoke_validated(
            messages, parser, config=config, response_format=response_format,
            repair_json_syntax=repair_json_syntax,
        )
        return replace(result, provider="local-glm-probe", model_id=self.MODEL_ID)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("deepseek", "glm"), default="deepseek")
    parser.add_argument("--glm-reasoning", choices=("off", "low"), default="off")
    parser.add_argument("--max-runtime-seconds", type=int, default=1200)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--approval-id")
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--case", default="micro_one_rule")
    parser.add_argument("--convert-fixture", action="store_true")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.max_runtime_seconds < 1:
        parser.error("max runtime must be positive")
    # The 2026-09-23 bounded experiment is closed. Keep the reproducible
    # adapter and evidence, but require a reviewed edit and fresh owner
    # authority before another paid request can be sent by this harness.
    if not args.source_only and args.provider != "glm":
        parser.error("paid quality probe closed; new owner approval and reviewed guard required")

    repo = Path(__file__).resolve().parents[2]
    os.environ["PYTHONPATH"] = str(repo / "apps" / "api")
    sys.path.insert(0, str(repo / "apps" / "api"))
    env = dotenv_values(repo.parent.parent / ".env")
    if args.convert_fixture:
        for name in ("DOCLING_URL", "DOCLING_API_KEY"):
            if env.get(name):
                os.environ[name] = str(env[name])
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.application import generate_evidence_course, to_generation_artifacts
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.ingestion import DocumentChunker, DocumentConverter

    cases = json.loads((repo / "apps/api/tests/fixtures/course_generation_backward/corpus.json").read_text(encoding="utf-8"))["cases"]
    case = next((item for item in cases if item["id"] == args.case), None)
    if case is None:
        parser.error("unknown synthetic corpus case")
    if args.convert_fixture and case["id"] not in {"structured_policy", "spreadsheet_primary_auxiliary"}:
        parser.error("conversion fixture is available only for PDF and XLSX cases")
    conversion_started = perf_counter()
    doc_id = f"synthetic-{case['id']}"
    if args.convert_fixture:
        fixture_name = {
            "structured_policy": "structured_policy.pdf",
            "spreadsheet_primary_auxiliary": "collections.xlsx",
        }[case["id"]]
        fixture = repo / "apps/api/tests/fixtures/course_generation_backward" / fixture_name
        if not fixture.is_file():
            parser.error("approved synthetic fixture missing")
        converted = await DocumentConverter().convert(str(fixture))
        engine = converted["metadata"].get("engine", "")
        if fixture.suffix == ".pdf" and (engine == "pypdf" or converted["metadata"].get("fallback_used")):
            raise SystemExit("live_docling_unavailable: conversion fell back to pypdf")
        if fixture.suffix == ".xlsx" and engine != "openpyxl":
            raise SystemExit("unexpected_spreadsheet_converter")
        rows = DocumentChunker().chunk_markdown(converted["markdown"], doc_id, case["filename"])
        chunks = tuple(
            DirectSourceChunk(
                chunk_id=f"{doc_id}:{index}", doc_id=doc_id, doc_name=case["filename"],
                title=case["title"], headings=tuple(json.loads(row["metadata"]["headings"])),
                text=row["text"], source_revision="synthetic-v1", chunk_index=index,
            ) for index, row in enumerate(rows)
        )
    else:
        engine = "frozen_markdown_chunks"
        chunks = tuple(
            DirectSourceChunk(
                chunk_id=f"{doc_id}:{index}", doc_id=doc_id, doc_name=case["filename"],
                title=case["title"], headings=(chunk["heading"],), text=chunk["text"],
                source_revision="synthetic-v1", chunk_index=index,
            ) for index, chunk in enumerate(case["chunks"])
        )
    conversion_seconds = perf_counter() - conversion_started
    corpus = DirectSourceCorpus(
        tenant_id="synthetic-quality-probe",
        documents=(DirectSourceDocument(
            doc_id=doc_id, title=case["title"], filename=case["filename"],
            category="training_material", source_revision="synthetic-v1", chunks=chunks,
        ),), total_chars=sum(len(chunk.text) for chunk in chunks), total_chunks=len(chunks),
    )
    if args.source_only:
        print(json.dumps({
            "case": case["id"], "engine": engine,
            "conversion_seconds": round(conversion_seconds, 3),
            "chunks": [{"headings": chunk.headings, "text": chunk.text} for chunk in chunks],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.provider == "glm":
        client = LocalGLM(max_calls=args.max_calls, reasoning=args.glm_reasoning)
    else:
        raise AssertionError("paid provider must remain closed")
    if args.output and args.output.exists():
        parser.error("output artifact exists; refusing overwrite")

    def emit(value: dict[str, Any]) -> None:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n",
            )
            print(json.dumps({"case": args.case, "status": value.get("status"),
                              "calls": client.calls, "output": str(args.output)}, ensure_ascii=False))
        else:
            print(json.dumps(value, ensure_ascii=False, indent=2))

    try:
        generated = await asyncio.wait_for(
            generate_evidence_course(
                corpus, intent=CourseIntent(), generation_client=client, embedding_client=NoEmbedding(),
            ), timeout=args.max_runtime_seconds,
        )
        artifacts = to_generation_artifacts(generated)
        lessons = [lesson for module in artifacts.content.modules for lesson in module.lessons]
        questions = [question for assessment in artifacts.assessment.assessments for question in assessment.mcq]
        emit({
            "status": "completed",
            "case": case["id"], "calls": client.calls,
            "converter_engine": engine,
            "conversion_seconds": round(conversion_seconds, 3),
            "timings": [asdict(item) for item in generated.result.timings],
            "provider": args.provider,
            "glm_reasoning": args.glm_reasoning,
            "provider_failures": client.failures,
            "call_details": client.call_details,
            "lessons": [{"title": lesson.title, "content": lesson.content} for lesson in lessons],
            "questions": [{
                "prompt": question.question,
                "options": [option.text for option in question.options],
                "correct": [option.text for option in question.options if option.is_correct],
                "source_quote": question.source_quote,
            } for question in questions],
            "publishable": generated.result.publishability.publishable,
            "publishability_reasons": generated.result.publishability.reasons,
            "fallback_count": generated.result.deterministic_fallback_count,
            "assessment_review": generated.result.assessment_review,
        })
        return 0
    except BudgetStop as exc:
        emit({"status": "budget_stopped", "case": args.case, "calls": client.calls,
              "stopped": str(exc), "call_details": client.call_details})
        return 2
    except Exception as exc:
        emit({"status": "failed", "case": args.case, "calls": client.calls,
              "failure_type": type(exc).__name__, "call_details": client.call_details})
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
