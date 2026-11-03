"""Canonical, server-owned citation binding for V3 source units.

This module only proves literal provenance.  It deliberately does not make a
claim about whether a citation semantically supports an answer or explanation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.models import RuleEntity
from app.modules.ai.v3.source_units import find_rendered_quote_spans, rendered_candidate_preserves_table_boundaries
from app.modules.ai.v3.validator import normalize_literal_quote_with_char_map


@dataclass(frozen=True)
class CanonicalCitation:
    text: str
    start: int
    end: int
    identity: str


def resolve_owned_citation(
    corpus: DirectSourceCorpus,
    rule: RuleEntity,
    quote: str,
) -> CanonicalCitation | None:
    """Resolve exactly one quote inside one authenticated rule-owned span.

    The returned text is always sliced from the canonical document.  A quote
    repeated outside the owned span is harmless; repeated or overlapping
    candidates inside the owned span are ambiguous and fail closed.
    """
    if (
        not corpus.tenant_id
        or not rule.doc_id
        or not rule.source_revision
        or not isinstance(quote, str)
        or not quote.strip()
        or type(rule.source_start) is not int
        or type(rule.source_end) is not int
    ):
        return None
    docs = [
        doc for doc in corpus.documents
        if doc.doc_id == rule.doc_id
        and doc.source_revision == rule.source_revision
        and doc.source_text is not None
    ]
    if len(docs) != 1:
        return None
    source = docs[0].source_text or ""
    if not 0 <= rule.source_start < rule.source_end <= len(source):
        return None

    candidates: set[tuple[int, int]] = set()
    needle, _ = normalize_literal_quote_with_char_map(quote.strip())
    haystack, offsets = normalize_literal_quote_with_char_map(source)
    if needle and offsets:
        pos = 0
        while (index := haystack.find(needle, pos)) >= 0:
            end_index = index + len(needle)
            if end_index <= len(offsets):
                start, end = offsets[index], offsets[end_index - 1] + 1
                if rule.source_start <= start < end <= rule.source_end:
                    candidates.add((start, end))
            pos = index + 1

    # Compare both projections: a literal occurrence must not hide another
    # rendered occurrence. Nested endpoint differences around the SAME markup
    # are one physical occurrence; two distinct literal matches remain ambiguous.
    rendered: set[tuple[int, int]] = set()
    for start, end in find_rendered_quote_spans(source, quote.strip()):
        # Candidate retrieval deliberately strips table delimiters. Restore
        # only the quote's explicit outer cell boundaries, across display-only
        # markers, before checking that no cell boundary was lost or moved.
        if quote.strip().startswith("|"):
            boundary = source.rfind("|", rule.source_start, start)
            if boundary >= 0 and rendered_candidate_preserves_table_boundaries(source[boundary:start], "|"):
                start = boundary
        if quote.strip().endswith("|"):
            boundary = source.find("|", end, rule.source_end)
            if boundary >= 0 and rendered_candidate_preserves_table_boundaries(source[end:boundary + 1], "|"):
                end = boundary + 1
        if (
            rule.source_start <= start < end <= rule.source_end
            and rendered_candidate_preserves_table_boundaries(source[start:end], quote.strip())
        ):
            rendered.add((start, end))
    if len(candidates) > 1 or len(rendered) > 1:
        return None
    if candidates and rendered:
        literal_start, literal_end = next(iter(candidates))
        rendered_start, rendered_end = next(iter(rendered))
        if not (literal_start <= rendered_start < rendered_end <= literal_end
                or rendered_start <= literal_start < literal_end <= rendered_end):
            return None
    if not candidates:
        candidates = rendered
    if not candidates:
        return None
    start, end = next(iter(candidates))
    text = source[start:end]
    identity_payload = {
        "tenant": corpus.tenant_id,
        "document": rule.doc_id,
        "revision": rule.source_revision,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "start": start,
        "end": end,
    }
    identity = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CanonicalCitation(text=text, start=start, end=end, identity=identity)
