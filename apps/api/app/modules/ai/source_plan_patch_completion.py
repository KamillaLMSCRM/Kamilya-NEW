"""Pure completion of omitted bytes in server-scoped target patches.

Completion is a transport operation only.  It copies exact held values into an
already-provided existing target row and grants no edit scope, source meaning,
or admission.
"""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from typing import Any

_TARGET_FIELDS = frozenset({
    "source_refs",
    "governing_bindings",
    "context",
    "question_format",
    "answer_components",
    "construction_mode",
    "fixed_source_context",
    "assessed_focus",
    "source_quote_proposition",
})
_BINDING_ADDITIONS = "governing_binding_additions"
_WIRE_FIELDS = _TARGET_FIELDS | {_BINDING_ADDITIONS}
_CANONICAL_DEFAULTS: dict[str, Any] = {
    "governing_bindings": [],
    "question_format": "",
    "construction_mode": "",
    "fixed_source_context": None,
    "assessed_focus": "",
    "source_quote_proposition": None,
}


def _row_inventory(rows: Any) -> dict[str, dict[str, Any]] | None:
    if not isinstance(rows, list):
        return None
    inventory: dict[str, dict[str, Any]] = {}
    for row in rows:
        target_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(target_id, str) or not target_id or target_id in inventory:
            return None
        inventory[target_id] = row
    return inventory


def _operation_inventory(
    operations: Any,
    held_ids: set[str],
) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(operations, list):
        return None
    inventory: dict[str, tuple[str, ...]] = {}
    for operation in operations:
        target_id = operation.get("target_id") if isinstance(operation, dict) else None
        fields = operation.get("repair_fields") if isinstance(operation, dict) else None
        if (
            not isinstance(target_id, str)
            or not target_id
            or target_id not in held_ids
            or target_id in inventory
            or not isinstance(fields, list)
            or any(not isinstance(field, str) or field not in _WIRE_FIELDS for field in fields)
            or len(fields) != len(set(fields))
        ):
            return None
        inventory[target_id] = tuple(fields)
    return inventory


def _admitted_ids(value: Any) -> set[str] | None:
    if isinstance(value, str | bytes) or not isinstance(value, Collection):
        return None
    rows = list(value)
    if any(not isinstance(row, str) or not row for row in rows) or len(rows) != len(set(rows)):
        return None
    return set(rows)


def complete_scoped_target_patches(
    payload: Any,
    *,
    held_targets: Any,
    repair_operations: Any,
    admitted_target_ids: Collection[str] = (),
) -> Any:
    """Copy omitted permitted fields from held targets into a detached payload.

    Malformed or ambiguous inventories cause total abstention.  Valid foreign,
    new, admitted, or unscoped rows remain byte-for-byte unchanged so downstream
    authority and schema validators retain their existing failure behavior.
    """

    completed = deepcopy(payload)
    if not isinstance(completed, dict):
        return completed
    proposed = _row_inventory(completed.get("targets"))
    held = _row_inventory(held_targets)
    admitted = _admitted_ids(admitted_target_ids)
    if proposed is None or held is None or admitted is None:
        return completed
    operations = _operation_inventory(repair_operations, set(held))
    if operations is None:
        return completed

    for target_id, row in proposed.items():
        if target_id not in held or target_id not in operations or target_id in admitted:
            continue
        original = held[target_id]
        for field in operations[target_id]:
            if field in row:
                continue
            if field == _BINDING_ADDITIONS:
                if "governing_bindings" not in row:
                    row[field] = []
                continue
            if field in original:
                row[field] = deepcopy(original[field])
            elif field in _CANONICAL_DEFAULTS:
                row[field] = deepcopy(_CANONICAL_DEFAULTS[field])
    return completed
