"""Validate trusted, source-bound reference decisions for generation.

Only a server-side authenticated decision loader may construct these records.
This module does not authenticate users or load decisions from request metadata.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.ai.direct_source import DirectSourceDocument
    from app.modules.ai.schemas import SourceReferenceDecisionInput
    from app.modules.ai.v3.models import RuleEntity


@dataclass(frozen=True, slots=True)
class SourceReferenceDecision:
    tenant_id: str
    document_id: str
    source_revision: str
    converted_text_sha256: str
    reference_start: int
    reference_end: int
    reference_exact: str
    target_start: int
    target_end: int
    target_exact: str
    authority: str
    approved_by: str = ""


def admit_reference_decisions(
    values: list[SourceReferenceDecisionInput], tenant_id: str, user_id: str, selected_documents: Sequence[object],
) -> list[dict[str, object]]:
    """Stamp authenticated actor/tenant server-side; never accept authority from input."""
    if not tenant_id or not user_id:
        raise ValueError("reference_decision_authority_invalid")
    allowed = {str(value) for value in selected_documents}
    records: list[dict[str, object]] = []
    for value in values:
        payload = value.model_dump(mode="json", exclude={"confirmed"})
        if payload.get("document_id") not in allowed:
            raise ValueError("reference_decision_document_invalid")
        record = SourceReferenceDecision(**payload, tenant_id=tenant_id,
                                         authority="methodologist_confirmed", approved_by=user_id)
        records.append(asdict(record))
    return records


def hydrate_reference_decisions(
    records: object, tenant_id: str, user_id: str, selected_documents: list[str],
) -> tuple[SourceReferenceDecision, ...]:
    """Rebuild only actor-bound records read from the authoritative owned job."""
    if not isinstance(records, list) or not tenant_id or not user_id:
        raise ValueError("reference_decision_authority_invalid")
    allowed = set(selected_documents)
    decisions: list[SourceReferenceDecision] = []
    expected_fields = set(SourceReferenceDecision.__dataclass_fields__)
    for record in records:
        if (not isinstance(record, dict) or set(record) != expected_fields
                or record.get("tenant_id") != tenant_id or record.get("approved_by") != user_id
                or record.get("authority") != "methodologist_confirmed" or record.get("document_id") not in allowed):
            raise ValueError("reference_decision_authority_invalid")
        decisions.append(SourceReferenceDecision(**record))
    return tuple(decisions)


def reference_context_for_rules(
    tenant_id: str, documents: tuple[DirectSourceDocument, ...],
    decisions: tuple[SourceReferenceDecision, ...], rules: tuple[RuleEntity, ...],
) -> tuple[str, ...]:
    """Return context only for a decision's referenced source unit, or fail closed."""
    contexts: list[str] = []
    seen: set[tuple[str, str, int, int]] = set()
    for decision in decisions:
        if (not isinstance(decision, SourceReferenceDecision) or not tenant_id or decision.tenant_id != tenant_id
                or decision.authority not in {"owner_chat", "methodologist_confirmed"}
                or (decision.authority == "methodologist_confirmed" and not decision.approved_by)):
            raise ValueError("reference_decision_authority_invalid")
        matches = [doc for doc in documents if doc.doc_id == decision.document_id
                   and doc.source_revision == decision.source_revision]
        if len(matches) != 1 or matches[0].source_text is None:
            raise ValueError("reference_decision_document_invalid")
        source = matches[0].source_text
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != decision.converted_text_sha256:
            raise ValueError("reference_decision_content_changed")
        for start, end, expected in ((decision.reference_start, decision.reference_end, decision.reference_exact),
                                     (decision.target_start, decision.target_end, decision.target_exact)):
            if (type(start) is not int or type(end) is not int or not isinstance(expected, str) or not expected.strip()
                    or not 0 <= start < end <= len(source) or source[start:end] != expected):
                raise ValueError("reference_decision_span_invalid")
        identity = (decision.document_id, decision.source_revision, decision.reference_start, decision.reference_end)
        if identity in seen:
            raise ValueError("reference_decision_duplicate")
        seen.add(identity)
        if any(rule.doc_id == decision.document_id and rule.source_revision == decision.source_revision
               and rule.source_start is not None and rule.source_end is not None
               and rule.source_start <= decision.reference_start < decision.reference_end <= rule.source_end
               for rule in rules):
            contexts.append(
                f"Уточнение ({decision.authority}) для документа {decision.document_id}, ревизия {decision.source_revision}: "
                f"ссылка «{decision.reference_exact}» относится к фрагменту «{decision.target_exact}». "
                "Это подтверждённая трактовка, а не изменение исходного документа; её следует проверить при приёмке."
            )
    return tuple(contexts)
