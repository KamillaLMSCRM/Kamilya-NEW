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
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values


class BudgetStop(BaseException):
    """Escape application fallbacks when the external-call budget is exhausted."""


class NoEmbedding:
    async def embed_documents_with_provenance(self, _texts: list[str], *, on_progress=None):
        from app.modules.ai.llm_client import AllProvidersFailedError

        raise AllProvidersFailedError("embeddings intentionally excluded from seam probe")

    async def embed_queries_with_provenance(self, _texts: list[str], *, on_progress=None):
        raise AssertionError("query embeddings must not run after document failure")


class BoundedDeepSeek:
    def __init__(self, key: str, *, max_calls: int, max_cost: float):
        self.key = key
        self.max_calls = max_calls
        self.max_cost = max_cost
        self.calls = 0
        self.estimated_usd = 0.0
        self.failures: list[str] = []
        self.call_details: list[dict[str, Any]] = []

    async def ainvoke_validated(
        self, messages: list[dict[str, Any]], parser, config=None,
        response_format=None, repair_json_syntax=False,
    ):
        from app.modules.ai.llm_client import (
            AllProvidersFailedError,
            ValidatedLLMResult,
        )

        # Worst-case billing bound: even if every UTF-8 character were a token,
        # eight calls at these request limits stay far below the approved $2.
        input_chars = sum(len(str(message.get("content", ""))) for message in messages)
        max_output_tokens = 8192
        worst_call_usd = (input_chars * 0.30 + max_output_tokens * 1.20) / 1_000_000
        if input_chars > 20_000:
            raise BudgetStop("request input exceeds 20,000-character fixture guard")
        if self.calls >= self.max_calls or self.estimated_usd + worst_call_usd > self.max_cost:
            raise BudgetStop("approved call or cost budget exhausted")
        self.calls += 1
        self.estimated_usd += worst_call_usd
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
                raise AllProvidersFailedError("live probe provider HTTP failure")
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
            value = parser(content)
            usage = data.get("usage", {})
            # Peak prices, intentionally conservative; cache hits are counted
            # as misses and no discount is assumed.
            actual_usd = (
                int(usage.get("prompt_tokens", input_chars)) * 0.30
                + int(usage.get("completion_tokens", max_output_tokens)) * 1.20
            ) / 1_000_000
            self.estimated_usd += max(0.0, actual_usd - worst_call_usd)
            return ValidatedLLMResult(
                provider="deepseek-bounded-probe", model_id="deepseek-flash",
                value=value, attempt_count=1, failure_reasons=(),
            )
        except BudgetStop:
            raise
        except AllProvidersFailedError:
            raise
        except Exception as exc:
            self.failures.append(type(exc).__name__)
            raise AllProvidersFailedError("live probe validation or transport failure") from exc


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--max-cost-usd", type=float, default=2.0)
    parser.add_argument("--case", default="micro_one_rule")
    args = parser.parse_args()
    # The only approved experiment is exhausted. A subsequent paid run requires
    # fresh owner authority and a reviewed code change to this allowlist.
    approved_call_limits = {"2026-09-23": 8}
    consumed_calls = {"2026-09-23": 8}
    if args.approval_id not in approved_call_limits or (
        consumed_calls[args.approval_id] >= approved_call_limits[args.approval_id]
    ):
        parser.error("no unspent provider experiment approval is configured")
    if not args.allow_paid or not 1 <= args.max_calls <= 8 or not 0 < args.max_cost_usd <= 2:
        parser.error("explicit --allow-paid and approved limits of <=8 calls, <=$2 required")

    repo = Path(__file__).resolve().parents[2]
    os.environ["PYTHONPATH"] = str(repo / "apps" / "api")
    sys.path.insert(0, str(repo / "apps" / "api"))
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.evidence_engine.application import generate_evidence_course, to_generation_artifacts
    from app.modules.ai.evidence_engine.models import CourseIntent

    key = dotenv_values(repo.parent.parent / ".env").get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY absent in the canonical Kamilya environment")
    cases = json.loads((repo / "apps/api/tests/fixtures/course_generation_backward/corpus.json").read_text(encoding="utf-8"))["cases"]
    case = next((item for item in cases if item["id"] == args.case), None)
    if case is None:
        parser.error("unknown synthetic corpus case")
    doc_id = f"synthetic-{case['id']}"
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"{doc_id}:{index}", doc_id=doc_id, doc_name=case["filename"],
            title=case["title"], headings=(chunk["heading"],), text=chunk["text"],
            source_revision="synthetic-v1", chunk_index=index,
        ) for index, chunk in enumerate(case["chunks"])
    )
    corpus = DirectSourceCorpus(
        tenant_id="synthetic-quality-probe",
        documents=(DirectSourceDocument(
            doc_id=doc_id, title=case["title"], filename=case["filename"],
            category="training_material", source_revision="synthetic-v1", chunks=chunks,
        ),), total_chars=sum(len(chunk.text) for chunk in chunks), total_chunks=len(chunks),
    )
    client = BoundedDeepSeek(str(key), max_calls=args.max_calls, max_cost=args.max_cost_usd)
    try:
        generated = await generate_evidence_course(
            corpus, intent=CourseIntent(), generation_client=client, embedding_client=NoEmbedding(),
        )
        artifacts = to_generation_artifacts(generated)
        lessons = [lesson for module in artifacts.content.modules for lesson in module.lessons]
        questions = [question for assessment in artifacts.assessment.assessments for question in assessment.mcq]
        print(json.dumps({
            "case": case["id"], "calls": client.calls,
            "conservative_usd_upper_estimate": round(client.estimated_usd, 5),
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
            "assessment_review": generated.result.assessment_review,
        }, ensure_ascii=False, indent=2))
        return 0
    except BudgetStop as exc:
        print(json.dumps({"case": args.case, "calls": client.calls,
                          "estimated_usd": round(client.estimated_usd, 5),
                          "stopped": str(exc), "call_details": client.call_details}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"case": args.case, "calls": client.calls,
                          "estimated_usd": round(client.estimated_usd, 5),
                          "failure_type": type(exc).__name__,
                          "call_details": client.call_details}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
