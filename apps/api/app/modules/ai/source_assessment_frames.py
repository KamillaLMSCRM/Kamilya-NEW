"""LOCAL V88: explicit typed semantics over immutable whole-source custody.

No inference, admission, segmentation or character-union completeness heuristic.
The existing native parser and independent all-original audit remain mandatory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from app.modules.ai.assessment_facets import FACET_ROLES
from app.modules.ai.checklist_leaf_layout import prove_checklist_leaf_layout
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_assessment_graph import (
    MAX_GRAPH_ROWS,
    SourceGraphError,
    _compile_declared_atoms,
    _fields,
    _handle,
    _handles,
    _hash,
    _quote,
)
from app.modules.ai.source_frame_quote_codec import normalize_frame_quotes
from app.modules.ai.source_frame_timing import (
    ApplicationPreludeClaim,
    TimingCaseValidationError,
    _validate_application_timing_case,
    validate_timing_case,
)

APPLICATION_TIMING_DISPLAY_POLICY = "application-branch-effective-action-display-v1"


@dataclass(frozen=True)
class SourceCustodyUnit:
    unit_id: str
    ref: str
    source_id: str
    source_sha256: str
    exact_text: str


@dataclass(frozen=True)
class CompiledAssessmentFrames:
    plan: dict[str, Any]
    units: tuple[SourceCustodyUnit, ...]
    frame_targets: dict[str, tuple[str, ...]]
    timing_roles: dict[str, dict[str, Any]]
    timing_projections: dict[str, dict[str, Any]] = field(default_factory=dict)
    quote_boundary_normalizations: tuple[dict[str, Any], ...] = ()
    compiler_wire: dict[str, Any] | None = None
    model_wire_sha256: str | None = None
    canonical_wire_sha256: str | None = None
    wire_quote_normalizations: tuple[dict[str, Any], ...] = ()
    semantic_approval: Literal[False] = field(default=False, init=False)


class FrameGovernanceError(SourceGraphError):
    """Exact negative layout navigation, never an inserted binding or approval."""

    def __init__(self, findings: list[dict[str, Any]]):
        super().__init__("incomplete_checklist_governance")
        self.findings = findings


def checklist_governance_findings(
    frame: Any,
    declarations: Any,
    fact: Any,
) -> list[dict[str, Any]]:
    """Return bounded physical-layout negatives from explicitly bound declarations."""
    if (not isinstance(frame, dict) or frame.get("kind") != "checklist"
            or not _handle(frame.get("handle")) or not isinstance(frame.get("ref"), str)
            or not frame["ref"].strip()
            or not isinstance(frame.get("bindings"), list)
            or len(frame["bindings"]) > MAX_GRAPH_ROWS
            or any(not _handle(handle) for handle in frame["bindings"])
            or len(set(frame["bindings"])) != len(frame["bindings"])
            or not isinstance(frame.get("owner"), dict)
            or set(frame["owner"]) != {"quote", "role", "effect"}
            or not isinstance(frame["owner"]["quote"], str) or not frame["owner"]["quote"].strip()
            or len(frame["owner"]["quote"]) > 65536
            or not isinstance(frame["owner"]["role"], str)
            or frame["owner"]["role"] not in FACET_ROLES
            or not isinstance(frame["owner"]["effect"], str)
            or frame["owner"]["effect"] not in ("none", "scopes_action")
            or not isinstance(frame.get("leaves"), list) or not 0 < len(frame["leaves"]) <= 12
            or any(not isinstance(leaf, str) or not leaf.strip() or len(leaf) > 320
                   for leaf in frame["leaves"])
            or not isinstance(declarations, Mapping) or not isinstance(fact, SourceFact)
            or not isinstance(fact.value, str) or not fact.value.strip() or len(fact.value) > 65536):
        return []
    try:
        fact.value.encode()
    except UnicodeEncodeError:
        return []

    supplied = [frame["owner"]]
    for handle in frame["bindings"]:
        declaration = declarations.get(handle)
        if (not isinstance(declaration, dict)
                or set(declaration) != {"handle", "ref", "quote", "role", "effect"}
                or declaration["handle"] != handle
                or not isinstance(declaration["ref"], str) or not declaration["ref"].strip()
                or not isinstance(declaration["quote"], str) or not declaration["quote"].strip()
                or len(declaration["quote"]) > 65536
                or not isinstance(declaration["role"], str)
                or declaration["role"] not in FACET_ROLES
                or not isinstance(declaration["effect"], str)
                or declaration["effect"] not in ("none", "scopes_action")):
            return []
        if declaration["ref"] == frame["ref"]:
            supplied.append(declaration)

    governance: dict[str, dict[str, Any]] = {}
    for leaf in frame["leaves"]:
        proof = prove_checklist_leaf_layout(fact.value, leaf)
        if proof is None:
            continue  # Unsupported layout supplies no invented owner.
        line_start = max(fact.value.rfind("\n", 0, proof.governor.start),
                         fact.value.rfind("\r", 0, proof.governor.start)) + 1
        governor_quotes = {proof.governor.quote, fact.value[line_start:proof.governor.end]}
        required = (("actor", {proof.owner.quote}), ("scope", governor_quotes))
        matched = [role for role, quotes in required
                   if any(row["role"] == role and row["quote"] in quotes for row in supplied)]
        missing = [{"role": role, "acceptable_spans": [
            asdict(proof.owner) if role == "actor" else {"start": proof.governor.end - len(quote),
                "end": proof.governor.end, "quote": quote} for quote in sorted(quotes)]}
            for role, quotes in required if role not in matched]
        if missing:
            finding = {"code": "incomplete_checklist_governance", "frame_handle": frame["handle"],
                "ref": frame["ref"], "source_sha256": proof.source_sha256,
                "physical_owner": asdict(proof.owner), "physical_governor": asdict(proof.governor),
                "matched_roles": matched, "missing_declarations": missing, "semantic_approval": False}
            key = _hash(finding)
            row = governance.setdefault(key, finding | {"affected_leaves": []})
            if asdict(proof.leaf) not in row["affected_leaves"]:
                row["affected_leaves"].append(asdict(proof.leaf))
    return list(governance.values())


def _units(refs: Mapping[str, SourceFact], primary_refs: set[str]) -> tuple[SourceCustodyUnit, ...]:
    if (not isinstance(refs, Mapping) or not refs or len(refs) > 256
            or any(not isinstance(ref, str) or not isinstance(fact, SourceFact) for ref, fact in refs.items())
            or not isinstance(primary_refs, set) or not 0 < len(primary_refs) <= MAX_GRAPH_ROWS or not primary_refs <= set(refs)):
        raise SourceGraphError("invalid_source_ownership")
    if len({fact.fact_id for fact in refs.values()}) != len(refs):
        raise SourceGraphError("duplicate_source_identity")
    units = []
    for ref, fact in refs.items():
        if ref not in primary_refs:
            continue
        if not isinstance(fact.value, str) or not fact.value.strip() or len(fact.value) > 65536:
            raise SourceGraphError("invalid_custody_source")
        sha = hashlib.sha256(fact.value.encode()).hexdigest()
        uid = "U" + _hash({"ref": ref, "source_id": fact.fact_id, "source_sha256": sha})
        units.append(SourceCustodyUnit(uid, ref, fact.fact_id, sha, fact.value))
    return tuple(units)


def compile_assessment_frames(raw: Any, refs: Mapping[str, SourceFact],
                              primary_refs: set[str]) -> CompiledAssessmentFrames:
    """Expand only declared frames; links/bytes NEVER constitute semantic approval."""
    _units(refs, primary_refs)
    try:
        canonical, receipts = normalize_frame_quotes(raw, refs, primary_refs, applications=False)
    except SourceGraphError as exc:
        if str(exc).startswith("source_frame_quote_wire_"):
            # Preserve existing typed structural refusal/recovery codes. This
            # negative-only probe can never return an alternative accepted plan.
            _compile_frames(raw, refs, primary_refs, {})
        raise
    compiled = _compile_frames(canonical, refs, primary_refs, {})
    return replace(compiled, compiler_wire=canonical, model_wire_sha256=_hash(raw),
        canonical_wire_sha256=_hash(canonical), wire_quote_normalizations=receipts)


def compiled_frame_wire(raw: Any, compiled: CompiledAssessmentFrames) -> dict[str, Any]:
    """Rederive the model-to-compiler copy from immutable primary source units."""
    if compiled.compiler_wire is None:
        if (not isinstance(raw, dict) or compiled.model_wire_sha256 is not None or compiled.canonical_wire_sha256 is not None
                or compiled.wire_quote_normalizations):
            raise SourceGraphError("source_frames_quote_wire_identity")
        return raw
    refs = {unit.ref: SourceFact(unit.source_id, "", "", unit.exact_text, "") for unit in compiled.units}
    canonical, receipts = normalize_frame_quotes(raw, refs, set(refs), applications=False)
    if (_hash(raw) != compiled.model_wire_sha256 or _hash(canonical) != compiled.canonical_wire_sha256
            or _hash(canonical) != _hash(compiled.compiler_wire)
            or _hash(receipts) != _hash(compiled.wire_quote_normalizations)):
        raise SourceGraphError("source_frames_quote_wire_identity")
    return compiled.compiler_wire


def _application_preludes(raw: Any, refs: Mapping[str, SourceFact], primary_refs: set[str],
                         claims: tuple[dict[str, str], ...], custody_graph: dict[str, Any]
                         ) -> dict[str, tuple[ApplicationPreludeClaim, ...]]:
    """Validate private server-derived claim identities, never infer an antecedent."""
    _units(refs, primary_refs)
    if len(claims) > 512:
        raise SourceGraphError("invalid_application_prelude_claim")
    full_frames, full_qualifiers = custody_graph["frames"], custody_graph["qualifiers"]
    owners = {f["handle"]: f for f in full_frames if isinstance(f, dict) and _handle(f.get("handle"))
        and sum(isinstance(other, dict) and other.get("handle") == f["handle"] for other in full_frames) == 1}
    declarations = {q["handle"]: q for q in full_qualifiers if isinstance(q, dict) and _handle(q.get("handle"))
        and sum(isinstance(other, dict) and other.get("handle") == q["handle"] for other in full_qualifiers) == 1}
    subset = {f.get("handle"): f for f in raw["frames"] if isinstance(f, dict) and _handle(f.get("handle"))}
    local_declarations = {q.get("handle"): q for q in raw["qualifiers"] if isinstance(q, dict) and _handle(q.get("handle"))}
    graph_sha = _hash(custody_graph)
    result: dict[str, list[ApplicationPreludeClaim]] = {}
    seen: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for claim in claims:
        _fields(claim, {"owner_handle", "native_qualifier_handle", "predecessor_handle", "application_id"},
                "invalid_application_prelude_claim")
        if any(not _handle(value) for value in claim.values()):
            raise SourceGraphError("invalid_application_prelude_claim")
        owner, handle, predecessor, application_id = (claim[key] for key in
            ("owner_handle", "native_qualifier_handle", "predecessor_handle", "application_id"))
        if (owner, handle) in seen or application_id in ids:
            raise SourceGraphError("invalid_application_prelude_claim")
        seen.add((owner, handle))
        ids.add(application_id)
        frame, declaration, prior = owners.get(owner), declarations.get(handle), owners.get(predecessor)
        if (frame is None or declaration is None or prior is None or predecessor == owner
                or frame.get("kind") != "timing_case" or prior.get("kind") != "decision"
                or not isinstance(frame.get("ref"), str) or frame["ref"] not in primary_refs
                or prior.get("ref") != frame["ref"] or declaration.get("ref") != frame["ref"]
                or declaration.get("role") != "scope" or declaration.get("effect") != "none"
                or not isinstance(frame.get("bindings"), list) or handle not in frame["bindings"]):
            raise SourceGraphError("invalid_application_prelude_claim")
        _quote(frame["ref"], declaration.get("quote"), refs)
        _quote(frame["ref"], prior.get("answer"), refs)
        if owner not in subset:
            continue  # A diagnostic subset never receives another owner's byte custody.
        if subset[owner] != frame or local_declarations.get(handle) != declaration:
            raise SourceGraphError("invalid_application_prelude_claim")
        result.setdefault(owner, []).append(ApplicationPreludeClaim(owner, handle, predecessor, application_id,
            frame["ref"], prior["answer"], graph_sha))
    return {owner: tuple(rows) for owner, rows in result.items()}


def _compile_application_assessment_frames(raw: Any, refs: Mapping[str, SourceFact], primary_refs: set[str],
                                          claims: tuple[dict[str, str], ...], *,
                                          custody_graph: dict[str, Any] | None = None) -> CompiledAssessmentFrames:
    preludes = _application_preludes(raw, refs, primary_refs, claims, custody_graph if custody_graph is not None else raw)
    return _compile_frames(raw, refs, primary_refs, preludes, project_timing_action=True)


def _application_timing_findings(frame: Any, declarations: dict[str, Any], refs: dict[str, SourceFact],
                                 primary: set[str], claims: tuple[dict[str, str], ...],
                                 custody_graph: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(frame, dict) or frame.get("kind") != "timing_case":
        return []
    handle = frame.get("handle")
    if not isinstance(handle, str):
        return []
    try:
        preludes = _application_preludes({"frames": [frame], "qualifiers": list(declarations.values())},
                                         refs, primary, claims, custody_graph)
        _validate_application_timing_case(frame, declarations, refs, preludes.get(handle, ()))
    except TimingCaseValidationError as exc:
        return exc.findings
    except (SourceGraphError, KeyError, TypeError, ValueError, AttributeError):
        return []  # Invalid private claims cannot create a positive or guessed geometry.
    return []


def _compile_frames(raw: Any, refs: Mapping[str, SourceFact], primary_refs: set[str],
                    application_preludes: dict[str, tuple[ApplicationPreludeClaim, ...]], *,
                    project_timing_action: bool = False) -> CompiledAssessmentFrames:
    units = _units(refs, primary_refs)
    _fields(raw, {"frames", "qualifiers"}, "invalid_frame_graph_schema")
    if (not isinstance(raw["frames"], list) or not 0 < len(raw["frames"]) <= MAX_GRAPH_ROWS
            or not isinstance(raw["qualifiers"], list) or len(raw["qualifiers"]) > MAX_GRAPH_ROWS):
        raise SourceGraphError("invalid_frame_graph_count")
    declarations: dict[str, dict[str, Any]] = {}
    declared_meanings: dict[str, str] = {}
    for row in raw["qualifiers"]:
        _fields(row, {"handle", "ref", "quote", "role", "effect"}, "invalid_frame_qualifier_schema")
        if (not _handle(row["handle"]) or row["handle"] in declarations
                or not isinstance(row["ref"], str) or row["ref"] not in primary_refs
                or not isinstance(row["role"], str) or row["role"] not in FACET_ROLES
                or row["effect"] not in ("none", "scopes_action")):
            raise SourceGraphError("invalid_frame_qualifier")
        _quote(row["ref"], row["quote"], refs)
        meaning = _hash({key: value for key, value in row.items() if key != "handle"})
        declared_meanings[row["handle"]] = meaning
        declarations[row["handle"]] = row

    atoms: list[dict[str, Any]] = []
    qualifiers: dict[str, dict[str, Any]] = {}
    members: dict[str, list[str]] = {}
    timing_members: dict[str, dict[str, Any]] = {}
    timing_projections: dict[str, dict[str, Any]] = {}
    governance_findings: dict[str, dict[str, Any]] = {}
    used_declarations: set[str] = set()

    def bind(ref: str, quote: Any, role: Any, effect: Any, handles: list[str]) -> None:
        if (not isinstance(role, str) or role not in FACET_ROLES
                or effect not in ("none", "scopes_action", "changes_timing")):
            raise SourceGraphError("invalid_frame_binding")
        _quote(ref, quote, refs)
        # Intern only identical DECLARED facts; no source-driven role inference.
        meaning = _hash({"ref": ref, "quote": quote, "role": role, "effect": effect})
        if meaning not in qualifiers:
            qualifiers[meaning] = {"handle": "q" + str(len(qualifiers) + 1), "ref": ref,
                "quote": quote, "role": role, "effect": effect, "applies_to": []}
        qualifiers[meaning]["applies_to"] = sorted(set(qualifiers[meaning]["applies_to"]) | set(handles))

    def atom(ref: str, piece: Any, dimension: Any, context: Any, *, answers: Any = None) -> str:
        _fields(piece, {"label", "answer"}, "invalid_frame_atom_schema")
        handle = "a" + str(len(atoms) + 1)
        values = [piece["answer"]] if answers is None else answers
        if (not isinstance(values, list) or not 0 < len(values) <= 12
                or any(not isinstance(value, str) or not value.strip() for value in values)):
            raise SourceGraphError("invalid_frame_answers")
        if any(len(value) > 320 for value in values):
            raise SourceGraphError("frame_answer_length_exceeded")
        if isinstance(context, list) and any(value in row["text"] for value in values for row in context
                if isinstance(row, dict) and row.get("ref") == ref and isinstance(row.get("text"), str)):
            raise SourceGraphError("frame_context_discloses_answer")
        atoms.append({"handle": handle, "label": piece["label"], "ref": ref, "dimension": dimension,
            "form": "decision" if answers is None else "all_required", "answers": values, "context": context})
        return handle

    common = {"handle", "kind", "ref", "label", "context", "bindings"}
    extra = {"decision": {"dimension", "answer"}, "checklist": {"dimension", "owner", "leaves"},
             "timing_case": {"fork", "action", "purposes", "branches"}}
    for frame in raw["frames"]:
        if not isinstance(frame, dict) or not isinstance(frame.get("kind"), str) or frame["kind"] not in extra:
            raise SourceGraphError("unsupported_frame_kind")
        _fields(frame, common | extra[frame["kind"]], "invalid_frame_schema")
        handle, ref = frame["handle"], frame["ref"]
        if (not _handle(handle) or handle in members or handle in declarations or not isinstance(ref, str) or ref not in primary_refs
                or not isinstance(frame["label"], str) or not frame["label"].strip() or len(frame["label"]) > 240
                or not isinstance(frame["context"], list)):
            raise SourceGraphError("invalid_frame_identity")
        qhandles = _handles(frame["bindings"], declarations)
        used_declarations.update(qhandles)
        context = frame["context"]
        owned: list[str] = []
        if frame["kind"] == "decision":
            owned.append(atom(ref, {"label": frame["label"], "answer": frame["answer"]}, frame["dimension"], context))
        elif frame["kind"] == "checklist":
            owner = frame["owner"]
            _fields(owner, {"quote", "role", "effect"}, "invalid_checklist_owner")
            if owner["effect"] not in ("none", "scopes_action"):
                raise SourceGraphError("invalid_checklist_owner_effect")
            owned.append(atom(ref, {"label": frame["label"], "answer": ""}, frame["dimension"],
                              context, answers=frame["leaves"]))
            bind(ref, owner["quote"], owner["role"], owner["effect"], owned)
            for finding in checklist_governance_findings(frame, declarations, refs[ref]):
                key = _hash({key: value for key, value in finding.items() if key != "affected_leaves"})
                governance_findings[key] = finding
        else:
            geometry = (_validate_application_timing_case(frame, declarations, dict(refs), application_preludes[handle])
                if handle in application_preludes else validate_timing_case(frame, declarations, dict(refs)))
            fork, pair_spans = geometry.fork, geometry.pair_spans
            effective_action, prefix = geometry.action, geometry.prefix
            if geometry.projection is not None:
                timing_projections[handle] = geometry.projection
            shared = atom(ref, effective_action, "action", context)
            owned.append(shared)
            for purpose in frame["purposes"]:
                phandle = atom(ref, purpose, "outcome", context)
                owned.append(phandle)
                bind(ref, effective_action["answer"], "scope", "none", [phandle])
            # Only timing questions receive their exact effective shared action
            # as zero-credit display context. It distinguishes different actions
            # with the same case selector without leaking a branch's schedule or
            # putting the action's own answer into its assessed target's context.
            branch_context = context + ([{"ref": ref, "text": effective_action["answer"]}]
                if project_timing_action else [])
            peers = [atom(ref, {"label": branch["label"], "answer": branch["answer"]}, "timing",
                          branch_context + [{"ref": ref, "text": branch["selector"]}])
                     for branch in frame["branches"]]
            bind(ref, fork, "timing", "changes_timing", peers)
            timing_members[handle] = {"action": shared, "purposes": owned[1:], "branches": peers}
            owned.extend(peers)
            if prefix is not None:
                bind(ref, prefix, "actor", "none", owned)
        for qhandle in qhandles:
            declaration = declarations[qhandle]
            if declaration["ref"] == ref and any(answer in declaration["quote"] for child in owned
                                                  for answer in atoms[int(child[1:]) - 1]["answers"]):
                raise SourceGraphError("frame_shared_support_contains_answer")
            if frame["kind"] == "timing_case" and declaration["ref"] == ref:
                qstart = refs[ref].value.index(declaration["quote"])
                qend = qstart + len(declaration["quote"])
                fork_start = refs[ref].value.index(frame["fork"])
                if any(fork_start + start < qend and qstart < fork_start + end for start, end, _, _ in pair_spans):
                    raise SourceGraphError("frame_shared_support_is_branch_local")
            bind(declaration["ref"], declaration["quote"], declaration["role"], declaration["effect"], owned)
        members[handle] = owned
    # Temporary aliases are syntax only. bind() already interns exact semantic
    # facts; an unused alias cannot broadcast support or create assessed credit.
    if {declared_meanings[handle] for handle in used_declarations} != set(declared_meanings.values()):
        raise SourceGraphError("orphan_frame_qualifier")
    if governance_findings:
        raise FrameGovernanceError(list(governance_findings.values()))
    compiled = _compile_declared_atoms(atoms, list(qualifiers.values()), refs, primary_refs)
    target_by_o = {row["id"]: row["target_ids"][0] for row in compiled.plan["material_obligations"]}
    links = {handle: tuple(dict.fromkeys(target_by_o[oid] for child in children
                for oid in compiled.obligation_ids[child])) for handle, children in sorted(members.items())}
    target_of = {child: target_by_o[oids[0]] for child, oids in compiled.obligation_ids.items()}
    roles = {handle: {"action": target_of[row["action"]],
                     "purposes": [target_of[child] for child in row["purposes"]],
                     "branches": [target_of[child] for child in row["branches"]]}
             for handle, row in timing_members.items()}
    return CompiledAssessmentFrames(compiled.plan, units, links, roles, timing_projections,
                                    compiled.quote_boundary_normalizations)
