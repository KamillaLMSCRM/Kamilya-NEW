"""Project audit gap text onto exact source bytes without changing meaning."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

AUDIT_GAP_LAYOUT_POLICY = "source-audit-gap-layout-v1"
_SEPARATORS = SOURCE_HORIZONTAL_SPACE + "\r\n"
_SEPARATOR_SET = frozenset(_SEPARATORS)
_SEPARATOR_PATTERN = f"[{re.escape(_SEPARATORS)}]+"
_RECEIPT_FIELDS = {
    "policy",
    "gap_index",
    "ref",
    "source_sha256",
    "requested_text",
    "requested_sha256",
    "canonical_sha256",
    "start",
    "end",
    "separator_change_count",
}


class AuditGapLayoutError(ValueError):
    """A saved audit-gap layout receipt cannot be reproduced exactly."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_configuration(sources: object, max_chars: object) -> dict[str, str]:
    if (
        not isinstance(sources, dict)
        or any(
            not isinstance(ref, str)
            or not ref
            or not isinstance(source, str)
            for ref, source in sources.items()
        )
    ):
        raise AuditGapLayoutError("audit_gap_layout_invalid_sources")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise AuditGapLayoutError("audit_gap_layout_invalid_max_chars")
    return sources


def _word_character(value: str) -> bool:
    return re.fullmatch(r"\w", value, flags=re.UNICODE) is not None


def _projection(
    requested: object,
    *,
    source: str,
    max_chars: int,
) -> tuple[str, int, int, int] | None:
    if (
        not isinstance(requested, str)
        or not requested
        or requested != requested.strip()
        or len(requested) > max_chars
        or requested in source
        or any(character.isspace() and character not in _SEPARATOR_SET for character in requested)
    ):
        return None
    pieces = [piece for piece in re.split(f"({_SEPARATOR_PATTERN})", requested) if piece]
    if not pieces or not any(
        piece and all(character in _SEPARATOR_SET for character in piece)
        for piece in pieces
    ):
        return None
    requested_separators: list[str] = []
    pattern_parts: list[str] = []
    for piece in pieces:
        if all(character in _SEPARATOR_SET for character in piece):
            requested_separators.append(piece)
            pattern_parts.append(f"({_SEPARATOR_PATTERN})")
        else:
            pattern_parts.append(re.escape(piece))
    pattern = "".join(pattern_parts)
    if _word_character(requested[0]):
        pattern = r"(?<!\w)" + pattern
    if _word_character(requested[-1]):
        pattern += r"(?!\w)"

    overlapping = re.compile(rf"(?=({pattern}))", flags=re.UNICODE)
    matches = tuple(overlapping.finditer(source))
    if len(matches) != 1:
        return None
    match = matches[0]
    start, end = match.span(1)
    canonical = source[start:end]
    if canonical == requested or len(canonical) > max_chars:
        return None
    canonical_separators = list(match.groups()[1:])
    if len(canonical_separators) != len(requested_separators):
        return None
    separator_change_count = sum(
        requested_run != canonical_run
        for requested_run, canonical_run in zip(
            requested_separators,
            canonical_separators,
            strict=True,
        )
    )
    if separator_change_count == 0:
        return None
    return canonical, start, end, separator_change_count


def _receipt(
    *,
    gap_index: int,
    ref: str,
    source: str,
    requested: str,
    canonical: str,
    start: int,
    end: int,
    separator_change_count: int,
) -> dict[str, Any]:
    return {
        "policy": AUDIT_GAP_LAYOUT_POLICY,
        "gap_index": gap_index,
        "ref": ref,
        "source_sha256": _digest(source),
        "requested_text": requested,
        "requested_sha256": _digest(requested),
        "canonical_sha256": _digest(canonical),
        "start": start,
        "end": end,
        "separator_change_count": separator_change_count,
    }


def canonicalize_audit_gap_layout(
    verdict: Any,
    sources: dict[str, str],
    max_chars: int,
) -> tuple[Any, list[dict[str, Any]]]:
    """Align eligible gap text to one exact source interval.

    Malformed or ambiguous individual gaps are intentionally left untouched so
    the existing strict admission validator remains their sole rejection path.
    """

    source_map = _validate_configuration(sources, max_chars)
    canonical = deepcopy(verdict)
    if not isinstance(canonical, dict) or not isinstance(canonical.get("source_gaps"), list):
        return canonical, []
    receipts: list[dict[str, Any]] = []
    seen_identities: set[tuple[str, str, int, int, str]] = set()
    for gap_index, gap in enumerate(canonical["source_gaps"]):
        if not isinstance(gap, dict):
            continue
        ref_value = gap.get("ref")
        if not isinstance(ref_value, str):
            continue
        ref = ref_value
        requested = gap.get("missing_source_text")
        source = source_map.get(ref)
        if source is None:
            continue
        projection = _projection(requested, source=source, max_chars=max_chars)
        if projection is None or not isinstance(requested, str):
            continue
        projected_text, start, end, separator_change_count = projection
        identity = (ref, _digest(source), start, end, _digest(projected_text))
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        gap["missing_source_text"] = projected_text
        receipts.append(
            _receipt(
                gap_index=gap_index,
                ref=ref,
                source=source,
                requested=requested,
                canonical=projected_text,
                start=start,
                end=end,
                separator_change_count=separator_change_count,
            )
        )
    return canonical, receipts


def validate_audit_gap_layout_receipts(
    verdict: Any,
    sources: dict[str, str],
    max_chars: int,
    receipts: Any,
) -> None:
    """Recompute every saved normalization and reject any custody mismatch."""

    source_map = _validate_configuration(sources, max_chars)
    if not isinstance(receipts, list):
        raise AuditGapLayoutError("audit_gap_layout_invalid_receipts")
    if not receipts:
        return
    if not isinstance(verdict, dict) or not isinstance(verdict.get("source_gaps"), list):
        raise AuditGapLayoutError("audit_gap_layout_invalid_verdict")
    gaps = verdict["source_gaps"]
    seen_indexes: set[int] = set()
    seen_identities: set[tuple[Any, ...]] = set()
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
            raise AuditGapLayoutError("audit_gap_layout_invalid_receipt_shape")
        gap_index = receipt["gap_index"]
        if (
            type(gap_index) is not int
            or not 0 <= gap_index < len(gaps)
            or gap_index in seen_indexes
        ):
            raise AuditGapLayoutError("audit_gap_layout_invalid_gap_index")
        seen_indexes.add(gap_index)
        ref = receipt["ref"]
        source = source_map.get(ref) if isinstance(ref, str) else None
        requested = receipt["requested_text"]
        hashes = (
            receipt["source_sha256"],
            receipt["requested_sha256"],
            receipt["canonical_sha256"],
        )
        if (
            receipt["policy"] != AUDIT_GAP_LAYOUT_POLICY
            or not isinstance(receipt["policy"], str)
            or not isinstance(ref, str)
            or source is None
            or not isinstance(requested, str)
            or any(not isinstance(value, str) or len(value) != 64 for value in hashes)
            or type(receipt["start"]) is not int
            or type(receipt["end"]) is not int
            or type(receipt["separator_change_count"]) is not int
            or receipt["start"] < 0
            or receipt["end"] <= receipt["start"]
            or receipt["separator_change_count"] <= 0
        ):
            raise AuditGapLayoutError("audit_gap_layout_invalid_source_identity")
        projection = _projection(requested, source=source, max_chars=max_chars)
        if projection is None or not isinstance(requested, str):
            raise AuditGapLayoutError("audit_gap_layout_unreproducible")
        canonical, start, end, separator_change_count = projection
        expected = _receipt(
            gap_index=gap_index,
            ref=ref,
            source=source,
            requested=requested,
            canonical=canonical,
            start=start,
            end=end,
            separator_change_count=separator_change_count,
        )
        if receipt != expected:
            raise AuditGapLayoutError("audit_gap_layout_receipt_mismatch")
        gap = gaps[gap_index]
        if (
            not isinstance(gap, dict)
            or gap.get("ref") != ref
            or gap.get("missing_source_text") != canonical
            or source[start:end] != canonical
        ):
            raise AuditGapLayoutError("audit_gap_layout_canonical_row_mismatch")
        identity = (
            ref,
            receipt["source_sha256"],
            receipt["canonical_sha256"],
            start,
            end,
        )
        if identity in seen_identities:
            raise AuditGapLayoutError("audit_gap_layout_duplicate_identity")
        seen_identities.add(identity)
