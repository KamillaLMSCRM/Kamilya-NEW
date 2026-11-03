"""Negative-only target context candidate inventory for source-plan audits.

The module projects existing exact qualification facet IDs for explicit critic
comparison.  It does not infer facet applicability, add bindings, establish
coverage, approve a target, or treat an audit classification as source truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

_CONTEXT_AXES = (
    "participants",
    "temporal_setting",
    "condition",
    "exception",
    "prerequisite",
    "antecedent",
)
_CONTEXT_STATUSES = frozenset({"not_required", "covered", "missing", "ambiguous"})
_CANDIDATE_PARTS = ("applies", "not_applicable", "ambiguous")
_ASSESSED_ONLY_ROLES = frozenset({"quantity", "operator"})
_ROLE_AXIS = {
    "actor": "participants",
    "recipient": "participants",
    "timing": "temporal_setting",
    "condition": "condition",
    "exception": "exception",
}
_KNOWN_CONTEXT_ROLES = frozenset({*_ROLE_AXIS, "scope"})


@dataclass(frozen=True)
class TargetContextPartitionGap:
    """One attributable malformed candidate partition; never a model verdict."""

    target_id: str
    code: str
    missing_candidate_ids: tuple[str, ...] = ()
    unexpected_candidate_ids: tuple[str, ...] = ()
    duplicate_candidate_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "code": self.code,
            "missing_candidate_ids": list(self.missing_candidate_ids),
            "unexpected_candidate_ids": list(self.unexpected_candidate_ids),
            "duplicate_candidate_ids": list(self.duplicate_candidate_ids),
        }


@dataclass(frozen=True)
class TargetContextPartitionIsolation:
    """Negative-only row validation beside the immutable raw audit."""

    effective_verdict: dict[str, Any]
    valid_target_ids: tuple[str, ...]
    invalid_target_ids: tuple[str, ...]
    gaps: tuple[TargetContextPartitionGap, ...]
    raw_rows_sha256: str
    binding_gaps: tuple[tuple[str, str], ...] = ()


def _invalid(detail: str) -> ValueError:
    return ValueError("source_plan_invalid_target_context_candidate_" + detail)


def _source_text(refs: Mapping[str, Any], ref: str) -> str:
    if ref not in refs:
        raise _invalid("source_ref")
    source = refs[ref]
    if isinstance(source, Mapping):
        text = source.get("value", source.get("text"))
    else:
        text = getattr(source, "value", None)
    if not isinstance(text, str) or not text:
        raise _invalid("source_text")
    return text


def _unique_span(text: str, quote: str) -> tuple[int, int] | None:
    if not isinstance(quote, str) or not quote:
        return None
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        return None
    return start, start + len(quote)


def _paragraph_bounds(text: str, position: int) -> tuple[int, int]:
    """Return exact structural block bounds; blank lines are the only boundary."""
    start, end = 0, len(text)
    for separator in re.finditer(r"\n[ \t]*\n", text):
        if separator.end() <= position:
            start = separator.end()
            continue
        if separator.start() >= position:
            end = separator.start()
            break
    return start, end


def _target_evidence_positions(target: Mapping[str, Any], refs: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    positions: dict[str, list[int]] = {}
    groups = target.get("answer_components", [])
    if not isinstance(groups, list):
        raise _invalid("target_components")
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("ref"), str):
            raise _invalid("target_component")
        ref, terms = group["ref"], group.get("terms")
        if not isinstance(terms, list):
            raise _invalid("target_component_terms")
        text = _source_text(refs, ref)
        for term in terms:
            span = _unique_span(text, term) if isinstance(term, str) else None
            if span is not None:
                positions.setdefault(ref, []).append(span[0])
    return {ref: tuple(sorted(set(values))) for ref, values in positions.items()}


def _binding_matches_facet(binding: Any, facet: Mapping[str, Any]) -> bool:
    return (
        isinstance(binding, Mapping)
        and binding.get("ref") == facet.get("ref")
        and binding.get("quote") == facet.get("quote")
        and binding.get("role") == facet.get("role")
        and binding.get("branch_effect") == facet.get("branch_effect")
    )


def _shares_exact_evidence_block(
    facet: Mapping[str, Any],
    target_id: str,
    targets: Mapping[str, Mapping[str, Any]],
    positions: Mapping[str, Mapping[str, tuple[int, ...]]],
    refs: Mapping[str, Any],
) -> bool:
    """Whether a present peer target makes this exact facet partitionable.

    Facet ownership is not semantic applicability.  It only closes the audit
    inventory for source-local peers whose exact answer evidence occupies the
    same structural block.  Missing/foreign owners and unlocated evidence grant
    nothing.
    """
    ref, quote, owners = facet.get("ref"), facet.get("quote"), facet.get("target_ids")
    if (not isinstance(ref, str) or not isinstance(quote, str) or not isinstance(owners, list)
            or any(not isinstance(owner, str) or not owner for owner in owners)):
        return False
    text = _source_text(refs, ref)
    facet_span = _unique_span(text, quote)
    if facet_span is None:
        return False
    facet_block = _paragraph_bounds(text, facet_span[0])
    target_starts = positions[target_id].get(ref, ())
    if not target_starts:
        return False
    target_blocks = {_paragraph_bounds(text, start) for start in target_starts}
    if facet_block not in target_blocks:
        return False
    for owner in owners:
        peer = targets.get(owner)
        if peer is None or ref not in peer.get("source_refs", []):
            continue
        if any(_paragraph_bounds(text, start) == facet_block
               for start in positions[owner].get(ref, ())):
            return True
    return False


def build_target_context_candidates(
    payload: Mapping[str, Any], refs: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    """Project exact preceding, bound, or source-local peer facets per target.

    Selection is structural only: same target source owner, exact source bytes,
    before exact answer evidence in the same blank-line-delimited block, or an
    exact ref/quote/role binding already held by the target.  Facets owned by a
    present target with exact evidence in that same block are exposed
    symmetrically so the auditor must classify irrelevant alternatives instead
    of returning IDs the server never offered. For ordinary targets, an exact
    same-ref assessed term cannot be a context candidate; its global facet and
    any held binding remain unchanged for their independent native/audit checks.
    """
    if not isinstance(payload, Mapping) or not isinstance(refs, Mapping):
        raise _invalid("input")
    targets, facets = payload.get("targets"), payload.get("qualification_facets", [])
    if not isinstance(targets, list) or not isinstance(facets, list):
        raise _invalid("inventory")

    facet_rows: list[tuple[int, Mapping[str, Any], int]] = []
    facet_ids: set[str] = set()
    for index, facet in enumerate(facets):
        if not isinstance(facet, Mapping):
            raise _invalid("facet")
        facet_id, ref, quote, role = (
            facet.get("id"), facet.get("ref"), facet.get("quote"), facet.get("role")
        )
        if (
            not isinstance(facet_id, str)
            or not facet_id
            or facet_id in facet_ids
            or not isinstance(ref, str)
            or not isinstance(quote, str)
            or not quote
            or not isinstance(role, str)
            or not role
        ):
            raise _invalid("facet")
        text = _source_text(refs, ref)
        first = text.find(quote)
        if first < 0:
            raise _invalid("facet_quote")
        facet_ids.add(facet_id)
        facet_rows.append((index, facet, first))

    target_rows: dict[str, Mapping[str, Any]] = {}
    target_positions: dict[str, Mapping[str, tuple[int, ...]]] = {}
    for target in targets:
        if not isinstance(target, Mapping) or not isinstance(target.get("id"), str):
            raise _invalid("target")
        target_id = target["id"]
        if not target_id or target_id in target_rows:
            raise _invalid("target")
        source_refs = target.get("source_refs")
        bindings = target.get("governing_bindings", [])
        if (
            not isinstance(source_refs, list)
            or any(not isinstance(ref, str) for ref in source_refs)
            or not isinstance(bindings, list)
        ):
            raise _invalid("target_scope")
        target_rows[target_id] = target
        target_positions[target_id] = _target_evidence_positions(target, refs)

    result: dict[str, tuple[str, ...]] = {}
    for target_id, target in target_rows.items():
        source_refs = target.get("source_refs")
        bindings = target.get("governing_bindings", [])
        if not isinstance(source_refs, list) or not isinstance(bindings, list):
            raise _invalid("target_scope")  # Defensive re-narrowing for typed Mapping values.
        positions = target_positions[target_id]
        groups = target.get("answer_components", [])
        groups = groups if isinstance(groups, list) else []
        assessed = {
            (group["ref"], term)
            for group in groups
            if isinstance(group, Mapping) and isinstance(group.get("ref"), str)
            and isinstance(group.get("terms"), list)
            for term in group["terms"] if isinstance(term, str)
        } if target.get("construction_mode", "") == "" else set()
        candidates: list[tuple[int, int, str]] = []
        for index, facet, first in facet_rows:
            ref, quote, role = facet["ref"], facet["quote"], facet["role"]
            if ref not in source_refs or role in _ASSESSED_ONLY_ROLES or (ref, quote) in assessed:
                continue
            linked = any(_binding_matches_facet(binding, facet) for binding in bindings)
            peer = _shares_exact_evidence_block(
                facet, target_id, target_rows, target_positions, refs,
            )
            if linked or peer:
                candidates.append((first, index, facet["id"]))
                continue
            text = _source_text(refs, ref)
            span = _unique_span(text, quote)
            if span is None:
                continue
            for evidence_start in positions.get(ref, ()):
                if span[1] > evidence_start:
                    continue
                facet_block = _paragraph_bounds(text, span[0])
                evidence_block = _paragraph_bounds(text, evidence_start)
                if facet_block == evidence_block:
                    candidates.append((span[0], index, facet["id"]))
                    break
        candidates.sort()
        result[target_id] = tuple(candidate_id for _start, _index, candidate_id in candidates)
    return result


def _validate_axes(axes: Any) -> dict[str, str]:
    if (
        not isinstance(axes, dict)
        or set(axes) != set(_CONTEXT_AXES)
        or any(type(status) is not str or status not in _CONTEXT_STATUSES for status in axes.values())
    ):
        raise _invalid("axes")
    return axes


def _partition_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise _invalid("partition")
    if len(set(value)) != len(value):
        raise _invalid("partition_duplicate")
    return tuple(value)


def _make_negative(axes: dict[str, str], role: str, status: str) -> None:
    axis = _ROLE_AXIS.get(role)
    affected = (axis,) if axis is not None else _CONTEXT_AXES
    for name in affected:
        current = axes[name]
        if status == "ambiguous":
            axes[name] = "ambiguous"
        elif current not in {"missing", "ambiguous"}:
            axes[name] = "missing"


def validate_context_candidate_partition(
    verdict: Any, payload: Mapping[str, Any], refs: Mapping[str, Any],
) -> dict[str, Any]:
    """Strict legacy validator; any malformed target row rejects the audit."""
    result = isolate_context_candidate_partitions(verdict, payload, refs)
    if result.gaps:
        code = result.gaps[0].code
        if code == "partition_shape":
            raise _invalid("partition")
        if code == "partition_duplicate":
            raise _invalid("partition_duplicate")
        raise _invalid("partition_inventory")
    # A binding gap is a target-local negative, never a fabricated uncertainty
    # in all six semantic axes. Low-level context-only callers carry no votes.
    if result.binding_gaps and "target_verdicts" in result.effective_verdict:
        from app.modules.ai.target_context_audit import withhold_missing_context_bindings

        return withhold_missing_context_bindings(
            result.effective_verdict, tuple(payload_target["id"] for payload_target in payload["targets"]),
            result.binding_gaps,
        )
    return result.effective_verdict


def isolate_context_candidate_partitions(
    verdict: Any, payload: Mapping[str, Any], refs: Mapping[str, Any],
) -> TargetContextPartitionIsolation:
    """Isolate attributable partition defects and add negatives only to valid rows.

    The target row and six-axis inventories stay globally strict.  Only the
    three candidate lists inside a uniquely owned row can become a local gap.
    Missing IDs are never classified and malformed rows never grant coverage.
    """
    if not isinstance(verdict, dict):
        raise _invalid("verdict")
    inventory = build_target_context_candidates(payload, refs)
    facets = payload.get("qualification_facets", [])
    facet_by_id = {facet["id"]: facet for facet in facets}
    target_by_id = {target["id"]: target for target in payload.get("targets", [])}
    rows = verdict.get("target_context_verdicts")
    if not isinstance(rows, list) or len(rows) != len(inventory):
        raise _invalid("row_inventory")

    raw_rows = verdict.get("target_context_verdicts")
    raw_rows_sha256 = hashlib.sha256(
        json.dumps(raw_rows, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    canonical = deepcopy(verdict)
    seen: set[str] = set()
    valid: list[str] = []
    invalid: list[str] = []
    gaps: list[TargetContextPartitionGap] = []
    binding_gaps: list[tuple[str, str]] = []
    for row in canonical["target_context_verdicts"]:
        if not isinstance(row, dict) or set(row) != {"target_id", "axes", "candidates"}:
            raise _invalid("row")
        target_id = row["target_id"]
        if not isinstance(target_id, str) or target_id not in inventory or target_id in seen:
            raise _invalid("row_inventory")
        seen.add(target_id)
        axes = _validate_axes(row["axes"])
        parts = row["candidates"]
        shape_invalid = not isinstance(parts, dict) or set(parts) != set(_CANDIDATE_PARTS)
        partition: dict[str, tuple[str, ...]] = {}
        if not shape_invalid:
            for name in _CANDIDATE_PARTS:
                value = parts[name]
                if (not isinstance(value, list)
                        or any(not isinstance(item, str) or not item for item in value)):
                    shape_invalid = True
                    break
                partition[name] = tuple(value)
        flattened = tuple(
            item for name in _CANDIDATE_PARTS for item in partition.get(name, ())
        )
        duplicate_ids = tuple(dict.fromkeys(
            item for item in flattened if flattened.count(item) > 1
        ))
        expected = inventory[target_id]
        missing_ids = tuple(item for item in expected if item not in flattened)
        unexpected_ids = tuple(dict.fromkeys(item for item in flattened if item not in expected))
        if shape_invalid or missing_ids or unexpected_ids or duplicate_ids:
            if shape_invalid:
                code = "partition_shape"
            elif duplicate_ids:
                code = "partition_duplicate"
            elif missing_ids and not unexpected_ids:
                code = "partition_missing"
            elif unexpected_ids and not missing_ids:
                code = "partition_unexpected"
            else:
                code = "partition_inventory"
            invalid.append(target_id)
            gaps.append(TargetContextPartitionGap(
                target_id=target_id,
                code=code,
                missing_candidate_ids=missing_ids,
                unexpected_candidate_ids=unexpected_ids,
                duplicate_candidate_ids=duplicate_ids,
            ))
            continue
        valid.append(target_id)

        target = target_by_id[target_id]
        bindings = target.get("governing_bindings", [])
        for facet_id in partition["applies"]:
            facet = facet_by_id[facet_id]
            if facet["role"] not in _KNOWN_CONTEXT_ROLES:
                _make_negative(axes, facet["role"], "ambiguous")
                continue
            if any(_binding_matches_facet(binding, facet) for binding in bindings):
                continue
            if facet["role"] == "scope":
                binding_gaps.append((target_id, facet_id))
                continue
            status = "missing" if facet["role"] in _ROLE_AXIS else "ambiguous"
            _make_negative(axes, facet["role"], status)
        for facet_id in partition["ambiguous"]:
            _make_negative(axes, facet_by_id[facet_id]["role"], "ambiguous")
    if seen != set(inventory):
        raise _invalid("row_inventory")
    return TargetContextPartitionIsolation(
        effective_verdict=canonical,
        valid_target_ids=tuple(target_id for target_id in inventory if target_id in valid),
        invalid_target_ids=tuple(target_id for target_id in inventory if target_id in invalid),
        gaps=tuple(gaps),
        raw_rows_sha256=raw_rows_sha256,
        binding_gaps=tuple(binding_gaps),
    )
