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

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.modules.ai.direct_source import DirectSourceError, load_direct_source_corpus
from app.modules.ai.llm_client import AllProvidersFailedError, ResilientLLMClient
from app.modules.ai.source_editorial_model import editorial_review_messages, prepare_source_working_edition
from app.modules.source_editorial_review.domain import POLICY, ReviewConflictError, render_text, text_hash
from app.modules.source_editorial_review.service import add_event, history, owned_document, read_state, review_enabled

logger = logging.getLogger(__name__)
_BLOCK_CHARS = 36_000
_OUTLINE_LINE = re.compile(r"^\s*(?:#{1,6}\s|\d+(?:\.\d+)*(?:[.)]|\s)\s*)\S")
_ANALYSIS_POLICY = "human-source-editorial-analysis-v2"
_SEMANTIC_REVIEW = """
You also own an independent pre-publication check of the ORIGINAL rules, even
when there are no proposed text edits. Your output has exactly three top-level keys:
proposal_sha256, rows, source_questions. The first two keep the edit-review contract.
Before checking the edits, trace each decision whose outcome affects what a
learner should do. Test each boundary at the exact value and check conditions,
exceptions, responsible roles, referenced clauses, conflicting deadlines and
unreadable terms. For example, two rules saying "below/up to N" and "above N"
without explicitly saying what applies at N require an owner question if the
wording can reasonably leave that value out. Do not assume an inclusive reading.
If the original explicitly settles the boundary elsewhere, do not report it.
Use the outline only as context for cross-references; quote from the local original.
The author's candidate uncertainties are clues to check, not established facts.
Do not ask the owner to fix spelling, formatting, or an unapproved cosmetic
edit. Ask only where the original cannot establish what a learner should do.

Each source_questions row has only excerpt (a unique exact original quotation,
up to 2000 characters), category (boundary|conflict|reference|responsibility|
exception|unclear), and reason (a concrete question and relevant interpretations
in the original language, up to 700 characters). Include a separate row per
material finding. Do not manufacture findings or resolve them yourself. If no
human decision is needed, explicitly return an empty source_questions array.
"""

class _SourceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    excerpt: str = Field(min_length=1, max_length=2000)
    category: str = Field(pattern=r"^(boundary|conflict|reference|responsibility|exception|unclear)$")
    reason: str = Field(min_length=3, max_length=700)


class _IndependentReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: list[dict[str, Any]] = Field(max_length=256)
    source_questions: list[_SourceQuestion] = Field(max_length=256)


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
    basis = text_hash(_ANALYSIS_POLICY + ":" + source_id + ":" + text_hash(original) + ":" + text_hash(outline_text))
    for index, (offset, local) in enumerate(bounded_blocks):
        if not local.strip():
            continue
        key = text_hash(f"{basis}:{index}:{offset}:{text_hash(local)}")
        saved = retained.get(key) if retained is not None else None
        if saved is not None:
            questions.extend(saved["questions"])
            auto.extend(saved["automatic"])
            continue

        independent: _IndependentReview | None = None
        block_calls = 0
        candidate_questions: object = []

        async def invoke(messages: list[dict[str, str]]) -> object:
            nonlocal independent, block_calls, candidate_questions
            block_calls += 1
            payload = json.loads(messages[1]["content"])
            if "proposal_sha256" in payload:
                if outline_text:
                    payload["related_source_outline"] = outline_text
                if candidate_questions:
                    payload["author_candidate_uncertainties"] = candidate_questions
                patch_contract = messages[0]["content"].replace(
                    'Output exactly {"proposal_sha256": supplied value, "rows": [...]}.', ""
                )
                independent = _IndependentReview.model_validate(await complete_json([
                    {"role": "system", "content": patch_contract + _SEMANTIC_REVIEW},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ]))
                if independent.proposal_sha256 != payload["proposal_sha256"]:
                    raise ReviewConflictError("source_review_independent_proposal_changed")
                return independent.model_dump(exclude={"source_questions"})
            authored = await complete_json(messages)
            if isinstance(authored, Mapping):
                candidate_questions = authored.get("unresolved", [])
            return authored

        result = await prepare_source_working_edition(local, source_id=source_id,
            chunk_id=f"editorial-doc:{document_id}:{index}", complete_json=invoke)
        if independent is None:
            wire = await invoke(editorial_review_messages(local, result.proposal))
            if wire != result.review_wire or independent is None:
                raise ReviewConflictError("source_review_independent_proposal_changed")
        calls += block_calls
        block_questions: list[dict[str, Any]] = []
        block_auto = []
        for n, finding in enumerate(independent.source_questions):
            start = local.index(finding.excerpt) if local.count(finding.excerpt) == 1 else None
            block_questions.append({"id": f"s{index}-{n}", "start": None if start is None else offset + start,
                "end": None if start is None else offset + start + len(finding.excerpt),
                "quote": finding.excerpt, "category": finding.category, "reason": finding.reason})
        # Failed cosmetic proposals keep their original text. They are not
        # human blockers; only the independent policy questions are shown.
        for patch in result.proposal.patches:
            if patch.alias in result.edition.applied_patch_aliases:
                block_auto.append({"id": f"a{index}-{patch.alias}", "start": offset + patch.start,
                    "end": offset + patch.end, "before": patch.before, "after": patch.after,
                    "reason": patch.reason, "category": patch.category})
        if checkpoint is not None:
            await checkpoint(key, {"questions": block_questions, "automatic": block_auto, "calls": block_calls})
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
            "automatic": auto, "model_calls": calls, "policy": POLICY, "analysis_policy": _ANALYSIS_POLICY}


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
        return bool((latest.kind == "running" and latest.id == claim.id) or (
            latest.kind == "analysis_block" and latest.payload.get("claim_id") == str(claim.id)
        ))

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
            from app.modules.ai.qa_luna_dev_route import QA_TENANT

            settings = get_settings()
            managed = None
            if tenant_id == QA_TENANT and settings.AI_MANAGED_LUNA_QA_DEV_ENABLED:
                managed = await create_managed_qa_client(settings=settings, tenant_id=tenant_id,
                    user_id=claim.actor_id, job_id=str(claim.id), profile="luna6")
            llm = await ResilientLLMClient.from_settings_async(
                temperature=0.1, max_tokens=16_384,
            ) if managed is None else None
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
                standard = await llm.ainvoke(
                    messages, response_format={"type": "json_object"}, request_profile="course_generation",
                )
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
        if isinstance(error, DirectSourceError):
            code = error.code
        elif isinstance(error, ReviewConflictError):
            code = str(error)
        elif isinstance(error, AllProvidersFailedError):
            code = "source_review_provider_unavailable"
        elif isinstance(error, TimeoutError):
            code = "source_review_timeout"
        elif isinstance(error, json.JSONDecodeError | ValidationError):
            code = "source_review_invalid_response"
        else:
            code = "source_review_analysis_failed"
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
