"""Pure, source-owned inventory and coverage custody for the V86 prototype."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.modules.ai.assessment_components import MAX_SOURCE_PASSAGE_CHARS
from app.modules.ai.source_layout import parse_source_marker

MAX_INVENTORY_ITEMS = 96
MAX_QUOTE_CHARS = MAX_SOURCE_PASSAGE_CHARS
_KINDS = frozenset({"operative", "qualification", "reference", "uncertain"})
_DISPOSITIONS = frozenset({"assessed", "qualification", "reference", "unresolved"})


class SourceInventoryError(ValueError):
    """Raised when a source-inventory seam fails closed."""


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    ref: str
    source_id: str
    source_sha256: str
    exact_text: str


@dataclass(frozen=True, slots=True)
class SourceInventoryItem:
    item_id: str
    ref: str
    quote: str
    start: int
    end: int
    source_sha256: str
    kind: str


@dataclass(frozen=True, slots=True)
class SourceInventoryGap:
    gap_id: str
    ref: str
    missing_source_text: str
    reason: str
    start: int
    end: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class InventoryItemVerdict:
    item_id: str
    supported: bool
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceInventorySnapshot:
    sources: tuple[SourceIdentity, ...]
    items: tuple[SourceInventoryItem, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class AuditedSourceInventory:
    snapshot: SourceInventorySnapshot
    verdicts: tuple[InventoryItemVerdict, ...]
    gaps: tuple[SourceInventoryGap, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class InventoryDisposition:
    """A source-conserving MODEL CLAIM, never assessment admission/completeness."""
    inventory_id: str
    disposition: str
    obligation_ids: tuple[str, ...]
    qualification_bindings: tuple[tuple[str, str], ...]
    semantic_approval: Literal[False] = field(default=False, init=False)

    @property
    def has_unresolved(self) -> bool:
        return self.disposition == "unresolved"


def _text(value: Any, maximum: int = 100) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and value == value.strip()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _source_rows(sources: Mapping[str, Any], primary_refs: set[str]) -> tuple[SourceIdentity, ...]:
    if not isinstance(sources, Mapping) or not primary_refs:
        raise SourceInventoryError("invalid_sources")
    if any(not _text(ref) for ref in primary_refs) or not primary_refs <= set(sources):
        raise SourceInventoryError("foreign_primary_ref")
    rows = []
    for ref in sorted(primary_refs):
        value = sources[ref]
        if not isinstance(value, tuple | list) or len(value) != 2:
            raise SourceInventoryError("invalid_source_identity")
        source_id, text = value
        if not _text(source_id, 300) or not isinstance(text, str) or not text:
            raise SourceInventoryError("invalid_source_identity")
        rows.append(SourceIdentity(ref, source_id, hashlib.sha256(text.encode()).hexdigest(), text))
    return tuple(rows)


def _span(source: SourceIdentity, quote: str) -> tuple[int, int]:
    if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_QUOTE_CHARS:
        raise SourceInventoryError("invalid_quote")
    start = source.exact_text.find(quote)
    if start < 0 or source.exact_text.find(quote, start + 1) >= 0:
        raise SourceInventoryError("nonunique_or_missing_quote")
    return start, start + len(quote)


def seal_source_inventory(raw: Any, sources: Mapping[str, Any], primary_refs: set[str] | tuple[str, ...]) -> SourceInventorySnapshot:
    if not isinstance(raw, dict) or set(raw) != {"items"} or not isinstance(raw["items"], list):
        raise SourceInventoryError("invalid_inventory_shape")
    if (not isinstance(primary_refs, set | frozenset | tuple | list)
            or any(not _text(ref) for ref in primary_refs)
            or len(set(primary_refs)) != len(primary_refs)):
        raise SourceInventoryError("invalid_primary_refs")
    primary = set(primary_refs)
    identities = _source_rows(sources, primary)
    by_ref = {row.ref: row for row in identities}
    if not 0 < len(raw["items"]) <= MAX_INVENTORY_ITEMS:
        raise SourceInventoryError("invalid_inventory_count")
    seen: set[str] = set()
    items = []
    for row in raw["items"]:
        if not isinstance(row, dict) or set(row) != {"id", "ref", "quote", "kind"}:
            raise SourceInventoryError("invalid_inventory_item")
        item_id, ref, quote, kind = (row[key] for key in ("id", "ref", "quote", "kind"))
        if (not _text(item_id) or re.fullmatch(r"I[A-Za-z0-9_-]{1,99}", item_id) is None
                or item_id in seen or not isinstance(ref, str) or ref not in by_ref
                or not isinstance(kind, str) or kind not in _KINDS):
            raise SourceInventoryError("invalid_inventory_item")
        seen.add(item_id)
        start, end = _span(by_ref[ref], quote)
        items.append(SourceInventoryItem(item_id, ref, quote, start, end,
                                         by_ref[ref].source_sha256, kind))
    if {item.ref for item in items} != primary:
        raise SourceInventoryError("missing_primary_inventory")
    signature = _fingerprint({"sources": [asdict(row) for row in identities], "items": [asdict(row) for row in items]})
    return SourceInventorySnapshot(identities, tuple(items), signature)


def _verify_snapshot(snapshot: SourceInventorySnapshot, sources: Mapping[str, Any]) -> None:
    if (not isinstance(snapshot, SourceInventorySnapshot)
            or not isinstance(snapshot.sources, tuple) or not isinstance(snapshot.items, tuple)
            or any(not isinstance(row, SourceIdentity) for row in snapshot.sources)
            or any(not isinstance(row, SourceInventoryItem) for row in snapshot.items)):
        raise SourceInventoryError("invalid_snapshot")
    resealed = seal_source_inventory({"items": [{"id": row.item_id, "ref": row.ref,
        "quote": row.quote, "kind": row.kind} for row in snapshot.items]}, sources,
        tuple(row.ref for row in snapshot.sources))
    if resealed != snapshot:
        raise SourceInventoryError("stale_source_identity")


def seal_inventory_audit(snapshot: SourceInventorySnapshot, raw: Any,
                         sources: Mapping[str, Any]) -> AuditedSourceInventory:
    if not isinstance(snapshot, SourceInventorySnapshot) or not isinstance(raw, dict):
        raise SourceInventoryError("invalid_audit")
    if set(raw) != {"source_refs", "item_verdicts", "source_gaps"}:
        raise SourceInventoryError("invalid_audit_shape")
    _verify_snapshot(snapshot, sources)
    inspected = raw["source_refs"]
    if (not isinstance(inspected, list) or any(not _text(ref) for ref in inspected)
            or len(inspected) != len(set(inspected))
            or set(inspected) != {source.ref for source in snapshot.sources}):
        raise SourceInventoryError("invalid_audit_refs")
    verdict_rows = raw["item_verdicts"]
    if not isinstance(verdict_rows, list) or len(verdict_rows) != len(snapshot.items):
        raise SourceInventoryError("invalid_item_verdict_count")
    by_item = {item.item_id: item for item in snapshot.items}
    verdicts: list[InventoryItemVerdict] = []
    for row in verdict_rows:
        if not isinstance(row, dict) or set(row) != {"item_id", "supported", "errors"}:
            raise SourceInventoryError("invalid_item_verdict")
        item_id, supported, errors = (row[key] for key in ("item_id", "supported", "errors"))
        if (not _text(item_id) or item_id not in by_item or type(supported) is not bool
                or not isinstance(errors, list) or len(errors) > 8
                or any(not _text(error, 240) for error in errors)):
            raise SourceInventoryError("invalid_item_verdict")
        if supported and errors or not supported and not errors:
            raise SourceInventoryError("invalid_item_verdict")
        if any(item.item_id == item_id for item in verdicts):
            raise SourceInventoryError("duplicate_item_verdict")
        verdicts.append(InventoryItemVerdict(item_id, supported, tuple(errors)))
    if {row.item_id for row in verdicts} != set(by_item):
        raise SourceInventoryError("missing_item_verdict")
    gaps = []
    seen_gap_spans: set[tuple[str, int, int]] = set()
    if not isinstance(raw["source_gaps"], list) or len(raw["source_gaps"]) > MAX_INVENTORY_ITEMS:
        raise SourceInventoryError("invalid_source_gaps")
    for index, row in enumerate(raw["source_gaps"], 1):
        if not isinstance(row, dict) or set(row) != {"ref", "missing_source_text", "reason"}:
            raise SourceInventoryError("invalid_source_gap")
        ref, text, reason = (row[key] for key in ("ref", "missing_source_text", "reason"))
        if not _text(ref) or ref not in {source.ref for source in snapshot.sources}:
            raise SourceInventoryError("invalid_source_gap")
        source = next(source for source in snapshot.sources if source.ref == ref)
        start, end = _span(source, text)
        if not _text(reason, 240) or (ref, start, end) in seen_gap_spans:
            raise SourceInventoryError("invalid_source_gap")
        seen_gap_spans.add((ref, start, end))
        gaps.append(SourceInventoryGap(f"G{index}", ref, text, reason, start, end, source.source_sha256))
    signature = _fingerprint({"snapshot": asdict(snapshot), "verdicts": [asdict(row) for row in verdicts],
                              "gaps": [asdict(row) for row in gaps]})
    return AuditedSourceInventory(snapshot, tuple(verdicts), tuple(gaps), signature)


def _verify_audited(audited: AuditedSourceInventory, sources: Mapping[str, Any]) -> None:
    if (not isinstance(audited, AuditedSourceInventory) or not isinstance(audited.verdicts, tuple)
            or not isinstance(audited.gaps, tuple)
            or any(not isinstance(row, InventoryItemVerdict) for row in audited.verdicts)
            or any(not isinstance(row.errors, tuple) for row in audited.verdicts)
            or any(not isinstance(row, SourceInventoryGap) for row in audited.gaps)):
        raise SourceInventoryError("invalid_audited_snapshot")
    _verify_snapshot(audited.snapshot, sources)
    resealed = seal_inventory_audit(audited.snapshot, {
        "source_refs": [row.ref for row in audited.snapshot.sources],
        "item_verdicts": [{"item_id": row.item_id, "supported": row.supported,
                           "errors": list(row.errors)} for row in audited.verdicts],
        "source_gaps": [{"ref": row.ref, "missing_source_text": row.missing_source_text,
                         "reason": row.reason} for row in audited.gaps]}, sources)
    if resealed != audited:
        raise SourceInventoryError("stale_audited_snapshot")


def _require_span_conservation(source: SourceIdentity, start: int, end: int,
                               spans: list[tuple[int, int]]) -> None:
    """No operative words vanish. Covered bindings still grant ZERO answer credit."""
    covered = [False] * (end - start)
    for left, right in spans:
        covered[left - start:right - start] = [True] * (right - left)
    # Structural list markers are proved at ORIGINAL physical line boundaries,
    # not guessed from a number at the beginning of a selected substring.
    offset = 0
    for line in source.exact_text.splitlines(keepends=True):
        marker = parse_source_marker(line.rstrip("\r\n"))
        if marker is not None:
            left, right = offset + marker.raw_start, offset + marker.content_start
            if start <= left and right <= end:
                covered[left - start:right - start] = [True] * (right - left)
        offset += len(line)
    quote = source.exact_text[start:end]
    # The closed separator may remain between assessed pieces. No action,
    # modality, unit, number, condition or purpose token is a free separator.
    for match in re.finditer(r"[,;][ \t\u00a0\u202f]*(?:а|но|и|либо|или)[ \t\u00a0\u202f]+", quote, re.IGNORECASE):
        if not any(covered[match.start():match.end()]):
            covered[match.start():match.end()] = [True] * len(match.group())
    punctuation = frozenset(",;:.!?…()[]«»\"'")
    for index, (char, owned) in enumerate(zip(quote, covered, strict=True)):
        if owned or char.isspace():
            continue
        # A sign/range dash is NOT a free separator. Neither is punctuation
        # adjacent to a digit: splitting 1,5 or 1.5 must preserve the number.
        numeric_neighbor = ((index > 0 and quote[index - 1].isdigit())
                            or (index + 1 < len(quote) and quote[index + 1].isdigit()))
        if char not in punctuation or numeric_neighbor:
            raise SourceInventoryError("unmapped_inventory_text")


def _validate_inventory_coverage(audited: AuditedSourceInventory, raw_coverage: Any,
                                final_obligations: Any, sources: Mapping[str, Any], *,
                                provisional_reclassification: bool) -> tuple[InventoryDisposition, ...]:
    if not isinstance(audited, AuditedSourceInventory) or not isinstance(raw_coverage, list):
        raise SourceInventoryError("invalid_coverage")
    _verify_audited(audited, sources)
    current = audited.snapshot.sources
    obligation_rows = final_obligations.values() if isinstance(final_obligations, Mapping) else final_obligations
    if not isinstance(final_obligations, Mapping | list | tuple):
        raise SourceInventoryError("invalid_final_obligations")
    obligations = {}
    for row in obligation_rows:
        if not isinstance(row, dict) or not _text(row.get("id")) or row["id"] in obligations:
            raise SourceInventoryError("invalid_final_obligation")
        if (set(row) != {"id", "ref", "quote"} or not _text(row["ref"])
                or row["ref"] not in {source.ref for source in current}):
            raise SourceInventoryError("invalid_final_obligation")
        _span(next(source for source in current if source.ref == row["ref"]), row["quote"])
        obligations[row["id"]] = row
    units: dict[str, tuple[str, int, int, str]] = {}
    for item in audited.snapshot.items:
        units[item.item_id] = (item.ref, item.start, item.end, item.kind)
    for gap in audited.gaps:
        units[gap.gap_id] = (gap.ref, gap.start, gap.end, "uncertain")
    if len(raw_coverage) != len(units):
        raise SourceInventoryError("incomplete_coverage")
    result = []
    seen: set[str] = set()
    verdict = {row.item_id: row for row in audited.verdicts}
    for row in raw_coverage:
        if not isinstance(row, dict) or set(row) != {"inventory_id", "disposition", "obligation_ids", "qualification_bindings"}:
            raise SourceInventoryError("invalid_coverage_row")
        ident, disposition, obligation_ids, bindings = (row[key] for key in
            ("inventory_id", "disposition", "obligation_ids", "qualification_bindings"))
        if (not _text(ident) or ident not in units or ident in seen
                or not isinstance(disposition, str) or disposition not in _DISPOSITIONS):
            raise SourceInventoryError("invalid_coverage_row")
        seen.add(ident)
        if (not isinstance(obligation_ids, list) or len(obligation_ids) > MAX_INVENTORY_ITEMS
                or any(not _text(oid) for oid in obligation_ids)
                or len(set(obligation_ids)) != len(obligation_ids)):
            raise SourceInventoryError("invalid_coverage_row")
        if not isinstance(bindings, list) or len(bindings) > MAX_INVENTORY_ITEMS:
            raise SourceInventoryError("invalid_coverage_row")
        ref, start, end, kind = units[ident]
        source = next(source for source in current if source.ref == ref)
        owned_spans: list[tuple[int, int]] = []
        seen_bindings: set[tuple[str, str]] = set()
        for binding in bindings:
            if (not isinstance(binding, dict) or set(binding) != {"ref", "quote"}
                    or binding["ref"] != ref or not isinstance(binding["quote"], str)):
                raise SourceInventoryError("invalid_qualification_binding")
            bstart, bend = _span(next(source for source in current if source.ref == ref), binding["quote"])
            if not (start <= bstart and bend <= end) or (ref, binding["quote"]) in seen_bindings:
                raise SourceInventoryError("qualification_outside_inventory")
            seen_bindings.add((ref, binding["quote"]))
            owned_spans.append((bstart, bend))
        if not provisional_reclassification and ident.startswith("G") and disposition in {"qualification", "reference"}:
            raise SourceInventoryError("gap_cannot_claim_coverage")
        if disposition == "assessed":
            if not obligation_ids:
                raise SourceInventoryError("invalid_assessed_coverage")
            for oid in obligation_ids:
                obligation = obligations.get(oid)
                if obligation is None or obligation["ref"] != ref:
                    raise SourceInventoryError("invalid_assessed_coverage")
                ostart, oend = _span(next(source for source in current if source.ref == ref), obligation["quote"])
                if not (start <= ostart and oend <= end):
                    raise SourceInventoryError("obligation_outside_inventory")
                owned_spans.append((ostart, oend))
            _require_span_conservation(source, start, end, owned_spans)
        elif disposition in {"qualification", "reference"}:
            if (obligation_ids or (not provisional_reclassification and (
                    kind != disposition or not verdict.get(ident, InventoryItemVerdict(ident, False, ())).supported))
                    or (provisional_reclassification and disposition == "reference" and bindings)
                    or (disposition == "qualification" and not bindings)):
                raise SourceInventoryError("invalid_zero_credit_coverage")
            if disposition == "qualification":
                _require_span_conservation(source, start, end, owned_spans)
        elif obligation_ids or bindings:
            raise SourceInventoryError("invalid_unresolved_coverage")
        result.append(InventoryDisposition(ident, disposition, tuple(obligation_ids),
                                           tuple((binding["ref"], binding["quote"]) for binding in bindings)))
    if seen != set(units):
        raise SourceInventoryError("incomplete_coverage")
    return tuple(result)


def validate_inventory_coverage(audited: AuditedSourceInventory, raw_coverage: Any,
                                final_obligations: Any, sources: Mapping[str, Any]) -> tuple[InventoryDisposition, ...]:
    """V86 strict classification custody; never semantic approval."""
    return _validate_inventory_coverage(audited, raw_coverage, final_obligations, sources,
                                        provisional_reclassification=False)


def validate_inventory_claims(audited: AuditedSourceInventory, raw_coverage: Any,
                              final_obligations: Any, sources: Mapping[str, Any]) -> tuple[InventoryDisposition, ...]:
    """V87 source-conserving CLAIMS only; matching independent A4 is mandatory.

    A provisional kind/gap is not semantic authority. This deliberately permits
    its correction but grants no positive disposition/admission by itself.
    """
    return _validate_inventory_coverage(audited, raw_coverage, final_obligations, sources,
                                        provisional_reclassification=True)


__all__ = [
    "AuditedSourceInventory", "InventoryDisposition", "InventoryItemVerdict", "SourceIdentity",
    "SourceInventoryError", "SourceInventoryGap", "SourceInventoryItem", "SourceInventorySnapshot",
    "seal_inventory_audit", "seal_source_inventory", "validate_inventory_coverage", "validate_inventory_claims",
]
