"""Compile opaque selections from exact components of held ordinary targets.

This module can catalogue only text that already
exists in a held plan and decode opaque catalogue identifiers back into the
same canonical ``answer_components`` shape.  It does not infer, complete, or
approve source content.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from app.modules.ai.assessment_components import MAX_COMPONENT_TEXT_CHARS
from app.modules.ai.source_coordinator_boundary import prove_source_coordinator_boundary
from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

COMPONENT_SELECTION_POLICY = "held-source-component-selection-v2"
MAX_CATALOG_TARGETS = 96
MAX_COMPONENT_GROUPS = 12
MAX_TERMS_PER_GROUP = 8
_SUBSTANTIVE_AFTER_SENTENCE = re.compile(
    rf"[.!?…][{re.escape(SOURCE_HORIZONTAL_SPACE)}]+[^\W\d_]",
    flags=re.UNICODE,
)


class ComponentSelectionError(ValueError):
    """The held catalogue or an opaque component selection is not trustworthy."""


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _scope_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ComponentSelectionError(f"component_selection_{label}_shape")
    if any(not isinstance(item, str) or not item for item in value):
        raise ComponentSelectionError(f"component_selection_{label}_shape")
    if len(set(value)) != len(value):
        raise ComponentSelectionError(f"component_selection_duplicate_{label}")
    return value


def _held_index(held_targets: object) -> dict[str, dict[str, Any]]:
    if not isinstance(held_targets, list) or len(held_targets) > MAX_CATALOG_TARGETS:
        raise ComponentSelectionError("component_selection_held_target_bounds")
    indexed: dict[str, dict[str, Any]] = {}
    for target in held_targets:
        if not isinstance(target, dict):
            raise ComponentSelectionError("component_selection_held_target_shape")
        target_id = target.get("id")
        if not isinstance(target_id, str) or not target_id:
            raise ComponentSelectionError("component_selection_held_target_identity")
        if target_id in indexed:
            raise ComponentSelectionError("component_selection_duplicate_held_target")
        indexed[target_id] = target
    return indexed


def _source_index(sources: object) -> dict[str, str]:
    if not isinstance(sources, dict) or any(
        not isinstance(ref, str)
        or not ref
        or not isinstance(text, str)
        or not text
        for ref, text in sources.items()
    ):
        raise ComponentSelectionError("component_selection_source_shape")
    return sources


def _eligible_owner_entries(
    target: dict[str, Any],
    *,
    sources: dict[str, str],
    scope_sha256: str,
) -> list[dict[str, Any]] | None:
    if target.get("construction_mode") != "" or "construction_mode" not in target:
        return None
    source_refs = target.get("source_refs")
    if (
        not isinstance(source_refs, list)
        or not source_refs
        or any(not isinstance(ref, str) or not ref for ref in source_refs)
        or len(set(source_refs)) != len(source_refs)
    ):
        return None
    owned_refs = set(source_refs)
    components = target.get("answer_components")
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENT_GROUPS:
        return None

    target_id = target["id"]
    owner_entries: list[dict[str, Any]] = []
    seen_literals: set[tuple[str, str]] = set()
    for component_index, component in enumerate(components):
        if not isinstance(component, dict):
            return None
        ref = component.get("ref")
        terms = component.get("terms")
        if (
            not isinstance(ref, str)
            or ref not in sources
            or ref not in owned_refs
            or not isinstance(terms, list)
            or not 1 <= len(terms) <= MAX_TERMS_PER_GROUP
        ):
            return None
        source = sources[ref]
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        stripped_lines = tuple(line.strip() for line in source.split("\n"))
        for term_index, quote in enumerate(terms):
            if (
                not isinstance(quote, str)
                or not quote
                or quote != quote.strip()
                or len(quote) > MAX_COMPONENT_TEXT_CHARS
                or (ref, quote) in seen_literals
            ):
                return None
            start = source.find(quote)
            if (
                start < 0
                or start != source.rfind(quote)
                or not any(quote in line for line in stripped_lines)
            ):
                return None
            seen_literals.add((ref, quote))
            end = start + len(quote)
            identity = {
                "policy": COMPONENT_SELECTION_POLICY,
                "scope_sha256": scope_sha256,
                "source_sha256": source_sha256,
                "target_id": target_id,
                "ref": ref,
                "component_index": component_index,
                "term_index": term_index,
                "quote": quote,
                "start": start,
                "end": end,
            }
            owner_entries.append(
                {
                    "id": _sha256(identity),
                    "target_id": target_id,
                    "ref": ref,
                    "component_index": component_index,
                    "term_index": term_index,
                    "quote": quote,
                    "start": start,
                    "end": end,
                    "source_sha256": source_sha256,
                }
            )
    return owner_entries


def _eligible_completion_entry(
    target: dict[str, Any],
    *,
    held_targets: list[dict[str, Any]],
    sources: dict[str, str],
    scope_sha256: str,
) -> dict[str, Any] | None:
    """Return one literal same-line completion proved from the original source.

    A terminal punctuation mark followed by another letter conservatively
    abstains.  This can reject abbreviations, but it cannot merge a second
    sentence into one assessment decision through semantic guesswork.
    """

    if (
        target.get("construction_mode") != ""
        or "construction_mode" not in target
        or target.get("question_format", "") != ""
    ):
        return None
    source_refs = target.get("source_refs")
    if (
        not isinstance(source_refs, list)
        or not source_refs
        or any(not isinstance(ref, str) or not ref for ref in source_refs)
        or len(set(source_refs)) != len(source_refs)
    ):
        return None
    components = target.get("answer_components")
    if not isinstance(components, list) or len(components) != 1:
        return None
    component = components[0]
    if not isinstance(component, dict):
        return None
    ref = component.get("ref")
    terms = component.get("terms")
    if (
        not isinstance(ref, str)
        or ref not in source_refs
        or ref not in sources
        or not isinstance(terms, list)
        or len(terms) != 1
    ):
        return None
    held_component = terms[0]
    if (
        not isinstance(held_component, str)
        or not held_component
        or held_component != held_component.strip()
        or "\r" in held_component
        or "\n" in held_component
        or len(held_component) > MAX_COMPONENT_TEXT_CHARS
    ):
        return None
    source = sources[ref]
    if source.find(held_component) < 0 or source.find(held_component) != source.rfind(held_component):
        return None
    boundary = prove_source_coordinator_boundary(source, held_component)
    if boundary is None:
        return None
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if (
        boundary.source_sha256 != source_sha256
        or source[boundary.component_start:boundary.component_end] != held_component
        or boundary.physical_line_end <= boundary.component_end
    ):
        return None
    complete = source[boundary.component_start:boundary.physical_line_end]
    if (
        not complete
        or complete == held_component
        or complete != complete.strip()
        or "\r" in complete
        or "\n" in complete
        or len(complete) > MAX_COMPONENT_TEXT_CHARS
        or source.find(complete) != boundary.component_start
        or source.rfind(complete) != boundary.component_start
        or _SUBSTANTIVE_AFTER_SENTENCE.search(boundary.raw_tail) is not None
    ):
        return None
    for peer in held_targets:
        if peer["id"] == target["id"]:
            continue
        peer_components = peer.get("answer_components")
        if not isinstance(peer_components, list):
            continue
        for peer_component in peer_components:
            if not isinstance(peer_component, dict) or peer_component.get("ref") != ref:
                continue
            peer_terms = peer_component.get("terms")
            if not isinstance(peer_terms, list):
                continue
            for peer_term in peer_terms:
                if not isinstance(peer_term, str) or not peer_term:
                    continue
                cursor = 0
                while (position := source.find(peer_term, cursor)) >= 0:
                    if position < boundary.physical_line_end and position + len(peer_term) > boundary.component_start:
                        return None
                    cursor = position + 1
    boundary_identity = {
        "source_sha256": boundary.source_sha256,
        "component_start": boundary.component_start,
        "component_end": boundary.component_end,
        "physical_line_end": boundary.physical_line_end,
        "raw_tail": boundary.raw_tail,
        "separator_start": boundary.separator_start,
        "separator_end": boundary.separator_end,
        "separator_quote": boundary.separator_quote,
        "punctuation_offset": boundary.punctuation_offset,
        "punctuation_owner": boundary.punctuation_owner,
    }
    identity = {
        "policy": COMPONENT_SELECTION_POLICY,
        "scope_sha256": scope_sha256,
        "kind": "source_completion",
        "held_target_sha256": _sha256(target),
        "source_sha256": source_sha256,
        "target_id": target["id"],
        "ref": ref,
        "old_component": held_component,
        "quote": complete,
        "start": boundary.component_start,
        "end": boundary.physical_line_end,
        "boundary": boundary_identity,
    }
    return {
        "id": _sha256(identity),
        "kind": "source_completion",
        "target_id": target["id"],
        "ref": ref,
        "component_index": 0,
        "term_index": 0,
        "quote": complete,
        "start": boundary.component_start,
        "end": boundary.physical_line_end,
        "source_sha256": source_sha256,
    }


def build_held_component_catalog(
    held_targets: list[dict[str, Any]],
    sources: dict[str, str],
    permitted_target_ids: tuple[str, ...],
    admitted_target_ids: tuple[str, ...] = (),
    completion_target_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return an opaque catalogue of exact, source-local held components.

    A malformed component abstains its entire target owner.  Malformed global
    identity or scope is an error because it would make opaque ownership
    ambiguous.
    """

    indexed = _held_index(held_targets)
    source_index = _source_index(sources)
    permitted = _scope_tuple(permitted_target_ids, label="permitted_scope")
    admitted = _scope_tuple(admitted_target_ids, label="admitted_scope")
    completion = _scope_tuple(completion_target_ids, label="completion_scope")
    if any(target_id not in indexed for target_id in (*permitted, *admitted)):
        raise ComponentSelectionError("component_selection_unknown_scope_target")
    if not set(completion) <= set(permitted):
        raise ComponentSelectionError("component_selection_invalid_completion_scope")
    for target_id in completion:
        target = indexed[target_id]
        if (
            target_id in admitted
            or target.get("construction_mode") != ""
            or "construction_mode" not in target
        ):
            raise ComponentSelectionError("component_selection_invalid_completion_scope")

    scope_body = {
        "policy": COMPONENT_SELECTION_POLICY,
        "held_targets": held_targets,
        "sources": sources,
        "permitted_target_ids": permitted,
        "admitted_target_ids": admitted,
        "completion_target_ids": completion,
    }
    scope_sha256 = _sha256(scope_body)
    permitted_set = set(permitted)
    admitted_set = set(admitted)
    completion_set = set(completion)
    entries: list[dict[str, Any]] = []
    for target in held_targets:
        target_id = target["id"]
        if target_id not in permitted_set or target_id in admitted_set:
            continue
        if target_id in completion_set:
            completion_entry = _eligible_completion_entry(
                target,
                held_targets=held_targets,
                sources=source_index,
                scope_sha256=scope_sha256,
            )
            if completion_entry is not None:
                entries.append(completion_entry)
        else:
            owner_entries = _eligible_owner_entries(
                target,
                sources=source_index,
                scope_sha256=scope_sha256,
            )
            if owner_entries is not None:
                entries.extend(owner_entries)

    entry_ids = [entry["id"] for entry in entries]
    if len(set(entry_ids)) != len(entry_ids):
        raise ComponentSelectionError("component_selection_duplicate_catalog_id")
    catalog_body = {
        "policy": COMPONENT_SELECTION_POLICY,
        "scope_sha256": scope_sha256,
        "entries": entries,
    }
    return {**catalog_body, "catalog_sha256": _sha256(catalog_body)}


def _selection_rows(payload: object) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return None
    if not any(
        isinstance(target, dict) and "answer_component_selections" in target
        for target in targets
    ):
        return None
    if any(not isinstance(target, dict) for target in targets):
        raise ComponentSelectionError("component_selection_target_shape")
    return targets


def compile_component_selections(
    payload: dict[str, Any],
    *,
    held_targets: list[dict[str, Any]],
    sources: dict[str, str],
    permitted_target_ids: tuple[str, ...],
    admitted_target_ids: tuple[str, ...] = (),
    completion_target_ids: tuple[str, ...] = (),
    catalog: dict[str, Any],
) -> dict[str, Any]:
    """Decode explicit opaque selections into canonical answer components only."""

    compiled = deepcopy(payload)
    target_rows = _selection_rows(compiled)
    if target_rows is None:
        return compiled

    rebuilt = build_held_component_catalog(
        held_targets,
        sources,
        permitted_target_ids,
        admitted_target_ids,
        completion_target_ids,
    )
    if not isinstance(catalog, dict) or catalog != rebuilt:
        raise ComponentSelectionError("component_selection_stale_catalog")

    held = _held_index(held_targets)
    permitted = set(_scope_tuple(permitted_target_ids, label="permitted_scope"))
    admitted = set(_scope_tuple(admitted_target_ids, label="admitted_scope"))
    completion = set(_scope_tuple(completion_target_ids, label="completion_scope"))
    entries = {entry["id"]: entry for entry in rebuilt["entries"]}
    row_ids: list[str] = []
    for row in target_rows:
        target_id = row.get("id")
        if not isinstance(target_id, str) or not target_id:
            raise ComponentSelectionError("component_selection_target_identity")
        row_ids.append(target_id)
    if len(set(row_ids)) != len(row_ids):
        raise ComponentSelectionError("component_selection_duplicate_target")

    for row in target_rows:
        if "answer_component_selections" not in row:
            continue
        target_id = row["id"]
        held_target = held.get(target_id)
        if held_target is None:
            raise ComponentSelectionError("component_selection_new_target")
        if target_id not in permitted:
            raise ComponentSelectionError("component_selection_unpermitted_target")
        if target_id in admitted:
            raise ComponentSelectionError("component_selection_admitted_target")
        if held_target.get("construction_mode") != "" or "construction_mode" not in held_target:
            raise ComponentSelectionError("component_selection_typed_target")
        if "answer_components" in row:
            raise ComponentSelectionError("component_selection_alias_raw_dual")

        selections = row["answer_component_selections"]
        if not isinstance(selections, list) or not 1 <= len(selections) <= MAX_COMPONENT_GROUPS:
            raise ComponentSelectionError("component_selection_group_bounds")
        if target_id in completion and (
            len(selections) != 1
            or not isinstance(selections[0], dict)
            or set(selections[0]) != {"candidate_ids"}
            or not isinstance(selections[0]["candidate_ids"], list)
            or len(selections[0]["candidate_ids"]) != 1
        ):
            raise ComponentSelectionError("component_selection_completion_selection_shape")
        decoded: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for group in selections:
            if not isinstance(group, dict) or set(group) != {"candidate_ids"}:
                raise ComponentSelectionError("component_selection_group_shape")
            candidate_ids = group["candidate_ids"]
            if (
                not isinstance(candidate_ids, list)
                or not 1 <= len(candidate_ids) <= MAX_TERMS_PER_GROUP
                or any(not isinstance(candidate_id, str) or not candidate_id for candidate_id in candidate_ids)
                or len(set(candidate_ids)) != len(candidate_ids)
            ):
                raise ComponentSelectionError("component_selection_candidate_bounds")
            if any(candidate_id in seen_ids for candidate_id in candidate_ids):
                raise ComponentSelectionError("component_selection_duplicate_candidate")
            selected_entries: list[dict[str, Any]] = []
            for candidate_id in candidate_ids:
                entry = entries.get(candidate_id)
                if entry is None:
                    raise ComponentSelectionError("component_selection_unknown_id")
                if entry["target_id"] != target_id:
                    raise ComponentSelectionError("component_selection_cross_owner")
                if target_id in completion and entry.get("kind") != "source_completion":
                    raise ComponentSelectionError("component_selection_completion_candidate_kind")
                selected_entries.append(entry)
                seen_ids.add(candidate_id)
            refs = {entry["ref"] for entry in selected_entries}
            if len(refs) != 1:
                raise ComponentSelectionError("component_selection_cross_ref")
            decoded.append(
                {
                    "ref": selected_entries[0]["ref"],
                    "terms": [entry["quote"] for entry in selected_entries],
                }
            )
        del row["answer_component_selections"]
        row["answer_components"] = decoded
    return compiled
