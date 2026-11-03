"""Pure append-only compiler for scoped source-plan binding repair candidates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, NoReturn


class SourcePlanBindingPatchError(ValueError):
    """The candidate patch cannot be compiled without changing binding custody."""


def _fail(code: str) -> NoReturn:
    raise SourcePlanBindingPatchError("source_plan_binding_patch_" + code)


def _target_inventory(rows: Any, *, owner: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        _fail(owner + "_targets_invalid")
    inventory: dict[str, dict[str, Any]] = {}
    for row in rows:
        target_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(target_id, str) or not target_id:
            _fail(owner + "_target_invalid")
        if target_id in inventory:
            _fail(owner + "_target_duplicate")
        inventory[target_id] = row
    return inventory


def compile_append_only_binding_patch(
    payload: dict[str, Any],
    *,
    held_targets: list[dict[str, Any]],
    permitted_target_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Compile candidate additions onto exact held prefixes without semantic inference."""

    if not isinstance(payload, dict):
        _fail("payload_invalid")
    held = _target_inventory(held_targets, owner="held")
    proposed = _target_inventory(payload.get("targets"), owner="payload")
    if (
        not isinstance(permitted_target_ids, tuple)
        or any(not isinstance(target_id, str) or not target_id for target_id in permitted_target_ids)
        or len(set(permitted_target_ids)) != len(permitted_target_ids)
        or not set(permitted_target_ids) <= set(held)
    ):
        _fail("permitted_targets_invalid")
    permitted = set(permitted_target_ids)
    compiled = deepcopy(payload)
    compiled_by_id = {row["id"]: row for row in compiled["targets"]}

    for target_id, row in proposed.items():
        has_alias = "governing_binding_additions" in row
        has_canonical = "governing_bindings" in row
        if has_alias and has_canonical:
            _fail("ambiguous_binding_fields")
        if target_id not in permitted:
            if has_alias:
                _fail("unpermitted_additions")
            continue
        if not has_alias or has_canonical:
            _fail("permitted_additions_required")
        additions = row["governing_binding_additions"]
        if not isinstance(additions, list) or any(not isinstance(item, dict) for item in additions):
            _fail("additions_invalid")
        old = held[target_id].get("governing_bindings", [])
        if not isinstance(old, list) or any(not isinstance(item, dict) for item in old):
            _fail("held_bindings_invalid")
        bindings = deepcopy(old)
        for addition in additions:
            if addition not in bindings:
                bindings.append(deepcopy(addition))
        compiled_row = compiled_by_id[target_id]
        del compiled_row["governing_binding_additions"]
        compiled_row["governing_bindings"] = bindings
    return compiled
