"""Unselected server-owned corpus factory for V3 source checks."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.ai.direct_source import DirectSourceCorpus, load_direct_source_corpus
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_source_verifier import build_owned_source_verifier
from app.modules.ai.v3.pending_stage_transactions import _locked_job
from app.modules.source_editorial_review.service import SOURCE_PINS, resolve_pins


def _selection(job: Any) -> tuple[str, ...]:
    params = job.params if isinstance(job.params, dict) else {}
    selected = params.get("documents")
    if (not isinstance(selected, list) or not selected or not all(isinstance(v, str) for v in selected)
            or len(selected) != len(set(selected))):
        raise ValueError("v3_owned_selection_invalid")
    ids = tuple(selected)
    if any(str(UUID(value)) != value for value in ids):
        raise ValueError("v3_owned_selection_invalid")
    return ids


@dataclass(repr=False)
class OwnedSourceContext:
    corpus: DirectSourceCorpus = field(repr=False)
    journal: Any = field(repr=False)
    tenant_id: UUID
    user_id: UUID
    job_id: str
    selection: tuple[str, ...]

    def __repr__(self) -> str:
        return "OwnedSourceContext(<redacted>)"

    async def verify_locked(self, session: Any, job: Any, plan: dict[str, Any]) -> bool:
        try:
            if _selection(job) != self.selection:
                return False
            verify = build_owned_source_verifier(corpus=self.corpus, tenant_id=self.tenant_id,
                                                 user_id=self.user_id, job_id=self.job_id)
            return await verify(session, job, plan)
        except Exception:
            return False

    async def verify_before_send(self, plan: dict[str, Any]) -> bool:
        try:
            async with self.journal.sessions() as session:
                job = await _locked_job(session, self.journal, self.user_id)
                return await self.verify_locked(session, job, plan) is True
        except BaseException:
            return False


async def load_owned_source_context(*, journal: Any, tenant_id: UUID, user_id: UUID, job_id: str) -> OwnedSourceContext:
    """Read job selection, load via canonical server loader, then recheck under lock."""
    failed = False
    context: OwnedSourceContext | None = None
    try:
        if str(tenant_id) != journal.tenant_id or job_id != journal.job_id or not isinstance(user_id, UUID):
            raise ValueError("v3_owned_scope_invalid")
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            selected = _selection(job)
            analysis = job.params.get("source_analysis")
            approved = (await resolve_pins(session, tenant_id, selected, analysis[SOURCE_PINS])
                        if isinstance(analysis, dict) and SOURCE_PINS in analysis else None)
        if approved is None:
            corpus = await load_direct_source_corpus(list(selected), tenant_id=tenant_id)
        else:
            corpus = await load_direct_source_corpus(list(selected), tenant_id=tenant_id, approved_documents=approved)
        context = OwnedSourceContext(corpus, journal, tenant_id, user_id, job_id, selected)
        text = "\n\n".join(item.source_text for item in corpus.documents if item.source_text)
        plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": str(tenant_id), "job_id": job_id,
                "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            if await context.verify_locked(session, job, plan) is not True:
                raise ValueError("v3_owned_source_invalid")
    except BaseException:
        failed = True
    if failed or context is None:
        raise ExtractionOutcomeUnknownError("v3_owned_source_unverified")
    return context
