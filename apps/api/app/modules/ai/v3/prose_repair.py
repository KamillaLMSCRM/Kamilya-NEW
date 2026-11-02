"""Strict, all-or-nothing application of bounded prose repair proposals."""
from typing import Any


def unchanged_context(current_source: list[str], current_references: tuple[str, ...],
                      source_snapshot: tuple[str, ...], reference_snapshot: tuple[str, ...]) -> bool:
    return tuple(current_source) == source_snapshot and tuple(current_references) == reference_snapshot


def apply_prose_repairs(original: str, parts: dict[str, str], proposal: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(proposal, dict) or set(proposal) != {"repairs"} or not isinstance(proposal["repairs"], list):
        raise ValueError("prose_repair_invalid")
    if not parts or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in parts.items()):
        raise ValueError("prose_repair_parts_invalid")
    edits: list[tuple[int, int, str]] = []
    updated: dict[str, str] = {}
    for item in proposal["repairs"]:
        if not isinstance(item, dict) or set(item) != {"id", "old", "new"}:
            raise ValueError("prose_repair_invalid")
        key, old, new = item["id"], item["old"], item["new"]
        if (not isinstance(key, str) or key not in parts or key in updated
                or not isinstance(old, str) or not old.strip() or not isinstance(new, str) or not new.strip()
                or old == new or parts[key].count(old) != 1 or original.count(old) != 1
                or original.count(parts[key]) != 1):
            raise ValueError("prose_repair_span_invalid")
        start = original.index(parts[key]) + parts[key].index(old)
        edits.append((start, start + len(old), new))
        updated[key] = parts[key].replace(old, new, 1)
    if set(updated) != set(parts):
        raise ValueError("prose_repair_ids_invalid")
    edits.sort()
    if any(edits[i][1] > edits[i + 1][0] for i in range(len(edits) - 1)):
        raise ValueError("prose_repair_overlap")
    result = original
    for start, end, replacement in reversed(edits):
        result = result[:start] + replacement + result[end:]
    return result, updated
