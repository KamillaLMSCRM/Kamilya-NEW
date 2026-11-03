"""Pure target lineage over trusted compiler coordinates, never effect approval."""

from __future__ import annotations

import hashlib
import json
from typing import Any

POLICY = "source-target-coordinates-v1"
_FIELDS = {"target_id", "owner", "role", "anchor"}
_ROLES = {"decision", "checklist", "action", "purpose", "branch"}
_MAX_RECORDS = 4096
_MAX_STRING = 256


class TargetCoordinatesError(ValueError):
    """Malformed coordinate declarations cannot establish lineage."""


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _groups(records: Any) -> dict[tuple[str, str], dict[str, dict[str, str]]]:
    if not isinstance(records, list) or len(records) > _MAX_RECORDS:
        raise TargetCoordinatesError("source_target_coordinates_records")
    groups: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    identifiers: set[str] = set()
    for row in records:
        if (not isinstance(row, dict) or set(row) != _FIELDS
                or any(not isinstance(value, str) or not value.strip() or len(value) > _MAX_STRING
                       for value in row.values())):
            raise TargetCoordinatesError("source_target_coordinates_record")
        try:
            for value in row.values():
                value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TargetCoordinatesError("source_target_coordinates_record") from exc
        if row["role"] not in _ROLES:
            raise TargetCoordinatesError("source_target_coordinates_role")
        if row["target_id"] in identifiers:
            raise TargetCoordinatesError("source_target_coordinates_duplicate_id")
        identifiers.add(row["target_id"])
        group = groups.setdefault((row["owner"], row["role"]), {})
        if row["anchor"] in group:
            raise TargetCoordinatesError("source_target_coordinates_duplicate_anchor")
        group[row["anchor"]] = row
    return groups


def match_target_coordinates(before: Any, after: Any) -> dict[str, Any]:
    """Match identity separately from effect, abstaining on ambiguous survivors.

    Exact unique anchors survive neutral reordering. An owner-role singleton
    transition establishes only lineage; it never proves equivalent meaning.
    """
    old_groups, new_groups = _groups(before), _groups(after)
    matches: list[dict[str, str]] = []
    unresolved_old: list[str] = []
    unresolved_new: list[str] = []
    removed_old: list[str] = []
    added_new: list[str] = []
    for key in sorted(old_groups.keys() | new_groups.keys()):
        old = old_groups.get(key, {})
        new = new_groups.get(key, {})
        common = old.keys() & new.keys()
        for anchor in common:
            matches.append({"old_target_id": old[anchor]["target_id"], "new_target_id": new[anchor]["target_id"],
                            "method": "exact_anchor"})
        remaining_old = [row["target_id"] for anchor, row in old.items() if anchor not in common]
        remaining_new = [row["target_id"] for anchor, row in new.items() if anchor not in common]
        if len(remaining_old) == len(remaining_new) == 1:
            matches.append({"old_target_id": remaining_old[0], "new_target_id": remaining_new[0], "method": "singleton"})
        elif remaining_old and remaining_new:
            unresolved_old.extend(remaining_old)
            unresolved_new.extend(remaining_new)
        else:
            removed_old.extend(remaining_old)
            added_new.extend(remaining_new)
    record = {"policy": POLICY, "before_sha256": _hash(before), "after_sha256": _hash(after),
              "matches": sorted(matches, key=lambda row: (row["old_target_id"], row["new_target_id"])),
              "unresolved_old": sorted(unresolved_old), "unresolved_new": sorted(unresolved_new),
              "removed_old": sorted(removed_old), "added_new": sorted(added_new), "semantic_approval": False}
    return {**record, "receipt_sha256": _hash(record)}
