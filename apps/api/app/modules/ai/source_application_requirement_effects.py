"""Typed refusal effects; a changed repair route is never semantic approval."""

from __future__ import annotations

import hashlib
import re
from typing import Any, NoReturn

from app.modules.ai.source_application_requirements import CONTEXT_FUNCTIONS, NATIVE_ASPECT_FIELDS
from app.modules.ai.source_assessment_graph import _hash
from app.modules.ai.source_assessment_plan import SourcePlanError

POLICY = "application-requirement-effects-v2"
_AXES = {"actor_identity": "participants", "recipient_identity": "participants",
    "temporal_setting": "temporal_setting", "condition": "condition",
    "prior_action_prerequisite": "prerequisite", "antecedent_reference": "antecedent", "exception": "exception"}
_ROLES = {"actor_identity": "actor", "recipient_identity": "recipient",
    "static_scope": "scope", "quantity_support": "quantity", "operator_support": "operator"}


def _fail() -> NoReturn:
    raise SourcePlanError("source_applications_requirement_effect_integrity")


def _validated_anchor(anchor: Any, view: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(anchor, dict) or set(anchor) != {
            "ref", "source_id", "source_sha256", "start", "end", "quote_sha256"}:
        _fail()
    sources = [row for row in view["sources"] if row["ref"] == anchor["ref"] and row["primary"]]
    if len(sources) != 1:
        _fail()
    source = sources[0]
    start, end, text = anchor["start"], anchor["end"], source["text"]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
            or anchor["source_id"] != source["source_id"]
            or anchor["source_sha256"] != hashlib.sha256(text.encode()).hexdigest()
            or anchor["quote_sha256"] != hashlib.sha256(text[start:end].encode()).hexdigest()):
        _fail()
    return anchor, text


def _same_source(span: dict[str, Any], anchor: dict[str, Any]) -> bool:
    return all(span.get(key) == anchor[key] for key in ("ref", "source_id", "source_sha256"))


def _covers(span: dict[str, Any], anchor: dict[str, Any]) -> bool:
    return (_same_source(span, anchor) and type(span.get("start")) is int and type(span.get("end")) is int
        and span["start"] <= anchor["start"] < anchor["end"] <= span["end"])


def requirement_effect(subject: Any, receipt: dict[str, Any], state: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Measure this requirement alone, independently of permitted raw edits.

    Context functions require complete anchored coverage. Unrelated or partial
    evidence cannot change an effect. Native-aspect custody remains separate;
    requirement identity is never guessed from free-form error messages.
    """
    if not isinstance(subject, dict):
        _fail()
    target_rows = [row for row in state["target"] if row["alias"] == target_id]
    if len(target_rows) != 1:
        _fail()
    kind = subject.get("type")
    if kind == "native_aspect":
        if set(subject) != {"type", "field"} or subject["field"] not in NATIVE_ASPECT_FIELDS:
            _fail()
        effect = {"aspect": target_rows[0]["aspects"][subject["field"]]}
    elif kind == "context_function":
        if set(subject) != {"type", "function", "anchor"} or subject["function"] not in CONTEXT_FUNCTIONS:
            _fail()
        view = receipt["view"]
        anchor, source_text = _validated_anchor(subject["anchor"], view)
        targets = [row for row in view["targets"] if row["id"] == target_id]
        if len(targets) != 1:
            _fail()
        target, function = targets[0], subject["function"]
        spans = {row["id"]: row for row in view["evidence_spans"]}
        own = [spans[eid] for part in target["answer_components"] for eid in part["evidence_ids"]]
        # Complete means one complete source premise, never an arbitrary
        # intersection with a broad original-unit span.
        own_route = any(_covers(span, anchor) for span in own)
        displayed_route = False
        if "display_context_policy" in view:
            from app.modules.ai.source_application_display import validate_display_selection

            display_proofs = validate_display_selection(receipt, target_id, target["display_context_ids"])
            displayed_route = any(_covers(display_proof, anchor) for display_proof in display_proofs)
        else:
            for row in target["context"]:
                text = row["text"]
                start = source_text.find(text)
                if (row["ref"] == anchor["ref"] and text and start >= 0 and source_text.rfind(text) == start
                        and start <= anchor["start"] < anchor["end"] <= start + len(text)):
                    displayed_route = True
        applications = []
        app_state = {row["alias"]: row for row in state["application"]}
        for row in view["applications"]:
            if (row["id"] not in target["application_ids"] or row["application_kind"] != function
                    or target_id not in row["target_ids"] or not _covers(spans[row["evidence_id"]], anchor)):
                continue
            if (function == "prior_action_prerequisite"
                    and (row.get("predecessor_provenance") or {}).get("kind") != "exact_complete_answer"):
                continue
            # Referencing applications depend on the actual predecessor's
            # meaning. Other functions retain only this anchored typed effect,
            # so a cosmetic quote extension cannot reset the refusal.
            proof = {"function": function, "anchor": anchor}
            if function in {"prior_action_prerequisite", "antecedent_reference"}:
                predecessor = app_state[row["id"]].get("predecessor_effect")
                if not isinstance(predecessor, str):
                    continue
                proof["predecessor_effect"] = predecessor
            applications.append(_hash(proof))
        native = []
        allowed = set(target["native_relation_ids_by_axis"].get(_AXES.get(function, ""), []))
        applied = {support["relation_id"] for support in target["assembled_assessment_projection"]["available_native_supports"]
            if support.get("credit") == "context_only"}
        for row in view["relations"]:
            memberships = any(member["target_id"] == receipt["target_map"][target_id]
                and row["id"] in member["claim_ids"] for member in receipt["memberships"])
            if (row["id"] not in target["relation_ids"] or row["id"] not in applied or not memberships
                    or target_id not in row["target_ids"] or not _covers(spans[row["evidence_id"]], anchor)
                    or (row["id"] not in allowed and function not in {"static_scope", "quantity_support", "operator_support"})
                    or (function in _ROLES and row["role"] != _ROLES[function])):
                continue
            native.append(_hash({"kind": row["kind"], "role": row["role"], "effect": row["effect"], "anchor": anchor}))
        proofs = (["own:" + _hash(anchor)] if own_route else []) + (["displayed:" + _hash(anchor)] if displayed_route else [])
        proofs += ["application:" + proof for proof in applications] + ["native:" + proof for proof in native]
        effect = {"function": function, "anchor": anchor, "route_proofs": sorted(set(proofs))}
    else:
        _fail()
    return {"policy": POLICY, "subject": subject, "effect": effect, "signature": _hash(effect), "semantic_approval": False}


def unchanged_requirement(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """A removed support is not an improvement or a fresh repair opportunity."""
    if (any(not isinstance(row, dict) or set(row) != {"policy", "subject", "effect", "signature", "semantic_approval"}
            or not isinstance(row["subject"], dict) or not isinstance(row["effect"], dict) for row in (before, after))
            or before["subject"] != after["subject"] or before["policy"] != POLICY or after["policy"] != POLICY
            or any(row.get("semantic_approval") is not False or row.get("signature") != _hash(row.get("effect"))
                   for row in (before, after))):
        _fail()
    if before["subject"]["type"] == "context_function":
        for row in (before, after):
            effect = row["effect"]
            proofs = effect.get("route_proofs")
            if (set(effect) != {"function", "anchor", "route_proofs"}
                    or effect["function"] != row["subject"]["function"] or effect["anchor"] != row["subject"]["anchor"]
                    or not isinstance(proofs, list) or len(proofs) > 4096
                    or any(not isinstance(proof, str) or re.fullmatch(r"(?:own|displayed|application|native):[0-9a-f]{64}", proof) is None
                           for proof in proofs) or len(proofs) != len(set(proofs))):
                _fail()
        return not (set(after["effect"]["route_proofs"]) - set(before["effect"]["route_proofs"]))
    return bool(before["signature"] == after["signature"])
