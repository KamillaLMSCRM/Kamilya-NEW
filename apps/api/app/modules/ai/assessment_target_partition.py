"""Pure structural partitioning for validated ordinary assessment targets.

This helper preserves source-owned component groups.  It does not validate
source truth, infer semantic equivalence, or approve assessment coverage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from copy import deepcopy
from typing import Any

MAX_PLAN_TARGETS = 96
MAX_TARGET_ID_CHARS = 100
MAX_PARTITION_CHARS = 240
_SEPARATOR_CHARS = 2


def _group_size(group: Mapping[str, Any]) -> int:
    terms = group.get("terms")
    if (
        not isinstance(terms, list)
        or not terms
        or not all(isinstance(term, str) for term in terms)
    ):
        raise ValueError("invalid_partition_component")
    return max(len(term) for term in terms)


def _component_partitions(
    components: list[Mapping[str, Any]], maximum_chars: int,
) -> list[tuple[int, int]]:
    partitions: list[tuple[int, int]] = []
    start = 0
    current_size = 0
    for index, group in enumerate(components):
        group_size = _group_size(group)
        joined_size = (
            group_size
            if index == start
            else current_size + _SEPARATOR_CHARS + group_size
        )
        if index > start and joined_size > maximum_chars:
            partitions.append((start, index))
            start = index
            current_size = group_size
        else:
            current_size = joined_size
    partitions.append((start, len(components)))
    return partitions


def _child_id(parent: Mapping[str, Any], start: int, end: int) -> str:
    components = parent["answer_components"]
    identity = {
        "parent_id": parent["id"],
        "component_indexes": list(range(start, end)),
        "components": [
            {"ref": group["ref"], "terms": group["terms"]}
            for group in components[start:end]
        ],
        "context": parent.get("context", []),
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "partition-" + hashlib.sha256(encoded).hexdigest()


def _child_source_refs(
    components: list[Mapping[str, Any]], context: Any, primary_refs: Collection[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for group in components:
        source_ref = group.get("ref")
        if isinstance(source_ref, str) and source_ref not in seen:
            seen.add(source_ref)
            ordered.append(source_ref)
    if isinstance(context, list):
        for part in context:
            source_ref = part.get("ref") if isinstance(part, dict) else None
            if isinstance(source_ref, str) and source_ref in primary_refs and source_ref not in seen:
                seen.add(source_ref)
                ordered.append(source_ref)
    return ordered


def _relink_obligations(
    obligations: Any,
    child_occurrences: Mapping[str, Mapping[tuple[str, str], list[str]]],
) -> None:
    if not isinstance(obligations, list):
        return
    for obligation in obligations:
        if not isinstance(obligation, dict) or not isinstance(
            obligation.get("target_ids"), list
        ):
            continue
        source_ref = obligation.get("ref")
        quote = obligation.get("quote")
        if not isinstance(source_ref, str) or not isinstance(quote, str):
            continue
        relinked: list[Any] = []
        for target_id in obligation["target_ids"]:
            occurrences = child_occurrences.get(target_id)
            if occurrences is None:
                relinked.append(target_id)
                continue
            matching_children = occurrences.get((source_ref, quote), [])
            if len(matching_children) == 1:
                relinked.append(matching_children[0])
        obligation["target_ids"] = relinked


def partition_operational_plan(
    plan: Mapping[str, Any],
    eligible_target_ids: Collection[str],
    maximum_chars: int = 240,
) -> dict[str, Any]:
    """Split eligible ordinary targets into bounded adjacent AND partitions."""
    if not isinstance(plan, Mapping) or not isinstance(plan.get("targets"), list):
        raise ValueError("invalid_partition_plan")
    if (
        isinstance(maximum_chars, bool)
        or not isinstance(maximum_chars, int)
        or not 1 <= maximum_chars <= MAX_PARTITION_CHARS
    ):
        raise ValueError("invalid_partition_maximum_chars")
    if isinstance(eligible_target_ids, str | bytes | Mapping) or not isinstance(
        eligible_target_ids, Collection
    ):
        raise ValueError("invalid_eligible_target_ids")
    eligible = frozenset(eligible_target_ids)
    if not all(isinstance(target_id, str) for target_id in eligible):
        raise ValueError("invalid_eligible_target_id")

    result = deepcopy(dict(plan))
    targets = result["targets"]
    if len(targets) > MAX_PLAN_TARGETS:
        raise ValueError("assessment_target_count_overflow")
    occupied_ids = {
        row.get("id")
        for row in targets
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    output: list[Any] = []
    child_ids: dict[str, list[str]] = {}
    child_occurrences: dict[str, dict[tuple[str, str], list[str]]] = {}
    for row in targets:
        if (
            not isinstance(row, dict)
            or row.get("id") not in eligible
            or row.get("construction_mode", "") != ""
            or row.get("question_format", "") != ""
            or not isinstance(row.get("answer_components"), list)
            or not row["answer_components"]
        ):
            output.append(row)
            continue
        components = row["answer_components"]
        partitions = _component_partitions(components, maximum_chars)
        if len(partitions) == 1:
            output.append(row)
            continue
        parent_occurrences: dict[tuple[str, str], list[str]] = {}
        child_ids[row["id"]] = []
        for start, end in partitions:
            child = deepcopy(row)
            child_id = _child_id(row, start, end)
            if len(child_id) > MAX_TARGET_ID_CHARS or child_id in occupied_ids:
                raise ValueError("assessment_target_id_collision")
            occupied_ids.add(child_id)
            child_ids[row["id"]].append(child_id)
            child["id"] = child_id
            child["answer_components"] = deepcopy(components[start:end])
            child["source_refs"] = _child_source_refs(
                components[start:end], row.get("context", []), row.get("source_refs", [])
            )
            output.append(child)
            for group in components[start:end]:
                source_ref = group.get("ref")
                if not isinstance(source_ref, str):
                    continue
                for term in group["terms"]:
                    parent_occurrences.setdefault((source_ref, term), []).append(child_id)
        child_occurrences[row["id"]] = parent_occurrences
    if len(output) > MAX_PLAN_TARGETS:
        raise ValueError("assessment_target_count_overflow")
    result["targets"] = output
    _relink_obligations(result.get("material_obligations"), child_occurrences)
    # A governing facet follows the complete native component union, never one
    # convenient child. Fresh parsing/audit validates every resulting owner.
    facets = result.get("qualification_facets", [])
    if not isinstance(facets, list):
        raise ValueError("invalid_partition_facets")
    for facet in facets:
        if not isinstance(facet, dict):
            raise ValueError("invalid_partition_facet")
        for field in ("target_ids", "branch_target_ids"):
            links = facet.get(field)
            if not isinstance(links, list) or any(not isinstance(link, str) for link in links):
                raise ValueError("invalid_partition_facet_links")
            facet[field] = list(dict.fromkeys(child for link in links for child in child_ids.get(link, [link])))
    return result


__all__ = ["partition_operational_plan"]
