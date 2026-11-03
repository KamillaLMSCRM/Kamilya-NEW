"""Pure reconciliation for model-declared material assessment obligations.

This module proves only exact structural bindings supplied by its callers.  It
does not infer material completeness, semantic equivalence, or question truth.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.ai.teaching_context import TeachingContext

MAX_OBLIGATION_ID_CHARS = 100
MAX_OPAQUE_ID_CHARS = 192
MAX_QUOTE_CHARS = 512
MAX_INVENTORY_ROWS = 192
MAX_TARGET_BINDINGS = 192
MAX_TARGET_IDS_PER_OBLIGATION = 192
MAX_TARGET_ANCHORS = 192

MATERIAL_DIMENSIONS = frozenset(
    {
        "action",
        "object",
        "condition",
        "exception",
        "timing",
        "actor",
        "quantity",
        "operator",
        "outcome",
    }
)
EVIDENCE_LEVELS = frozenset({"source_recognition", "operational_decision"})

_RAW_FIELDS = frozenset(
    {"id", "ref", "quote", "dimension", "target_ids", "evidence_level"}
)
_REPAIR_TARGET_SUFFIX = re.compile(
    r"[0-9a-f]{12}(?:-(?:[2-9]|[1-8][0-9]|9[0-7]))?"
)


@dataclass(frozen=True)
class MaterialObligation:
    obligation_id: str
    source_ref: str
    source_id: str
    quote: str
    dimension: str
    evidence_level: str
    target_ids: tuple[str, ...]
    quote_start: int | None = None
    quote_end: int | None = None


@dataclass(frozen=True)
class InvalidMaterialObligation:
    obligation_id: str
    source_ref: str
    code: str = "nonliteral_obligation_quote"


@dataclass(frozen=True)
class MaterialObligationEnumIssue:
    """One typed provider-owned enum field that needs a bounded repair."""

    obligation_id: str
    field: str
    invalid_value: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class MaterialInventory:
    present: bool
    obligations: tuple[MaterialObligation, ...]
    unresolved_ids: tuple[str, ...]
    unresolved_refs: tuple[str, ...]
    invalid_obligations: tuple[InvalidMaterialObligation, ...] = ()


@dataclass(frozen=True)
class _ValidatedTargetAnchor:
    source_id: str
    focus: str
    evidence_level: str
    focus_start: int
    focus_end: int


def _is_opaque_id(value: Any, *, maximum: int = MAX_OPAQUE_ID_CHARS) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value[0].isalnum()
        and all(character.isalnum() or character in ":._-" for character in value)
    )


def _is_target_id(value: Any) -> bool:
    if _is_opaque_id(value):
        return True
    if not isinstance(value, str) or len(value) > MAX_OPAQUE_ID_CHARS:
        return False
    base, separator, suffix = value.rpartition("~repair-")
    return bool(
        separator
        and "~" not in base
        and _is_opaque_id(base)
        and _REPAIR_TARGET_SUFFIX.fullmatch(suffix)
    )


def _bounded_literal_pattern(value: str) -> re.Pattern[str]:
    prefix = r"(?<!\w)" if value[:1].isalnum() else ""
    suffix = r"(?!\w)" if value[-1:].isalnum() else ""
    return re.compile(prefix + re.escape(value) + suffix)


def _validated_sources(
    sources: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    if not isinstance(sources, Mapping):
        raise ValueError("invalid_sources_shape")
    validated: dict[str, tuple[str, str]] = {}
    for source_ref, source in sources.items():
        if not _is_opaque_id(source_ref):
            raise ValueError("invalid_source_ref")
        if not isinstance(source, tuple) or len(source) != 2:
            raise ValueError("invalid_source_binding")
        source_id, original = source
        if not _is_opaque_id(source_id):
            raise ValueError("invalid_source_id")
        if not isinstance(original, str) or not original:
            raise ValueError("invalid_source_text")
        validated[source_ref] = (source_id, original)
    return validated


def _validated_targets(
    targets: Mapping[str, tuple[tuple[str, str, str], ...]],
) -> dict[str, tuple[tuple[str, str, str], ...]]:
    if not isinstance(targets, Mapping):
        raise ValueError("invalid_targets_shape")
    validated: dict[str, tuple[tuple[str, str, str], ...]] = {}
    for target_id, bindings in targets.items():
        if not _is_target_id(target_id):
            raise ValueError("invalid_target_id")
        if not isinstance(bindings, tuple) or len(bindings) > MAX_TARGET_BINDINGS:
            raise ValueError("invalid_target_bindings")
        checked_bindings: list[tuple[str, str, str]] = []
        seen_bindings: set[tuple[str, str, str]] = set()
        for binding in bindings:
            if not isinstance(binding, tuple) or len(binding) != 3:
                raise ValueError("invalid_target_binding")
            source_id, focus, evidence_level = binding
            if not _is_opaque_id(source_id):
                raise ValueError("invalid_target_source_id")
            if (
                not isinstance(focus, str)
                or not focus
                or focus != focus.strip()
                or len(focus) > MAX_QUOTE_CHARS
            ):
                raise ValueError("invalid_target_focus")
            if evidence_level not in EVIDENCE_LEVELS:
                raise ValueError("invalid_target_evidence_level")
            signature = (source_id, focus, evidence_level)
            if signature in seen_bindings:
                raise ValueError("duplicate_target_binding")
            seen_bindings.add(signature)
            checked_bindings.append(signature)
        validated[target_id] = tuple(checked_bindings)
    return validated


def _validated_id_collection(
    values: Collection[str],
    *,
    known: Mapping[str, Any],
    validator: Callable[[Any], bool],
    shape_error: str,
    id_error: str,
    duplicate_error: str,
    foreign_error: str,
) -> tuple[str, ...]:
    if (
        isinstance(values, str | bytes | Mapping)
        or not isinstance(values, Collection)
    ):
        raise ValueError(shape_error)
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not validator(value):
            raise ValueError(id_error)
        if value in seen:
            raise ValueError(duplicate_error)
        if value not in known:
            raise ValueError(foreign_error)
        seen.add(value)
        result.append(value)
    return tuple(result)


def _validated_target_anchors(
    target_anchors: Mapping[str, tuple[tuple[str, str, str, str], ...]] | None,
    *,
    targets: Mapping[str, tuple[tuple[str, str, str], ...]],
    sources: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[_ValidatedTargetAnchor, ...]]:
    if target_anchors is None:
        return {}
    if not isinstance(target_anchors, Mapping):
        raise ValueError("invalid_target_anchors_shape")

    sources_by_id: dict[str, list[str]] = {}
    for source_id, original in sources.values():
        sources_by_id.setdefault(source_id, []).append(original)

    validated: dict[str, tuple[_ValidatedTargetAnchor, ...]] = {}
    for target_id, anchors in target_anchors.items():
        if not _is_target_id(target_id):
            raise ValueError("invalid_anchor_target_id")
        if target_id not in targets:
            raise ValueError("foreign_anchor_target_id")
        if not isinstance(anchors, tuple):
            raise ValueError("invalid_target_anchors")
        if len(anchors) > MAX_TARGET_ANCHORS:
            raise ValueError("invalid_target_anchors_bounds")

        checked: list[_ValidatedTargetAnchor] = []
        seen: set[tuple[str, str, str, str]] = set()
        for anchor in anchors:
            if not isinstance(anchor, tuple) or len(anchor) != 4:
                raise ValueError("invalid_target_anchor")
            source_id, focus, evidence_level, proposition = anchor
            if not _is_opaque_id(source_id):
                raise ValueError("invalid_anchor_source_id")
            owner_originals = sources_by_id.get(source_id, ())
            if not owner_originals:
                raise ValueError("foreign_anchor_source_id")
            if len(owner_originals) != 1:
                raise ValueError("ambiguous_anchor_source_id")
            if (
                not isinstance(focus, str)
                or not focus
                or focus != focus.strip()
                or len(focus) > MAX_QUOTE_CHARS
            ):
                raise ValueError("invalid_anchor_focus")
            if evidence_level not in EVIDENCE_LEVELS:
                raise ValueError("invalid_anchor_evidence_level")
            if (
                not isinstance(proposition, str)
                or not proposition
                or proposition != proposition.strip()
                or len(proposition) > MAX_QUOTE_CHARS
            ):
                raise ValueError("invalid_anchor_proposition")
            if (source_id, focus, evidence_level) not in targets[target_id]:
                raise ValueError("anchor_target_binding_mismatch")

            original = owner_originals[0]
            proposition_matches = tuple(
                _bounded_literal_pattern(proposition).finditer(original)
            )
            if not proposition_matches:
                raise ValueError("nonliteral_anchor_proposition")
            if len(proposition_matches) != 1:
                raise ValueError("nonunique_anchor_proposition")
            focus_matches = tuple(_bounded_literal_pattern(focus).finditer(proposition))
            if not focus_matches:
                raise ValueError("nonliteral_anchor_focus")
            if len(focus_matches) != 1:
                raise ValueError("nonunique_anchor_focus")

            signature = (source_id, focus, evidence_level, proposition)
            if signature in seen:
                raise ValueError("duplicate_target_anchor")
            seen.add(signature)
            proposition_start = proposition_matches[0].start()
            focus_start = proposition_start + focus_matches[0].start()
            checked.append(
                _ValidatedTargetAnchor(
                    source_id=source_id,
                    focus=focus,
                    evidence_level=evidence_level,
                    focus_start=focus_start,
                    focus_end=focus_start + len(focus),
                )
            )
        validated[target_id] = tuple(checked)
    return validated


def _missing_inventory_id(index: int) -> str:
    return f"__missing_inventory__:{index}"


def inspect_material_obligation_enum_fields(
    raw: Sequence[Mapping[str, Any]] | None,
    *,
    source_refs: Collection[str],
    target_ids: Collection[str],
    deferred_quote_length_ids: Collection[str] = (),
) -> tuple[MaterialObligationEnumIssue, ...]:
    """Inventory only repairable enum strings after strict ownership checks.

    This is a request-schema preflight, not material reconciliation or semantic
    approval. Unsupported strings may be repaired by the model. Malformed types,
    fields, ownership, IDs, quotes, and links fail closed instead of being
    converted into a guessed enum value. A caller may defer only the maximum
    length check for explicitly named rows that a separate structural contract
    has already proved eligible for exact source-preserving reprojection.
    """
    known_sources = {value: None for value in source_refs}
    known_targets = {value: None for value in target_ids}
    if any(not _is_opaque_id(value) for value in known_sources):
        raise ValueError("invalid_source_ref")
    if any(not _is_target_id(value) for value in known_targets):
        raise ValueError("invalid_target_id")
    if (isinstance(deferred_quote_length_ids, str | bytes | Mapping)
            or not isinstance(deferred_quote_length_ids, Collection)):
        raise ValueError("invalid_deferred_quote_length_id")
    deferred_ids = set(deferred_quote_length_ids)
    if any(not _is_opaque_id(value, maximum=MAX_OBLIGATION_ID_CHARS)
           for value in deferred_ids):
        raise ValueError("invalid_deferred_quote_length_id")
    if raw is None:
        if deferred_ids:
            raise ValueError("invalid_deferred_quote_length_id")
        return ()
    if isinstance(raw, str | bytes | Mapping) or not isinstance(raw, Sequence):
        raise ValueError("invalid_inventory_shape")
    if len(raw) > MAX_INVENTORY_ROWS:
        raise ValueError("invalid_inventory_bounds")

    issues: list[MaterialObligationEnumIssue] = []
    seen_ids: set[str] = set()
    for row in raw:
        if not isinstance(row, Mapping):
            raise ValueError("invalid_inventory_shape")
        if frozenset(row) != _RAW_FIELDS:
            raise ValueError("invalid_obligation_schema")
        obligation_id = row["id"]
        if not _is_opaque_id(obligation_id, maximum=MAX_OBLIGATION_ID_CHARS):
            raise ValueError("invalid_obligation_id")
        if obligation_id in seen_ids:
            raise ValueError("duplicate_obligation_id")
        seen_ids.add(obligation_id)

        source_ref = row["ref"]
        if not _is_opaque_id(source_ref):
            raise ValueError("invalid_obligation_ref")
        if source_ref not in known_sources:
            raise ValueError("foreign_source_ref")
        quote = row["quote"]
        if (not isinstance(quote, str) or not quote or quote != quote.strip()
                or (len(quote) > MAX_QUOTE_CHARS and obligation_id not in deferred_ids)):
            raise ValueError("invalid_obligation_quote")
        requested_target_ids = row["target_ids"]
        if not isinstance(requested_target_ids, list):
            raise ValueError("invalid_obligation_target_ids")
        if len(requested_target_ids) > MAX_TARGET_IDS_PER_OBLIGATION:
            raise ValueError("invalid_obligation_target_ids_bounds")
        _validated_id_collection(
            requested_target_ids,
            known=known_targets,
            validator=_is_target_id,
            shape_error="invalid_obligation_target_ids",
            id_error="invalid_obligation_target_id",
            duplicate_error="duplicate_obligation_target_id",
            foreign_error="foreign_target_id",
        )

        dimension = row["dimension"]
        if not isinstance(dimension, str):
            raise ValueError("invalid_obligation_dimension")
        if dimension not in MATERIAL_DIMENSIONS:
            issues.append(MaterialObligationEnumIssue(
                obligation_id=obligation_id,
                field="dimension",
                invalid_value=dimension,
                allowed_values=tuple(sorted(MATERIAL_DIMENSIONS)),
            ))
        evidence_level = row["evidence_level"]
        if not isinstance(evidence_level, str):
            raise ValueError("invalid_evidence_level")
        if evidence_level not in EVIDENCE_LEVELS:
            issues.append(MaterialObligationEnumIssue(
                obligation_id=obligation_id,
                field="evidence_level",
                invalid_value=evidence_level,
                allowed_values=tuple(sorted(EVIDENCE_LEVELS)),
            ))
    if not deferred_ids <= seen_ids:
        raise ValueError("invalid_deferred_quote_length_id")
    return tuple(issues)


def apply_material_obligation_enum_patches(
    raw: Sequence[Mapping[str, Any]],
    *,
    issues: Sequence[MaterialObligationEnumIssue],
    patches: Sequence[Mapping[str, Any]],
    source_refs: Collection[str],
    target_ids: Collection[str],
) -> list[dict[str, Any]]:
    """Overlay only explicitly invalid enum fields, preserving every other field."""
    current = inspect_material_obligation_enum_fields(
        raw,
        source_refs=source_refs,
        target_ids=target_ids,
    )
    if tuple(issues) != current:
        raise ValueError("invalid_material_enum_patch_issues")
    by_id: dict[str, dict[str, MaterialObligationEnumIssue]] = {}
    for issue in current:
        by_id.setdefault(issue.obligation_id, {})[issue.field] = issue
    if (isinstance(patches, str | bytes | Mapping) or not isinstance(patches, Sequence)
            or len(patches) != len(by_id)):
        raise ValueError("invalid_material_enum_patch_shape")
    patch_by_id: dict[str, Mapping[str, Any]] = {}
    for incoming_patch in patches:
        if (not isinstance(incoming_patch, Mapping)
                or not isinstance(incoming_patch.get("id"), str)):
            raise ValueError("invalid_material_enum_patch_shape")
        obligation_id = incoming_patch["id"]
        fields = by_id.get(obligation_id)
        if (fields is None or obligation_id in patch_by_id
                or set(incoming_patch) != {"id", *fields}):
            raise ValueError("invalid_material_enum_patch_scope")
        for field, issue in fields.items():
            value = incoming_patch[field]
            if not isinstance(value, str) or value not in issue.allowed_values:
                raise ValueError("invalid_material_enum_patch_value")
        patch_by_id[obligation_id] = incoming_patch
    if set(patch_by_id) != set(by_id):
        raise ValueError("invalid_material_enum_patch_scope")

    repaired = []
    for row in raw:
        copied = dict(row)
        row_patch = patch_by_id.get(copied["id"])
        if row_patch is not None:
            for field in by_id[copied["id"]]:
                copied[field] = row_patch[field]
        repaired.append(copied)
    if inspect_material_obligation_enum_fields(
        repaired,
        source_refs=source_refs,
        target_ids=target_ids,
    ):
        raise ValueError("invalid_material_enum_patch_value")
    return repaired


def reconcile_material_obligations(
    raw: Sequence[Mapping[str, Any]] | None,
    *,
    sources: Mapping[str, tuple[str, str]],
    targets: Mapping[str, tuple[tuple[str, str, str], ...]],
    admitted_target_ids: Collection[str],
    require_inventory: bool,
    excluded_refs: Collection[str] = (),
    target_anchors: Mapping[str, tuple[tuple[str, str, str, str], ...]] | None = None,
    isolate_nonliteral_quotes: bool = False,
    teaching_contexts: Sequence[TeachingContext] = (),
) -> MaterialInventory:
    """Validate and reconcile exact material-obligation bindings.

    Returned target IDs are a structural intersection only: a requested target
    must be admitted and carry an exact same-source, same-focus, same-level
    binding.  Every other declared obligation remains explicitly unresolved.
    Optional nonliteral-quote isolation reports an otherwise valid invented row
    as an unresolved invalid record and never creates a material obligation.
    """
    if not isinstance(require_inventory, bool):
        raise ValueError("invalid_require_inventory")
    if not isinstance(isolate_nonliteral_quotes, bool):
        raise ValueError("invalid_isolate_nonliteral_quotes")

    checked_sources = _validated_sources(sources)
    # These are independently admitted source-plan contexts, never model-owned
    # exclusion flags. Rederive their full original-span custody here; all
    # declared obligations and the caller's operational floor remain intact.
    from app.modules.ai.teaching_context import complete_teaching_context_source_refs

    context_accounted = complete_teaching_context_source_refs(teaching_contexts, checked_sources)
    checked_targets = _validated_targets(targets)
    checked_anchors = _validated_target_anchors(
        target_anchors,
        targets=checked_targets,
        sources=checked_sources,
    )
    admitted = frozenset(
        _validated_id_collection(
            admitted_target_ids,
            known=checked_targets,
            validator=_is_target_id,
            shape_error="invalid_admitted_target_ids",
            id_error="invalid_admitted_target_id",
            duplicate_error="duplicate_admitted_target_id",
            foreign_error="foreign_admitted_target_id",
        )
    )
    excluded = frozenset(
        _validated_id_collection(
            excluded_refs,
            known=checked_sources,
            validator=_is_opaque_id,
            shape_error="invalid_excluded_refs",
            id_error="invalid_excluded_ref",
            duplicate_error="duplicate_excluded_ref",
            foreign_error="foreign_excluded_ref",
        )
    )

    if raw is None:
        rows: tuple[Mapping[str, Any], ...] = ()
        present = False
    elif isinstance(raw, str | bytes | Mapping) or not isinstance(raw, Sequence):
        raise ValueError("invalid_inventory_shape")
    else:
        rows = tuple(raw)
        present = True

    if len(rows) > MAX_INVENTORY_ROWS:
        raise ValueError("invalid_inventory_bounds")
    if not rows:
        if not present and not require_inventory:
            return MaterialInventory(False, (), (), ())
        missing_refs = tuple(sorted(ref for ref in checked_sources if ref not in excluded
            and not (present and ref in context_accounted)))
        return MaterialInventory(
            present,
            (),
            tuple(_missing_inventory_id(index) for index, _ in enumerate(missing_refs, 1)),
            missing_refs,
        )

    obligations: list[MaterialObligation] = []
    unresolved_ids: list[str] = []
    unresolved_refs: list[str] = []
    invalid_obligations: list[InvalidMaterialObligation] = []
    seen_obligation_ids: set[str] = set()
    accounted_refs: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("invalid_inventory_shape")
        if frozenset(row) != _RAW_FIELDS:
            raise ValueError("invalid_obligation_schema")

        obligation_id = row["id"]
        source_ref = row["ref"]
        quote = row["quote"]
        dimension = row["dimension"]
        requested_target_ids = row["target_ids"]
        evidence_level = row["evidence_level"]

        if not _is_opaque_id(obligation_id, maximum=MAX_OBLIGATION_ID_CHARS):
            raise ValueError("invalid_obligation_id")
        if obligation_id in seen_obligation_ids:
            raise ValueError("duplicate_obligation_id")
        seen_obligation_ids.add(obligation_id)

        if not _is_opaque_id(source_ref):
            raise ValueError("invalid_obligation_ref")
        if source_ref not in checked_sources:
            raise ValueError("foreign_source_ref")
        if source_ref in excluded:
            raise ValueError("excluded_obligation_ref")
        source_id, original = checked_sources[source_ref]

        if (
            not isinstance(quote, str)
            or not quote
            or quote != quote.strip()
            or len(quote) > MAX_QUOTE_CHARS
        ):
            raise ValueError("invalid_obligation_quote")
        literal_matches = tuple(_bounded_literal_pattern(quote).finditer(original))
        if not literal_matches and not isolate_nonliteral_quotes:
            raise ValueError("nonliteral_obligation_quote")

        if dimension not in MATERIAL_DIMENSIONS:
            raise ValueError("invalid_obligation_dimension")
        if evidence_level not in EVIDENCE_LEVELS:
            raise ValueError("invalid_evidence_level")

        if not isinstance(requested_target_ids, list):
            raise ValueError("invalid_obligation_target_ids")
        if len(requested_target_ids) > MAX_TARGET_IDS_PER_OBLIGATION:
            raise ValueError("invalid_obligation_target_ids_bounds")
        requested = _validated_id_collection(
            requested_target_ids,
            known=checked_targets,
            validator=_is_target_id,
            shape_error="invalid_obligation_target_ids",
            id_error="invalid_obligation_target_id",
            duplicate_error="duplicate_obligation_target_id",
            foreign_error="foreign_target_id",
        )
        if not literal_matches:
            invalid_obligations.append(
                InvalidMaterialObligation(
                    obligation_id=obligation_id,
                    source_ref=source_ref,
                )
            )
            accounted_refs.add(source_ref)
            unresolved_ids.append(obligation_id)
            if source_ref not in unresolved_refs:
                unresolved_refs.append(source_ref)
            continue

        triple = (source_id, quote, evidence_level)
        if len(literal_matches) == 1:
            resolved_span = (literal_matches[0].start(), literal_matches[0].end())
            eligible = tuple(
                target_id
                for target_id in requested
                if target_id in admitted and triple in checked_targets[target_id]
            )
        else:
            target_spans = {
                target_id: {
                    (anchor.focus_start, anchor.focus_end)
                    for anchor in checked_anchors.get(target_id, ())
                    if (
                        anchor.source_id,
                        anchor.focus,
                        anchor.evidence_level,
                    )
                    == triple
                }
                for target_id in requested
            }
            exact_triple_target_ids = tuple(
                target_id
                for target_id in requested
                if triple in checked_targets[target_id]
            )
            all_spans = set().union(*target_spans.values()) if target_spans else set()
            if (
                exact_triple_target_ids
                and all(target_spans[target_id] for target_id in exact_triple_target_ids)
                and len(all_spans) == 1
            ):
                resolved_span = next(iter(all_spans))
                eligible = tuple(
                    target_id
                    for target_id in requested
                    if (
                        target_id in admitted
                        and triple in checked_targets[target_id]
                        and resolved_span in target_spans[target_id]
                    )
                )
            else:
                resolved_span = None
                eligible = ()
        obligations.append(
            MaterialObligation(
                obligation_id=obligation_id,
                source_ref=source_ref,
                source_id=source_id,
                quote=quote,
                dimension=dimension,
                evidence_level=evidence_level,
                target_ids=eligible,
                quote_start=resolved_span[0] if resolved_span is not None else None,
                quote_end=resolved_span[1] if resolved_span is not None else None,
            )
        )
        accounted_refs.add(source_ref)
        if not eligible:
            unresolved_ids.append(obligation_id)
            if source_ref not in unresolved_refs:
                unresolved_refs.append(source_ref)

    missing_refs = tuple(sorted(
        source_ref
        for source_ref in checked_sources
        if source_ref not in excluded and source_ref not in accounted_refs and source_ref not in context_accounted
    ))
    for index, source_ref in enumerate(missing_refs, 1):
        unresolved_ids.append(_missing_inventory_id(index))
        if source_ref not in unresolved_refs:
            unresolved_refs.append(source_ref)

    return MaterialInventory(
        present=True,
        obligations=tuple(obligations),
        unresolved_ids=tuple(unresolved_ids),
        unresolved_refs=tuple(unresolved_refs),
        invalid_obligations=tuple(invalid_obligations),
    )


__all__ = [
    "EVIDENCE_LEVELS",
    "InvalidMaterialObligation",
    "MATERIAL_DIMENSIONS",
    "MaterialInventory",
    "MaterialObligation",
    "MaterialObligationEnumIssue",
    "apply_material_obligation_enum_patches",
    "inspect_material_obligation_enum_fields",
    "reconcile_material_obligations",
]
