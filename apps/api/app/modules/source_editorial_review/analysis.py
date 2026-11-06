"""Source-only analysis with original-coordinate findings and guarded auto edits."""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.modules.ai.direct_source import DirectSourceError, load_direct_source_corpus
from app.modules.ai.source_editorial_model import prepare_source_working_edition
from app.modules.source_editorial_review.domain import POLICY, ReviewConflictError, render_text, text_hash
from app.modules.source_editorial_review.service import add_event, history, owned_document, read_state, review_enabled

logger = logging.getLogger(__name__)
_BLOCK_CHARS = 36_000
_OUTLINE_LINE = re.compile(r"^\s*(?:#{1,6}\s|\d+(?:\.\d+)*(?:[.)]|\s)\s*)\S")
_SEMANTIC_REVIEW = """
Also act as the policy owner's source reviewer. Report only ambiguities that can
change actions or learning: conflicting rules and deadlines, unassigned roles,
several plausible clause targets, a gap/overlap at numeric boundaries, missing
exceptions or unreadable terms. Put them in unresolved with an exact local
quote. Explain the question and plausible readings in the original language
within the existing reason field. Do not turn any such interpretation into a
patch. Do not invent a resolution, external standard, or missing fact.
If an outline is present, use it only to check related sections and references.
Do not report a distant line as a quote unless it is literally in original.
"""


def blocks(original: str) -> Iterator[tuple[int, str]]:
    start = 0
    while start < len(original):
        limit = min(start + _BLOCK_CHARS, len(original))
        if limit < len(original):
            floor = start + _BLOCK_CHARS // 2
            paragraph = original.rfind("\n\n", floor, limit)
            line = original.rfind("\n", floor, limit)
            space = original.rfind(" ", floor, limit)
            for pos, width in ((paragraph, 2), (line, 1), (space, 1)):
                if pos >= floor:
                    limit = pos + width
                    break
        yield start, original[start:limit]
        start = limit


async def analyze(
    original: str, *, source_id: str, document_id: str,
    complete_json: Callable[[list[dict[str, str]]], Awaitable[object]],
    retained: Mapping[str, dict[str, Any]] | None = None,
    checkpoint: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    render_text(original, [])
    bounded_blocks = list(blocks(original))
    outline = [line.strip()[:400] for line in original.splitlines() if _OUTLINE_LINE.match(line)]
    outline_text = "\n".join(outline) if len(bounded_blocks) > 1 else ""
    # An outline supplements the full local blocks; it never replaces one.
    if len(outline_text) > 24_000:
        headings = [line for line in outline if line.startswith("#")]
        outline_text = "\n".join(headings)[:24_000]
    questions: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []
    calls = 0
    basis = text_hash(POLICY + ":" + source_id + ":" + text_hash(original) + ":" + text_hash(outline_text))
    for index, (offset, local) in enumerate(bounded_blocks):
        if not local.strip():
            continue
        key = text_hash(f"{basis}:{index}:{offset}:{text_hash(local)}")
        saved = retained.get(key) if retained is not None else None
        if saved is not None:
            questions.extend(saved["questions"])
            auto.extend(saved["automatic"])
            continue

        async def invoke(messages: list[dict[str, str]]) -> object:
            if messages[0]["content"].startswith("You are a conservative source-document editor"):
                payload = json.loads(messages[1]["content"])
                if outline_text:
                    payload["related_source_outline"] = outline_text
                messages = [
                    {"role": "system", "content": messages[0]["content"] + _SEMANTIC_REVIEW},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ]
            return await complete_json(messages)

        result = await prepare_source_working_edition(local, source_id=source_id,
            chunk_id=f"editorial-doc:{document_id}:{index}", complete_json=invoke)
        calls += result.model_calls
        block_questions = []
        block_auto = []
        for gap in result.edition.gaps:
            block_questions.append({"id": f"q{index}-{gap.alias}", "start": offset + gap.start,
                "end": offset + gap.end, "quote": local[gap.start:gap.end],
                "category": gap.category, "reason": gap.reason})
        for diagnostic in result.unbound_diagnostics:
            block_questions.append({"id": f"u{index}-{diagnostic.alias}", "start": None, "end": None,
                "quote": diagnostic.reported_excerpt, "category": diagnostic.category, "reason": diagnostic.reason})
        for patch in result.proposal.patches:
            if patch.alias in result.edition.applied_patch_aliases:
                block_auto.append({"id": f"a{index}-{patch.alias}", "start": offset + patch.start,
                    "end": offset + patch.end, "before": patch.before, "after": patch.after,
                    "reason": patch.reason, "category": patch.category})
        if checkpoint is not None:
            await checkpoint(key, {"questions": block_questions, "automatic": block_auto, "calls": result.model_calls})
        questions.extend(block_questions)
        auto.extend(block_auto)

    # Merge overlapping findings so two answers cannot overwrite the same source
    # span. Do not apply even a safe auto edit inside a decision a human must make.
    grouped: list[dict[str, Any]] = []
    anchored = sorted((q for q in questions if q["start"] is not None), key=lambda q: q["start"])
    for row in anchored:
        if not grouped or grouped[-1]["end"] <= row["start"]:
            grouped.append(dict(row))
        else:
            last = grouped[-1]
            last["end"] = max(last["end"], row["end"])
            last["quote"] = original[last["start"]:last["end"]]
            if row["reason"] not in last["reason"]:
                last["reason"] += "\n" + row["reason"]
    auto = [row for row in auto if not any(
        row["start"] < question["end"] and question["start"] < row["end"] for question in grouped
    )]
    render_text(original, auto)
    return {"original": original, "issues": [*grouped, *(q for q in questions if q["start"] is None)],
            "automatic": auto, "model_calls": calls, "policy": POLICY}


async def run_analysis(tenant_id: UUID, document_id: UUID, event_id: UUID) -> str:
    if not review_enabled():
        return "disabled"
    async with async_session_factory() as db:
        await db.execute(text("SELECT set_current_tenant(:tenant)"), {"tenant": str(tenant_id)})
        doc = await owned_document(db, tenant_id, document_id, lock=True)
        rows = await history(db, tenant_id, document_id)
        if not rows or rows[-1].id != event_id or rows[-1].kind != "queued":
            return "already_claimed"
        queued = rows[-1]
        if queued.created_at < datetime.now(UTC) - timedelta(minutes=20):
            return "expired"
        state = read_state(rows, doc.content_sha256)
        claim = add_event(db, doc, actor_id=queued.actor_id, sequence=state.revision + 1,
                          kind="running", payload={"queued_event_id": str(event_id)})
        await db.commit()

    def owns(latest: Any) -> bool:
        return (latest.kind == "running" and latest.id == claim.id) or (
            latest.kind == "analysis_block" and latest.payload.get("claim_id") == str(claim.id)
        )

    retained = {row.payload["key"]: row.payload["result"] for row in rows if row.kind == "analysis_block"}

    async def save_block(key: str, result: dict[str, Any]) -> None:
        async with async_session_factory() as db:
            await db.execute(text("SELECT set_current_tenant(:tenant)"), {"tenant": str(tenant_id)})
            doc = await owned_document(db, tenant_id, document_id, lock=True)
            events = await history(db, tenant_id, document_id)
            if not events or not owns(events[-1]) or doc.content_sha256 != claim.original_blob_sha256:
                raise ReviewConflictError("source_review_analysis_claim_changed")
            add_event(db, doc, actor_id=claim.actor_id, sequence=events[-1].sequence + 1, kind="analysis_block",
                      payload={"claim_id": str(claim.id), "key": key, "result": result})
            await db.commit()
    async def verify_claim() -> bool:
        async with async_session_factory() as db:
            await db.execute(text("SELECT set_current_tenant(:tenant)"), {"tenant": str(tenant_id)})
            current = await owned_document(db, tenant_id, document_id)
            events = await history(db, tenant_id, document_id)
            return bool(events and owns(events[-1]) and current.content_sha256 == claim.original_blob_sha256)

    try:
        async with asyncio.timeout(750):
            corpus = await load_direct_source_corpus([str(document_id)], tenant_id=tenant_id)
            source = corpus.documents[0]
            if source.source_revision != f"document:{claim.original_blob_sha256}" or not source.source_text:
                raise ReviewConflictError("source_review_original_changed")
            if source.review_only_source_unresolved:
                raise ReviewConflictError("source_review_extraction_incomplete")
            from app.modules.ai.direct_luna_responses_factory import create_managed_qa_client
            from app.modules.ai.llm_client import create_llm
            from app.modules.ai.qa_luna_dev_route import QA_TENANT

            settings = get_settings()
            managed = None
            if tenant_id == QA_TENANT and settings.AI_MANAGED_LUNA_QA_DEV_ENABLED:
                managed = await create_managed_qa_client(settings=settings, tenant_id=tenant_id,
                    user_id=claim.actor_id, job_id=str(claim.id), profile="luna6")
            llm = create_llm(temperature=0.1, max_tokens=16_384) if managed is None else None
            usage: list[dict[str, Any]] = []

            async def complete(messages: list[dict[str, str]]) -> object:
                if managed is not None:
                    prepared = await managed.prepare(messages, max_output_tokens=16_384, ownership_checkpoint=verify_claim)
                    reply = await managed.invoke(prepared, tenant_id=tenant_id, user_id=claim.actor_id,
                        job_id=str(claim.id), ownership_checkpoint=verify_claim,
                        stage_id=text_hash(json.dumps(messages, ensure_ascii=False, sort_keys=True)))
                    usage.append({"model": reply.model, **asdict(reply.usage)})
                    return reply.content
                if llm is None or not await verify_claim():
                    raise ReviewConflictError("source_review_analysis_claim_changed")
                standard = await llm.ainvoke(messages, response_format={"type": "json_object"})
                return json.loads(standard.content)

            try:
                payload = await analyze(source.source_text.strip(), source_id=source.source_revision,
                                        document_id=str(document_id), complete_json=complete, retained=retained,
                                        checkpoint=save_block)
            finally:
                if managed is not None:
                    managed.close()
            payload["usage"] = usage
            payload["fidelity"] = asdict(source.conversion_fidelity)
            kind = "analyzed"
    except Exception as error:
        code = error.code if isinstance(error, DirectSourceError) else (
            str(error) if isinstance(error, ReviewConflictError) else "source_review_analysis_failed"
        )
        logger.warning("Source review analysis failed (%s)", type(error).__name__)
        payload, kind = {"code": code}, "failed"
    async with async_session_factory() as db:
        await db.execute(text("SELECT set_current_tenant(:tenant)"), {"tenant": str(tenant_id)})
        doc = await owned_document(db, tenant_id, document_id, lock=True)
        rows = await history(db, tenant_id, document_id)
        if not rows or not owns(rows[-1]) or doc.content_sha256 != claim.original_blob_sha256:
            return "claim_changed"
        add_event(db, doc, actor_id=claim.actor_id, sequence=rows[-1].sequence + 1, kind=kind, payload=payload)
        await db.commit()
    return kind
