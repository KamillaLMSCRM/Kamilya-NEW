"""Server-admitted, job-pinned runtime settings for deterministic stage replay."""

from __future__ import annotations

from typing import Any

KEY = "v3_literal_source_access"
POLICY = "literal-reference-access-v1"
BOUNDED_JOINT_EDITOR = "bounded-joint-editor-v1"
RELATED_SOURCE_JOINT_EDITOR = "bounded-joint-related-source-v2"
BRANCH_REVIEW_JOINT_EDITOR = "bounded-joint-branch-review-v3"
_PINNED_SETTINGS = {"policy", "runtime_revision", "literal_chars", "lookup_rounds"}


def pin_settings(snapshot: Any) -> dict[str, Any]:
    value = {
        "policy": POLICY,
        "runtime_revision": snapshot.revision,
        "literal_chars": snapshot.integer("generation.reference_literal_chars"),
        "lookup_rounds": snapshot.integer("generation.reference_lookup_rounds"),
        "joint_editor": BRANCH_REVIEW_JOINT_EDITOR,
    }
    checked_settings(value)
    return value


def checked_settings(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) not in (_PINNED_SETTINGS, _PINNED_SETTINGS | {"joint_editor"})
        or "joint_editor" in value and value["joint_editor"] not in (BOUNDED_JOINT_EDITOR, RELATED_SOURCE_JOINT_EDITOR, BRANCH_REVIEW_JOINT_EDITOR)
        or value["policy"] != POLICY
        or type(value["runtime_revision"]) is not int
        or value["runtime_revision"] < 0
        or type(value["literal_chars"]) is not int
        or not 1000 <= value["literal_chars"] <= 120000
        or type(value["lookup_rounds"]) is not int
        or not 0 <= value["lookup_rounds"] <= 3
    ):
        raise ValueError("source_access_pinned_settings_invalid")
    return dict(value)
