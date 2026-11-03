"""Server-owned bridge from admitted source targets to final teaching bodies.

The two existing critics supply independent meaning judgments. This adapter only
compiles their closed inventory and rebinds evidence; it makes no model calls.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from app.modules.ai.assessment_components import ComponentRequirement, OwnedComponent
from app.modules.ai.component_surface_comparison import lexical_span_is_complete
from app.modules.ai.final_teaching_eligibility import (
    FinalTeachingCatalog,
    FinalTeachingRoleResult,
    TeachingCandidateIdentity,
    TeachingRequirement,
    TeachingSourceBinding,
    TeachingSourceContext,
    bind_final_teaching_role,
    derive_teaching_inventory_contract,
    teaching_entry_supports_requirement,
)

if TYPE_CHECKING:
    from app.modules.ai.lesson_cycle import Candidate, LearningTarget, LessonPacket, ReviewedQuestion


def teaching_requirements(
    targets: Sequence[LearningTarget], components: Sequence[ComponentRequirement],
    source_fact_ids: Sequence[tuple[str, str]],
) -> tuple[TeachingRequirement, ...]:
    """Preserve native component OR alternatives, AND rows and governing facets."""
    facts = dict(source_fact_ids)
    requirements = [TeachingRequirement(
        component, "action", tuple(dict.fromkeys(
            facts[row.source_id] for row in component.alternatives if row.source_id in facts)))
        for component in components]
    for target in targets:
        seen: set[tuple[str, str, str]] = set()
        owner_fact_ids = tuple(dict.fromkeys(facts[fid] for owners in target.component_source_ids
                                             for fid in owners if fid in facts))
        for binding in (*target.original_context_bindings, *target.qualification_bindings):
            owner, quote, facet = (binding.get(key) for key in ("source_id", "quote", "facet_id"))
            if not isinstance(owner, str) or not isinstance(quote, str) or not isinstance(facet, str):
                continue  # Native packet validation owns malformed planner data.
            key = (owner, quote, facet)
            if key in seen:
                continue
            seen.add(key)
            requirements.append(TeachingRequirement(
                ComponentRequirement(target.target_id, f"{target.target_id}:T{len(seen)}",
                                     (OwnedComponent(owner, quote),), False),
                "condition" if binding.get("role") in {"condition", "exception", "timing", "scope"} else "action",
                (facts[owner],) if owner in facts else (),
                owner_fact_ids=owner_fact_ids,
            ))
    return tuple(requirements)


def teaching_source_contexts(packet: LessonPacket, target_ids: Sequence[str]) -> tuple[TeachingSourceContext, ...]:
    bindings: dict[str, list[TeachingSourceBinding]] = {}
    facts_by_id = {fact.fact_id: fact for fact in packet.teaching_source_facts}
    fact_owners = dict(packet.teaching_source_fact_ids)
    for target in packet.targets:
        if target.target_id not in target_ids:
            continue
        for value in (*target.original_context_bindings, *target.qualification_bindings):
            row = TeachingSourceBinding(**{key: value[key] for key in (
                "facet_id", "source_id", "quote", "role", "branch_effect", "quote_start", "quote_end")})
            owned = bindings.setdefault(row.source_id, [])
            if row not in owned:
                owned.append(row)
    return tuple(TeachingSourceContext(
        row.source_id, row.source_id, row.original_text or row.text,
        tuple(bindings.get(row.source_id, ())), facts_by_id.get(fact_owners.get(row.source_id, "")))
        for row in packet.sources)


def packet_teaching_requirements(packet: LessonPacket, target_ids: Sequence[str],
                                 components: Sequence[ComponentRequirement]) -> tuple[TeachingRequirement, ...]:
    return teaching_requirements(tuple(row for row in packet.targets if row.target_id in target_ids),
                                 components, packet.teaching_source_fact_ids)


def teaching_role(
    packet: LessonPacket, question: Candidate | ReviewedQuestion, target_ids: Sequence[str], key: int,
    rows: object, *, role: Literal["review", "counter"], components: Sequence[ComponentRequirement],
) -> FinalTeachingRoleResult:
    requirements = packet_teaching_requirements(packet, target_ids, components)
    ids = {row.component.component_id for row in requirements}
    all_ids = {row.component.component_id for row in teaching_requirements(
        tuple(target for target in packet.targets if target.target_id in question.target_ids),
        tuple(ComponentRequirement(target.target_id, f"{target.target_id}:C{index}",
            tuple(OwnedComponent(owner, text) for text, owner in zip(group, owners, strict=True)),
            target.question_format == "full_set")
            for target in packet.targets if target.target_id in question.target_ids and target.component_source_ids
            for index, (group, owners) in enumerate(zip(target.answer_requirements, target.component_source_ids, strict=True), 1)),
        packet.teaching_source_fact_ids)}
    valid_inventory = (isinstance(rows, list | tuple)
        and all(isinstance(row, dict) and isinstance(row.get("requirement_id"), str)
                and isinstance(row.get("teaching_quotes"), dict) for row in rows)
        and len(rows) == len(all_ids) and {row.get("requirement_id") for row in rows} == all_ids)
    # A critic may legitimately narrow target coverage. Keep exact existing rows
    # for retained requirements; never synthesize a missing vote for a new target.
    projected = [row for row in rows if isinstance(row, dict) and row.get("requirement_id") in ids] \
        if valid_inventory and isinstance(rows, list | tuple) else None
    return bind_final_teaching_role(
        packet.teaching_catalogs or (), requirements, projected, role=role,
        candidate=TeachingCandidateIdentity(packet.lesson_id, question.question_id,
                                            tuple(row.target_id for row in packet.targets if row.target_id in target_ids),
                                            question.text, question.options, key),
        source_contexts=teaching_source_contexts(packet, target_ids),
    )


def _literal_quote_addresses(requirement: TeachingRequirement,
                             catalogs: Sequence[FinalTeachingCatalog], *,
                             city_inventory: bool = False) -> list[dict[str, str]]:
    """Locate literal components; an address is never a meaning or key vote."""
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for catalog in catalogs:
        for entry in catalog.entries:
            if not teaching_entry_supports_requirement(entry, requirement):
                continue
            for alternative in requirement.component.alternatives:
                query = (re.sub(r"\bг\.\s*", "г. ", alternative.text, flags=re.I)
                         if city_inventory else alternative.text)
                parts = query.split()
                if not parts:
                    continue
                pattern = re.escape(parts[0])
                for previous, part in zip(parts, parts[1:], strict=False):
                    separator = r"\s*" if city_inventory and previous.casefold() == "г." else r"\s+"
                    pattern += separator + re.escape(part)
                if parts[0][0].isalnum():
                    pattern = r"(?<!\w)" + pattern
                if parts[-1][-1].isalnum():
                    pattern += r"(?!\w)"
                matches = list(re.finditer(pattern, entry.body, re.I))
                if len(matches) != 1:
                    continue
                quote = matches[0].group()
                if not lexical_span_is_complete(entry.body, matches[0].start(), matches[0].end()):
                    continue
                address = (entry.ref_id, quote)
                if address not in seen:
                    seen.add(address)
                    result.append({"teaching_ref": entry.ref_id, "quote": quote})
                    if len(result) == 4:
                        return result
    return result


def teaching_wire(packet: LessonPacket, target_ids: Sequence[str],
                  components: Sequence[ComponentRequirement], *, blind: bool = False) -> dict[str, Any]:
    requirements = packet_teaching_requirements(packet, target_ids, components)
    contexts = teaching_source_contexts(packet, target_ids)
    inventories = {}
    city_inventory_ids: set[str] = set()
    for requirement in requirements:
        contract = derive_teaching_inventory_contract(requirement, contexts)
        if contract is not None:
            city_inventory_ids.add(requirement.component.component_id)
        if contract is not None and contract.needs_semantic_identity:
            inventories[requirement.component.component_id] = {
                "kind": contract.kind,
                "items": [{"item_id": item.item_id, "source_text": item.source_text}
                          for item in contract.items],
            }
    return {
        "requirements": [{"requirement_id": row.component.component_id,
            "target_id": row.component.target_id, "kind": row.kind,
            **({"inventory_contract": inventories[row.component.component_id]}
               if row.component.component_id in inventories else {}),
            **({"quote_candidates": _literal_quote_addresses(row, packet.teaching_catalogs or (),
                    city_inventory=row.component.component_id in city_inventory_ids)}
               if not blind or row.kind != "action" else {}),
            **({} if blind and row.kind == "action" else {"alternatives": [
                {"source_id": value.source_id, "text": value.text} for value in row.component.alternatives]})}
            for row in requirements],
    }


def final_teaching_wire(catalogs: Sequence[FinalTeachingCatalog]) -> dict[str, Any]:
    return {"bodies": [{"ref": entry.ref_id, "lesson_id": entry.lesson_id,
                       "text": entry.body, "requires_refs": list(entry.dependency_refs)}
                      for catalog in catalogs for entry in catalog.entries],
            "custody": [{"lesson_id": row.lesson_id, "binding": row.surface_binding_sha256,
                         "gaps": [asdict(gap) for gap in row.gaps]} for row in catalogs],
            "membership_is_not_meaning": True}
