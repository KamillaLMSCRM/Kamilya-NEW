"""Pure restricted patch materializer for an unapproved typed-frame graph.

This intentionally is not an RFC 6902 implementation. It accepts only the
request-scoped operations owned by the LOCAL compiler-recovery contract.
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from app.modules.ai.source_assessment_graph import SourceGraphError

_MAX_OPERATIONS = 64
_MAX_PAYLOAD_BYTES = 256 * 1024
_MAX_DEPTH = 8
_MAX_NODES = 12_000
_MAX_STRING_CHARS = 65_536
_MAX_FRAMES = 96
_MAX_QUALIFIERS = 96

_FRAME_FIELDS = {
    "handle",
    "kind",
    "ref",
    "label",
    "context",
    "bindings",
    "dimension",
    "answer",
    "owner",
    "leaves",
    "fork",
    "action",
    "purposes",
    "branches",
}
_QUALIFIER_FIELDS = {"handle", "ref", "quote", "role", "effect"}
_INDEX = re.compile(r"0|[1-9][0-9]*")


def _raise(code: str) -> None:
    raise SourceGraphError(code)


def _validate_json(value: Any) -> None:
    nodes = 0
    active: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            _raise("invalid_frame_patch_resources")
        if isinstance(item, str):
            if len(item) > _MAX_STRING_CHARS:
                _raise("invalid_frame_patch_resources")
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                _raise("invalid_frame_patch_unicode")
            return
        if item is None or isinstance(item, bool | int):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                _raise("invalid_frame_patch_data")
            return
        if not isinstance(item, dict | list):
            _raise("invalid_frame_patch_data")
        identity = id(item)
        if identity in active:
            _raise("invalid_frame_patch_data")
        active.add(identity)
        try:
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        _raise("invalid_frame_patch_data")
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
        finally:
            active.remove(identity)

    visit(value, 1)


def _validate_root(value: Any) -> None:
    if (not isinstance(value, dict) or set(value) != {"frames", "qualifiers"}
            or not isinstance(value["frames"], list) or not isinstance(value["qualifiers"], list)
            or not 1 <= len(value["frames"]) <= _MAX_FRAMES
            or len(value["qualifiers"]) > _MAX_QUALIFIERS):
        _raise("invalid_frame_patch_graph")


def _parse_path(operation: str, path: Any) -> tuple[str, int | str, str | None]:
    if not isinstance(path, str):
        _raise("invalid_frame_patch_path")
    parts = path.split("/")
    if len(parts) not in (3, 4) or parts[0] or parts[1] not in ("frames", "qualifiers"):
        _raise("invalid_frame_patch_path")
    root, index_text = parts[1], parts[2]
    if operation == "add":
        if len(parts) != 3 or index_text != "-":
            _raise("invalid_frame_patch_path")
        return root, "-", None
    if not _INDEX.fullmatch(index_text):
        _raise("invalid_frame_patch_path")
    index = int(index_text)
    if operation == "remove":
        if len(parts) != 3:
            _raise("invalid_frame_patch_path")
        return root, index, None
    if operation != "replace":
        _raise("invalid_frame_patch_operation")
    field = parts[3] if len(parts) == 4 else None
    allowed = _FRAME_FIELDS if root == "frames" else _QUALIFIER_FIELDS
    if field is not None and field not in allowed:
        _raise("invalid_frame_patch_path")
    return root, index, field


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(path.split("/")[1:])


def _conflicts(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    common = min(len(left), len(right))
    return left[:common] == right[:common]


def apply_frame_patch(before: Any, payload: Any) -> dict[str, Any]:
    """Apply the accepted sparse compiler patch without mutating either input."""

    _validate_json(before)
    _validate_root(before)
    _validate_json(payload)
    try:
        payload_bytes = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        _raise("invalid_frame_patch_data")
    if len(payload_bytes) > _MAX_PAYLOAD_BYTES:
        _raise("invalid_frame_patch_resources")
    if not isinstance(payload, dict) or set(payload) != {"operations"}:
        _raise("invalid_frame_patch_payload")
    operations = payload["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= _MAX_OPERATIONS:
        _raise("invalid_frame_patch_payload")

    parsed: list[tuple[str, str, int | str, str | None, Any]] = []
    paths: list[tuple[str, tuple[str, ...]]] = []
    phase = 0
    last_removal: dict[str, int] = {}
    for row in operations:
        if not isinstance(row, dict) or row.get("op") not in ("replace", "remove", "add"):
            _raise("invalid_frame_patch_operation")
        operation = row["op"]
        expected = {"op", "path"} if operation == "remove" else {"op", "path", "value"}
        if set(row) != expected:
            _raise("invalid_frame_patch_operation")
        current_phase = {"replace": 0, "remove": 1, "add": 2}[operation]
        if current_phase < phase:
            _raise("invalid_frame_patch_order")
        phase = current_phase
        root, index, field = _parse_path(operation, row["path"])
        path = _path_parts(row["path"])
        if any(_conflicts(path, previous) and not (operation == previous_op == "add" and path == previous)
               for previous_op, previous in paths):
            _raise("invalid_frame_patch_conflict")
        paths.append((operation, path))
        if operation == "remove":
            assert isinstance(index, int)
            previous = last_removal.get(root)
            if previous is not None and index >= previous:
                _raise("invalid_frame_patch_order")
            last_removal[root] = index
        parsed.append((operation, root, index, field, row.get("value")))

    result: dict[str, Any] = copy.deepcopy(before)
    for operation, root, index, field, value in parsed:
        rows = result[root]
        if operation == "add":
            rows.append(copy.deepcopy(value))
            continue
        assert isinstance(index, int)
        original_rows = before[root]
        if index >= len(original_rows):
            _raise("invalid_frame_patch_target")
        if operation == "remove":
            rows.pop(index)
            continue
        original = original_rows[index]
        if field is None:
            rows[index] = copy.deepcopy(value)
            continue
        if not isinstance(original, dict) or field not in original:
            _raise("invalid_frame_patch_target")
        if not isinstance(rows[index], dict):
            _raise("invalid_frame_patch_target")
        rows[index][field] = copy.deepcopy(value)

    _validate_json(result)
    _validate_root(result)
    return result
