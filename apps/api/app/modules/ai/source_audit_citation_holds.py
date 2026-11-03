"""Exact source custody for negative citations; never source or edit authority."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

POLICY = "negative-citation-hold-v1"
_DELIMITERS = frozenset(".,;:")


def unique_literal_interval(source: str, quote: str) -> tuple[int, int] | None:
    """Count overlapping occurrences, without case or punctuation normalization."""
    if not quote:
        return None
    start = source.find(quote)
    if start < 0 or source.find(quote, start + 1) >= 0:
        return None
    return start, start + len(quote)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_negative_citation_holds(
    response: Any, receipt: dict[str, Any],
) -> tuple[Any, list[dict[str, Any]]]:
    """Separate a uniquely located delimiter error from trusted source gaps.

    Unsupported rows stay untouched for the strict semantic parser to reject.
    Held rows keep the source unresolved and grant no new-goal permission. The
    raw response is immutable; no semantic vote is changed or manufactured.
    """
    projected = deepcopy(response)
    if not isinstance(projected, dict) or not isinstance(projected.get("source_gaps"), list):
        return projected, []
    sources = {row["ref"]: row["text"] for row in receipt["view"]["sources"] if row["primary"]}
    holds: list[dict[str, Any]] = []
    retained = []
    for index, gap in enumerate(projected["source_gaps"]):
        if (not isinstance(gap, dict) or set(gap) != {"ref", "missing_source_text", "reason"}
                or not isinstance(gap["ref"], str) or gap["ref"] not in sources
                or not isinstance(gap["missing_source_text"], str)
                or not isinstance(gap["reason"], str) or not gap["reason"].strip()
                or len(gap["reason"]) > 240):
            retained.append(gap)
            continue
        quote, source = gap["missing_source_text"], sources[gap["ref"]]
        if (not quote or quote != quote.strip() or len(quote) < 2
                or quote[-1] not in _DELIMITERS or quote in source):
            retained.append(gap)
            continue
        prefix = quote[:-1]
        candidates = []
        start = source.find(prefix)
        while start >= 0:
            end = start + len(quote)
            if end <= len(source) and source[end - 1] in _DELIMITERS and source[end - 1] != quote[-1]:
                candidates.append((start, end))
                if len(candidates) > 1:
                    break
            start = source.find(prefix, start + 1)
        if len(candidates) != 1:
            retained.append(gap)
            continue
        start, end = candidates[0]
        canonical = source[start:end]
        holds.append({"policy": POLICY, "gap_index": index, "ref": gap["ref"],
            "source_sha256": _sha(source), "start": start, "end": end,
            "requested_text": quote, "requested_sha256": _sha(quote),
            "canonical_text": canonical, "canonical_sha256": _sha(canonical), "reason": gap["reason"],
            "semantic_approval": False, "addition_goal_authority": False})
    projected["source_gaps"] = retained
    return projected, holds
