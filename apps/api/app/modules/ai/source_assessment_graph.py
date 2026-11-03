"""LOCAL V87 structural compiler: model semantics once, canonical fields derived.

No model, database or admission. Exact custody is necessary, not semantic proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.modules.ai.assessment_facets import BRANCH_EFFECTS, FACET_ROLES
from app.modules.ai.assessment_obligations import MATERIAL_DIMENSIONS
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_inventory import (
    AuditedSourceInventory,
    InventoryDisposition,
    SourceInventoryError,
    validate_inventory_claims,
)
from app.modules.ai.source_literal import source_context_fields

MAX_GRAPH_ROWS = 96
OBLIGATION_QUOTE_POLICY = "source-quote-boundaries-v1"


class SourceGraphError(ValueError):
    """An invalid graph is diagnostic data, never a partial approved checkpoint."""


@dataclass(frozen=True)
class CompiledAssessmentGraph:
    plan: dict[str, Any]
    inventory_coverage: list[dict[str, Any]]
    claims: tuple[InventoryDisposition, ...]
    quote_boundary_normalizations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class _DeclaredAtoms:
    plan: dict[str, Any]
    obligation_ids: dict[str, list[str]]
    qualifiers: dict[str, dict[str, str]]
    quote_boundary_normalizations: tuple[dict[str, Any], ...] = ()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _sorted(rows: list[Any]) -> list[Any]:
    return sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


def _fields(row: Any, keys: set[str], code: str) -> None:
    if not isinstance(row, dict) or set(row) != keys:
        raise SourceGraphError(code)


def _handle(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is not None


def _handles(value: Any, known: Mapping[str, Any], *, nonempty: bool = False) -> list[str]:
    if (not isinstance(value, list) or len(value) > MAX_GRAPH_ROWS or (nonempty and not value)
            or any(not _handle(item) or item not in known for item in value)
            or len(set(value)) != len(value)):
        raise SourceGraphError("invalid_handle_links")
    return sorted(value)


def _quote(ref: Any, quote: Any, refs: Mapping[str, SourceFact]) -> None:
    if (not isinstance(ref, str) or ref not in refs or not isinstance(quote, str)
            or not quote.strip() or len(quote) > 65536 or refs[ref].value.count(quote) != 1):
        raise SourceGraphError("nonliteral_ambiguous_or_foreign_quote")


def _compile_declared_atoms(raw_atoms: Any, raw_qualifiers: Any,
                            refs: Mapping[str, SourceFact], primary_refs: set[str]) -> _DeclaredAtoms:
    """Shared private canonical compiler; caller owns its separate custody policy."""
    raw = {"atoms": raw_atoms, "qualifiers": raw_qualifiers}
    if (not isinstance(refs, Mapping) or not refs or any(not isinstance(fact, SourceFact) for fact in refs.values())
            or not isinstance(primary_refs, set) or not primary_refs or not primary_refs <= set(refs)):
        raise SourceGraphError("invalid_source_ownership")
    if len({fact.fact_id for fact in refs.values()}) != len(refs):
        raise SourceGraphError("duplicate_source_identity")
    for key in ("atoms", "qualifiers"):
        if not isinstance(raw[key], list) or len(raw[key]) > MAX_GRAPH_ROWS:
            raise SourceGraphError("invalid_graph_count")
    if not raw["atoms"]:
        raise SourceGraphError("missing_assessment_atoms")
    atoms: dict[str, dict[str, Any]] = {}
    for row in raw["atoms"]:
        _fields(row, {"handle", "label", "ref", "dimension", "form", "answers", "context"}, "invalid_atom_schema")
        handle, ref = row["handle"], row["ref"]
        if (not _handle(handle) or handle in atoms or not isinstance(ref, str) or ref not in primary_refs
                or not isinstance(row["label"], str) or not row["label"].strip() or len(row["label"]) > 240
                or not isinstance(row["dimension"], str) or row["dimension"] not in MATERIAL_DIMENSIONS
                or row["form"] not in ("decision", "all_required")):
            raise SourceGraphError("invalid_atom_identity_dimension_or_form")
        answers = row["answers"]
        if (not isinstance(answers, list) or not 0 < len(answers) <= 12
                or any(not isinstance(answer, str) for answer in answers)
                or len(set(answers)) != len(answers)
                or (row["form"] == "decision" and len(answers) != 1)):
            raise SourceGraphError("invalid_atom_answer_shape")
        for answer in answers:
            _quote(ref, answer, refs)
        spans = sorted((refs[ref].value.index(answer), refs[ref].value.index(answer) + len(answer)) for answer in answers)
        if any(right > next_left for (_, right), (next_left, _) in zip(spans, spans[1:], strict=False)):
            raise SourceGraphError("overlapping_all_required_answers")
        if not isinstance(row["context"], list) or len(row["context"]) > 16:
            raise SourceGraphError("invalid_atom_context")
        context = []
        for piece in row["context"]:
            _fields(piece, {"ref", "text"}, "invalid_context_schema")
            cref, text = piece["ref"], piece["text"]
            if (not isinstance(cref, str) or cref not in refs or not isinstance(text, str) or not text.strip()
                    or not any(text in field for field in source_context_fields(refs[cref]))):
                raise SourceGraphError("invalid_context_source")
            context.append(dict(piece))
        if len({_hash(piece) for piece in context}) != len(context):
            raise SourceGraphError("duplicate_context")
        atoms[handle] = dict(row, form="decision" if len(answers) == 1 else row["form"],
                             answers=sorted(answers, key=refs[ref].value.index), context=_sorted(context))

    qualifiers: dict[str, dict[str, Any]] = {}
    bindings: dict[str, list[dict[str, str]]] = {handle: [] for handle in atoms}
    qualifier_meanings: set[str] = set()
    for row in raw["qualifiers"]:
        _fields(row, {"handle", "ref", "quote", "role", "effect", "applies_to"}, "invalid_qualifier_schema")
        handle = row["handle"]
        if (not _handle(handle) or handle in qualifiers
                or not isinstance(row["role"], str) or row["role"] not in FACET_ROLES
                or not isinstance(row["effect"], str) or row["effect"] not in BRANCH_EFFECTS):
            raise SourceGraphError("invalid_qualifier_identity_role_or_effect")
        _quote(row["ref"], row["quote"], refs)
        members = _handles(row["applies_to"], atoms, nonempty=True)
        binding = {"ref": row["ref"], "quote": row["quote"], "role": row["role"], "branch_effect": row["effect"]}
        fingerprint = _hash(binding)
        if fingerprint in qualifier_meanings:
            raise SourceGraphError("duplicate_qualifier_meaning")
        qualifier_meanings.add(fingerprint)
        qualifiers[handle] = binding
        for member in members:
            bindings[member].append(binding)

    targets, obligations = [], []
    normalizations: list[dict[str, Any]] = []
    canonical_meanings: set[str] = set()
    obligation_ids: dict[str, list[str]] = {}
    used_ids: set[str] = set()
    for handle, atom in atoms.items():
        semantic = {key: value for key, value in atom.items() if key not in {"handle", "label"}}
        semantic |= {"source_id": refs[atom["ref"]].fact_id,
                     "source_sha256": hashlib.sha256(refs[atom["ref"]].value.encode()).hexdigest(),
                     "bindings": _sorted(bindings[handle])}
        canonical_meaning = _hash(semantic | {"answers": [answer.strip() for answer in atom["answers"]]})
        if canonical_meaning in canonical_meanings:
            raise SourceGraphError("duplicate_atom_meaning_or_hash_collision")
        canonical_meanings.add(canonical_meaning)
        tid = "T" + _hash(semantic)
        if tid in used_ids:
            raise SourceGraphError("duplicate_atom_meaning_or_hash_collision")
        used_ids.add(tid)
        target = {"id": tid, "description": atom["label"].strip(), "source_refs": [atom["ref"]],
                  "context": atom["context"], "construction_mode": "",
                  "question_format": "full_set" if atom["form"] == "all_required" else "",
                  "answer_components": [{"ref": atom["ref"], "terms": [answer]} for answer in atom["answers"]],
                  "governing_bindings": _sorted(bindings[handle])}
        targets.append(target)
        obligation_ids[handle] = []
        for answer in atom["answers"]:
            canonical_quote = answer.strip()
            if canonical_quote != answer:
                # Raw answer custody was checked above. The consumer already
                # canonicalizes target terms; material quotes must agree without
                # changing submitted answers, source bytes or target identities.
                # Recheck uniqueness: padding must never select an occurrence.
                _quote(atom["ref"], canonical_quote, refs)
            oid = "O" + _hash({"target_id": tid, "ref": atom["ref"], "quote": canonical_quote, "dimension": atom["dimension"]})
            if oid in used_ids:
                raise SourceGraphError("obligation_hash_collision")
            used_ids.add(oid)
            obligation_ids[handle].append(oid)
            obligations.append({"id": oid, "ref": atom["ref"], "quote": canonical_quote, "dimension": atom["dimension"],
                                "target_ids": [tid], "evidence_level": "operational_decision"})
            if canonical_quote != answer:
                source = refs[atom["ref"]]
                original_start = source.value.index(answer)
                canonical_start = original_start + len(answer) - len(answer.lstrip())
                normalizations.append({"policy": OBLIGATION_QUOTE_POLICY, "ref": atom["ref"],
                    "source_id": source.fact_id, "source_sha256": hashlib.sha256(source.value.encode()).hexdigest(),
                    "atom_handle": handle, "target_id": tid, "obligation_id": oid,
                    "original_quote_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                    "canonical_quote_sha256": hashlib.sha256(canonical_quote.encode()).hexdigest(),
                    "original_span": {"start": original_start, "end": original_start + len(answer)},
                    "canonical_span": {"start": canonical_start, "end": canonical_start + len(canonical_quote)},
                    "semantic_approval": False})

    source_order = {ref: index for index, ref in enumerate(refs)}
    targets.sort(key=lambda row: (source_order[row["source_refs"][0]],
        refs[row["source_refs"][0]].value.index(row["answer_components"][0]["terms"][0]), row["id"]))
    target_order = {row["id"]: index for index, row in enumerate(targets)}
    obligations.sort(key=lambda row: (target_order[row["target_ids"][0]], refs[row["ref"]].value.index(row["quote"]), row["id"]))
    return _DeclaredAtoms({"targets": targets, "material_obligations": obligations, "excluded_units": []},
                          obligation_ids, qualifiers, tuple(normalizations))


def compile_assessment_graph(raw: Any, audited: AuditedSourceInventory,
                              refs: Mapping[str, SourceFact], primary_refs: set[str]) -> CompiledAssessmentGraph:
    """V87 still conserves inventory spans; the private compiler grants no approval."""
    _fields(raw, {"atoms", "qualifiers", "coverage"}, "invalid_graph_schema")
    if not isinstance(audited, AuditedSourceInventory):
        raise SourceGraphError("invalid_audited_inventory")
    if not isinstance(raw["coverage"], list) or len(raw["coverage"]) > MAX_GRAPH_ROWS:
        raise SourceGraphError("invalid_graph_count")
    compiled = _compile_declared_atoms(raw["atoms"], raw["qualifiers"], refs, primary_refs)
    atoms, obligation_ids, qualifiers = compiled.obligation_ids, compiled.obligation_ids, compiled.qualifiers
    obligations = compiled.plan["material_obligations"]
    coverage = []
    used_atoms: set[str] = set()
    for row in raw["coverage"]:
        _fields(row, {"inventory_id", "disposition", "atoms", "qualifiers"}, "invalid_coverage_schema")
        owners = _handles(row["atoms"], atoms)
        qhandles = _handles(row["qualifiers"], qualifiers)
        disposition = row["disposition"]
        if (not isinstance(disposition, str) or disposition not in {"assessed", "qualification", "reference", "unresolved"}
                or (disposition == "assessed" and not owners)
                or (disposition != "assessed" and owners)
                or (disposition == "qualification" and not qhandles)
                or (disposition in {"reference", "unresolved"} and qhandles)):
            raise SourceGraphError("invalid_disposition_credit")
        used_atoms.update(owners)
        qspans = [{"ref": qualifiers[q]["ref"], "quote": qualifiers[q]["quote"]} for q in qhandles]
        coverage.append({"inventory_id": row["inventory_id"], "disposition": disposition,
                         "obligation_ids": sorted(oid for owner in owners for oid in obligation_ids[owner]),
                         "qualification_bindings": _sorted(qspans)})
    if used_atoms != set(atoms):
        raise SourceGraphError("orphan_assessment_atom")
    try:
        claims = validate_inventory_claims(audited, coverage,
            [{key: row[key] for key in ("id", "ref", "quote")} for row in obligations],
            {ref: (fact.fact_id, fact.value) for ref, fact in refs.items()})
    except SourceInventoryError as exc:
        raise SourceGraphError("inventory_claim_" + str(exc)) from exc
    if {source.ref for source in audited.snapshot.sources} != primary_refs:
        raise SourceGraphError("inventory_primary_universe_changed")
    coverage = sorted(coverage, key=lambda row: row["inventory_id"])
    return CompiledAssessmentGraph(compiled.plan, coverage, tuple(sorted(claims, key=lambda row: row.inventory_id)),
                                   compiled.quote_boundary_normalizations)
