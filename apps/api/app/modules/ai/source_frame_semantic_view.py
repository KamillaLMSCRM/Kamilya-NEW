"""One typed semantic audit input; source geometry never grants admission.

The canonical native plan remains authoritative.  This module only projects its
claims and strictly transports fresh votes back.  Every facet/target membership
has one row with a conjunction of all producing claims, including mixed origins.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from app.modules.ai import source_assessment_plan as native
from app.modules.ai.checklist_leaf_layout import prove_checklist_leaf_layout
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_assessment_frames import CompiledAssessmentFrames, compiled_frame_wire
from app.modules.ai.source_assessment_graph import SourceGraphError, _hash
from app.modules.ai.source_audit_citation_holds import unique_literal_interval
from app.modules.ai.source_frame_applications import (
    CompiledApplicationGraph,
    application_graph_receipt,
    application_partition_custody,
)
from app.modules.ai.source_frame_patch import _validate_json

SCHEMA = "semantic_audit_view_v2"
APPLICATION_SCHEMA = "semantic_audit_view_v3"
STATUS_TRANSLATION_POLICY = "application-status-basis-v2"
CONTEXT_TRANSLATION_POLICY = "application-context-selection-v2"
DISPLAY_CONTEXT_TRANSLATION_POLICY = "application-context-display-selection-v1"
CONTEXT_BASES = ("applications", "own_answer", "native_relations")
CONTEXT_AXES = ("participants", "temporal_setting", "condition", "exception", "prerequisite", "antecedent")
_AXIS_KINDS = {
    "participants": frozenset({"actor_identity", "recipient_identity"}),
    "temporal_setting": frozenset({"temporal_setting"}),
    "condition": frozenset({"condition"}),
    "exception": frozenset(),
    "prerequisite": frozenset({"prior_action_prerequisite"}),
    "antecedent": frozenset({"antecedent_reference"}),
}
RELATION_ERRORS = {
    "timing_partition": frozenset({"wrong_pairing", "incomplete_branches", "wrong_applicability", "unsupported_meaning"}),
    "interrupted_action": frozenset({"wrong_actor", "missing_modality", "wrong_action", "wrong_applicability", "unsupported_meaning"}),
    "action_scopes_purpose": frozenset({"wrong_dependency", "wrong_applicability", "unsupported_meaning"}),
    "checklist_governance": frozenset({"wrong_actor", "wrong_governor", "incomplete_leaves", "wrong_applicability", "unsupported_meaning"}),
}


def build_semantic_audit_view(raw: dict[str, Any], compiled: CompiledAssessmentFrames,
                             plan: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_semantic_audit_view(compiled_frame_wire(raw, compiled), compiled, plan, sources)


def build_application_audit_view(graph: CompiledApplicationGraph, plan: dict[str, Any],
                                 sources: list[dict[str, Any]]) -> dict[str, Any]:
    """LOCAL V3 projection from a freshly compiled, unapproved application graph."""
    digest = application_graph_receipt(graph)
    refs = dict(graph.source_facts)
    if (digest != graph.receipt_sha256 or graph.semantic_approval is not False
            or len(refs) != len(graph.source_facts)
            or _hash({ref: asdict(fact) for ref, fact in refs.items()}) != graph.source_sha256):
        raise native.SourcePlanError("source_applications_view_graph_integrity")
    primary = {unit.ref for unit in graph.compiled.units}
    _, _, expected_plan = native._parse(json.dumps(graph.compiled.plan), refs, primary, partition_targets=False,
                                         _application_partition_custody=application_partition_custody(graph))
    if _hash(plan) != _hash(expected_plan):
        raise native.SourcePlanError("source_applications_view_plan_integrity")
    if _hash(sources) != _hash(source_fact_audit_sources(refs, primary)):
        raise native.SourcePlanError("source_applications_view_source_integrity")
    projected = sum(len(graph.compiled.frame_targets[row["owner_handle"]]) for row in graph.applications)
    if projected > 512:
        raise native.SourcePlanError("source_applications_view_resources")
    receipt = _build_semantic_audit_view(graph.native_graph, graph.compiled, plan, sources, graph=graph)
    if len(json.dumps(receipt["view"], ensure_ascii=False, separators=(",", ":")).encode()) > 256 * 1024:
        raise native.SourcePlanError("source_applications_view_resources")
    return receipt


def source_fact_audit_sources(refs: dict[str, SourceFact], primary: set[str]) -> list[dict[str, Any]]:
    """One canonical source descriptor projection; no model/source interpretation."""
    documents: dict[tuple[str, str], str] = {}
    sources: list[dict[str, Any]] = [{"ref": ref, "source_id": fact.fact_id, "primary": ref in primary,
        "text": fact.value, "subject": fact.subject, "attribute": fact.attribute,
        "locator": native._model_locator(fact.source_locator, documents, ref)} for ref, fact in refs.items()]
    for source in sources:
        source["context_metadata"] = [{"ref": source["ref"], "text": row["text"]}
            for row in native._case_context_metadata(source) if len(row["text"]) <= 300]
    return sources


def build_application_status_view(graph: CompiledApplicationGraph, plan: dict[str, Any],
                                  sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Explicit LOCAL projection of available support, not authored/rendered proof.

    Membership comes from the native plan, never adjacency or an action/purpose
    reference. Structural relations may be related without qualifying a target.
    The legacy V3 builder and its public witness wire remain unchanged.
    """
    receipt = build_application_audit_view(graph, plan, sources)
    view = receipt["view"]
    relations = {row["id"]: row for row in view["relations"]}
    for target in view["targets"]:
        supports = []
        axes: dict[str, list[str]] = {axis: [] for axis in CONTEXT_AXES}
        canonical_id = receipt["target_map"][target["id"]]
        for membership in receipt["memberships"]:
            if membership["target_id"] != canonical_id:
                continue
            for claim in membership["claim_ids"]:
                if claim not in relations:
                    continue
                relation = relations[claim]
                supports.append({"relation_id": claim, "facet_id": membership["facet_id"],
                    "evidence_id": relation["evidence_id"], "role": relation["role"],
                    "effect": relation["effect"], "credit": "context_only"})
                # These are compiler-typed support roles, not interpretations of
                # what an arbitrary scope quote might mean in natural language.
                if relation["kind"] == "interrupted_action" and relation["role"] == "actor":
                    axes["participants"].append(claim)
                elif (relation["kind"] == "timing_partition" and relation["role"] == "timing"
                      and relation["effect"] == "changes_timing"):
                    axes["temporal_setting"].append(claim)
        target["native_relation_ids_by_axis"] = {axis: sorted(set(ids)) for axis, ids in axes.items()}
        target["assembled_assessment_projection"] = {
            "assessed_evidence_ids": deepcopy(target["own_answer_evidence_ids"]),
            "declared_application_ids": deepcopy(target["application_ids"]),
            "available_native_supports": supports,
            "related_but_not_applied_relation_ids": sorted(set(target["relation_ids"])
                - {support["relation_id"] for support in supports}),
            "authored_question_render_verified": False,
        }
    receipt["status_translation_policy"] = STATUS_TRANSLATION_POLICY
    receipt["view_sha256"] = _hash({key: value for key, value in receipt.items() if key != "view_sha256"})
    if len(json.dumps(view, ensure_ascii=False, separators=(",", ":")).encode()) > 256 * 1024:
        raise native.SourcePlanError("source_applications_view_resources")
    return receipt


def _expose_branch_conditions(view: dict[str, Any]) -> None:
    """Expose existing displayed branch selectors, never invent a context vote."""
    evidence = {row["id"]: row for row in view["evidence_spans"]}
    relations = {row["id"]: row for row in view["relations"]}
    sources = {row["ref"]: row for row in view["sources"]}
    for target in view["targets"]:
        for claim in target["native_relation_ids_by_axis"]["temporal_setting"]:
            relation = relations[claim]
            pairs = [row for row in relation.get("branch_pairs", []) if row.get("target_id") == target["id"]]
            if (relation["kind"] != "timing_partition" or relation["role"] != "timing"
                    or relation["effect"] != "changes_timing" or len(pairs) != 1
                    or target["id"] not in relation["target_ids"] or not target["owner_handles"]
                    or set(relation["owner_handles"]) != set(target["owner_handles"])):
                continue
            pair = pairs[0]
            selector = evidence.get(pair.get("selector_evidence_id"))
            answer = evidence.get(pair.get("answer_evidence_id"))
            envelope = evidence.get(relation["evidence_id"])
            if (selector is None or answer is None or envelope is None
                    or pair.get("answer_evidence_id") not in target["own_answer_evidence_ids"]
                    or selector["ref"] != answer["ref"] or selector["ref"] != envelope["ref"]
                    or selector["ref"] not in target["source_refs"]
                    or selector["ref"] not in sources or sources[selector["ref"]]["primary"] is not True
                    or not (envelope["start"] <= selector["start"] < selector["end"] <= envelope["end"]
                            and envelope["start"] <= answer["start"] < answer["end"] <= envelope["end"])
                    or not (selector["end"] <= answer["start"] or answer["end"] <= selector["start"])):
                continue
            text = sources[selector["ref"]]["text"][selector["start"]:selector["end"]]
            if selector.get("quote") != text or not any(
                    row.get("ref") == selector["ref"] and row.get("text") == text for row in target["context"]):
                continue
            target["native_relation_ids_by_axis"]["condition"] = sorted(set(
                target["native_relation_ids_by_axis"]["condition"]) | {claim})


def build_application_context_view(graph: CompiledApplicationGraph, plan: dict[str, Any],
                                   sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Same verified support inventory, explicitly bound to the selection protocol."""
    receipt = build_application_status_view(graph, plan, sources)
    _expose_branch_conditions(receipt["view"])
    evidence = {row["id"]: row for row in receipt["view"]["evidence_spans"]}
    originals = {row["ref"]: row["text"] for row in receipt["view"]["sources"]}

    def assessed_span(eid: str) -> dict[str, Any]:
        row = evidence[eid]
        # The verified compact span omits duplicate quote bytes for a whole
        # source. Resolve that representation from its exact owning source;
        # missing arbitrary quote data is never silently repaired.
        quote = (originals[row["ref"]][row["start"]:row["end"]]
                 if row.get("whole_source") is True else row["quote"])
        return {"evidence_id": eid, **{key: row[key] for key in ("ref", "start", "end")}, "quote": quote}

    for target in receipt["view"]["targets"]:
        target["candidate_goal_presence"] = {
            "target_declared": True,
            "own_assessed_evidence": [assessed_span(eid) for eid in target["own_answer_evidence_ids"]],
            "context_applications_required_for_target_existence": False,
            "semantic_approval": False, "authored_question_render_verified": False,
        }
    if len(json.dumps(receipt["view"], ensure_ascii=False, separators=(",", ":")).encode()) > 256 * 1024:
        raise native.SourcePlanError("source_applications_view_resources")
    receipt["status_translation_policy"] = CONTEXT_TRANSLATION_POLICY
    receipt["view_sha256"] = _hash({key: value for key, value in receipt.items() if key != "view_sha256"})
    return receipt


def _build_semantic_audit_view(raw: dict[str, Any], compiled: CompiledAssessmentFrames,
                              plan: dict[str, Any], sources: list[dict[str, Any]],
                              *, graph: CompiledApplicationGraph | None = None) -> dict[str, Any]:
    """Project a compiler-valid candidate without suppressing any qualification edge."""
    source_by_ref = {row["ref"]: row for row in sources}
    if (len(source_by_ref) != len(sources) or any(type(row.get("primary")) is not bool for row in sources)
            or {row["ref"] for row in sources if row["primary"]} != {unit.ref for unit in compiled.units}):
        raise native.SourcePlanError("source_frames_view_source_identity")
    for unit in compiled.units:
        row = source_by_ref.get(unit.ref, {})
        if (row.get("source_id") != unit.source_id or row.get("text") != unit.exact_text
                or row.get("primary") is not True
                or hashlib.sha256(unit.exact_text.encode()).hexdigest() != unit.source_sha256):
            raise native.SourcePlanError("source_frames_view_source_identity")
    target_map = {f"T{i}": row["id"] for i, row in enumerate(plan["targets"], 1)}
    unit_map = {f"U{i}": unit.unit_id for i, unit in enumerate(compiled.units, 1)}
    tid = {canonical: alias for alias, canonical in target_map.items()}
    facets = {row["id"]: row for row in plan["qualification_facets"]}
    facet_by_meaning = {(row["ref"], row["quote"], row["role"], row["branch_effect"]): row for row in facets.values()}
    if len(facet_by_meaning) != len(facets):
        raise native.SourcePlanError("source_frames_view_duplicate_facet")
    membership: dict[tuple[str, str], set[str]] = {}
    for facet in facets.values():
        for target in facet["target_ids"]:
            if target not in tid or (facet["id"], target) in membership:
                raise native.SourcePlanError("source_frames_view_invalid_membership")
            membership[facet["id"], target] = set()
    evidence: list[dict[str, Any]] = []
    evidence_ids: dict[tuple[str, int, int], str] = {}

    def span(ref: str, quote: str, *, within: str | None = None) -> str:
        source = source_by_ref.get(ref)
        if source is None or not quote:
            raise native.SourcePlanError("source_frames_view_nonunique_span")
        if within is not None:
            if source["text"].count(within) != 1 or within.count(quote) != 1:
                raise native.SourcePlanError("source_frames_view_nonunique_span")
            start = source["text"].index(within) + within.index(quote)
        else:
            if source["text"].count(quote) != 1:
                raise native.SourcePlanError("source_frames_view_nonunique_span")
            start = source["text"].index(quote)
        key = (ref, start, start + len(quote))
        if key not in evidence_ids:
            alias = "E" + str(len(evidence) + 1)
            evidence_ids[key] = alias
            evidence.append({"id": alias, "ref": ref, "source_id": source["source_id"],
                "source_sha256": hashlib.sha256(source["text"].encode()).hexdigest(),
                "start": start, "end": start + len(quote),
                **({"whole_source": True} if quote == source["text"] else {"quote": quote})})
        return evidence_ids[key]

    bindings: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    routes: dict[str, dict[str, Any]] = {}
    frames = {row["handle"]: row for row in raw["frames"]}
    declarations = {row["handle"]: row for row in raw["qualifiers"]}
    physical_headers: set[tuple[str, str]] = set()
    for frame in raw["frames"]:
        if frame["kind"] == "checklist":
            for leaf in frame["leaves"]:
                proof = prove_checklist_leaf_layout(source_by_ref[frame["ref"]]["text"], leaf)
                if proof is not None:
                    physical_headers.add((frame["ref"], proof.owner.quote))

    def claim(kind: str, handles: list[str], targets: list[str], ref: str, quote: str,
              role: str, effect: str, details: dict[str, Any], fields: list[str]) -> str:
        relation = kind not in ("producer_binding", "producer_application")
        rows = relations if relation else bindings
        alias = ("R" if relation else "A" if graph is not None else "B") + str(len(rows) + 1)
        if not targets or not set(handles) <= set(frames):
            raise native.SourcePlanError("source_frames_view_invalid_claim_owner")
        facet = facet_by_meaning.get((ref, quote, role, effect))
        if facet is None or not set(targets) <= set(facet["target_ids"]):
            raise native.SourcePlanError("source_frames_view_unmapped_claim")
        for target in targets:
            membership[facet["id"], target].add(alias)
        rows.append({"id": alias, "kind": kind, "owner_handles": sorted(handles),
            "target_ids": [tid[value] for value in targets], "evidence_id": span(ref, quote),
            "role": role, "effect": effect, **details})
        routes[alias] = {"owner_handles": sorted(handles), "fields": fields,
                         "target_ids": sorted(targets), "facet_id": facet["id"]}
        return alias

    for handle, frame in frames.items():
        if graph is not None:
            for application in graph.applications:
                if application["owner_handle"] != handle:
                    continue
                declaration = declarations[application["native_qualifier_handle"]]
                for target in compiled.frame_targets[handle]:
                    alias = claim("producer_application", [handle], [target], declaration["ref"],
                        declaration["quote"], declaration["role"], declaration["effect"],
                        {"application_id": application["id"], "application_kind": application["kind"],
                         "repair_cohort_id": "owner:" + handle,
                         "predecessor_frame": application["predecessor_frame"],
                         "predecessor_provenance": deepcopy(application["predecessor_provenance"])},
                        ["bindings", "qualifiers"])
                    routes[alias]["repair_cohort_id"] = "owner:" + handle
            continue
        meanings: dict[tuple[str, str, str, str], list[str]] = {}
        for qhandle in frame["bindings"]:
            declaration = declarations[qhandle]
            key = tuple(declaration[key] for key in ("ref", "quote", "role", "effect"))
            meanings.setdefault(key, []).append(qhandle)
        for (ref, quote, role, effect), qhandles in meanings.items():
            for target in compiled.frame_targets[handle]:
                claim("producer_binding", [handle], [target], ref, quote, role, effect,
                    {"qualifier_handles": sorted(qhandles),
                     "provenance_kind": "physical_header" if (ref, quote) in physical_headers else "producer_quote"},
                    ["bindings", "qualifiers"])
    for handle, frame in frames.items():
        owned = list(compiled.frame_targets[handle])
        ref = frame["ref"]
        if frame["kind"] == "checklist":
            owner = frame["owner"]
            headers = {proof.owner.quote for leaf in frame["leaves"]
                       if (proof := prove_checklist_leaf_layout(source_by_ref[ref]["text"], leaf)) is not None}
            claim("checklist_governance", [handle], owned, ref, owner["quote"], owner["role"], owner["effect"],
                {"leaf_evidence_ids": [span(ref, leaf) for leaf in frame["leaves"]],
                 "header_evidence_ids": [span(ref, header) for header in sorted(headers)],
                 "governor_evidence_id": span(ref, owner["quote"]),
                 "declaration_ids": [row["id"] for row in bindings if handle in row["owner_handles"]]},
                ["owner", "bindings", "leaves", "qualifiers"])
        elif frame["kind"] == "timing_case":
            roles = compiled.timing_roles[handle]
            claim("timing_partition", [handle], list(roles["branches"]), ref, frame["fork"], "timing", "changes_timing",
                {"action_target_id": tid[roles["action"]], "purpose_target_ids": [tid[t] for t in roles["purposes"]],
                 "branch_pairs": [{"target_id": tid[target], "selector_evidence_id": span(ref, branch["selector"], within=frame["fork"]),
                                   "answer_evidence_id": span(ref, branch["answer"])}
                                  for target, branch in zip(roles["branches"], frame["branches"], strict=True)]},
                ["fork", "action", "purposes", "branches", "bindings", "context"])
            if projection := compiled.timing_projections.get(handle):
                claim("interrupted_action", [handle], owned, ref, projection["prefix"]["quote"], "actor", "none",
                    {"action_target_id": tid[roles["action"]], "original_action_evidence_id": span(ref, projection["original_action"]["quote"]),
                     "selector_evidence_id": span(ref, projection["first_selector"]["quote"], within=frame["fork"]),
                     "predicate_evidence_id": span(ref, projection["predicate"]["quote"])},
                    ["fork", "action", "branches", "bindings"])
            action = next(row for row in plan["targets"] if row["id"] == roles["action"])
            component, = action["answer_components"]
            answer, = component["terms"]
            for purpose in roles["purposes"]:
                claim("action_scopes_purpose", [handle], [purpose], ref, answer, "scope", "none",
                    {"from_target_id": tid[roles["action"]], "to_target_id": tid[purpose]}, ["action", "purposes", "bindings"])
    if any(not claims for claims in membership.values()):
        raise native.SourcePlanError("source_frames_view_uncovered_membership")
    targets = []
    for target in plan["targets"]:
        canonical = target["id"]
        row = deepcopy(target)
        row.pop("governing_bindings", None)
        row["id"] = tid[canonical]
        row["answer_components"] = [{"ref": part["ref"], "evidence_ids": [span(part["ref"], text) for text in part["terms"]]}
                                    for part in target["answer_components"]]
        row["binding_ids"] = [item["id"] for item in bindings if tid[canonical] in item["target_ids"]]
        row["relation_ids"] = [item["id"] for item in relations if tid[canonical] in item["target_ids"]
            or item.get("action_target_id") == tid[canonical] or item.get("from_target_id") == tid[canonical]]
        row["owner_handles"] = sorted(handle for handle, ids in compiled.frame_targets.items() if canonical in ids)
        if graph is not None:
            if len(row["owner_handles"]) != 1:
                raise native.SourcePlanError("source_applications_view_owner_identity")
            row["application_ids"] = row.pop("binding_ids")
            row["application_ids_by_axis"] = {axis: [item["id"] for item in bindings
                if row["id"] in item["target_ids"] and item["application_kind"] in _AXIS_KINDS[axis]]
                for axis in CONTEXT_AXES}
            row["own_answer_evidence_ids"] = sorted({eid for part in row["answer_components"] for eid in part["evidence_ids"]})
            row["unit_ids"] = [alias for alias, unit in zip(unit_map, compiled.units, strict=True)
                               if unit.ref in row["source_refs"]]
            if not row["unit_ids"]:
                raise native.SourcePlanError("source_applications_view_unit_identity")
        row["operative_dimensions"] = sorted({obligation["dimension"] for obligation in plan["material_obligations"]
                                             if canonical in obligation["target_ids"]})
        routes[row["id"]] = {"owner_handles": row["owner_handles"], "fields": list(native._TARGET_REPAIR_FIELDS), "target_ids": [canonical]}
        targets.append(row)
    view = {"schema": APPLICATION_SCHEMA if graph is not None else SCHEMA,
        "sources": deepcopy(sources), "evidence_spans": evidence, "targets": targets,
        "applications" if graph is not None else "bindings": bindings, "relations": relations,
        "original_units": [{"unit_id": alias, "ref": unit.ref, "source_id": unit.source_id, "source_sha256": unit.source_sha256}
                           for alias, unit in zip(unit_map, compiled.units, strict=True)],
        "native_vetoes": [{"target_id": tid[target], "errors": deepcopy(errors)} for target, errors in plan.get("target_validation_errors", {}).items()]}
    receipt = {"view": view, "target_map": target_map, "unit_map": unit_map,
        "memberships": [{"facet_id": facet, "target_id": target, "claim_ids": sorted(claims)}
                        for (facet, target), claims in sorted(membership.items())], "owner_routes": routes,
        "raw_sha256": _hash(raw), "plan_sha256": _hash(plan)}
    if graph is not None:
        receipt.update(application_receipt_sha256=graph.receipt_sha256,
                       application_wire_sha256=graph.wire_sha256, source_fact_sha256=graph.source_sha256)
        # Machine-only shape tag from the validated graph. Content custody stays
        # target-local: raw owner frames also contain sibling goals and labels.
        receipt["negative_owner_kinds"] = {frame["handle"]: frame["kind"] for frame in raw["frames"]}
    return receipt | {"view_sha256": _hash(receipt)}


def canonicalize_semantic_audit(response: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    return _canonicalize_semantic_audit(response, receipt)


def _canonicalize_semantic_audit(response: Any, receipt: dict[str, Any],
                                 *, applications: bool = False) -> dict[str, Any]:
    """Require a fresh closed vote inventory; any negative claim vetoes its facet."""
    if (receipt.get("view_sha256") != _hash({key: value for key, value in receipt.items() if key != "view_sha256"})
            or receipt["view"].get("schema") != (APPLICATION_SCHEMA if applications else SCHEMA)):
        raise native.SourcePlanError("source_frames_view_integrity")
    expected_keys = {"source_refs", "target_verdicts", "binding_verdicts", "relation_verdicts", "source_gaps", "unit_verdicts"}
    if applications:
        expected_keys = (expected_keys - {"binding_verdicts"}) | {"application_verdicts", "context_verdicts"}
    if not isinstance(response, dict) or set(response) != expected_keys:
        raise native.SourcePlanError("source_frames_view_vote_schema")
    view = receipt["view"]
    primary = {row["ref"] for row in view["sources"] if row["primary"]}
    known_refs = {row["ref"] for row in view["sources"]}
    inspected = response["source_refs"]
    if (not isinstance(inspected, list) or any(not isinstance(ref, str) for ref in inspected)
            or len(inspected) != len(set(inspected)) or not primary <= set(inspected) <= known_refs):
        raise native.SourcePlanError("source_frames_view_source_votes")
    if not isinstance(response["source_gaps"], list):
        raise native.SourcePlanError("source_frames_view_source_gaps")
    sources = {row["ref"]: row["text"] for row in view["sources"]}
    for gap in response["source_gaps"]:
        if (not isinstance(gap, dict) or set(gap) != {"ref", "missing_source_text", "reason"}
                or not isinstance(gap["ref"], str) or gap["ref"] not in primary
                or not isinstance(gap["missing_source_text"], str) or not gap["missing_source_text"].strip()
                or unique_literal_interval(sources[gap["ref"]], gap["missing_source_text"]) is None
                or not isinstance(gap["reason"], str) or not gap["reason"].strip() or len(gap["reason"]) > 240):
            raise native.SourcePlanError("source_frames_view_source_gaps")
    claim_votes: dict[str, dict[str, Any]] = {}
    canonical_targets = []
    for collection, inventory, idkey in (("target_verdicts", "targets", "target_id"),
                                       (("application_verdicts", "applications", "claim_id") if applications
                                        else ("binding_verdicts", "bindings", "binding_id")),
                                       ("relation_verdicts", "relations", "relation_id")):
        expected = {row["id"]: row for row in view[inventory]}
        votes = response[collection]
        if not isinstance(votes, list) or len(votes) != len(expected):
            raise native.SourcePlanError("source_frames_view_missing_votes")
        seen: set[str] = set()
        for vote in votes:
            fields = {idkey, "admit", "errors"}
            if inventory == "targets":
                fields.add("repair_fields")
            elif inventory == "relations":
                fields.add("error_codes")
            if (not isinstance(vote, dict) or set(vote) != fields or not isinstance(vote[idkey], str)
                    or vote[idkey] not in expected or vote[idkey] in seen or type(vote["admit"]) is not bool
                    or not isinstance(vote["errors"], list) or len(vote["errors"]) > 8
                    or any(not isinstance(error, str) or not error.strip() or len(error) > 240 for error in vote["errors"])
                    or vote["admit"] != (not vote["errors"])):
                raise native.SourcePlanError("source_frames_view_invalid_vote")
            alias = vote[idkey]
            seen.add(alias)
            if inventory == "targets":
                fields_value = vote["repair_fields"]
                if (not isinstance(fields_value, list) or any(not isinstance(field, str) for field in fields_value)
                        or len(fields_value) != len(set(fields_value)) or not set(fields_value) <= set(native._TARGET_REPAIR_FIELDS)
                        or vote["admit"] != (not fields_value)):
                    raise native.SourcePlanError("source_frames_view_target_repair_fields")
                canonical_targets.append(deepcopy(vote) | {"target_id": receipt["target_map"][alias]})
            else:
                if inventory == "relations":
                    codes = vote["error_codes"]
                    if (not isinstance(codes, list) or any(not isinstance(code, str) for code in codes)
                            or len(codes) != len(set(codes)) or not set(codes) <= RELATION_ERRORS[expected[alias]["kind"]]
                            or vote["admit"] != (not codes)):
                        raise native.SourcePlanError("source_frames_view_relation_error_codes")
                claim_votes[alias] = vote
    facet_errors: dict[str, list[str]] = {}
    edge_votes = []
    for membership in receipt["memberships"]:
        errors = facet_errors.setdefault(membership["facet_id"], [])
        edge_errors: list[str] = []
        for claim_id in membership["claim_ids"]:
            vote = claim_votes[claim_id]
            errors.extend(f"{claim_id}: {error}" for error in vote["errors"] if f"{claim_id}: {error}" not in errors)
            edge_errors.extend(f"{claim_id}: {error}" for error in vote["errors"])
        edge_votes.append({"facet_id": membership["facet_id"], "target_id": membership["target_id"],
                           "admit": not edge_errors, "errors": edge_errors})
    units = deepcopy(response["unit_verdicts"])
    if not isinstance(units, list) or len(units) != len(receipt["unit_map"]):
        raise native.SourcePlanError("source_frames_view_unit_votes")
    seen_units: set[str] = set()
    for unit in units:
        if (not isinstance(unit, dict) or set(unit) != {"unit_id", "review_state", "errors"}
                or not isinstance(unit["unit_id"], str) or unit["unit_id"] not in receipt["unit_map"]
                or unit["unit_id"] in seen_units or unit["review_state"] not in ("complete", "unresolved")
                or not isinstance(unit["errors"], list) or len(unit["errors"]) > 8
                or any(not isinstance(error, str) or not error.strip() or len(error) > 240 for error in unit["errors"])
                or (unit["review_state"] == "complete") != (not unit["errors"])):
            raise native.SourcePlanError("source_frames_view_unit_votes")
        seen_units.add(unit["unit_id"])
        unit["unit_id"] = receipt["unit_map"][unit["unit_id"]]
    return {"source_refs": deepcopy(response["source_refs"]), "source_gaps": deepcopy(response["source_gaps"]),
        "qualification_edge_verdicts": edge_votes,
        "target_verdicts": canonical_targets, "facet_verdicts": [{"facet_id": facet, "admit": not errors, "errors": errors}
                                                               for facet, errors in sorted(facet_errors.items())], "unit_verdicts": units}


def translate_application_status_audit(response: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    """Route critic-owned semantic bases to V3 witnesses, never repair a vote.

    The complete vote inventory is validated before deriving any IDs. Placement
    remains a fresh critic decision; this function knows only target-local sets.
    Separate strict context parsers share only native/cohort withholding logic;
    relation evidence is never relabeled as an application or assessed answer.
    """
    return _translate_application_context(response, receipt, selection=False)


def translate_application_context_audit(response: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    """LOCAL selection wire: derive mandatory positive membership, never meaning.

    Raw semantic negatives always withhold. Protocol conflicts also withhold, but
    only RAW semantic negatives can authorize edits in the orchestrator. The raw
    response and every conflict remain bound in the persisted audit record.
    """
    return _translate_application_context(response, receipt, selection=True)


def build_application_display_view(graph: CompiledApplicationGraph, plan: dict[str, Any],
                                   sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Explicit LOCAL display availability; source proof is not a positive vote."""
    from app.modules.ai.source_application_display import POLICY, build_display_inventory

    receipt = build_application_context_view(graph, plan, sources)
    rows = build_display_inventory(receipt, graph)
    view = receipt["view"]
    view["display_context_policy"] = POLICY
    view["display_witnesses"] = rows
    for target in view["targets"]:
        target["display_context_ids"] = sorted(row["id"] for row in rows if row["target_id"] == target["id"])
    receipt["status_translation_policy"] = DISPLAY_CONTEXT_TRANSLATION_POLICY
    receipt["view_sha256"] = _hash({key: value for key, value in receipt.items() if key != "view_sha256"})
    if len(json.dumps(view, ensure_ascii=False, separators=(",", ":")).encode()) > 256 * 1024:
        raise native.SourcePlanError("source_applications_view_resources")
    return receipt


def translate_application_display_audit(response: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    """Require a fresh, exact target-local selection for displayed support."""
    return _translate_application_context(response, receipt, selection=True, display_selection=True)


def _translate_application_context(response: Any, receipt: dict[str, Any], *, selection: bool,
                                   display_selection: bool = False) -> dict[str, Any]:
    try:
        _validate_json(response)
    except SourceGraphError as exc:
        raise native.SourcePlanError("source_applications_context_resources") from exc
    canonical = _canonicalize_semantic_audit(response, receipt, applications=True)
    policy = (DISPLAY_CONTEXT_TRANSLATION_POLICY if display_selection else
              CONTEXT_TRANSLATION_POLICY if selection else STATUS_TRANSLATION_POLICY)
    if receipt.get("status_translation_policy") != policy:
        raise native.SourcePlanError("source_applications_context_policy")
    targets = {row["id"]: row for row in receipt["view"]["targets"]}
    positives = {row["claim_id"] for row in response["application_verdicts"] if row["admit"]}
    positive_relations = {row["relation_id"] for row in response["relation_verdicts"] if row["admit"]}
    claims = {row["id"]: row for row in receipt["view"]["applications"]}
    context = response["context_verdicts"]
    if not isinstance(context, list) or len(context) != len(targets):
        raise native.SourcePlanError("source_applications_context_inventory")
    translated = deepcopy(response)
    seen: set[str] = set()
    missing: dict[str, list[str]] = {}
    diagnostics: list[dict[str, Any]] = []
    for row in translated["context_verdicts"]:
        if (not isinstance(row, dict) or set(row) != {"target_id", "axes"}
                or not isinstance(row["target_id"], str) or row["target_id"] not in targets
                or row["target_id"] in seen or not isinstance(row["axes"], list)
                or len(row["axes"]) != len(CONTEXT_AXES)):
            raise native.SourcePlanError("source_applications_context_inventory")
        target = targets[row["target_id"]]
        seen.add(row["target_id"])
        seen_axes: set[str] = set()
        axes = []
        for axis in row["axes"]:
            expected_axis = {"axis", "status", "own_answer_support" if selection else "basis", "reason"}
            if display_selection:
                expected_axis.add("display_context_ids")
            if (not isinstance(axis, dict) or set(axis) != expected_axis
                    or not isinstance(axis["axis"], str) or axis["axis"] not in CONTEXT_AXES
                    or axis["axis"] in seen_axes or not isinstance(axis["status"], str)
                    or axis["status"] not in ("covered", "not_required", "missing", "ambiguous")
                    or (type(axis["own_answer_support"]) is not bool if selection else (
                        not isinstance(axis["basis"], list)
                        or any(not isinstance(basis, str) or basis not in CONTEXT_BASES for basis in axis["basis"])
                        or axis["basis"] != [basis for basis in CONTEXT_BASES if basis in axis["basis"]]))
                    or not isinstance(axis["reason"], str) or len(axis["reason"]) > 240):
                raise native.SourcePlanError("source_applications_context_axis")
            name, status = axis["axis"], axis["status"]
            seen_axes.add(name)
            positive = [claim for claim in target["application_ids_by_axis"][name] if claim in positives]
            relations = [claim for claim in target["native_relation_ids_by_axis"][name] if claim in positive_relations]
            own = target["own_answer_evidence_ids"]
            display = []
            if display_selection:
                from app.modules.ai.source_application_display import validate_display_selection

                display = [proof["id"] for proof in validate_display_selection(
                    receipt, row["target_id"], axis["display_context_ids"])]
                if display and status != "covered":
                    raise native.SourcePlanError("source_applications_context_negative_display_selection")
            witnesses = []
            domains = {"applications": positive, "own_answer": own, "native_relations": relations}
            if display_selection:
                domains["display_context"] = display
            if selection:
                codes = []
                conflict = False
                if status in ("missing", "ambiguous") and axis["own_answer_support"]:
                    codes.append("negative_own_answer_not_support")
                if status == "covered":
                    basis = (["applications"] if positive else []) + (["own_answer"] if axis["own_answer_support"] else []) + (["native_relations"] if relations else [])
                    if display:
                        basis.append("display_context")
                    if not basis or any(not domains[domain] for domain in basis):
                        codes.append("covered_without_positive_witness")
                        conflict = True
                    if axis["reason"] != "":
                        codes.append("covered_nonempty_reason")
                        conflict = True
                    if name == "prerequisite" and any(
                        (claims[claim].get("predecessor_provenance") or {}).get("kind") != "exact_complete_answer"
                        for claim in positive
                    ):
                        codes.append("partial_predecessor_not_support")
                        conflict = True
                else:
                    basis = []
                    if not axis["reason"].strip():
                        codes.append("noncovered_reason_missing")
                        conflict = True
                    if status == "not_required" and (axis["own_answer_support"] or positive or relations or display):
                        codes.append("not_required_positive_support_conflict")
                        conflict = True
                if codes:
                    diagnostics.append({"target_id": row["target_id"], "axis": name, "code": codes[0], "codes": codes,
                        "raw_status": status, "raw_own_answer_support": axis["own_answer_support"],
                        "withhold": conflict or status in ("missing", "ambiguous"),
                        "repair_fields_granted": [], "semantic_approval": False})
                if conflict:
                    status, basis = "ambiguous", []
                    axis["reason"] = "context_protocol_conflict: " + ",".join(codes)
            else:
                basis = axis["basis"]
            if status == "covered":
                if (not basis or axis["reason"] != ""
                        or any(not domains[domain] for domain in basis)
                        or (positive and "applications" not in basis)
                        or (relations and "native_relations" not in basis)):
                    raise native.SourcePlanError("source_applications_context_basis")
                for domain in basis:
                    witnesses.extend(domains[domain])
                if len(witnesses) > 96:
                    raise native.SourcePlanError("source_applications_context_resources")
                if name == "prerequisite" and any(
                    (claims[claim].get("predecessor_provenance") or {}).get("kind") != "exact_complete_answer"
                    for claim in positive
                ):
                    raise native.SourcePlanError("source_applications_context_partial_predecessor")
            elif (basis or not axis["reason"].strip()
                  or (status == "not_required" and (positive or relations))):
                raise native.SourcePlanError("source_applications_context_basis")
            if status in ("missing", "ambiguous"):
                missing.setdefault(row["target_id"], []).append(name)
            axes.append({"axis": name, "status": status, "witness_ids": witnesses, "reason": axis["reason"]})
        row["axes"] = axes
    canonical = _withhold_application_owners(response, receipt, canonical, missing)
    result = {"policy": policy, "raw_sha256": _hash(response),
            "translated_sha256": _hash(translated), "wire_response": translated, "response": canonical}
    if selection:
        result["context_diagnostics"] = diagnostics
    return result


def canonicalize_application_audit(response: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    """Transport fresh V3 judgments; context and owner cohorts can only withhold."""
    try:
        _validate_json(response)
    except SourceGraphError as exc:
        raise native.SourcePlanError("source_applications_context_resources") from exc
    canonical = _canonicalize_semantic_audit(response, receipt, applications=True)
    view = receipt["view"]
    targets = {row["id"]: row for row in view["targets"]}
    claims = {row["id"]: row for row in view["applications"]}
    positives = {row["claim_id"] for row in response["application_verdicts"] if row["admit"]}
    context = response["context_verdicts"]
    if not isinstance(context, list) or len(context) != len(targets):
        raise native.SourcePlanError("source_applications_context_inventory")
    seen: set[str] = set()
    missing: dict[str, list[str]] = {}
    for row in context:
        if (not isinstance(row, dict) or set(row) != {"target_id", "axes"}
                or not isinstance(row["target_id"], str) or row["target_id"] not in targets
                or row["target_id"] in seen or not isinstance(row["axes"], list)
                or len(row["axes"]) != len(CONTEXT_AXES)):
            raise native.SourcePlanError("source_applications_context_inventory")
        target = targets[row["target_id"]]
        seen.add(row["target_id"])
        axes: set[str] = set()
        for axis in row["axes"]:
            if (not isinstance(axis, dict) or set(axis) != {"axis", "status", "witness_ids", "reason"}
                    or not isinstance(axis["axis"], str) or axis["axis"] not in CONTEXT_AXES
                    or axis["axis"] in axes or not isinstance(axis["status"], str)
                    or axis["status"] not in ("covered", "not_required", "missing", "ambiguous")
                    or not isinstance(axis["reason"], str) or len(axis["reason"]) > 240
                    or not isinstance(axis["witness_ids"], list) or len(axis["witness_ids"]) > 96
                    or any(not isinstance(witness, str) for witness in axis["witness_ids"])
                    or len(set(axis["witness_ids"])) != len(axis["witness_ids"])):
                raise native.SourcePlanError("source_applications_context_axis")
            name, status, witnesses = axis["axis"], axis["status"], set(axis["witness_ids"])
            axes.add(name)
            compatible = set(target["application_ids_by_axis"][name])
            positive = compatible & positives
            own = set(target["own_answer_evidence_ids"])
            if status == "covered":
                if (not witnesses or axis["reason"] != "" or not positive <= witnesses
                        or not witnesses <= positive | own):
                    raise native.SourcePlanError("source_applications_context_witness")
                if name == "prerequisite" and any(
                    (claims[claim].get("predecessor_provenance") or {}).get("kind") != "exact_complete_answer"
                    for claim in witnesses & positive
                ):
                    raise native.SourcePlanError("source_applications_context_partial_predecessor")
            else:
                if (not axis["reason"].strip() or (status != "ambiguous" and witnesses)
                        or not witnesses <= compatible | own
                        or (status == "not_required" and positive)):
                    raise native.SourcePlanError("source_applications_context_witness")
            if status in ("missing", "ambiguous"):
                missing.setdefault(row["target_id"], []).append(name)

    return _withhold_application_owners(response, receipt, canonical, missing)


def _withhold_application_owners(response: dict[str, Any], receipt: dict[str, Any],
                                 canonical: dict[str, Any], missing: dict[str, list[str]]) -> dict[str, Any]:
    """Shared withholding only; strict V3/V5 context parsers never cross-accept."""
    view = receipt["view"]
    targets = {row["id"]: row for row in view["targets"]}
    # Native admission remains target/edge-local, but a raw frame edit is atomic.
    # Retain every original vote/error; withhold all children of a rejected owner.
    routes = receipt["owner_routes"]
    rejected = {owner for target in missing for owner in routes[target]["owner_handles"]}
    binding_owners = set(rejected)
    owner_fields: dict[str, set[str]] = {}
    for channel, idkey in (("target_verdicts", "target_id"), ("application_verdicts", "claim_id"),
                           ("relation_verdicts", "relation_id")):
        for vote in response[channel]:
            if vote["admit"]:
                continue
            for owner in routes[vote[idkey]]["owner_handles"]:
                rejected.add(owner)
                if channel == "target_verdicts":
                    owner_fields.setdefault(owner, set()).update(vote["repair_fields"])
                elif channel == "application_verdicts":
                    binding_owners.add(owner)
    rejected.update(owner for veto in view["native_vetoes"]
                    for owner in routes[veto["target_id"]]["owner_handles"])
    unresolved_units: set[str] = set()
    canonical_targets = {row["target_id"]: row for row in canonical["target_verdicts"]}
    for alias, target in targets.items():
        if not rejected.intersection(target["owner_handles"]):
            continue
        verdict = canonical_targets[receipt["target_map"][alias]]
        if verdict["admit"]:
            verdict["admit"] = False
            verdict["errors"] = ["context_incomplete: " + ", ".join(missing[alias]) if alias in missing
                                 else "owner_cohort_requires_review"]
        owners = set(target["owner_handles"])
        if binding_owners.intersection(owners) and "governing_bindings" not in verdict["repair_fields"]:
            verdict["repair_fields"].append("governing_bindings")
        if not verdict["repair_fields"]:
            # A cohort sibling inherits only the rejected target's native fields.
            # Relation/native veto routes remain in the raw receipt; their
            # structural review does NOT grant new binding mutation authority.
            inherited = set().union(*(owner_fields.get(owner, set()) for owner in owners))
            verdict["repair_fields"] = sorted(inherited or {"source_quote_proposition"})
        unresolved_units.update(receipt["unit_map"][uid] for uid in target["unit_ids"])
    for unit in canonical["unit_verdicts"]:
        if unit["unit_id"] in unresolved_units and unit["review_state"] == "complete":
            unit["review_state"] = "unresolved"
            unit["errors"] = ["owner_context_or_claim_requires_review"]
    return canonical
