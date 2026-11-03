"""Bounded reference-namespace navigation; no guessed binding or repair."""

from __future__ import annotations

from typing import Any

from app.modules.ai.source_assessment_graph import SourceGraphError, _handle, _hash
from app.modules.ai.source_frame_patch import _validate_json

POLICY = "application-reference-inventory-v1"
_PREDECESSOR_KINDS = frozenset({"prior_action_prerequisite", "antecedent_reference"})


def application_reference_inventory(raw: Any) -> dict[str, Any]:
    """Describe exact dangling names, never infer quotes, kinds or substitutions.

    A mechanically closed reference set is not a valid/complete source graph.
    The unchanged compiler and fresh semantic audit remain authoritative.
    """
    result: dict[str, Any] = {"policy": POLICY, "raw_sha256": None,
        "namespaces": {"evidence": [], "predecessors": []}, "unresolved": [],
        "complete": False, "truncated": False, "referentially_closed": False,
        "semantic_approval": False, "edit_authority": False}

    def finish() -> dict[str, Any]:
        return result | {"inventory_sha256": _hash(result)}

    try:
        _validate_json(raw)
    except SourceGraphError:
        return finish()
    result["raw_sha256"] = _hash(raw)
    if not isinstance(raw, dict) or set(raw) != {"qualifiers", "frames"}:
        return finish()
    qualifiers, frames = raw["qualifiers"], raw["frames"]
    if not isinstance(qualifiers, list) or not isinstance(frames, list):
        return finish()
    if len(qualifiers) > 96 or len(frames) > 96:
        result["truncated"] = True
        return finish()
    evidence: dict[str, Any] = {}
    owners: dict[str, Any] = {}
    for rows, catalog in ((qualifiers, evidence), (frames, owners)):
        for row in rows:
            if (not isinstance(row, dict) or not _handle(row.get("handle"))
                    or not isinstance(row.get("ref"), str) or not row["ref"]
                    or row["handle"] in catalog):
                return finish()
            catalog[row["handle"]] = row
    total = 0
    for frame in frames:
        bindings = frame.get("bindings")
        if frame.get("kind") not in {"decision", "checklist", "timing_case"} or not isinstance(bindings, list):
            return finish()
        total += len(bindings)
        if len(bindings) > 96 or total > 512:
            result["truncated"] = True
            return finish()
        if any(not isinstance(row, dict) or set(row) != {"evidence_handle", "kind", "predecessor_frame"}
               or not isinstance(row["kind"], str) or not isinstance(row["evidence_handle"], str)
               or (row["predecessor_frame"] is not None and not isinstance(row["predecessor_frame"], str))
               for row in bindings):
            return finish()
    result["namespaces"] = {"evidence": [{"handle": h, "ref": row["ref"]}
        for h, row in sorted(evidence.items())], "predecessors": [{"handle": h, "ref": row["ref"]}
        for h, row in sorted(owners.items()) if row["kind"] == "decision"]}

    def negative(i: int, j: int, frame: dict[str, Any], field: str, value: Any, state: str) -> None:
        result["unresolved"].append({"owner_handle": frame["handle"], "owner_ref": frame["ref"],
            "field": field, "requested_handle": value if _handle(value) else None,
            "json_path": f"frames[{i}].bindings[{j}].{field}", "patch_path": f"/frames/{i}/bindings",
            "state": state, "other_namespace_match": isinstance(value, str) and value in (
                owners if field == "evidence_handle" else evidence)})

    for i, frame in enumerate(frames):
        for j, binding in enumerate(frame["bindings"]):
            name = binding["evidence_handle"]
            if not _handle(name):
                negative(i, j, frame, "evidence_handle", name, "invalid")
            elif name not in evidence:
                negative(i, j, frame, "evidence_handle", name, "missing")
            elif evidence[name]["ref"] != frame["ref"]:
                negative(i, j, frame, "evidence_handle", name, "foreign")
            prior = binding["predecessor_frame"]
            if binding["kind"] not in _PREDECESSOR_KINDS:
                if prior is not None:
                    negative(i, j, frame, "predecessor_frame", prior, "unexpected")
                continue
            if prior is None:
                negative(i, j, frame, "predecessor_frame", prior, "missing")
            elif not _handle(prior):
                negative(i, j, frame, "predecessor_frame", prior, "invalid")
            elif prior not in owners:
                negative(i, j, frame, "predecessor_frame", prior, "missing")
            elif prior == frame["handle"]:
                negative(i, j, frame, "predecessor_frame", prior, "self")
            elif owners[prior]["ref"] != frame["ref"]:
                negative(i, j, frame, "predecessor_frame", prior, "foreign")
            elif owners[prior]["kind"] != "decision":
                negative(i, j, frame, "predecessor_frame", prior, "wrong_kind")
    result["complete"] = True
    result["referentially_closed"] = not result["unresolved"]
    return finish()
