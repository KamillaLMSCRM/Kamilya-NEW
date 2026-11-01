"""Unwired source verifier for a locked V3 job and server-loaded corpus."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.models.document import Document
from app.modules.ai.direct_source import DirectSourceCorpus


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_owned_source_verifier(*, corpus: DirectSourceCorpus, tenant_id: UUID, user_id: UUID,
                                job_id: str) -> Callable[[Any, Any, dict[str, Any]], Awaitable[bool]]:
    """Return a DB-only callback. Caller already owns the job/delivery row lock.

    Documents are locked in UUID order using the same supplied session. Converted
    text is checked against the stage digest; the stored document hash identifies
    the source revision and is not assumed to hash converted text.
    """
    async def verify(session: Any, job: Any, plan: dict[str, Any]) -> bool:
        try:
            if (not isinstance(tenant_id, UUID) or not isinstance(user_id, UUID) or not isinstance(job_id, str)
                    or not job_id or str(corpus.tenant_id) != str(tenant_id) or str(job.id) != job_id
                    or job.tenant_id != tenant_id or job.user_id != user_id or job.status != "running"):
                return False
            params = job.params if isinstance(job.params, dict) else {}
            analysis = params.get("source_analysis")
            selected = params.get("documents")
            if (not isinstance(analysis, dict) or analysis.get("generation_engine") not in {"evidence_v3", "v3_cogen"}
                    or not isinstance(selected, list) or not selected or not all(isinstance(v, str) for v in selected)
                    or len(set(selected)) != len(selected) or selected != [str(d.doc_id) for d in corpus.documents]):
                return False
            ids = [UUID(value) for value in selected]
            if any(str(value) != original for value, original in zip(ids, selected, strict=True)):
                return False
            documents = {str(doc.doc_id): doc for doc in corpus.documents}
            if any(not isinstance(doc.source_text, str) or not doc.source_text for doc in corpus.documents):
                return False
            for document_id in sorted(ids, key=lambda value: value.int):
                row = await session.scalar(select(Document).where(Document.id == document_id,
                    Document.tenant_id == tenant_id).with_for_update().execution_options(populate_existing=True))
                doc = documents[str(document_id)]
                if (row is None or row.tenant_id != tenant_id or row.id != document_id
                        or row.lifecycle_status != "active" or not isinstance(row.content_sha256, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", row.content_sha256)
                        or doc.source_revision != f"document:{row.content_sha256}"):
                    return False
            if plan.get("schema") == "v3-stage-checkpoint-v1":
                source = "\n\n".join(item.source_text for item in corpus.documents if item.source_text)
                return (plan.get("tenant_id") == str(tenant_id) and plan.get("job_id") == job_id
                        and plan.get("source_sha256") == _sha(source))
            if plan.get("schema") == "v3-rule-extraction-checkpoint-v1":
                identity = plan.get("identity")
                if not isinstance(identity, dict):
                    return False
                selected_id = identity.get("document_id")
                if not isinstance(selected_id, str):
                    return False
                extracted = documents.get(selected_id)
                if extracted is None or not isinstance(extracted.source_text, str):
                    return False
                start, end = identity.get("unit_start"), identity.get("unit_end")
                if (not isinstance(start, str) or not isinstance(end, str)
                        or not re.fullmatch(r"0|[1-9][0-9]*", start) or not re.fullmatch(r"0|[1-9][0-9]*", end)):
                    return False
                left, right = int(start), int(end)
                return (identity.get("tenant_id") == str(tenant_id) and identity.get("job_id") == job_id
                        and identity.get("source_revision") == extracted.source_revision
                        and identity.get("source_sha256") == _sha(extracted.source_text)
                        and 0 <= left < right <= len(extracted.source_text)
                        and identity.get("unit_sha256") == _sha(extracted.source_text[left:right]))
            return False
        except (AttributeError, TypeError, ValueError, KeyError):
            return False
    return verify
