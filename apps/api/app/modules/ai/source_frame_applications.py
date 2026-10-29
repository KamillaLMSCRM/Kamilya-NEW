"""LOCAL explicit application compiler; no inference, votes or worker adoption.

The caller selects this protocol by crossing this seam. Evidence may be shared;
application ownership never is. The unchanged V8 compiler remains authoritative
for native shape, literal custody, physical governance and assessed credit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from math import isfinite
from typing import Any, Literal, NoReturn

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_assessment_frames import (
    CompiledAssessmentFrames,
    _compile_application_assessment_frames,
    _units,
)
from app.modules.ai.source_assessment_graph import MAX_GRAPH_ROWS, SourceGraphError, _fields, _handle, _hash, _quote
from app.modules.ai.source_frame_patch import _validate_json
from app.modules.ai.source_frame_quote_codec import POLICY as QUOTE_WIRE_POLICY
from app.modules.ai.source_frame_quote_codec import normalize_frame_quotes

SCHEMA = "source_application_graph_v1"
_MAX_OCCURRENCES = 512
_MAX_BYTES = 256 * 1024
_NATIVE_MEANING = {
    "actor_identity": ("actor", "none"),
    "recipient_identity": ("recipient", "none"),
    "temporal_setting": ("timing", "scopes_action"),
    "condition": ("condition", "scopes_action"),
    "static_scope": ("scope", "none"),
    "prior_action_prerequisite": ("scope", "none"),
    "antecedent_reference": ("scope", "none"),
    "quantity_support": ("quantity", "none"),
    "operator_support": ("operator", "none"),
}
_REFERENCING_KINDS = frozenset({"prior_action_prerequisite", "antecedent_reference"})


class SourceApplicationError(SourceGraphError):
    def __init__(self, code: str, *, path: str = "", raw_paths: dict[str, list[str]] | None = None,
                 evidence_paths: dict[str, str] | None = None,
                 native_findings: list[dict[str, Any]] | None = None):
        super().__init__(code)
        self.raw_paths = deepcopy(raw_paths or {})
        self.evidence_paths = deepcopy(evidence_paths or {})
        self.findings = deepcopy(native_findings) if native_findings is not None else [
            {"code": code, "json_path": path, "semantic_approval": False}]


@dataclass(frozen=True)
class CompiledApplicationGraph:
    compiled: CompiledAssessmentFrames
    native_graph: dict[str, Any]
    applications: tuple[dict[str, Any], ...]
    evidence_paths: dict[str, str]
    wire_sha256: str
    source_sha256: str
    receipt_sha256: str
    source_facts: tuple[tuple[str, SourceFact], ...]
    model_wire: dict[str, Any] | None = None
    model_wire_sha256: str | None = None
    wire_quote_policy: str | None = None
    wire_quote_normalizations: tuple[dict[str, Any], ...] = ()
    semantic_approval: Literal[False] = field(default=False, init=False)


def application_graph_receipt(graph: CompiledApplicationGraph) -> str:
    return _hash({"schema": SCHEMA, "wire": graph.wire_sha256, "sources": graph.source_sha256,
        "native_graph": graph.native_graph, "compiled": _hash(asdict(graph.compiled)),
        "applications": graph.applications, "evidence_paths": graph.evidence_paths,
        "model_wire": graph.model_wire_sha256, "quote_wire_policy": graph.wire_quote_policy,
        "wire_quote_normalizations": graph.wire_quote_normalizations})


def compile_model_application_graph(raw: Any, refs: Mapping[str, SourceFact],
                                     primary: set[str]) -> CompiledApplicationGraph:
    """Typed model-wire adapter; raw proposal and strict compiler stay separate."""
    _preflight(raw, refs, primary)
    try:
        canonical, receipts = normalize_frame_quotes(raw, refs, primary, applications=True)
    except SourceGraphError as exc:
        if str(exc).startswith("source_frame_quote_wire_"):
            compile_application_graph(raw, refs, primary)  # Refusal classification only; never acceptance fallback.
        raise
    graph = compile_application_graph(canonical, refs, primary)
    graph = replace(graph, model_wire=deepcopy(raw), model_wire_sha256=_hash(raw),
        wire_quote_policy=QUOTE_WIRE_POLICY, wire_quote_normalizations=receipts)
    return replace(graph, receipt_sha256=application_graph_receipt(graph))


def application_partition_custody(graph: CompiledApplicationGraph) -> tuple[Any, ...]:
    """Private-parse input rederived from a validated graph, never model plan fields."""
    from app.modules.ai.source_case_partition import ApplicationPartitionCustody

    refs = dict(graph.source_facts)
    source_sha = _hash({ref: asdict(fact) for ref, fact in sorted(refs.items())})
    expected = application_graph_receipt(graph)
    if source_sha != graph.source_sha256 or expected != graph.receipt_sha256:
        _fail("partition_custody_identity")
    if graph.wire_quote_policy is not None:
        if (graph.wire_quote_policy != QUOTE_WIRE_POLICY or not isinstance(graph.model_wire, dict)
                or _hash(graph.model_wire) != graph.model_wire_sha256):
            _fail("partition_custody_identity")
        try:
            canonical, receipts = normalize_frame_quotes(graph.model_wire, refs,
                {unit.ref for unit in graph.compiled.units}, applications=True)
        except SourceGraphError:
            _fail("partition_custody_identity")
        if _hash(canonical) != graph.wire_sha256 or _hash(receipts) != _hash(graph.wire_quote_normalizations):
            _fail("partition_custody_identity")
    elif graph.model_wire is not None or graph.model_wire_sha256 is not None or graph.wire_quote_normalizations:
        _fail("partition_custody_identity")
    frames = {frame["handle"]: frame for frame in graph.native_graph["frames"]}
    declarations = {row["handle"]: row for row in graph.native_graph["qualifiers"]}
    applications = {row["id"]: row for row in graph.applications}
    result = []
    for owner, projection in graph.compiled.timing_projections.items():
        custody = projection.get("application_prelude_custody")
        if custody is None:
            continue
        frame = frames[owner]
        ref = frame["ref"]
        if (custody["native_graph_sha256"] != _hash(graph.native_graph)
                or custody["source_sha256"] != sha256(refs[ref].value.encode()).hexdigest()
                or custody["frame_sha256"] != _hash(frame) or custody["semantic_approval"] is not False):
            _fail("partition_custody_identity")
        for claim in custody["claims"]:
            application = applications.get(claim["application_id"])
            if (application is None or application["kind"] != "antecedent_reference"
                    or application["owner_handle"] != owner or claim["owner_handle"] != owner
                    or application["native_qualifier_handle"] != claim["native_qualifier_handle"]
                    or application["predecessor_frame"] != claim["predecessor_handle"]
                    or claim["semantic_approval"] is not False):
                _fail("partition_custody_identity")
            qualifier = declarations[claim["native_qualifier_handle"]]
            result.append(ApplicationPartitionCustody(
                kind="antecedent_reference", application_id=application["id"], owner_handle=owner,
                native_qualifier_handle=claim["native_qualifier_handle"], predecessor_handle=claim["predecessor_handle"],
                source_ref=ref, source_sha256=custody["source_sha256"], fork_quote=frame["fork"], quote=qualifier["quote"],
                owner_target_ids=graph.compiled.frame_targets[owner],
                branch_target_ids=tuple(graph.compiled.timing_roles[owner]["branches"]),
                native_graph_sha256=custody["native_graph_sha256"], prelude_receipt_sha256=_hash(custody)))
    return tuple(result)


def _fail(code: str, path: str = "") -> NoReturn:
    raise SourceApplicationError("source_applications_" + code, path=path)


def _preflight(raw: Any, refs: Mapping[str, SourceFact], primary: set[str]) -> None:
    try:
        _validate_json(raw)  # Same depth/node/string/cycle/nonfinite/Unicode gates as patches.
    except SourceGraphError as exc:
        raise SourceApplicationError(str(exc).replace("invalid_frame_patch_", "source_applications_")) from exc
    if len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()) > _MAX_BYTES:
        _fail("resources")
    _fields(raw, {"qualifiers", "frames"}, "source_applications_invalid_root")
    validate_source_inventory(refs, primary)
    if (not isinstance(raw["qualifiers"], list) or len(raw["qualifiers"]) > MAX_GRAPH_ROWS
            or not isinstance(raw["frames"], list) or not 0 < len(raw["frames"]) <= MAX_GRAPH_ROWS):
        _fail("resources")
    count = 0
    handles: set[str] = set()
    for index, frame in enumerate(raw["frames"]):
        if (not isinstance(frame, dict) or not _handle(frame.get("handle"))
                or frame["handle"] in handles or not isinstance(frame.get("ref"), str)
                or frame["ref"] not in primary):
            _fail("invalid_owner", f"frames[{index}]")
        handles.add(frame["handle"])
        bindings = frame.get("bindings")
        if not isinstance(bindings, list) or len(bindings) > MAX_GRAPH_ROWS:
            _fail("resources", f"frames[{index}].bindings")
        count += len(bindings)
        if count > _MAX_OCCURRENCES:
            _fail("resources")


def validate_source_inventory(refs: Mapping[str, SourceFact], primary: set[str]) -> None:
    """Validate the exact fact inventory before an adapter spends a model call."""
    if (not isinstance(refs, Mapping) or not 0 < len(refs) <= 256
            or any(not isinstance(ref, str) or not isinstance(fact, SourceFact) for ref, fact in refs.items())
            or not isinstance(primary, set) or not 0 < len(primary) <= MAX_GRAPH_ROWS or not primary <= set(refs)):
        _fail("source_ownership")
    # Dataclass annotations do not validate runtime fields. Validate BEFORE any
    # quote scan/hash/set operation; reuse native custody rather than recompile.
    for ref, fact in refs.items():
        validate_source_fact(fact)
        try:
            _validate_json(ref)
        except SourceGraphError as exc:
            raise SourceApplicationError("source_applications_invalid_source_fact") from exc
    try:
        _units(refs, primary)
    except SourceGraphError as exc:
        raise SourceApplicationError(str(exc)) from exc


def validate_source_fact(fact: Any) -> None:
    """Validate scalar/runtime fields without deduplicating repeated source IDs."""
    if (not isinstance(fact, SourceFact)
            or any(not isinstance(getattr(fact, name), str) for name in
                   ("fact_id", "subject", "attribute", "value", "source_locator", "uncertainty"))
            or not fact.fact_id.strip() or type(fact.confidence) not in (int, float)
            or not 0 <= fact.confidence <= 1 or not isfinite(fact.confidence)):
        _fail("invalid_source_fact")
    try:
        _validate_json(asdict(fact))
    except SourceGraphError as exc:
        raise SourceApplicationError("source_applications_invalid_source_fact") from exc


def _cycles(edges: dict[str, set[str]]) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(owner: str) -> None:
        if owner in active:
            _fail("dependency_cycle")
        if owner in visited:
            return
        active.add(owner)
        for predecessor in edges[owner]:
            visit(predecessor)
        active.remove(owner)
        visited.add(owner)

    for owner in edges:
        visit(owner)


@dataclass(frozen=True)
class _PredecessorGeometry:
    start: int
    end: int
    answer_start: int
    answer_end: int

    @property
    def contained(self) -> bool:
        return self.answer_start <= self.start < self.end <= self.answer_end

    def provenance(self, ref: str) -> dict[str, Any] | None:
        if not self.contained:
            return None
        return {"kind": "exact_complete_answer" if (self.start, self.end) == (self.answer_start, self.answer_end)
                else "contained_in_complete_answer", "ref": ref,
            "binding_span": {"start": self.start, "end": self.end},
            "complete_answer_span": {"start": self.answer_start, "end": self.answer_end},
            "semantic_approval": False}


def _predecessor_geometry(ref: str, quote: Any, answer: Any,
                          refs: Mapping[str, SourceFact]) -> _PredecessorGeometry:
    """One geometry policy, only after unique literal custody of BOTH inputs."""
    _quote(ref, quote, refs)
    _quote(ref, answer, refs)
    source = refs[ref].value
    start, answer_start = source.index(quote), source.index(answer)
    return _PredecessorGeometry(start, start + len(quote), answer_start, answer_start + len(answer))


def _predecessor_custody_finding(geometry: _PredecessorGeometry, frame: dict[str, Any],
                                declaration: dict[str, Any], prior: dict[str, Any], *,
                                path: str, evidence_path: str, answer_path: str) -> dict[str, Any]:
    """Negative receipt shared by the rejecting kernel and diagnostic inventory."""
    quote, answer = declaration["quote"], prior["answer"]
    return {"code": "source_applications_predecessor_custody_not_contained", "json_path": path,
        "owner_handle": frame["handle"], "evidence_handle": declaration["handle"], "evidence_path": evidence_path,
        "predecessor_frame": prior["handle"], "predecessor_answer_path": answer_path, "ref": frame["ref"],
        "binding_quote": quote if len(quote) <= 320 else None,
        "complete_answer": answer if len(answer) <= 320 else None,
        "quote_text_omitted": len(quote) > 320 or len(answer) > 320,
        "binding_span": {"start": geometry.start, "end": geometry.end},
        "complete_answer_span": {"start": geometry.answer_start, "end": geometry.answer_end},
        "binding_quote_sha256": sha256(quote.encode()).hexdigest(),
        "complete_answer_sha256": sha256(answer.encode()).hexdigest(),
        "observed_containment": False, "required_provenance": "exact_complete_answer", "semantic_approval": False}


def _held_predecessor_pair(frame: dict[str, Any], application: dict[str, Any], declaration: Any,
                            owners: dict[str, Any], refs: Mapping[str, SourceFact], primary: set[str]) -> dict[str, Any]:
    """Provisional held-pair navigation, not semantic alternatives or a closed repair set."""
    unknown = {"status": "UNKNOWN", "scope": "held_literal_pair_only", "semantic_approval": False}
    predecessor = application.get("predecessor_frame")
    prior = owners.get(predecessor) if isinstance(predecessor, str) else None
    ref = frame.get("ref")
    if (set(application) != {"evidence_handle", "kind", "predecessor_frame"}
            or not isinstance(frame.get("handle"), str) or owners.get(frame["handle"]) is not frame
            or prior is None or predecessor == frame["handle"] or prior.get("kind") != "decision"
            or not isinstance(ref, str) or ref not in primary or prior.get("ref") != ref
            or not isinstance(declaration, dict) or set(declaration) != {"handle", "ref", "quote"}
            or declaration.get("ref") != ref):
        return unknown
    try:
        geometry = _predecessor_geometry(ref, declaration.get("quote"), prior.get("answer"), refs)
    except SourceGraphError:
        return unknown
    exact = declaration["quote"] == prior["answer"]
    return {"status": "UNIQUE_LITERAL_PAIR", "scope": "held_literal_pair_only", "ref": ref,
        "provided_predecessor": predecessor,
        "binding_span": {"start": geometry.start, "end": geometry.end},
        "predecessor_answer_span": {"start": geometry.answer_start, "end": geometry.answer_end},
        "binding_quote_sha256": sha256(declaration["quote"].encode()).hexdigest(),
        "predecessor_answer_sha256": sha256(prior["answer"].encode()).hexdigest(),
        "source_sha256": sha256(refs[ref].value.encode()).hexdigest(), "contained": geometry.contained,
        "exact_complete_answer": exact,
        "reference_kinds_passing_held_pair_custody": ["antecedent_reference"] + (["prior_action_prerequisite"] if exact else []),
        "other_graph_checks_pending": True, "recompute_if_evidence_changes": True, "semantic_approval": False}


def _unexpected_predecessor_finding(frame: dict[str, Any], application: dict[str, Any], *,
                                    path: str, evidence_path: str | None,
                                    held_pair: dict[str, Any] | None = None) -> dict[str, Any]:
    """The current declared kind's shape only; no choice of semantic repair."""
    return {"code": "source_applications_unexpected_predecessor", "json_path": path,
        "owner_handle": frame.get("handle"), "owner_path": path.split(".bindings[", 1)[0],
        "evidence_handle": application["evidence_handle"], "evidence_path": evidence_path,
        "declared_kind": application["kind"], "supplied_predecessor_frame": application["predecessor_frame"],
        "required_predecessor_for_current_kind": None,
        "referencing_kind_change_requires": "independent_source_meaning_and_existing_predecessor_custody_checks",
        "held_pair_custody": held_pair or {"status": "UNKNOWN", "scope": "held_literal_pair_only", "semantic_approval": False},
        "semantic_approval": False}


def compile_application_graph(raw: Any, refs: Mapping[str, SourceFact],
                              primary: set[str]) -> CompiledApplicationGraph:
    """Compile explicit owner applications, retaining claims rather than approving them."""
    _preflight(raw, refs, primary)
    declarations: dict[str, dict[str, Any]] = {}
    evidence_paths: dict[str, str] = {}
    carriers: set[tuple[str, str]] = set()
    for index, row in enumerate(raw["qualifiers"]):
        path = f"qualifiers[{index}]"
        _fields(row, {"handle", "ref", "quote"}, "source_applications_invalid_evidence_schema")
        if (not _handle(row["handle"]) or row["handle"] in declarations
                or not isinstance(row["ref"], str) or row["ref"] not in primary):
            _fail("invalid_evidence", path)
        _quote(row["ref"], row["quote"], refs)
        identity = (row["ref"], row["quote"])
        if identity in carriers:
            _fail("duplicate_evidence_alias", path)
        carriers.add(identity)
        declarations[row["handle"]] = row
        evidence_paths[row["handle"]] = path + ".quote"
    frames = {row["handle"]: row for row in raw["frames"]}
    native_frames = deepcopy(raw["frames"])
    native_qualifiers: dict[str, dict[str, Any]] = {}
    applications: list[dict[str, Any]] = []
    used: set[str] = set()
    edges: dict[str, set[str]] = {owner: set() for owner in frames}
    raw_paths: dict[str, list[str]] = {}
    for index, frame in enumerate(raw["frames"]):
        owner = frame["handle"]
        native_handles: list[str] = []
        seen: set[tuple[str, str, str | None]] = set()
        for ordinal, application in enumerate(frame["bindings"]):
            path = f"frames[{index}].bindings[{ordinal}]"
            _fields(application, {"evidence_handle", "kind", "predecessor_frame"}, "source_applications_invalid_application_schema")
            handle, kind, predecessor = (application[key] for key in ("evidence_handle", "kind", "predecessor_frame"))
            if not isinstance(handle, str) or handle not in declarations or not isinstance(kind, str):
                _fail("invalid_application", path)
            if kind not in _NATIVE_MEANING:
                _fail("unsupported_application_kind", path)
            declaration = declarations[handle]
            if declaration["ref"] != frame["ref"]:
                _fail("foreign_owner_evidence", path)
            if kind in _REFERENCING_KINDS:
                if not isinstance(predecessor, str) or predecessor not in frames or predecessor == owner:
                    _fail("invalid_predecessor", path)
                prior = frames[predecessor]
                if prior["ref"] != frame["ref"]:
                    _fail("foreign_predecessor", path)
                if prior.get("kind") != "decision":
                    _fail("unsupported_predecessor_shape", path)
                _quote(prior["ref"], prior.get("answer"), refs)
                edges[owner].add(predecessor)
            elif predecessor is not None:
                raise SourceApplicationError("source_applications_unexpected_predecessor", path=path,
                    raw_paths=raw_paths, evidence_paths=evidence_paths,
                    native_findings=[_unexpected_predecessor_finding(frame, application,
                        path=path, evidence_path=evidence_paths[handle],
                        held_pair=_held_predecessor_pair(frame, application, declaration, frames, refs, primary))])
            application_identity = (handle, kind, predecessor)
            if application_identity in seen:
                _fail("duplicate_application", path)
            seen.add(application_identity)
            used.add(handle)
            role, effect = _NATIVE_MEANING[kind]
            native_handle = "q" + _hash({"evidence_handle": handle, "kind": kind, "predecessor_frame": predecessor})
            if native_handle not in native_qualifiers:
                if len(native_qualifiers) >= MAX_GRAPH_ROWS:
                    _fail("resources", path)
                native_qualifiers[native_handle] = {"handle": native_handle, "ref": declaration["ref"],
                    "quote": declaration["quote"], "role": role, "effect": effect}
            if native_handle not in native_handles:
                native_handles.append(native_handle)
            record = {"id": "A" + _hash({"owner": owner, "ordinal": ordinal, "evidence": declaration,
                         "kind": kind, "predecessor_frame": predecessor}),
                "owner_handle": owner, "raw_path": path, "evidence_handle": handle,
                "evidence_path": evidence_paths[handle], "kind": kind, "predecessor_frame": predecessor,
                "native_qualifier_handle": native_handle, "predecessor_provenance": None,
                "semantic_approval": False}
            if kind in _REFERENCING_KINDS:
                prior = frames[predecessor]
                geometry = _predecessor_geometry(frame["ref"], declaration["quote"], prior["answer"], refs)
                if kind == "prior_action_prerequisite" and not geometry.contained:
                    predecessor_index = next(i for i, row in enumerate(raw["frames"]) if row["handle"] == predecessor)
                    code = "source_applications_predecessor_custody_not_contained"
                    raise SourceApplicationError(code, path=path, evidence_paths=evidence_paths,
                        raw_paths=raw_paths | {native_handle: [*raw_paths.get(native_handle, []), path]},
                        native_findings=[_predecessor_custody_finding(geometry, frame, declaration, prior,
                            path=path, evidence_path=evidence_paths[handle],
                            answer_path=f"frames[{predecessor_index}].answer")])
                record["predecessor_provenance"] = geometry.provenance(frame["ref"])
            applications.append(record)
            raw_paths.setdefault(native_handle, []).append(path)
        native_frames[index]["bindings"] = native_handles
    if used != set(declarations):
        _fail("unused_evidence")
    _cycles(edges)
    native_graph = {"qualifiers": list(native_qualifiers.values()), "frames": native_frames}
    prelude_claims = tuple({"owner_handle": row["owner_handle"], "native_qualifier_handle": row["native_qualifier_handle"],
        "predecessor_handle": row["predecessor_frame"], "application_id": row["id"]} for row in applications
        if row["kind"] == "antecedent_reference" and frames[row["owner_handle"]]["kind"] == "timing_case")
    try:
        compiled = _compile_application_assessment_frames(native_graph, refs, primary, prelude_claims)
    except SourceGraphError as exc:
        raise SourceApplicationError(str(exc), raw_paths=raw_paths, evidence_paths=evidence_paths,
            native_findings=getattr(exc, "findings", None)) from exc
    for application in applications:
        if application["kind"] != "prior_action_prerequisite":
            continue
        ref = declarations[application["evidence_handle"]]["ref"]
        span = application["predecessor_provenance"]["binding_span"]
        owned = set(compiled.frame_targets[application["owner_handle"]])
        for obligation in compiled.plan["material_obligations"]:
            if obligation["ref"] != ref or not owned.intersection(obligation["target_ids"]):
                continue
            start = refs[ref].value.index(obligation["quote"])
            if start < span["end"] and span["start"] < start + len(obligation["quote"]):
                _fail("predecessor_overlaps_assessed_owner", application["raw_path"])
    wire_sha256 = _hash(raw)
    source_sha256 = _hash({ref: asdict(fact) for ref, fact in sorted(refs.items())})
    graph = CompiledApplicationGraph(compiled, native_graph, tuple(applications), evidence_paths,
                                    wire_sha256, source_sha256, "", tuple(refs.items()))
    return replace(graph, receipt_sha256=application_graph_receipt(graph))
