"""Compile target-local exact source bindings into server-owned facet links.

The compiler derives identity and membership only. It never assigns semantic
roles/effects, invents branch endpoints, or grants assessment coverage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.ai.assessment_facets import (
    BRANCH_EFFECTS,
    FACET_ROLES,
    MATERIAL_BRANCH_EFFECTS,
    MAX_FACETS,
    MAX_ID_CHARS,
    MAX_QUOTE_CHARS,
    CanonicalAssessmentFacet,
    _is_opaque_id,
    _literal_occurrences,
    _resolve_quote_span,
    _validate_sources,
)

_BINDING_FIELDS = frozenset({"ref", "quote", "role", "branch_effect"})

BindingIssueCode = Literal[
    "invalid_binding_inventory",
    "invalid_binding_schema",
    "unknown_source_ref",
    "invalid_quote",
    "invalid_role",
    "invalid_branch_effect",
    "nonliteral_quote",
    "repeated_quote",
    "duplicate_target_binding",
]


@dataclass(frozen=True)
class CanonicalTargetGoverningBinding:
    facet_id: str
    source_ref: str
    source_id: str
    quote: str
    role: str
    branch_effect: str
    quote_start: int
    quote_end: int


@dataclass(frozen=True)
class TargetGoverningBindings:
    target_id: str
    bindings: tuple[CanonicalTargetGoverningBinding, ...]


@dataclass(frozen=True)
class InvalidTargetBindingIssue:
    target_id: str
    binding_index: int
    code: BindingIssueCode


@dataclass(frozen=True)
class GoverningBindingCompilation:
    facets: tuple[CanonicalAssessmentFacet, ...]
    target_bindings: tuple[TargetGoverningBindings, ...]
    invalid_target_issues: tuple[InvalidTargetBindingIssue, ...]
    assessment_unresolved_branch_facet_ids: tuple[str, ...]


@dataclass
class _BindingGroup:
    target_ids: set[str]


def _answer_component_envelopes(
    target_rows: Sequence[Mapping[str, Any]],
    sources: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[tuple[str, str, int], ...]]:
    """Return exact unique same-target component spans for quote location only."""
    result: dict[str, tuple[tuple[str, str, int], ...]] = {}
    for target_row in target_rows:
        if not isinstance(target_row, Mapping):
            continue
        target_id = target_row.get("id")
        source_refs = target_row.get("source_refs")
        components = target_row.get("answer_components")
        if (
            not isinstance(target_id, str)
            or not isinstance(source_refs, list)
            or not source_refs
            or any(not isinstance(ref, str) or ref not in sources for ref in source_refs)
            or not isinstance(components, list)
            or target_row.get("construction_mode") not in (None, "")
            or target_row.get("question_format")
        ):
            continue
        checked: list[tuple[str, str, int]] = []
        seen: set[tuple[str, str]] = set()
        for component in components:
            if not isinstance(component, Mapping):
                continue
            source_ref, terms = component.get("ref"), component.get("terms")
            if (not isinstance(source_ref, str) or source_ref not in source_refs
                    or not isinstance(terms, list)):
                continue
            for term in terms:
                key = (source_ref, term) if isinstance(source_ref, str) and isinstance(term, str) else None
                if (
                    key is None
                    or key in seen
                    or not term
                    or term != term.strip()
                    or len(term) > MAX_QUOTE_CHARS
                ):
                    continue
                seen.add(key)
                matches = _literal_occurrences(term, sources[source_ref][1])
                if len(matches) == 1:
                    checked.append((source_ref, term, matches[0].start()))
        if checked:
            result[target_id] = tuple(checked)
    return result


def _facet_id(
    *, source_ref: str, source_id: str, quote_start: int, quote_end: int, role: str, branch_effect: str,
) -> str:
    identity = json.dumps(
        [source_ref, source_id, quote_start, quote_end, role, branch_effect],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "G" + hashlib.sha256(identity.encode()).hexdigest()


def compile_assessment_governing_bindings(
    target_rows: Sequence[Mapping[str, Any]],
    *,
    sources: Mapping[str, tuple[str, str]],
) -> GoverningBindingCompilation:
    """Canonicalize explicit target attachments and derive their facet graph.

    Invalid binding rows are isolated to their owning target. A material facet
    with one explicitly attached target is returned as an assessment gap; the
    compiler never fabricates another branch target.
    """
    checked_sources = _validate_sources(sources)
    if isinstance(target_rows, str | bytes | Mapping) or not isinstance(target_rows, Sequence):
        raise ValueError("invalid_governing_target_rows")
    if len(target_rows) > MAX_FACETS:
        raise ValueError("governing_target_rows_bounds")
    component_envelopes = _answer_component_envelopes(target_rows, checked_sources)

    target_ids: list[str] = []
    seen_target_ids: set[str] = set()
    issues: list[InvalidTargetBindingIssue] = []
    # Group identity is exactly source span + caller-supplied role/effect.
    groups: dict[tuple[str, int, int, str, str], _BindingGroup] = {}

    for target_row in target_rows:
        if not isinstance(target_row, Mapping):
            raise ValueError("invalid_governing_target_row")
        target_id = target_row.get("id")
        if not isinstance(target_id, str) or not _is_opaque_id(target_id, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_governing_target_id")
        if target_id in seen_target_ids:
            raise ValueError("duplicate_governing_target_id")
        seen_target_ids.add(target_id)
        target_ids.append(target_id)

        raw_bindings = target_row.get("governing_bindings", [])
        if not isinstance(raw_bindings, list) or len(raw_bindings) > MAX_FACETS:
            issues.append(InvalidTargetBindingIssue(target_id, -1, "invalid_binding_inventory"))
            continue
        seen_target_keys: set[tuple[str, int, int, str, str]] = set()
        for binding_index, raw in enumerate(raw_bindings):
            if not isinstance(raw, Mapping) or frozenset(raw) != _BINDING_FIELDS:
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, "invalid_binding_schema"))
                continue
            source_ref = raw["ref"]
            if not isinstance(source_ref, str) or source_ref not in checked_sources:
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, "unknown_source_ref"))
                continue
            quote = raw["quote"]
            if (not isinstance(quote, str) or not quote or quote != quote.strip()
                    or len(quote) > MAX_QUOTE_CHARS):
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, "invalid_quote"))
                continue
            role = raw["role"]
            if not isinstance(role, str) or role not in FACET_ROLES:
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, "invalid_role"))
                continue
            branch_effect = raw["branch_effect"]
            if not isinstance(branch_effect, str) or branch_effect not in BRANCH_EFFECTS:
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, "invalid_branch_effect"))
                continue

            span = _resolve_quote_span(source_ref=source_ref, quote=quote, target_ids=(target_id,),
                sources=checked_sources, context_envelopes=component_envelopes)
            if span is None:
                matches = _literal_occurrences(quote, checked_sources[source_ref][1])
                code: BindingIssueCode = "nonliteral_quote" if not matches else "repeated_quote"
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, code))
                continue
            key = (source_ref, span[0], span[1], role, branch_effect)
            if key in seen_target_keys:
                issues.append(InvalidTargetBindingIssue(target_id, binding_index, "duplicate_target_binding"))
                continue
            seen_target_keys.add(key)
            group = groups.setdefault(key, _BindingGroup(set()))
            group.target_ids.add(target_id)

    facets: list[CanonicalAssessmentFacet] = []
    bindings_by_target: dict[str, list[CanonicalTargetGoverningBinding]] = {
        target_id: [] for target_id in target_ids
    }
    assessment_gaps: list[str] = []
    for key, group in groups.items():
        source_ref, quote_start, quote_end, role, branch_effect = key
        source_id, source_text = checked_sources[source_ref]
        facet_id = _facet_id(source_ref=source_ref, source_id=source_id,
            quote_start=quote_start, quote_end=quote_end, role=role, branch_effect=branch_effect)
        members = tuple(sorted(group.target_ids))
        branch_members = members if branch_effect in MATERIAL_BRANCH_EFFECTS else ()
        facets.append(CanonicalAssessmentFacet(facet_id, source_ref, source_id,
            source_text[quote_start:quote_end], role, branch_effect, members, branch_members,
            quote_start, quote_end))
        if branch_effect in MATERIAL_BRANCH_EFFECTS and len(members) < 2:
            assessment_gaps.append(facet_id)
        record = CanonicalTargetGoverningBinding(facet_id, source_ref, source_id,
            source_text[quote_start:quote_end], role, branch_effect, quote_start, quote_end)
        for target_id in members:
            bindings_by_target[target_id].append(record)

    facets.sort(key=lambda facet: facet.facet_id)
    target_bindings = tuple(TargetGoverningBindings(target_id,
        tuple(sorted(bindings_by_target[target_id], key=lambda binding: binding.facet_id)))
        for target_id in sorted(target_ids))
    return GoverningBindingCompilation(
        facets=tuple(facets),
        target_bindings=target_bindings,
        invalid_target_issues=tuple(issues),
        assessment_unresolved_branch_facet_ids=tuple(sorted(assessment_gaps)),
    )


__all__ = [
    "BindingIssueCode",
    "CanonicalTargetGoverningBinding",
    "GoverningBindingCompilation",
    "InvalidTargetBindingIssue",
    "TargetGoverningBindings",
    "compile_assessment_governing_bindings",
]
