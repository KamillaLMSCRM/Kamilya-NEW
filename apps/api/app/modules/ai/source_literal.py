"""Bounded source-field correspondence, never semantic entailment or OCR repair."""

from __future__ import annotations

import re

from app.modules.ai.evidence_engine.models import SourceFact


def source_context_fields(fact: SourceFact) -> tuple[str, ...]:
    """One owned fact, not a relation guessed between different table rows."""
    heading = " — ".join(part for part in (fact.subject, fact.attribute) if part)
    return tuple(dict.fromkeys(part for part in (fact.value, heading) if part))


def literal_source_span(value: str, source: str, *, allow_stem: bool = False) -> str | None:
    """Return original text; normalize whitespace/case only, not words/values."""
    if not value.strip():
        return None
    value = value.strip()
    pattern = r"\s+".join(re.escape(part) for part in re.split(r"\s+", value))
    if value[0].isalnum():
        pattern = r"(?<!\w)" + pattern
    if value[-1].isalnum() and not allow_stem:
        pattern += r"(?!\w)"
    elif value[-1].isdigit():
        pattern += r"(?!\d)"
    match = re.search(pattern, source, re.IGNORECASE)
    return match.group(0) if match is not None else None
