"""Pure source-preservation and explicit-branch reconciliation for assessment facets.

This module validates caller-supplied structure only.  It does not infer a
facet's semantic role or branch effect, establish source completeness, or
credit an action merely because a qualification appears in fixed context.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_FACETS = 192
MAX_ID_CHARS = 100
MAX_QUOTE_CHARS = 65_536
MAX_TARGET_IDS = 192
MAX_CONTEXT_ENVELOPES = 192
MAX_SHARED_SOURCE_GROUPS = 192

FACET_ROLES = frozenset(
    {"actor", "recipient", "timing", "condition", "exception", "scope", "quantity", "operator"}
)
BRANCH_EFFECTS = frozenset(
    {
        "none",
        "scopes_action",
        "changes_action",
        "changes_recipient",
        "changes_timing",
        "changes_outcome",
    }
)
MATERIAL_BRANCH_EFFECTS = BRANCH_EFFECTS - {"none", "scopes_action"}
_RAW_FIELDS = frozenset(
    {"id", "ref", "quote", "target_ids", "role", "branch_effect", "branch_target_ids"}
)


@dataclass(frozen=True)
class CanonicalAssessmentFacet:
    facet_id: str
    source_ref: str
    source_id: str
    quote: str
    role: str
    branch_effect: str
    target_ids: tuple[str, ...]
    branch_target_ids: tuple[str, ...]
    quote_start: int
    quote_end: int


@dataclass(frozen=True)
class FacetResolution:
    facets: tuple[CanonicalAssessmentFacet, ...]
    source_unresolved_facet_ids: tuple[str, ...]
    source_unresolved_refs: tuple[str, ...]
    assessment_unresolved_branch_facet_ids: tuple[str, ...]


def _is_opaque_id(value: Any, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value[0].isalnum()
        and all(character.isalnum() or character in ":._-" for character in value)
    )


def _literal_pattern(value: str) -> re.Pattern[str]:
    prefix = r"(?<!\w)" if value[:1].isalnum() else ""
    suffix = r"(?!\w)" if value[-1:].isalnum() else ""
    return re.compile(prefix + re.escape(value) + suffix)


def _literal_occurrences(value: str, text: str) -> tuple[re.Match[str], ...]:
    """Find up to two valid occurrences, including overlapping spans."""
    pattern = _literal_pattern(value)
    matches: list[re.Match[str]] = []
    position = 0
    while len(matches) < 2:
        match = pattern.search(text, position)
        if match is None:
            break
        matches.append(match)
        position = match.start() + 1
    return tuple(matches)


def _validate_sources(
    sources: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    if not isinstance(sources, Mapping):
        raise ValueError("invalid_facet_sources")
    validated: dict[str, tuple[str, str]] = {}
    for source_ref, binding in sources.items():
        if not _is_opaque_id(source_ref, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_facet_source_ref")
        if not isinstance(binding, tuple) or len(binding) != 2:
            raise ValueError("invalid_facet_source_binding")
        source_id, text = binding
        if not _is_opaque_id(source_id, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_facet_source_id")
        if not isinstance(text, str) or not text or len(text) > MAX_QUOTE_CHARS:
            raise ValueError("invalid_facet_source_text")
        validated[source_ref] = (source_id, text)
    return validated


def _validate_target_sources(
    target_sources: Mapping[str, tuple[str, ...]],
    *,
    sources: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, ...]]:
    if not isinstance(target_sources, Mapping):
        raise ValueError("invalid_facet_target_sources")
    validated: dict[str, tuple[str, ...]] = {}
    for target_id, source_refs in target_sources.items():
        if not _is_opaque_id(target_id, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_facet_target_id")
        if (
            not isinstance(source_refs, tuple)
            or not source_refs
            or len(source_refs) > MAX_TARGET_IDS
            or any(not _is_opaque_id(ref, maximum=MAX_ID_CHARS) for ref in source_refs)
            or len(set(source_refs)) != len(source_refs)
        ):
            raise ValueError("invalid_facet_target_source_refs")
        if any(ref not in sources for ref in source_refs):
            raise ValueError("unknown_facet_target_source_ref")
        validated[target_id] = source_refs
    return validated


def _validate_known_ids(
    values: Collection[str],
    *,
    known: Mapping[str, Any],
    label: str,
) -> frozenset[str]:
    if isinstance(values, str | bytes | Mapping) or not isinstance(values, Collection):
        raise ValueError(f"invalid_{label}_ids")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not _is_opaque_id(value, maximum=MAX_ID_CHARS):
            raise ValueError(f"invalid_{label}_id")
        if value in seen:
            raise ValueError(f"duplicate_{label}_id")
        if value not in known:
            raise ValueError(f"unknown_{label}_id")
        seen.add(value)
        result.append(value)
    return frozenset(result)


def _validate_shared_groups(
    groups: Sequence[Collection[str]],
    *,
    sources: Mapping[str, tuple[str, str]],
) -> tuple[frozenset[str], ...]:
    if isinstance(groups, str | bytes | Mapping) or not isinstance(groups, Sequence):
        raise ValueError("invalid_shared_branch_source_groups")
    if len(groups) > MAX_SHARED_SOURCE_GROUPS:
        raise ValueError("shared_branch_source_groups_bounds")
    validated: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()
    for group in groups:
        if isinstance(group, str | bytes | Mapping) or not isinstance(group, Collection):
            raise ValueError("invalid_shared_branch_source_group")
        refs = tuple(group)
        if (
            not 2 <= len(refs) <= MAX_TARGET_IDS
            or any(not _is_opaque_id(ref, maximum=MAX_ID_CHARS) for ref in refs)
            or len(set(refs)) != len(refs)
            or any(ref not in sources for ref in refs)
        ):
            raise ValueError("invalid_shared_branch_source_group")
        frozen = frozenset(refs)
        if frozen in seen:
            raise ValueError("duplicate_shared_branch_source_group")
        seen.add(frozen)
        validated.append(frozen)
    return tuple(validated)


def _validate_context_envelopes(
    envelopes: Mapping[str, tuple[tuple[str, str], ...]] | None,
    *,
    sources: Mapping[str, tuple[str, str]],
    target_sources: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[tuple[str, str, int], ...]]:
    if envelopes is None:
        return {}
    if not isinstance(envelopes, Mapping):
        raise ValueError("invalid_facet_context_envelopes")
    validated: dict[str, tuple[tuple[str, str, int], ...]] = {}
    for target_id, rows in envelopes.items():
        if target_id not in target_sources:
            raise ValueError("unknown_facet_context_target_id")
        if not isinstance(rows, tuple) or len(rows) > MAX_CONTEXT_ENVELOPES:
            raise ValueError("invalid_facet_context_envelopes")
        checked: list[tuple[str, str, int]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, tuple) or len(row) != 2:
                raise ValueError("invalid_facet_context_envelope")
            source_ref, quote = row
            if (
                source_ref not in target_sources[target_id]
                or not isinstance(quote, str)
                or not quote
                or quote != quote.strip()
                or len(quote) > MAX_QUOTE_CHARS
                or (source_ref, quote) in seen
            ):
                raise ValueError("invalid_facet_context_envelope")
            seen.add((source_ref, quote))
            matches = _literal_occurrences(quote, sources[source_ref][1])
            if len(matches) != 1:
                raise ValueError("unowned_facet_context_envelope")
            checked.append((source_ref, quote, matches[0].start()))
        validated[target_id] = tuple(checked)
    return validated


def _row_target_ids(
    value: Any,
    *,
    target_sources: Mapping[str, tuple[str, ...]],
    field: str,
    require_nonempty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_TARGET_IDS:
        raise ValueError(f"invalid_facet_{field}")
    if require_nonempty and not value:
        raise ValueError(f"invalid_facet_{field}")
    result: list[str] = []
    seen: set[str] = set()
    for target_id in value:
        if not _is_opaque_id(target_id, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_facet_target_id")
        if target_id in seen:
            raise ValueError("duplicate_facet_target_id")
        if target_id not in target_sources:
            raise ValueError("unknown_facet_target_id")
        seen.add(target_id)
        result.append(target_id)
    return tuple(result)


def _target_owns_source(
    target_id: str,
    source_ref: str,
    *,
    target_sources: Mapping[str, tuple[str, ...]],
    shared_groups: tuple[frozenset[str], ...],
) -> bool:
    owned = target_sources[target_id]
    if source_ref in owned:
        return True
    return any(source_ref in group and any(ref in group for ref in owned) for group in shared_groups)


def _resolve_quote_span(
    *,
    source_ref: str,
    quote: str,
    target_ids: tuple[str, ...],
    sources: Mapping[str, tuple[str, str]],
    context_envelopes: Mapping[str, tuple[tuple[str, str, int], ...]],
) -> tuple[int, int] | None:
    original = sources[source_ref][1]
    matches = _literal_occurrences(quote, original)
    if len(matches) == 1:
        return matches[0].start(), matches[0].end()
    if not matches:
        return None
    candidates: set[tuple[int, int]] = set()
    for target_id in target_ids:
        for envelope_ref, envelope, envelope_start in context_envelopes.get(target_id, ()):
            if envelope_ref != source_ref:
                continue
            local = _literal_occurrences(quote, envelope)
            if len(local) == 1:
                candidates.add(
                    (envelope_start + local[0].start(), envelope_start + local[0].end())
                )
    return next(iter(candidates)) if len(candidates) == 1 else None


def resolve_assessment_facets(
    raw: Sequence[Mapping[str, Any]] | None,
    *,
    sources: Mapping[str, tuple[str, str]],
    target_sources: Mapping[str, tuple[str, ...]],
    operational_target_ids: Collection[str],
    admitted_target_ids: Collection[str],
    retained_target_ids: Collection[str],
    context_envelopes: Mapping[str, tuple[tuple[str, str], ...]] | None = None,
    shared_branch_source_groups: Sequence[Collection[str]] = (),
) -> FacetResolution:
    """Validate source facets and reconcile only explicit, operational branches.

    ``none`` and ``scopes_action`` preserve source qualifications but never earn
    branch coverage.  Material effects are complete only when every explicitly
    linked branch target is operational, admitted, retained, and source-owned.
    """
    checked_sources = _validate_sources(sources)
    checked_target_sources = _validate_target_sources(
        target_sources, sources=checked_sources
    )
    operational = _validate_known_ids(
        operational_target_ids, known=checked_target_sources, label="operational_target"
    )
    admitted = _validate_known_ids(
        admitted_target_ids, known=checked_target_sources, label="admitted_target"
    )
    retained = _validate_known_ids(
        retained_target_ids, known=checked_target_sources, label="retained_target"
    )
    shared_groups = _validate_shared_groups(
        shared_branch_source_groups, sources=checked_sources
    )
    checked_envelopes = _validate_context_envelopes(
        context_envelopes,
        sources=checked_sources,
        target_sources=checked_target_sources,
    )

    if raw is None:
        rows: tuple[Mapping[str, Any], ...] = ()
    elif isinstance(raw, str | bytes | Mapping) or not isinstance(raw, Sequence):
        raise ValueError("invalid_facet_inventory_shape")
    else:
        rows = tuple(raw)
    if len(rows) > MAX_FACETS:
        raise ValueError("facet_inventory_bounds")

    facets: list[CanonicalAssessmentFacet] = []
    source_unresolved_ids: list[str] = []
    source_unresolved_refs: list[str] = []
    assessment_unresolved_ids: list[str] = []
    seen_ids: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping) or frozenset(row) != _RAW_FIELDS:
            raise ValueError("invalid_facet_schema")
        facet_id = row["id"]
        if not _is_opaque_id(facet_id, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_facet_id")
        if facet_id in seen_ids:
            raise ValueError("duplicate_facet_id")
        seen_ids.add(facet_id)

        source_ref = row["ref"]
        if not _is_opaque_id(source_ref, maximum=MAX_ID_CHARS):
            raise ValueError("invalid_facet_source_ref")
        if source_ref not in checked_sources:
            raise ValueError("unknown_facet_source_ref")
        quote = row["quote"]
        if (
            not isinstance(quote, str)
            or not quote
            or quote != quote.strip()
            or len(quote) > MAX_QUOTE_CHARS
        ):
            raise ValueError("invalid_facet_quote")
        role = row["role"]
        if role not in FACET_ROLES:
            raise ValueError("invalid_facet_role")
        branch_effect = row["branch_effect"]
        if branch_effect not in BRANCH_EFFECTS:
            raise ValueError("invalid_facet_branch_effect")
        target_ids = _row_target_ids(
            row["target_ids"],
            target_sources=checked_target_sources,
            field="target_ids",
            require_nonempty=True,
        )
        branch_target_ids = _row_target_ids(
            row["branch_target_ids"],
            target_sources=checked_target_sources,
            field="branch_target_ids",
            require_nonempty=False,
        )
        if branch_effect in {"none", "scopes_action"}:
            if branch_target_ids:
                raise ValueError("nonmaterial_facet_has_branch_targets")
        elif len(branch_target_ids) < 2:
            raise ValueError("material_facet_requires_explicit_branches")
        elif not set(branch_target_ids) <= set(target_ids):
            raise ValueError("branch_target_outside_facet_targets")

        if any(
            not _target_owns_source(
                target_id,
                source_ref,
                target_sources=checked_target_sources,
                shared_groups=shared_groups,
            )
            for target_id in (*target_ids, *branch_target_ids)
        ):
            raise ValueError("foreign_facet_target_owner")

        span = _resolve_quote_span(
            source_ref=source_ref,
            quote=quote,
            target_ids=target_ids,
            sources=checked_sources,
            context_envelopes=checked_envelopes,
        )
        if span is None:
            source_unresolved_ids.append(facet_id)
            if source_ref not in source_unresolved_refs:
                source_unresolved_refs.append(source_ref)
            continue

        if branch_effect in MATERIAL_BRANCH_EFFECTS and not set(branch_target_ids) <= (
            operational & admitted & retained
        ):
            assessment_unresolved_ids.append(facet_id)

        facets.append(
            CanonicalAssessmentFacet(
                facet_id=facet_id,
                source_ref=source_ref,
                source_id=checked_sources[source_ref][0],
                quote=quote,
                role=role,
                branch_effect=branch_effect,
                target_ids=target_ids,
                branch_target_ids=branch_target_ids,
                quote_start=span[0],
                quote_end=span[1],
            )
        )

    return FacetResolution(
        facets=tuple(facets),
        source_unresolved_facet_ids=tuple(source_unresolved_ids),
        source_unresolved_refs=tuple(source_unresolved_refs),
        assessment_unresolved_branch_facet_ids=tuple(assessment_unresolved_ids),
    )


__all__ = [
    "BRANCH_EFFECTS",
    "FACET_ROLES",
    "CanonicalAssessmentFacet",
    "FacetResolution",
    "resolve_assessment_facets",
]
