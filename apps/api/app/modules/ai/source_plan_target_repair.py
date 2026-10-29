"""Post-response identity custody for source-plan structural repair.

Unknown model target IDs are transport handles only. An unknown handle receives
a canonical ``new-*`` ID exclusively when existing held obligations prove one
unambiguous invalid parent. This module does not validate source meaning, carry
audit votes, grant coverage, or admit a target.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

MAX_TARGETS = 96
MAX_OBLIGATIONS = 1152
MAX_ID_CHARS = 192
_POLICY = "source-plan-repair-lineage-v1"


@dataclass(frozen=True)
class RepairAlias:
    raw_target_id: str
    canonical_target_id: str
    parent_target_id: str
    obligation_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParentRepairLineage:
    parent_target_id: str
    response_target_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]


@dataclass(frozen=True)
class RejectedRepairIdentity:
    raw_target_id: str
    obligation_ids: tuple[str, ...]
    parent_target_ids: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class RepairIdentityCanonicalization:
    response: dict[str, Any]
    aliases: tuple[RepairAlias, ...]
    parents: tuple[ParentRepairLineage, ...]
    rejected: tuple[RejectedRepairIdentity, ...]
    rejected_obligation_ids: tuple[str, ...]


def _identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_ID_CHARS
        and value == value.strip()
        and value.isascii()
        and value[0].isalnum()
        and all(character.isalnum() or character in ":._-" for character in value)
    )


def _rows(value: Any, *, maximum: int, error: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(error)
    return value


def _ids(value: Any, *, maximum: int, error: str) -> tuple[str, ...]:
    if (
        isinstance(value, str | bytes | Mapping)
        or not isinstance(value, Sequence)
        or not 1 <= len(value) <= maximum
    ):
        raise ValueError(error)
    result = tuple(value)
    if any(not _identifier(item) for item in result) or len(set(result)) != len(result):
        raise ValueError(error)
    return result


def _indexed_rows(
    rows: Sequence[Mapping[str, Any]], *, maximum: int, error: str,
) -> dict[str, Mapping[str, Any]]:
    if len(rows) > maximum:
        raise ValueError(error)
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not _identifier(row.get("id")) or row["id"] in indexed:
            raise ValueError(error)
        indexed[row["id"]] = row
    return indexed


def _alias(parent_target_id: str, obligation_ids: tuple[str, ...]) -> str:
    identity = {
        "policy": _POLICY,
        "parent_target_id": parent_target_id,
        "obligation_ids": list(obligation_ids),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return "new-" + hashlib.sha256(encoded).hexdigest()[:32]


def canonicalize_repair_child_ids(
    *,
    held_targets: Sequence[Mapping[str, Any]],
    held_inventory: Sequence[Mapping[str, Any]],
    invalid_parent_ids: Sequence[str],
    response: Mapping[str, Any],
    reserved_target_ids: Sequence[str],
) -> RepairIdentityCanonicalization:
    """Canonicalize only unknown IDs with exclusive held-obligation lineage.

    Malformed or ambiguous identities remain unchanged in the returned copy and
    are reported as rejected. Root must exclude them and independently validate
    every reported parent cohort before the mandatory fresh whole-plan audit.
    """

    held_target_by_id = _indexed_rows(
        tuple(held_targets), maximum=MAX_TARGETS,
        error="source_plan_repair_invalid_held_targets",
    )
    held_obligation_by_id = _indexed_rows(
        tuple(held_inventory), maximum=MAX_OBLIGATIONS,
        error="source_plan_repair_invalid_held_inventory",
    )
    invalid = _ids(
        invalid_parent_ids, maximum=MAX_TARGETS,
        error="source_plan_repair_invalid_parent_ids",
    )
    reserved = _ids(
        reserved_target_ids, maximum=MAX_TARGETS * 2,
        error="source_plan_repair_invalid_reserved_ids",
    )
    if not set(invalid) <= set(held_target_by_id) or not set(held_target_by_id) <= set(reserved):
        raise ValueError("source_plan_repair_invalid_identity_scope")
    if not isinstance(response, Mapping):
        raise ValueError("source_plan_repair_invalid_response")
    response_targets = _rows(
        response.get("targets"), maximum=MAX_TARGETS * 2,
        error="source_plan_repair_invalid_response_targets",
    )
    response_obligations = _rows(
        response.get("material_obligations"), maximum=MAX_OBLIGATIONS,
        error="source_plan_repair_invalid_response_inventory",
    )

    copied = deepcopy(dict(response))
    copied_targets = copied["targets"]
    copied_obligations = copied["material_obligations"]
    target_counts: Counter[str] = Counter()
    target_indexes: dict[str, list[int]] = defaultdict(list)
    malformed_target_rows = False
    for index, row in enumerate(response_targets):
        if not isinstance(row, Mapping) or not _identifier(row.get("id")):
            malformed_target_rows = True
            continue
        target_counts[row["id"]] += 1
        target_indexes[row["id"]].append(index)

    obligation_counts: Counter[str] = Counter()
    child_obligations: dict[str, set[str]] = defaultdict(set)
    child_errors: dict[str, set[str]] = defaultdict(set)
    rejected_obligations: set[str] = set()
    unknown_ids = {target_id for target_id in target_counts if target_id not in reserved}
    for row in response_obligations:
        if not isinstance(row, Mapping) or not _identifier(row.get("id")):
            continue
        obligation_id = row["id"]
        obligation_counts[obligation_id] += 1
        links = row.get("target_ids")
        linked_unknown = {
            target_id for target_id in links
            if isinstance(target_id, str) and target_id in unknown_ids
        } if isinstance(links, list) else set()
        if obligation_id not in held_obligation_by_id:
            rejected_obligations.add(obligation_id)
            for target_id in linked_unknown:
                child_errors[target_id].add("new_obligation_id")
            continue
        for target_id in linked_unknown:
            child_obligations[target_id].add(obligation_id)
        if (
            not isinstance(links, list)
            or not links
            or any(not _identifier(target_id) for target_id in links)
            or len(set(links)) != len(links)
        ):
            rejected_obligations.add(obligation_id)
            for target_id in linked_unknown:
                child_errors[target_id].add("invalid_obligation_links")
            continue
        if len(links) != 1:
            rejected_obligations.add(obligation_id)
            for target_id in linked_unknown:
                child_errors[target_id].add("shared_obligation_link")
            continue
    aliases: list[RepairAlias] = []
    occupied = set(reserved)
    rejected: list[RejectedRepairIdentity] = []
    for raw_target_id in target_counts:
        if raw_target_id not in unknown_ids:
            continue
        obligations = tuple(sorted(child_obligations.get(raw_target_id, set())))
        errors = child_errors[raw_target_id]
        if target_counts[raw_target_id] != 1:
            errors.add("duplicate_target_id")
        if not obligations:
            errors.add("missing_held_obligation_lineage")
        if any(obligation_counts[obligation_id] != 1 for obligation_id in obligations):
            errors.add("duplicate_obligation_id")
        parents: set[str] = set()
        for obligation_id in obligations:
            held_links = held_obligation_by_id[obligation_id].get("target_ids")
            if (
                not isinstance(held_links, list)
                or len(held_links) != 1
                or held_links[0] not in invalid
            ):
                errors.add("nonexclusive_held_obligation_owner")
                continue
            parents.add(held_links[0])
        if len(parents) != 1:
            errors.add("ambiguous_parent_lineage")
        if errors:
            rejected.append(RejectedRepairIdentity(
                raw_target_id, obligations, tuple(sorted(parents)), tuple(sorted(errors)),
            ))
            rejected_obligations.update(obligations)
            continue
        parent_target_id = next(iter(parents))
        canonical_target_id = _alias(parent_target_id, obligations)
        if canonical_target_id in occupied:
            rejected.append(RejectedRepairIdentity(
                raw_target_id, obligations, (parent_target_id,), ("canonical_alias_collision",),
            ))
            rejected_obligations.update(obligations)
            continue
        occupied.add(canonical_target_id)
        aliases.append(RepairAlias(
            raw_target_id, canonical_target_id, parent_target_id, obligations,
        ))

    alias_by_raw = {alias.raw_target_id: alias.canonical_target_id for alias in aliases}
    for raw_target_id, canonical_target_id in alias_by_raw.items():
        copied_targets[target_indexes[raw_target_id][0]]["id"] = canonical_target_id
    for index, row in enumerate(response_obligations):
        if not isinstance(row, Mapping) or not isinstance(row.get("target_ids"), list):
            continue
        copied_obligations[index]["target_ids"] = [
            alias_by_raw.get(target_id, target_id) for target_id in row["target_ids"]
        ]

    parent_targets: dict[str, list[str]] = {parent: [] for parent in invalid}
    parent_obligations: dict[str, set[str]] = {parent: set() for parent in invalid}
    for row in copied_targets:
        copied_id = row.get("id") if isinstance(row, Mapping) else None
        if isinstance(copied_id, str) and copied_id in parent_targets:
            parent_targets[copied_id].append(copied_id)
    for alias in aliases:
        parent_targets[alias.parent_target_id].append(alias.canonical_target_id)
        parent_obligations[alias.parent_target_id].update(alias.obligation_ids)
    rejected_raw_ids = {row.raw_target_id for row in rejected}
    for row in response_obligations:
        if not isinstance(row, Mapping) or row.get("id") not in held_obligation_by_id:
            continue
        obligation_id = row["id"]
        links = row.get("target_ids")
        held_links = held_obligation_by_id[obligation_id].get("target_ids")
        if (
            obligation_id in rejected_obligations
            or not isinstance(links, list)
            or len(links) != 1
            or links[0] in rejected_raw_ids
            or not isinstance(held_links, list)
            or len(held_links) != 1
            or held_links[0] not in parent_targets
        ):
            continue
        expected_parent = held_links[0]
        canonical_link = alias_by_raw.get(links[0], links[0])
        if canonical_link in parent_targets[expected_parent]:
            parent_obligations[expected_parent].add(obligation_id)
        elif links[0] in reserved:
            rejected_obligations.add(obligation_id)

    if malformed_target_rows:
        rejected.append(RejectedRepairIdentity("", (), (), ("malformed_target_row",)))
    parent_lineages = tuple(ParentRepairLineage(
        parent,
        tuple(dict.fromkeys(parent_targets[parent])),
        tuple(sorted(parent_obligations[parent])),
    ) for parent in invalid)
    return RepairIdentityCanonicalization(
        response=copied,
        aliases=tuple(aliases),
        parents=parent_lineages,
        rejected=tuple(rejected),
        rejected_obligation_ids=tuple(sorted(rejected_obligations)),
    )


def repair_identity_receipt(
    result: RepairIdentityCanonicalization,
) -> dict[str, Any]:
    """Rebuild the transport-identity audit receipt from typed custody output."""

    if not isinstance(result, RepairIdentityCanonicalization):
        raise ValueError("source_plan_repair_invalid_identity_result")
    body = {
        "policy": _POLICY,
        "aliases": [
            {
                "raw_target_id": row.raw_target_id,
                "canonical_target_id": row.canonical_target_id,
                "parent_target_id": row.parent_target_id,
                "obligation_ids": list(row.obligation_ids),
            }
            for row in result.aliases
        ],
        "parents": [
            {
                "parent_target_id": row.parent_target_id,
                "response_target_ids": list(row.response_target_ids),
                "obligation_ids": list(row.obligation_ids),
            }
            for row in result.parents
        ],
        "rejected": [
            {
                "raw_target_id": row.raw_target_id,
                "obligation_ids": list(row.obligation_ids),
                "parent_target_ids": list(row.parent_target_ids),
                "errors": list(row.errors),
            }
            for row in result.rejected
        ],
        "rejected_obligation_ids": list(result.rejected_obligation_ids),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return {**body, "identity_sha256": hashlib.sha256(encoded).hexdigest()}


__all__ = [
    "ParentRepairLineage",
    "RejectedRepairIdentity",
    "RepairAlias",
    "RepairIdentityCanonicalization",
    "canonicalize_repair_child_ids",
    "repair_identity_receipt",
]
