"""Bind assessment teaching evidence only to exact final learner-visible bodies.

This module is pure. It neither calls a model nor authorizes a question, answer
key, course, or publication decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypeGuard, cast

from app.modules.ai.assessment_components import MAX_REQUIREMENTS, ComponentRequirement, OwnedComponent
from app.modules.ai.assessment_facets import BRANCH_EFFECTS, FACET_ROLES
from app.modules.ai.assessment_preservation import (
    _PROTECTED_LITERALS,
    PreservationIssue,
    _word_info,
    component_preservation_issue,
)
from app.modules.ai.component_surface_comparison import (
    WholeComponentComparisonReceipt,
    bind_whole_component_comparison,
    lexical_span_is_complete,
    whole_component_comparison_receipt_valid,
)
from app.modules.ai.conditional_connective import (
    ConditionalConnectiveReceipt,
    conditional_connective_receipt,
    conditional_connective_receipt_valid,
)
from app.modules.ai.critical_preservation import critical_preservation_status
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.provider_engine import LessonSurfaceRenderScope
from app.modules.ai.evidence_engine.provider_models import GroundedBlock
from app.modules.ai.lesson_surface_review import (
    LessonSurfaceBlockCustody,
    PreparedLessonSurfaceReview,
)
from app.modules.ai.teaching_row_identity import (
    RowIdentityRestatementReceipt,
    bind_row_identity_restatement,
    row_identity_restatement_valid,
)

FINAL_TEACHING_ELIGIBILITY_POLICY = "final-teaching-eligibility-v9"
MAX_DIAGNOSTIC_REASON_CHARS = 300
TEACHING_RELATIONS = frozenset({"preserved", "missing", "unknown"})
TEACHING_ROLE_FIELDS = frozenset({"requirement_id", "relation", "teaching_refs", "reason"})
TEACHING_ROLE_QUOTE_FIELDS = TEACHING_ROLE_FIELDS | {"teaching_quotes"}
TEACHING_ROLE_INVENTORY_FIELDS = TEACHING_ROLE_QUOTE_FIELDS | {"inventory_matches"}
TEACHING_INVENTORY_MATCH_FIELDS = frozenset(
    {"item_id", "teaching_ref", "learner_quote", "relation", "reason"}
)
TEACHING_INVENTORY_RELATIONS = frozenset({"same_entity", "different", "unknown"})
_OPERATOR_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class TeachingEligibilityGap:
    code: str
    block_id: str = ""
    requirement_id: str = ""


@dataclass(frozen=True, slots=True)
class TeachingBlockRef:
    ref_id: str
    lesson_id: str
    block_id: str
    block_index: int
    fact_ids: tuple[str, ...]
    heading: str
    body: str
    body_start: int
    body_end: int
    body_sha256: str
    dependency_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupportedTeachingBlockRef(TeachingBlockRef):
    """Separately attributed support; never an owned-fact coverage list."""

    supporting_fact_ids: tuple[str, ...]
    owner_support_links: tuple[tuple[str, str], ...]
    support_binding_sha256: str


def teaching_entry_supports_requirement(entry: TeachingBlockRef, requirement: TeachingRequirement) -> bool:
    eligible = set(requirement.eligible_fact_ids)
    if set(entry.fact_ids) & eligible:
        return True
    return (requirement.kind == "condition" and isinstance(entry, SupportedTeachingBlockRef)
            and any(owner in requirement.owner_fact_ids and owner in entry.fact_ids
                    and support in eligible and support in entry.supporting_fact_ids
                    for owner, support in entry.owner_support_links))


@dataclass(frozen=True, slots=True)
class FinalTeachingCatalog:
    policy: str
    lesson_id: str
    lesson_sha256: str
    content_sha256: str
    custody_sha256: str
    surface_binding_sha256: str
    entries: tuple[TeachingBlockRef, ...]
    gaps: tuple[TeachingEligibilityGap, ...]


@dataclass(frozen=True, slots=True)
class TeachingSourceBinding:
    facet_id: str
    source_id: str
    quote: str
    role: str
    branch_effect: str
    quote_start: int
    quote_end: int


@dataclass(frozen=True, slots=True)
class TeachingSourceContext:
    source_id: str
    source_ref: str
    text: str
    governing_bindings: tuple[TeachingSourceBinding, ...]
    source_fact: SourceFact | None = None


@dataclass(frozen=True, slots=True)
class TeachingRequirement:
    component: ComponentRequirement
    kind: Literal["action", "condition"]
    eligible_fact_ids: tuple[str, ...]
    depends_on_requirement_ids: tuple[str, ...] = ()
    owner_fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TeachingCandidateIdentity:
    lesson_id: str
    question_id: str
    target_ids: tuple[str, ...]
    stem: str
    options: tuple[str, ...]
    selected_index: int


@dataclass(frozen=True, slots=True)
class TeachingRoleFailure:
    code: str
    requirement_id: str = ""


@dataclass(frozen=True, slots=True)
class BoundTeachingQuote:
    ref_id: str
    text: str
    quote_start: int
    quote_end: int
    quote_sha256: str


@dataclass(frozen=True, slots=True)
class TeachingInventoryItem:
    item_id: str
    source_id: str
    source_start: int
    source_end: int
    source_text: str
    source_text_sha256: str


@dataclass(frozen=True, slots=True)
class TeachingInventoryContract:
    requirement_id: str
    kind: Literal["city_list"]
    source_id: str
    source_sha256: str
    governing_prefix: str
    governing_prefix_start: int
    governing_prefix_end: int
    governing_prefix_sha256: str
    items: tuple[TeachingInventoryItem, ...]
    needs_semantic_identity: bool
    binding_sha256: str


@dataclass(frozen=True, slots=True)
class TeachingInventoryIdentityEvidence:
    role: Literal["review", "counter"]
    requirement_id: str
    item_id: str
    source_id: str
    source_start: int
    source_end: int
    source_text_sha256: str
    teaching_ref: str
    body_sha256: str
    learner_quote: str
    learner_start: int
    learner_end: int
    learner_quote_sha256: str
    candidate_sha256: str
    contract_binding_sha256: str
    relation: Literal["same_entity", "different", "unknown"]
    reason: str
    binding_sha256: str


@dataclass(frozen=True, slots=True)
class TeachingNativeProof:
    mode: Literal["exact_context_partition", "typed_closed_inventory", "canonical_direct_component", "strict_component_restatement", "conditional_connective_restatement", "source_row_identity_restatement"]
    source_id: str
    source_start: int
    source_end: int
    source_sha256: str
    source_interval_sha256: str
    component_start: int
    component_end: int
    learner_ref_id: str
    learner_quote_start: int
    learner_quote_end: int
    learner_quote_sha256: str
    covered_requirement_ids: tuple[str, ...]
    inventory_items: tuple[tuple[str, str], ...]
    binding_sha256: str
    component_comparison: WholeComponentComparisonReceipt | None = None
    conditional_connective: ConditionalConnectiveReceipt | None = None
    row_identity: RowIdentityRestatementReceipt | None = None


@dataclass(frozen=True, slots=True)
class BoundTeachingRequirement:
    role: Literal["review", "counter"]
    target_id: str
    requirement_id: str
    relation: Literal["preserved", "missing", "unknown"]
    teaching_refs: tuple[str, ...]
    teaching_quotes: tuple[BoundTeachingQuote, ...]
    body_sha256s: tuple[str, ...]
    reason: str
    native_proof: TeachingNativeProof | None
    inventory_matches: tuple[TeachingInventoryIdentityEvidence, ...]
    binding_sha256: str


@dataclass(frozen=True, slots=True)
class FinalTeachingRoleResult:
    policy: str
    role: str
    candidate_sha256: str
    source_sha256: str
    surface_registry_sha256: str
    evidence: tuple[BoundTeachingRequirement, ...]
    failures: tuple[TeachingRoleFailure, ...]
    negative_requirement_ids: tuple[str, ...]
    binding_sha256: str


@dataclass(frozen=True, slots=True)
class FinalTeachingAgreement:
    requirement_ids: tuple[str, ...]
    binding_sha256: str
    failures: tuple[TeachingRoleFailure, ...]


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _sequence(value: object) -> TypeGuard[Sequence[Any]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _empty_catalog(
    lesson_id: str,
    lesson_sha256: str,
    content_sha256: str,
    code: str,
) -> FinalTeachingCatalog:
    gaps = (TeachingEligibilityGap(code),)
    binding = _digest({
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "lesson_id": lesson_id,
        "lesson_sha256": lesson_sha256,
        "content_sha256": content_sha256,
        "custody_sha256": "",
        "entries": [],
        "gaps": [asdict(row) for row in gaps],
    })
    return FinalTeachingCatalog(
        FINAL_TEACHING_ELIGIBILITY_POLICY,
        lesson_id,
        lesson_sha256,
        content_sha256,
        "",
        binding,
        (),
        gaps,
    )


def derive_final_teaching_catalog(
    *,
    lesson: LessonDraft,
    prepared: PreparedLessonSurfaceReview,
    surface_scope: LessonSurfaceRenderScope,
    final_blocks: Sequence[GroundedBlock],
) -> FinalTeachingCatalog:
    """Derive addressable teaching bodies from fresh block custody and final text."""

    if not isinstance(lesson, LessonDraft) or not isinstance(lesson.content, str):
        return _empty_catalog("", _digest(""), _digest(""), "invalid_final_lesson")
    lesson_sha256 = _digest(asdict(lesson))
    content_sha256 = _digest(lesson.content)
    if (
        not isinstance(prepared, PreparedLessonSurfaceReview)
        or not isinstance(surface_scope, LessonSurfaceRenderScope)
        or not isinstance(surface_scope.custody, LessonSurfaceBlockCustody)
        or prepared.lesson_id != lesson.lesson_id
        or surface_scope.custody.lesson_id != lesson.lesson_id
        or surface_scope.custody.preparation_sha256 != prepared.preparation_sha256
        or not _sequence(final_blocks)
        or any(not isinstance(block, GroundedBlock) for block in final_blocks)
    ):
        return _empty_catalog(
            lesson.lesson_id,
            lesson_sha256,
            content_sha256,
            "invalid_surface_custody",
        )

    reconstructed = "\n\n".join(
        f"### {block.heading}\n\n{block.text}" for block in final_blocks
    )
    if reconstructed != lesson.content:
        return _empty_catalog(
            lesson.lesson_id,
            lesson_sha256,
            content_sha256,
            "final_surface_mismatch",
        )
    if any(
        block.lesson_id != lesson.lesson_id
        or not isinstance(block.heading, str)
        or not block.heading.strip()
        or not isinstance(block.text, str)
        or not block.text.strip()
        or not isinstance(block.fact_ids, tuple)
        or not block.fact_ids
        or len(block.fact_ids) != len(set(block.fact_ids))
        for block in final_blocks
    ):
        return _empty_catalog(
            lesson.lesson_id,
            lesson_sha256,
            content_sha256,
            "invalid_final_block",
        )

    candidate_by_id = {
        block["block_id"]: block
        for group in prepared.request_payload["groups"]
        for block in group["candidate_blocks"]
    }
    custody = surface_scope.custody
    group_by_block = {
        block_id: group
        for group in prepared.groups
        for block_id in group.block_ids
    }
    receipts = {receipt.block_id: receipt for receipt in custody.receipts}
    healthy_ids = tuple(custody.healthy_block_ids)
    if (
        custody.policy != prepared.policy
        or custody.candidate_sha256 != _digest([
            group.candidate_sha256 for group in prepared.groups
        ])
        or len(healthy_ids) != len(set(healthy_ids))
        or set(healthy_ids) != set(receipts)
        or any(block_id not in candidate_by_id for block_id in healthy_ids)
        or any(
            receipt.block_id not in group_by_block
            or receipt.lesson_id != lesson.lesson_id
            or receipt.request_alias != group_by_block[receipt.block_id].request_alias
            or receipt.source_sha256 != group_by_block[receipt.block_id].source_sha256
            or receipt.candidate_sha256 != _digest(candidate_by_id[receipt.block_id])
            or receipt.group_sha256 != group_by_block[receipt.block_id].group_sha256
            or receipt.preparation_sha256 != prepared.preparation_sha256
            or receipt.raw_review_sha256 != custody.raw_review_sha256
            or not all((
                receipt.entailed,
                receipt.conditions_exceptions_preserved,
                receipt.modality_negation_preserved,
                receipt.no_invented_claims,
                receipt.order_preserved,
                receipt.readable,
                receipt.grammatical,
                receipt.ocr_clean,
                receipt.instructional_structure,
            ))
            for receipt in custody.receipts
        )
    ):
        return _empty_catalog(
            lesson.lesson_id,
            lesson_sha256,
            content_sha256,
            "invalid_healthy_inventory",
        )

    used_final_indexes: set[int] = set()
    mapped: list[tuple[str, int, GroundedBlock, int, int]] = []
    gaps: list[TeachingEligibilityGap] = [
        TeachingEligibilityGap("surface_" + gap.code, gap.block_id)
        for gap in custody.gaps
    ] + [
        TeachingEligibilityGap("surface_parent_group_unproved", group_id)
        for group_id in custody.parent_group_gaps
    ]
    for block_id in healthy_ids:
        receipt = receipts[block_id]
        candidate = candidate_by_id[block_id]
        reviewed_fact_ids = surface_scope.reviewed_sources.get(receipt.block_index)
        group = group_by_block[block_id]
        matches = [
            (index, block)
            for index, block in enumerate(final_blocks)
            if index not in used_final_indexes
            and block.heading == candidate["heading"]
            and block.text == candidate["text"]
            and reviewed_fact_ids is not None
            and tuple(reviewed_fact_ids) == group.fact_ids
            and set(block.fact_ids) == set(reviewed_fact_ids)
        ]
        if len(matches) != 1:
            gaps.append(TeachingEligibilityGap("final_block_identity_unproved", block_id))
            continue
        final_index, final_block = matches[0]
        used_final_indexes.add(final_index)
        prefix = "\n\n".join(
            f"### {block.heading}\n\n{block.text}" for block in final_blocks[:final_index]
        )
        fragment_prefix = f"### {final_block.heading}\n\n"
        fragment_start = len(prefix) + (2 if final_index else 0)
        body_start = fragment_start + len(fragment_prefix)
        body_end = body_start + len(final_block.text)
        if lesson.content[body_start:body_end] != final_block.text:
            gaps.append(TeachingEligibilityGap("final_body_span_unproved", block_id))
            continue
        mapped.append((block_id, final_index, final_block, body_start, body_end))

    aliases = {
        block_id: "T" + _digest({
            "lesson_id": lesson.lesson_id,
            "block_id": block_id,
            "body": block.text,
        })[:12]
        for block_id, _final_index, block, _body_start, _body_end in mapped
    }
    entries: list[TeachingBlockRef] = []
    for block_id, final_index, block, body_start, body_end in mapped:
        receipt = receipts[block_id]
        if any(dependency not in aliases for dependency in receipt.depends_on_block_ids):
            gaps.append(TeachingEligibilityGap("final_block_dependency_open", block_id))
            continue
        entries.append(TeachingBlockRef(
            ref_id=aliases[block_id],
            lesson_id=lesson.lesson_id,
            block_id=block_id,
            block_index=final_index,
            fact_ids=block.fact_ids,
            heading=block.heading,
            body=block.text,
            body_start=body_start,
            body_end=body_end,
            body_sha256=hashlib.sha256(block.text.encode()).hexdigest(),
            dependency_refs=tuple(aliases[value] for value in receipt.depends_on_block_ids),
        ))

    entry_ids = {entry.block_id for entry in entries}
    changed = True
    while changed:
        changed = False
        for entry in tuple(entries):
            dependencies = receipts[entry.block_id].depends_on_block_ids
            if any(dependency not in entry_ids for dependency in dependencies):
                entries.remove(entry)
                entry_ids.remove(entry.block_id)
                gaps.append(TeachingEligibilityGap("final_block_dependency_open", entry.block_id))
                changed = True

    custody_sha256 = _digest(asdict(custody))
    binding_body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "lesson_id": lesson.lesson_id,
        "lesson_sha256": lesson_sha256,
        "content_sha256": content_sha256,
        "custody_sha256": custody_sha256,
        "entries": [asdict(row) for row in entries],
        "gaps": [asdict(row) for row in gaps],
    }
    return FinalTeachingCatalog(
        policy=FINAL_TEACHING_ELIGIBILITY_POLICY,
        lesson_id=lesson.lesson_id,
        lesson_sha256=lesson_sha256,
        content_sha256=content_sha256,
        custody_sha256=custody_sha256,
        surface_binding_sha256=_digest(binding_body),
        entries=tuple(entries),
        gaps=tuple(gaps),
    )


def _catalog_valid(catalog: object) -> bool:
    if not isinstance(catalog, FinalTeachingCatalog) or catalog.policy != FINAL_TEACHING_ELIGIBILITY_POLICY:
        return False
    ref_ids = [row.ref_id for row in catalog.entries]
    block_ids = [row.block_id for row in catalog.entries]
    if (
        not catalog.lesson_id
        or not catalog.lesson_sha256
        or not catalog.content_sha256
        or not catalog.custody_sha256
        or len(ref_ids) != len(set(ref_ids))
        or len(block_ids) != len(set(block_ids))
        or any(
            row.lesson_id != catalog.lesson_id
            or not row.heading.strip()
            or not row.body.strip()
            or hashlib.sha256(row.body.encode()).hexdigest() != row.body_sha256
            or not 0 <= row.body_start < row.body_end
            or row.body_end - row.body_start != len(row.body)
            or any(dependency not in ref_ids for dependency in row.dependency_refs)
            or (isinstance(row, SupportedTeachingBlockRef) and (
                not isinstance(row.supporting_fact_ids, tuple) or not row.supporting_fact_ids
                or any(not isinstance(fid, str) or not fid for fid in row.supporting_fact_ids)
                or len(set(row.supporting_fact_ids)) != len(row.supporting_fact_ids)
                or bool(set(row.supporting_fact_ids) & set(row.fact_ids))
                or not isinstance(row.owner_support_links, tuple) or not row.owner_support_links
                or any(not isinstance(link, tuple) or len(link) != 2
                       or not isinstance(link[0], str) or not isinstance(link[1], str) or link[0] not in row.fact_ids
                       or link[1] not in row.supporting_fact_ids for link in row.owner_support_links)
                or len(set(row.owner_support_links)) != len(row.owner_support_links)
                or not isinstance(row.support_binding_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", row.support_binding_sha256)))
            for row in catalog.entries
        )
    ):
        return False
    binding_body = {
        "policy": catalog.policy,
        "lesson_id": catalog.lesson_id,
        "lesson_sha256": catalog.lesson_sha256,
        "content_sha256": catalog.content_sha256,
        "custody_sha256": catalog.custody_sha256,
        "entries": [asdict(row) for row in catalog.entries],
        "gaps": [asdict(row) for row in catalog.gaps],
    }
    return _digest(binding_body) == catalog.surface_binding_sha256


def catalog_matches_final_content(
    catalog: FinalTeachingCatalog,
    *,
    lesson_id: str,
    content: str,
) -> bool:
    """Revalidate a catalog against the exact current learner-visible body."""

    return (
        isinstance(lesson_id, str)
        and bool(lesson_id)
        and isinstance(content, str)
        and _catalog_valid(catalog)
        and catalog.lesson_id == lesson_id
        and catalog.content_sha256 == _digest(content)
    )


def _candidate_sha256(candidate: object) -> str | None:
    if (
        not isinstance(candidate, TeachingCandidateIdentity)
        or any(not isinstance(value, str) or not value.strip()
               for value in (candidate.lesson_id, candidate.question_id, candidate.stem))
        or not isinstance(candidate.target_ids, tuple)
        or not candidate.target_ids
        or any(not isinstance(value, str) or not value for value in candidate.target_ids)
        or len(candidate.target_ids) != len(set(candidate.target_ids))
        or not isinstance(candidate.options, tuple)
        or len(candidate.options) < 2
        or any(not isinstance(value, str) or not value.strip() for value in candidate.options)
        or type(candidate.selected_index) is not int
        or not 0 <= candidate.selected_index < len(candidate.options)
    ):
        return None
    return _digest(asdict(candidate))


def _validated_sources(
    sources: object,
) -> tuple[dict[str, TeachingSourceContext], tuple[TeachingRoleFailure, ...]]:
    if not _sequence(sources):
        return {}, (TeachingRoleFailure("invalid_teaching_source_contexts"),)
    indexed: dict[str, TeachingSourceContext] = {}
    for source in sources:
        if (
            not isinstance(source, TeachingSourceContext)
            or not source.source_id
            or not source.source_ref
            or not source.text.strip()
            or source.source_id in indexed
            or not isinstance(source.governing_bindings, tuple)
            or (source.source_fact is not None and (
                not isinstance(source.source_fact, SourceFact)
                or source.source_fact.value != source.text
                or hashlib.sha256(json.dumps(asdict(source.source_fact), ensure_ascii=False,
                    sort_keys=True).encode()).hexdigest() != source.source_id))
        ):
            return {}, (TeachingRoleFailure("invalid_teaching_source_contexts"),)
        for binding in source.governing_bindings:
            if (
                not isinstance(binding, TeachingSourceBinding)
                or binding.source_id != source.source_id
                or binding.role not in FACET_ROLES
                or binding.branch_effect not in BRANCH_EFFECTS
                or not binding.facet_id
                or not binding.quote
                or type(binding.quote_start) is not int
                or type(binding.quote_end) is not int
                or not 0 <= binding.quote_start < binding.quote_end <= len(source.text)
                or source.text[binding.quote_start:binding.quote_end] != binding.quote
            ):
                return {}, (TeachingRoleFailure("invalid_teaching_source_binding"),)
        indexed[source.source_id] = source
    return indexed, ()


def _validated_requirements(
    requirements: object,
    sources: dict[str, TeachingSourceContext],
    candidate: TeachingCandidateIdentity,
) -> tuple[dict[str, TeachingRequirement], tuple[TeachingRoleFailure, ...]]:
    if (not _sequence(requirements) or not requirements
            or len(requirements) > MAX_REQUIREMENTS):
        return {}, (TeachingRoleFailure("invalid_teaching_requirements"),)
    indexed: dict[str, TeachingRequirement] = {}
    failures: list[TeachingRoleFailure] = []
    for requirement in requirements:
        if not isinstance(requirement, TeachingRequirement) or requirement.kind not in {"action", "condition"}:
            failures.append(TeachingRoleFailure("invalid_teaching_requirement"))
            continue
        component = requirement.component
        requirement_id = component.component_id if isinstance(component, ComponentRequirement) else ""
        if (
            not isinstance(component, ComponentRequirement)
            or not component.target_id
            or component.target_id not in candidate.target_ids
            or not requirement_id
            or requirement_id in indexed
            or not isinstance(component.alternatives, tuple)
            or not component.alternatives
            or not isinstance(component.full_set, bool)
            or not isinstance(requirement.eligible_fact_ids, tuple)
            or not requirement.eligible_fact_ids
            or any(not isinstance(value, str) or not value for value in requirement.eligible_fact_ids)
            or len(requirement.eligible_fact_ids) != len(set(requirement.eligible_fact_ids))
            or not isinstance(requirement.depends_on_requirement_ids, tuple)
            or any(not isinstance(value, str) or not value for value in requirement.depends_on_requirement_ids)
            or len(requirement.depends_on_requirement_ids) != len(set(requirement.depends_on_requirement_ids))
            or not isinstance(requirement.owner_fact_ids, tuple)
            or any(not isinstance(value, str) or not value for value in requirement.owner_fact_ids)
            or len(requirement.owner_fact_ids) != len(set(requirement.owner_fact_ids))
        ):
            failures.append(TeachingRoleFailure("invalid_teaching_requirement", requirement_id))
            continue
        alternative_valid = True
        for alternative in component.alternatives:
            source = sources.get(alternative.source_id) if isinstance(alternative, OwnedComponent) else None
            if (
                source is None
                or not alternative.text.strip()
                or source.text.count(alternative.text) != 1
            ):
                alternative_valid = False
                break
            start = source.text.index(alternative.text)
            end = start + len(alternative.text)
            owned = [
                row for row in source.governing_bindings
                if row.quote_start < end and start < row.quote_end
            ]
            if (
                requirement.kind == "condition"
                and not any(
                    row.role in {"condition", "exception", "timing", "scope"}
                    for row in owned
                )
            ):
                alternative_valid = False
                break
        if not alternative_valid:
            failures.append(TeachingRoleFailure("teaching_source_ownership_unproved", requirement_id))
            continue
        indexed[requirement_id] = requirement
    if failures:
        return indexed, tuple(failures)
    requirement_ids = set(indexed)
    if any(
        dependency == requirement_id or dependency not in requirement_ids
        for requirement_id, requirement in indexed.items()
        for dependency in requirement.depends_on_requirement_ids
    ):
        return indexed, (TeachingRoleFailure("teaching_requirement_dependency_invalid"),)

    visiting: set[str] = set()
    visited: set[str] = set()

    def cycle(requirement_id: str) -> bool:
        if requirement_id in visiting:
            return True
        if requirement_id in visited:
            return False
        visiting.add(requirement_id)
        if any(cycle(value) for value in indexed[requirement_id].depends_on_requirement_ids):
            return True
        visiting.remove(requirement_id)
        visited.add(requirement_id)
        return False

    if any(cycle(requirement_id) for requirement_id in indexed):
        return indexed, (TeachingRoleFailure("teaching_requirement_dependency_cycle"),)
    return indexed, ()


def _normalized_whitespace_with_spans(value: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(value):
        if value[index].isspace():
            end = index + 1
            while end < len(value) and value[end].isspace():
                end += 1
            if normalized and end < len(value):
                normalized.append(" ")
                spans.append((index, end))
            index = end
            continue
        normalized.append(value[index])
        spans.append((index, index + 1))
        index += 1
    return "".join(normalized), tuple(spans)


def _unique_source_interval(source: str, quote: str) -> tuple[int, int] | None:
    normalized_source, spans = _normalized_whitespace_with_spans(source)
    normalized_quote, _ = _normalized_whitespace_with_spans(quote)
    if not normalized_quote or normalized_source.count(normalized_quote) != 1:
        return None
    normalized_start = normalized_source.index(normalized_quote)
    normalized_end = normalized_start + len(normalized_quote)
    source_start, source_end = spans[normalized_start][0], spans[normalized_end - 1][1]
    if (
        source_start > 0
        and source[source_start - 1].isalnum()
        and source[source_start].isalnum()
    ) or (
        source_end < len(source)
        and source[source_end - 1].isalnum()
        and source[source_end].isalnum()
    ):
        return None
    return source_start, source_end


def _native_proof(
    *, mode: Literal["exact_context_partition", "typed_closed_inventory", "canonical_direct_component", "strict_component_restatement", "conditional_connective_restatement", "source_row_identity_restatement"],
    source: TeachingSourceContext, source_start: int, source_end: int,
    component_start: int, component_end: int, quote: BoundTeachingQuote,
    covered_requirement_ids: tuple[str, ...],
    inventory_items: tuple[tuple[str, str], ...] = (),
    component_comparison: WholeComponentComparisonReceipt | None = None,
    conditional_connective: ConditionalConnectiveReceipt | None = None,
    row_identity: RowIdentityRestatementReceipt | None = None,
) -> TeachingNativeProof:
    source_sha256 = hashlib.sha256(source.text.encode()).hexdigest()
    source_interval_sha256 = hashlib.sha256(
        source.text[source_start:source_end].encode()
    ).hexdigest()
    body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "mode": mode,
        "source_id": source.source_id,
        "source_start": source_start,
        "source_end": source_end,
        "source_sha256": source_sha256,
        "source_interval_sha256": source_interval_sha256,
        "component_start": component_start,
        "component_end": component_end,
        "learner_ref_id": quote.ref_id,
        "learner_quote_start": quote.quote_start,
        "learner_quote_end": quote.quote_end,
        "learner_quote_sha256": quote.quote_sha256,
        "covered_requirement_ids": list(covered_requirement_ids),
        "inventory_items": [list(row) for row in inventory_items],
        "component_comparison": asdict(component_comparison) if component_comparison else None,
        "conditional_connective": asdict(conditional_connective) if conditional_connective else None,
        "row_identity": asdict(row_identity) if row_identity else None,
    }
    return TeachingNativeProof(
        mode=mode,
        source_id=source.source_id,
        source_start=source_start,
        source_end=source_end,
        source_sha256=source_sha256,
        source_interval_sha256=source_interval_sha256,
        component_start=component_start,
        component_end=component_end,
        learner_ref_id=quote.ref_id,
        learner_quote_start=quote.quote_start,
        learner_quote_end=quote.quote_end,
        learner_quote_sha256=quote.quote_sha256,
        covered_requirement_ids=covered_requirement_ids,
        inventory_items=inventory_items,
        binding_sha256=_digest(body),
        component_comparison=component_comparison,
        conditional_connective=conditional_connective,
        row_identity=row_identity,
    )


def _exact_context_partition_proof(
    requirement: TeachingRequirement,
    quote: BoundTeachingQuote,
    requirements: dict[str, TeachingRequirement],
    parsed_rows: dict[str, dict[str, Any]],
    sources: dict[str, TeachingSourceContext],
) -> TeachingNativeProof | None:
    requirement_id = requirement.component.component_id
    for alternative in requirement.component.alternatives:
        source = sources[alternative.source_id]
        interval = _unique_source_interval(source.text, quote.text)
        if interval is None:
            continue
        source_start, source_end = interval
        source_interval = source.text[source_start:source_end]
        if source_interval.count(alternative.text) != 1 or quote.text.count(alternative.text) != 1:
            continue
        component_local_start = source_interval.index(alternative.text)
        component_local_end = component_local_start + len(alternative.text)
        excluded = (
            source_interval[:component_local_start]
            + " " * len(alternative.text)
            + source_interval[component_local_end:]
        )
        if re.search(r"(?<!\w)(?:не|ни|без|нельзя|нет)(?!\w)", excluded, re.IGNORECASE):
            continue
        if any(
            binding.quote_start < source_end
            and source_start < binding.quote_end
            and binding.branch_effect not in {"none", "scopes_action"}
            for binding in source.governing_bindings
        ):
            continue
        covered = [False] * len(source_interval)
        covered_ids: list[str] = []
        for other_id, other in requirements.items():
            row = parsed_rows.get(other_id)
            if row is None or row["relation"] != "preserved":
                continue
            matches = [candidate for candidate in other.component.alternatives
                       if candidate.source_id == alternative.source_id
                       and source_interval.count(candidate.text) == 1
                       and quote.text.count(candidate.text) == 1]
            if len(matches) != 1:
                continue
            match = matches[0]
            local_start = source_interval.index(match.text)
            local_end = local_start + len(match.text)
            covered[local_start:local_end] = [True] * (local_end - local_start)
            covered_ids.append(other_id)
        if requirement_id not in covered_ids:
            continue
        if any(char.isalnum() and not covered[index]
               for index, char in enumerate(source_interval)):
            continue
        component_start = source_start + component_local_start
        return _native_proof(
            mode="exact_context_partition",
            source=source,
            source_start=source_start,
            source_end=source_end,
            component_start=component_start,
            component_end=component_start + len(alternative.text),
            quote=quote,
            covered_requirement_ids=tuple(covered_ids),
        )
    return None


_PROPER_NAME_TOKEN = r"[А-ЯЁ][А-Яа-яЁё]*(?:-[А-ЯЁ][А-Яа-яЁё]*)*"
_PROPER_NAME = re.compile(rf"{_PROPER_NAME_TOKEN}(?:\s+{_PROPER_NAME_TOKEN})*")
_LEARNER_CITY_LIST = re.compile(
    rf"(?:[Вв]о?\s+)?(?P<type>[А-Яа-яЁё]+)\s+"
    rf"(?P<items>{_PROPER_NAME_TOKEN}(?:\s+{_PROPER_NAME_TOKEN})*"
    rf"(?:\s*,\s*{_PROPER_NAME_TOKEN}(?:\s+{_PROPER_NAME_TOKEN})*|"
    rf"\s+и\s+{_PROPER_NAME_TOKEN}(?:\s+{_PROPER_NAME_TOKEN})*)+)"
)


@dataclass(frozen=True, slots=True)
class _SourceCityInventory:
    governing_prefix: str
    prefix_start: int
    prefix_end: int
    items: tuple[tuple[str, int, int], ...]


def _source_city_inventory(component: str) -> _SourceCityInventory | None:
    for first_marker in re.finditer(r"(?<!\w)г\.\s*", component):
        tail_start = first_marker.start()
        tail = component[tail_start:]
        segments = tuple(re.finditer(r"[^,]+", tail))
        if len(segments) < 2 or ",".join(match.group() for match in segments) != tail:
            continue
        items: list[tuple[str, int, int]] = []
        for segment in segments:
            raw = segment.group()
            leading = len(raw) - len(raw.lstrip())
            part = raw.strip()
            match = re.fullmatch(rf"г\.\s*(?P<item>{_PROPER_NAME.pattern})", part)
            if match is None:
                break
            start = tail_start + segment.start() + leading + match.start("item")
            text = match.group("item")
            items.append((text, start, start + len(text)))
        if (
            len(items) != len(segments)
            or len({item[0].casefold() for item in items}) != len(items)
        ):
            continue
        return _SourceCityInventory(
            governing_prefix=component[:tail_start],
            prefix_start=0,
            prefix_end=tail_start,
            items=tuple(items),
        )
    return None


def _source_city_item_spans(component: str) -> tuple[tuple[str, int, int], ...] | None:
    inventory = _source_city_inventory(component)
    return inventory.items if inventory is not None else None


def _source_city_items(component: str) -> tuple[str, ...] | None:
    spans = _source_city_item_spans(component)
    return tuple(row[0] for row in spans) if spans is not None else None


def derive_teaching_inventory_contract(
    requirement: TeachingRequirement,
    source_contexts: Sequence[TeachingSourceContext],
) -> TeachingInventoryContract | None:
    """Compile one source-owned city inventory; no row or model can author it."""

    if (
        not isinstance(requirement, TeachingRequirement)
        or requirement.kind != "condition"
        or len(requirement.component.alternatives) != 1
        or not _sequence(source_contexts)
    ):
        return None
    alternative = requirement.component.alternatives[0]
    sources = {
        source.source_id: source for source in source_contexts
        if isinstance(source, TeachingSourceContext)
    }
    if len(sources) != len(source_contexts) or alternative.source_id not in sources:
        return None
    source = sources[alternative.source_id]
    inventory = _source_city_inventory(alternative.text)
    if inventory is None or source.text.count(alternative.text) != 1:
        return None
    component_start = source.text.index(alternative.text)
    if not any(
        binding.source_id == source.source_id
        and binding.role == "scope"
        and binding.quote == alternative.text
        and binding.quote_start == component_start
        and binding.quote_end == component_start + len(alternative.text)
        for binding in source.governing_bindings
    ):
        return None
    items: list[TeachingInventoryItem] = []
    needs_semantic_identity = False
    requirement_id = requirement.component.component_id
    for ordinal, (text, local_start, local_end) in enumerate(inventory.items, 1):
        source_start = component_start + local_start
        source_end = component_start + local_end
        item_id = "TI" + _digest({
            "requirement_id": requirement_id,
            "source_id": source.source_id,
            "source_start": source_start,
            "source_end": source_end,
            "source_text": text,
            "ordinal": ordinal,
        })[:24]
        items.append(TeachingInventoryItem(
            item_id=item_id,
            source_id=source.source_id,
            source_start=source_start,
            source_end=source_end,
            source_text=text,
            source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        ))
        for word in re.findall(r"[А-Яа-яЁё]+", text):
            if not _word_info(word).known:
                needs_semantic_identity = True
    source_sha256 = hashlib.sha256(source.text.encode()).hexdigest()
    body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "requirement_id": requirement_id,
        "kind": "city_list",
        "source_id": source.source_id,
        "source_sha256": source_sha256,
        "governing_prefix": inventory.governing_prefix,
        "governing_prefix_start": component_start + inventory.prefix_start,
        "governing_prefix_end": component_start + inventory.prefix_end,
        "governing_prefix_sha256": hashlib.sha256(inventory.governing_prefix.encode()).hexdigest(),
        "items": [asdict(item) for item in items],
        "needs_semantic_identity": needs_semantic_identity,
    }
    return TeachingInventoryContract(
        requirement_id=requirement_id,
        kind="city_list",
        source_id=source.source_id,
        source_sha256=source_sha256,
        governing_prefix=inventory.governing_prefix,
        governing_prefix_start=component_start + inventory.prefix_start,
        governing_prefix_end=component_start + inventory.prefix_end,
        governing_prefix_sha256=hashlib.sha256(inventory.governing_prefix.encode()).hexdigest(),
        items=tuple(items),
        needs_semantic_identity=needs_semantic_identity,
        binding_sha256=_digest(body),
    )


def _prefix_end(quote: str, governing_prefix: str) -> int | None:
    if not governing_prefix:
        return 0
    pieces = re.split(r"(\s+)", governing_prefix)
    pattern = "".join(r"\s+" if piece.isspace() else re.escape(piece)
                      for piece in pieces if piece)
    match = re.match(pattern, quote, re.IGNORECASE)
    return match.end() if match is not None else None


def _learner_city_item_spans(
    quote: str,
    governing_prefix: str = "",
) -> tuple[tuple[str, int, int], ...] | None:
    prefix_end = _prefix_end(quote, governing_prefix)
    if prefix_end is None:
        return None
    remainder = quote[prefix_end:]
    repeated = _source_city_inventory(remainder)
    if repeated is not None and not repeated.governing_prefix:
        return tuple(
            (text, prefix_end + start, prefix_end + end)
            for text, start, end in repeated.items
        )
    stripped = remainder.strip()
    match = _LEARNER_CITY_LIST.fullmatch(stripped)
    if match is None:
        return None
    city_type = _word_info(match.group("type"))
    if city_type.noun_lemmas != frozenset({"город"}):
        return None
    offset = prefix_end + len(remainder) - len(remainder.lstrip())
    items_text = match.group("items")
    items_start = offset + match.start("items")
    separators = tuple(re.finditer(r"\s*,\s*|\s+и\s+", items_text))
    boundaries = (0, *(separator.end() for separator in separators))
    endings = (*(separator.start() for separator in separators), len(items_text))
    items: list[tuple[str, int, int]] = []
    for start, end in zip(boundaries, endings, strict=True):
        raw = items_text[start:end]
        leading = len(raw) - len(raw.lstrip())
        text = raw.strip()
        if not text or _PROPER_NAME.fullmatch(text) is None:
            return None
        item_start = items_start + start + leading
        items.append((text, item_start, item_start + len(text)))
    return (
        tuple(items)
        if len(items) >= 2
        and len({item[0].casefold() for item in items}) == len(items)
        else None
    )


def _learner_city_items(quote: str, governing_prefix: str = "") -> tuple[str, ...] | None:
    spans = _learner_city_item_spans(quote, governing_prefix)
    return tuple(row[0] for row in spans) if spans is not None else None


def _city_item_identity(source_item: str, learner_item: str) -> Literal["same", "different", "unknown"]:
    """Compare one aligned city item without suffix guesses or name allowlists."""

    source_words = source_item.split()
    learner_words = learner_item.split()
    if len(source_words) != len(learner_words):
        return "different"
    unknown = False
    for source_word, learner_word in zip(source_words, learner_words, strict=True):
        source_parts = source_word.split("-")
        learner_parts = learner_word.split("-")
        if len(source_parts) != len(learner_parts):
            return "different"
        for source_part, learner_part in zip(source_parts, learner_parts, strict=True):
            if source_part.casefold() == learner_part.casefold():
                continue
            source_info = _word_info(source_part)
            learner_info = _word_info(learner_part)
            if (
                not source_info.known
                or not learner_info.known
                or not source_info.lemmas
                or not learner_info.lemmas
            ):
                unknown = True
                continue
            if source_info.lemmas.isdisjoint(learner_info.lemmas):
                return "different"
            if source_info.lemmas != learner_info.lemmas:
                unknown = True
    return "unknown" if unknown else "same"


def _same_inflected_name(source_item: str, learner_item: str) -> bool:
    return _city_item_identity(source_item, learner_item) == "same"


def _typed_closed_inventory_proof(
    requirement: TeachingRequirement,
    quote: BoundTeachingQuote,
    sources: dict[str, TeachingSourceContext],
) -> TeachingNativeProof | None:
    for alternative in requirement.component.alternatives:
        source_inventory = _source_city_inventory(alternative.text)
        source_items = _source_city_items(alternative.text)
        learner_items = _learner_city_items(
            quote.text,
            source_inventory.governing_prefix if source_inventory is not None else "",
        )
        source = sources[alternative.source_id]
        if (
            source_items is None
            or learner_items is None
            or len(source_items) != len(learner_items)
            or source.text.count(alternative.text) != 1
            or not all(_same_inflected_name(source_item, learner_item)
                       for source_item, learner_item in zip(source_items, learner_items, strict=True))
        ):
            continue
        source_start = source.text.index(alternative.text)
        return _native_proof(
            mode="typed_closed_inventory",
            source=source,
            source_start=source_start,
            source_end=source_start + len(alternative.text),
            component_start=source_start,
            component_end=source_start + len(alternative.text),
            quote=quote,
            covered_requirement_ids=(requirement.component.component_id,),
            inventory_items=tuple(zip(source_items, learner_items, strict=True)),
        )
    return None


def _protected_operator_attachment_signature(
    value: str,
) -> tuple[tuple[str, str], ...] | None:
    """Preserve conjunction attachment to existing protected operators.

    The shared lexical checker deliberately ignores ordinary conjunctions and
    prepositions so harmless grammatical restatements remain possible.  A
    conjunction immediately attached to a protected range/scope/operator token,
    however, is part of that operator relation and cannot be supplied by the two
    semantic role labels alone.
    """

    words = [match.group() for match in _OPERATOR_WORD.finditer(value)]
    signature: list[tuple[str, str]] = []
    try:
        for index, word in enumerate(words):
            normalized = word.casefold()
            if normalized not in _PROTECTED_LITERALS:
                continue
            connector = ""
            if index:
                previous = words[index - 1]
                info = _word_info(previous.casefold())
                if info.known and info.pos == "CONJ":
                    connector = previous.casefold()
            signature.append((normalized, connector))
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
    return tuple(signature)


def _strict_component_restatement_proof(
    requirement: TeachingRequirement,
    bodies: tuple[str, ...],
    quotes: tuple[BoundTeachingQuote, ...],
    parsed_rows: dict[str, dict[str, Any]],
    sources: dict[str, TeachingSourceContext],
) -> TeachingNativeProof | None:
    """Bind one whole, bidirectionally strict current-role restatement.

    This is not a synonym, attachment or deictic exception. The existing strict
    checker must accept both directions; a learner-side added object, missing
    condition, operator or other unproved material still prevents this mode.
    Public role/catalog/source/quote checks and the independent paired-role gate
    remain mandatory. Historical catalog policies are never upgraded here.
    """
    row = parsed_rows.get(requirement.component.component_id)
    if (len(quotes) != 1 or len(bodies) != 1 or bodies[0] != quotes[0].text
            or row is None or row["relation"] != "preserved"
            or any(parsed_rows.get(dependency, {}).get("relation") != "preserved"
                   for dependency in requirement.depends_on_requirement_ids)):
        return None
    quote = quotes[0]
    for alternative in requirement.component.alternatives:
        source = sources[alternative.source_id]
        source_relations = _protected_operator_attachment_signature(alternative.text)
        quote_relations = _protected_operator_attachment_signature(quote.text)
        if (source.text.count(alternative.text) != 1
                or source_relations is None
                or source_relations != quote_relations
                or component_preservation_issue(alternative.text, quote.text, source_context=source.text) is not None
                or component_preservation_issue(quote.text, alternative.text, source_context=quote.text) is not None):
            continue
        start = source.text.index(alternative.text)
        return _native_proof(mode="strict_component_restatement", source=source,
            source_start=start, source_end=start + len(alternative.text),
            component_start=start, component_end=start + len(alternative.text), quote=quote,
            covered_requirement_ids=(requirement.component.component_id,))
    return None


def _conditional_connective_proof(
    requirement: TeachingRequirement,
    bodies: tuple[str, ...],
    quotes: tuple[BoundTeachingQuote, ...],
    parsed_rows: dict[str, dict[str, Any]],
    sources: dict[str, TeachingSourceContext],
) -> TeachingNativeProof | None:
    """Preserve the entire source condition while shortening only its connector.

    Source ownership, current quote endpoints, dependency rows and both semantic
    roles are independently mandatory. This receipt is grammatical custody only.
    """
    row = parsed_rows.get(requirement.component.component_id)
    if (requirement.kind != "condition" or len(quotes) != 1 or len(bodies) != 1
            or bodies[0] != quotes[0].text or row is None or row["relation"] != "preserved"
            or any(parsed_rows.get(dependency, {}).get("relation") != "preserved"
                   for dependency in requirement.depends_on_requirement_ids)):
        return None
    quote = quotes[0]
    for alternative in requirement.component.alternatives:
        source = sources[alternative.source_id]
        if source.text.count(alternative.text) != 1:
            continue
        receipt = conditional_connective_receipt(alternative.text, quote.text)
        if not conditional_connective_receipt_valid(
                receipt, source_component=alternative.text, learner_quote=quote.text):
            continue
        start = source.text.index(alternative.text)
        return _native_proof(mode="conditional_connective_restatement", source=source,
            source_start=start, source_end=start + len(alternative.text),
            component_start=start, component_end=start + len(alternative.text), quote=quote,
            covered_requirement_ids=(requirement.component.component_id,),
            conditional_connective=receipt)
    return None


def _native_requirement_issue(
    requirement: TeachingRequirement,
    bodies: tuple[str, ...],
    quotes: tuple[BoundTeachingQuote, ...],
    requirements: dict[str, TeachingRequirement],
    parsed_rows: dict[str, dict[str, Any]],
    sources: dict[str, TeachingSourceContext],
    refs: dict[str, TeachingBlockRef],
) -> tuple[TeachingNativeProof | None, str | None]:
    for alternative in requirement.component.alternatives:
        source = sources[alternative.source_id]
        for quote in quotes:
            entry = refs[quote.ref_id]
            bindings = tuple(asdict(row) for row in source.governing_bindings)
            start, end = quote.quote_start - entry.body_start, quote.quote_end - entry.body_start
            comparison = bind_whole_component_comparison(alternative.text, quote.text,
                source_context=source.text, source_id=source.source_id,
                verified_governing_bindings=bindings, candidate_container=entry.body,
                candidate_start=start, candidate_end=end)
            if comparison is not None and whole_component_comparison_receipt_valid(
                    comparison, alternative.text, quote.text, source_context=source.text,
                    source_id=source.source_id, verified_governing_bindings=bindings,
                    candidate_container=entry.body, candidate_start=start, candidate_end=end):
                return _native_proof(mode="canonical_direct_component", source=source,
                    source_start=comparison.source_start, source_end=comparison.source_end,
                    component_start=comparison.source_start, component_end=comparison.source_end,
                    quote=quote, covered_requirement_ids=(requirement.component.component_id,),
                    component_comparison=comparison), None
    connective_proof = _conditional_connective_proof(requirement, bodies, quotes, parsed_rows, sources)
    if connective_proof is not None:
        return connective_proof, None
    row = parsed_rows.get(requirement.component.component_id)
    if (len(quotes) == 1 and len(bodies) == 1 and bodies[0] == quotes[0].text
            and row is not None and row["relation"] == "preserved"
            and all(parsed_rows.get(dependency, {}).get("relation") == "preserved"
                    for dependency in requirement.depends_on_requirement_ids)):
        for alternative in requirement.component.alternatives:
            source = sources[alternative.source_id]
            if source.source_fact is None:
                continue
            identity = bind_row_identity_restatement(source.source_fact, alternative.text, quotes[0].text)
            if identity is None or not row_identity_restatement_valid(identity, source.source_fact, alternative.text, quotes[0].text):
                continue
            start = source.text.index(alternative.text)
            return _native_proof(mode="source_row_identity_restatement", source=source,
                source_start=start, source_end=start + len(alternative.text),
                component_start=start, component_end=start + len(alternative.text), quote=quotes[0],
                covered_requirement_ids=(requirement.component.component_id,), row_identity=identity), None
    issues: list[tuple[OwnedComponent, PreservationIssue]] = []
    broad_strict_success = False
    for alternative in requirement.component.alternatives:
        source = sources[alternative.source_id]
        for body in bodies:
            issue = component_preservation_issue(
                alternative.text,
                body,
                source_context=source.text,
            )
            if issue is None:
                if not quotes or body == alternative.text:
                    return None, None
                broad_strict_success = True
                continue
            issues.append((alternative, issue))
    for quote in quotes:
        proof = _exact_context_partition_proof(
            requirement,
            quote,
            requirements,
            parsed_rows,
            sources,
        )
        if proof is not None:
            return proof, None
        proof = _typed_closed_inventory_proof(requirement, quote, sources)
        if proof is not None:
            return proof, None
    if broad_strict_success:
        proof = _strict_component_restatement_proof(requirement, bodies, quotes, parsed_rows, sources)
        if proof is not None:
            return proof, None
        return None, "teaching_native_context_partition_unproved"
    if not issues:
        return None, "teaching_native_material_unproved"
    alternative, first_issue = issues[0]
    if first_issue.get("code") == "source_word_order_unproved":
        source = sources[alternative.source_id]
        body = bodies[0]
        component_start = source.text.index(alternative.text)
        component_end = component_start + len(alternative.text)
        owned_bindings = tuple(
            row for row in source.governing_bindings
            if row.quote_start < component_end and component_start < row.quote_end
        )
        status = critical_preservation_status(
            alternative.text,
            ({"part": "answer", "role": "discriminating_answer", "text": body},),
            authoritative_answer=body,
            literal_issue_codes=("source_word_order_unproved",),
            claimed_component_count=1,
            source_context=source.text,
            source_id=source.source_id,
            comparison_mode="normative_restatement",
            validated_governing_bindings=tuple(asdict(row) for row in owned_bindings),
            custody_valid=True,
        )
        # This negative guard never converts a nonliteral residual into credit.
        return None, "teaching_native_" + str(status.get("status", "unresolved")) + "_" + str(status.get("code", "unproved"))
    return None, "teaching_native_" + str(first_issue.get("code", "material_unproved"))


def _bind_teaching_quotes(
    raw_quotes: object,
    teaching_refs: tuple[str, ...],
    refs: dict[str, TeachingBlockRef],
) -> tuple[BoundTeachingQuote, ...] | None:
    if not isinstance(raw_quotes, dict) or set(raw_quotes) != set(teaching_refs):
        return None
    raw_texts = tuple(raw_quotes.get(ref_id) for ref_id in teaching_refs)
    if (
        any(not isinstance(text, str) or not text.strip() for text in raw_texts)
        or len(set(raw_texts)) != len(raw_texts)
    ):
        return None
    texts = tuple(cast(str, text) for text in raw_texts)
    bound: list[BoundTeachingQuote] = []
    for ref_id, text in zip(teaching_refs, texts, strict=True):
        entry = refs[ref_id]
        if entry.body.count(text) != 1 or text in entry.heading:
            return None
        local_start = entry.body.index(text)
        if not lexical_span_is_complete(entry.body, local_start, local_start + len(text)):
            return None
        quote_start = entry.body_start + local_start
        bound.append(BoundTeachingQuote(
            ref_id=ref_id,
            text=text,
            quote_start=quote_start,
            quote_end=quote_start + len(text),
            quote_sha256=hashlib.sha256(text.encode()).hexdigest(),
        ))
    return tuple(bound)


def _bind_inventory_matches(
    raw_matches: object,
    *,
    contract: TeachingInventoryContract,
    requirement: TeachingRequirement,
    role: Literal["review", "counter"],
    quotes: tuple[BoundTeachingQuote, ...],
    refs: dict[str, TeachingBlockRef],
    sources: dict[str, TeachingSourceContext],
    candidate_sha256: str,
) -> tuple[
    tuple[TeachingInventoryIdentityEvidence, ...],
    TeachingNativeProof | None,
    str | None,
]:
    """Bind complete per-item identity evidence after native list-shape checks."""

    if (
        not contract.needs_semantic_identity
        or not _sequence(raw_matches)
        or len(raw_matches) != len(contract.items)
        or len(quotes) != 1
        or contract.source_id not in sources
    ):
        return (), None, "invalid_teaching_inventory_matches"
    quote = quotes[0]
    learner_spans = _learner_city_item_spans(quote.text, contract.governing_prefix)
    if learner_spans is None or len(learner_spans) != len(contract.items):
        return (), None, "invalid_teaching_inventory_shape"
    source = sources[contract.source_id]
    if hashlib.sha256(source.text.encode()).hexdigest() != contract.source_sha256:
        return (), None, "stale_teaching_inventory_contract"
    if (
        not 0 <= contract.governing_prefix_start <= contract.governing_prefix_end <= len(source.text)
        or source.text[contract.governing_prefix_start:contract.governing_prefix_end]
        != contract.governing_prefix
        or hashlib.sha256(contract.governing_prefix.encode()).hexdigest()
        != contract.governing_prefix_sha256
    ):
        return (), None, "stale_teaching_inventory_prefix"
    alternative = requirement.component.alternatives[0]
    if alternative.source_id != contract.source_id:
        return (), None, "teaching_inventory_source_mismatch"
    source_start = source.text.index(alternative.text)
    identities = tuple(
        _city_item_identity(item.source_text, learner_text)
        for item, (learner_text, _, _) in zip(
            contract.items,
            learner_spans,
            strict=True,
        )
    )
    if "different" in identities:
        return (), None, "teaching_inventory_known_contradiction"

    bound: list[TeachingInventoryIdentityEvidence] = []
    for ordinal, (raw, item, learner_span) in enumerate(
        zip(raw_matches, contract.items, learner_spans, strict=True),
        1,
    ):
        if not isinstance(raw, dict) or frozenset(raw) != TEACHING_INVENTORY_MATCH_FIELDS:
            return (), None, "invalid_teaching_inventory_match"
        item_id = raw.get("item_id")
        teaching_ref = raw.get("teaching_ref")
        learner_quote = raw.get("learner_quote")
        relation = raw.get("relation")
        reason = raw.get("reason")
        learner_text, learner_local_start, learner_local_end = learner_span
        if (
            item_id != item.item_id
            or teaching_ref != quote.ref_id
            or learner_quote != learner_text
            or relation not in TEACHING_INVENTORY_RELATIONS
            or relation != "same_entity"
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason.strip()) > MAX_DIAGNOSTIC_REASON_CHARS
            or quote.text.count(learner_text) != 1
            or source.text[item.source_start:item.source_end] != item.source_text
            or hashlib.sha256(item.source_text.encode()).hexdigest()
            != item.source_text_sha256
        ):
            return (), None, "invalid_teaching_inventory_match"
        entry = refs[quote.ref_id]
        learner_start = quote.quote_start + learner_local_start
        learner_end = quote.quote_start + learner_local_end
        evidence_body = {
            "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
            "role": role,
            "requirement_id": contract.requirement_id,
            "item_id": item.item_id,
            "ordinal": ordinal,
            "source_id": item.source_id,
            "source_start": item.source_start,
            "source_end": item.source_end,
            "source_text_sha256": item.source_text_sha256,
            "teaching_ref": quote.ref_id,
            "body_sha256": entry.body_sha256,
            "learner_quote": learner_text,
            "learner_start": learner_start,
            "learner_end": learner_end,
            "learner_quote_sha256": hashlib.sha256(learner_text.encode()).hexdigest(),
            "candidate_sha256": candidate_sha256,
            "contract_binding_sha256": contract.binding_sha256,
            "relation": relation,
            "reason": reason.strip(),
        }
        bound.append(TeachingInventoryIdentityEvidence(
            role=role,
            requirement_id=contract.requirement_id,
            item_id=item.item_id,
            source_id=item.source_id,
            source_start=item.source_start,
            source_end=item.source_end,
            source_text_sha256=item.source_text_sha256,
            teaching_ref=quote.ref_id,
            body_sha256=entry.body_sha256,
            learner_quote=learner_text,
            learner_start=learner_start,
            learner_end=learner_end,
            learner_quote_sha256=hashlib.sha256(learner_text.encode()).hexdigest(),
            candidate_sha256=candidate_sha256,
            contract_binding_sha256=contract.binding_sha256,
            relation=cast(Literal["same_entity", "different", "unknown"], relation),
            reason=reason.strip(),
            binding_sha256=_digest(evidence_body),
        ))
    proof = _native_proof(
        mode="typed_closed_inventory",
        source=source,
        source_start=source_start,
        source_end=source_start + len(alternative.text),
        component_start=source_start,
        component_end=source_start + len(alternative.text),
        quote=quote,
        covered_requirement_ids=(requirement.component.component_id,),
        inventory_items=tuple(
            (item.source_text, learner_text)
            for item, (learner_text, _, _) in zip(
                contract.items,
                learner_spans,
                strict=True,
            )
        ),
    )
    return tuple(bound), proof, None


def bind_final_teaching_role(
    catalogs: Sequence[FinalTeachingCatalog],
    requirements: Sequence[TeachingRequirement],
    rows: object,
    *,
    role: Literal["review", "counter"],
    candidate: TeachingCandidateIdentity,
    source_contexts: Sequence[TeachingSourceContext],
) -> FinalTeachingRoleResult:
    """Bind one critic's closed teaching inventory; this grants no admission."""

    failures: list[TeachingRoleFailure] = []
    candidate_sha256 = _candidate_sha256(candidate)
    if role not in {"review", "counter"}:
        failures.append(TeachingRoleFailure("invalid_teaching_role"))
    if candidate_sha256 is None:
        failures.append(TeachingRoleFailure("invalid_teaching_candidate"))
        candidate_sha256 = ""
    valid_catalogs = tuple(
        catalog for catalog in catalogs
        if isinstance(catalog, FinalTeachingCatalog) and _catalog_valid(catalog)
    ) if _sequence(catalogs) else ()
    if (
        not _sequence(catalogs)
        or not catalogs
        or len(valid_catalogs) != len(catalogs)
        or len({catalog.lesson_id for catalog in valid_catalogs}) != len(valid_catalogs)
        or (isinstance(candidate, TeachingCandidateIdentity)
            and (not valid_catalogs or valid_catalogs[-1].lesson_id != candidate.lesson_id))
    ):
        failures.append(TeachingRoleFailure("invalid_teaching_catalog_registry"))
    refs = {
        entry.ref_id: entry
        for catalog in valid_catalogs
        for entry in catalog.entries
    }
    if len(refs) != sum(len(catalog.entries) for catalog in valid_catalogs):
        failures.append(TeachingRoleFailure("duplicate_teaching_ref"))
    source_by_id, source_failures = _validated_sources(source_contexts)
    failures.extend(source_failures)
    requirement_by_id, requirement_failures = _validated_requirements(
        requirements,
        source_by_id,
        candidate,
    ) if isinstance(candidate, TeachingCandidateIdentity) else ({}, ())
    failures.extend(requirement_failures)
    inventory_contracts = {
        requirement_id: contract
        for requirement_id, requirement in requirement_by_id.items()
        if (
            (contract := derive_teaching_inventory_contract(requirement, source_contexts))
            is not None
            and contract.needs_semantic_identity
        )
    }

    parsed_rows: dict[str, dict[str, Any]] = {}
    negative_ids: list[str] = []
    if not _sequence(rows):
        failures.append(TeachingRoleFailure("invalid_teaching_rows"))
    else:
        for row in rows:
            requirement_id = row.get("requirement_id") if isinstance(row, dict) else ""
            if (
                not isinstance(row, dict)
                or frozenset(row) not in {
                    TEACHING_ROLE_FIELDS,
                    TEACHING_ROLE_QUOTE_FIELDS,
                    TEACHING_ROLE_INVENTORY_FIELDS,
                }
                or not isinstance(requirement_id, str)
                or requirement_id not in requirement_by_id
                or requirement_id in parsed_rows
            ):
                safe_requirement_id = requirement_id if isinstance(requirement_id, str) else ""
                failures.append(TeachingRoleFailure(
                    "invalid_or_duplicate_teaching_row",
                    safe_requirement_id,
                ))
                continue
            relation = row.get("relation")
            teaching_refs = row.get("teaching_refs")
            reason = row.get("reason")
            if (
                not isinstance(relation, str)
                or relation not in TEACHING_RELATIONS
                or not isinstance(teaching_refs, list)
                or any(not isinstance(value, str) or value not in refs for value in teaching_refs)
                or len(teaching_refs) != len(set(teaching_refs))
                or not isinstance(reason, str)
                or not reason.strip()
                or len(reason.strip()) > MAX_DIAGNOSTIC_REASON_CHARS
                or (relation == "preserved" and not teaching_refs)
                or ("inventory_matches" in row and (
                    relation != "preserved"
                    or requirement_id not in inventory_contracts
                    or "teaching_quotes" not in row
                ))
            ):
                failures.append(TeachingRoleFailure("invalid_teaching_row", requirement_id))
                continue
            bound_quotes: tuple[BoundTeachingQuote, ...] = ()
            if "teaching_quotes" in row:
                bound = _bind_teaching_quotes(
                    row.get("teaching_quotes"),
                    tuple(teaching_refs),
                    refs,
                )
                if bound is None:
                    failures.append(TeachingRoleFailure(
                        "invalid_teaching_quotes",
                        requirement_id,
                    ))
                    continue
                bound_quotes = bound
            parsed_rows[requirement_id] = {
                "relation": relation,
                "teaching_refs": tuple(teaching_refs),
                "teaching_quotes": bound_quotes,
                "inventory_matches": row.get("inventory_matches"),
                "reason": reason.strip(),
            }
            if relation != "preserved":
                negative_ids.append(requirement_id)
    if set(parsed_rows) != set(requirement_by_id):
        failures.append(TeachingRoleFailure("teaching_requirement_inventory_mismatch"))

    selected_refs = {
        ref_id
        for row in parsed_rows.values() if row["relation"] == "preserved"
        for ref_id in row["teaching_refs"]
    }
    if any(
        dependency not in selected_refs
        for ref_id in selected_refs
        for dependency in refs[ref_id].dependency_refs
    ):
        failures.append(TeachingRoleFailure("teaching_block_dependency_open"))

    evidence: list[BoundTeachingRequirement] = []
    for requirement_id, requirement in requirement_by_id.items():
        row = parsed_rows.get(requirement_id)
        if row is None:
            continue
        if any(
            dependency not in parsed_rows
            or parsed_rows[dependency]["relation"] != "preserved"
            for dependency in requirement.depends_on_requirement_ids
        ):
            failures.append(TeachingRoleFailure("teaching_requirement_dependency_open", requirement_id))
        selected = tuple(refs[value] for value in row["teaching_refs"])
        native_proof: TeachingNativeProof | None = None
        inventory_matches: tuple[TeachingInventoryIdentityEvidence, ...] = ()
        if row["relation"] == "preserved":
            if any(not teaching_entry_supports_requirement(entry, requirement) for entry in selected):
                failures.append(TeachingRoleFailure(
                    "teaching_ref_source_scope_mismatch",
                    requirement_id,
                ))
            native_proof, native_issue = _native_requirement_issue(
                requirement,
                tuple(
                    quote.text for quote in row["teaching_quotes"]
                ) or tuple(entry.body for entry in selected),
                row["teaching_quotes"],
                requirement_by_id,
                parsed_rows,
                source_by_id,
                refs,
            )
            raw_inventory_matches = row["inventory_matches"]
            contract = inventory_contracts.get(requirement_id)
            if contract is not None and raw_inventory_matches is None:
                failures.append(TeachingRoleFailure(
                    "teaching_inventory_matches_required",
                    requirement_id,
                ))
            elif raw_inventory_matches is not None:
                inventory_issue: str | None
                semantic_proof: TeachingNativeProof | None
                if contract is None:
                    inventory_issue = "invalid_teaching_inventory_matches"
                    semantic_proof = None
                else:
                    inventory_matches, semantic_proof, inventory_issue = _bind_inventory_matches(
                        raw_inventory_matches,
                        contract=contract,
                        requirement=requirement,
                        role=role,
                        quotes=row["teaching_quotes"],
                        refs=refs,
                        sources=source_by_id,
                        candidate_sha256=candidate_sha256,
                    )
                if inventory_issue is not None:
                    failures.append(TeachingRoleFailure(inventory_issue, requirement_id))
                elif native_issue in {
                    "teaching_native_missing_material_token",
                    "teaching_native_missing_unknown_source_token",
                }:
                    native_proof = semantic_proof
                    native_issue = None
            if native_issue is not None:
                failures.append(TeachingRoleFailure(native_issue, requirement_id))
        binding_body = {
            "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
            "role": role,
            "target_id": requirement.component.target_id,
            "requirement_id": requirement_id,
            "relation": row["relation"],
            "teaching_refs": list(row["teaching_refs"]),
            "teaching_quotes": [asdict(quote) for quote in row["teaching_quotes"]],
            "body_sha256s": [entry.body_sha256 for entry in selected],
            "reason": row["reason"],
            "native_proof": asdict(native_proof) if native_proof is not None else None,
            "inventory_matches": [asdict(match) for match in inventory_matches],
        }
        evidence.append(BoundTeachingRequirement(
            role=role,
            target_id=requirement.component.target_id,
            requirement_id=requirement_id,
            relation=row["relation"],
            teaching_refs=row["teaching_refs"],
            teaching_quotes=row["teaching_quotes"],
            body_sha256s=tuple(entry.body_sha256 for entry in selected),
            reason=row["reason"],
            native_proof=native_proof,
            inventory_matches=inventory_matches,
            binding_sha256=_digest(binding_body),
        ))

    source_sha256 = _digest({
        "requirements": [asdict(row) for row in requirement_by_id.values()],
        "source_contexts": [asdict(row) for row in source_by_id.values()],
    })
    surface_registry_sha256 = _digest([
        catalog.surface_binding_sha256 for catalog in valid_catalogs
    ])
    result_body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "role": role,
        "candidate_sha256": candidate_sha256,
        "source_sha256": source_sha256,
        "surface_registry_sha256": surface_registry_sha256,
        "evidence": [asdict(row) for row in evidence],
        "failures": [asdict(row) for row in failures],
        "negative_requirement_ids": negative_ids,
    }
    return FinalTeachingRoleResult(
        policy=FINAL_TEACHING_ELIGIBILITY_POLICY,
        role=role,
        candidate_sha256=candidate_sha256,
        source_sha256=source_sha256,
        surface_registry_sha256=surface_registry_sha256,
        evidence=tuple(evidence),
        failures=tuple(failures),
        negative_requirement_ids=tuple(negative_ids),
        binding_sha256=_digest(result_body),
    )


def _role_result_valid(result: object) -> bool:
    if not isinstance(result, FinalTeachingRoleResult):
        return False
    body = {
        "policy": result.policy,
        "role": result.role,
        "candidate_sha256": result.candidate_sha256,
        "source_sha256": result.source_sha256,
        "surface_registry_sha256": result.surface_registry_sha256,
        "evidence": [asdict(row) for row in result.evidence],
        "failures": [asdict(row) for row in result.failures],
        "negative_requirement_ids": list(result.negative_requirement_ids),
    }
    return (
        result.policy == FINAL_TEACHING_ELIGIBILITY_POLICY
        and result.role in {"review", "counter"}
        and len({row.requirement_id for row in result.evidence}) == len(result.evidence)
        and _digest(body) == result.binding_sha256
    )


def agree_final_teaching_roles(
    review: FinalTeachingRoleResult,
    counter: FinalTeachingRoleResult,
) -> FinalTeachingAgreement:
    """Require two closed independent roles without requiring identical refs."""

    failures: list[TeachingRoleFailure] = []
    if not _role_result_valid(review) or not _role_result_valid(counter):
        return FinalTeachingAgreement((), "", (TeachingRoleFailure("invalid_teaching_role_results"),))
    if review.role != "review" or counter.role != "counter":
        failures.append(TeachingRoleFailure("teaching_role_pair_invalid"))
    if (
        review.policy != FINAL_TEACHING_ELIGIBILITY_POLICY
        or counter.policy != FINAL_TEACHING_ELIGIBILITY_POLICY
        or review.candidate_sha256 != counter.candidate_sha256
        or review.source_sha256 != counter.source_sha256
        or review.surface_registry_sha256 != counter.surface_registry_sha256
    ):
        failures.append(TeachingRoleFailure("teaching_role_binding_mismatch"))
    review_ids = tuple(row.requirement_id for row in review.evidence)
    counter_ids = tuple(row.requirement_id for row in counter.evidence)
    if review_ids != counter_ids:
        failures.append(TeachingRoleFailure("teaching_role_inventory_mismatch"))
    if review.failures or counter.failures:
        failures.append(TeachingRoleFailure("teaching_role_failure_present"))
    if review.negative_requirement_ids or counter.negative_requirement_ids:
        failures.append(TeachingRoleFailure("teaching_requirement_not_preserved"))
    if any(row.relation != "preserved" for row in (*review.evidence, *counter.evidence)):
        failures.append(TeachingRoleFailure("teaching_requirement_not_preserved"))
    for review_row, counter_row in zip(review.evidence, counter.evidence, strict=False):
        if not review_row.inventory_matches and not counter_row.inventory_matches:
            continue
        review_matches = review_row.inventory_matches
        counter_matches = counter_row.inventory_matches
        if (
            not review_matches
            or not counter_matches
            or len(review_matches) != len(counter_matches)
            or any(match.relation != "same_entity" for match in (*review_matches, *counter_matches))
            or any(
                (
                    left.requirement_id,
                    left.item_id,
                    left.source_id,
                    left.source_start,
                    left.source_end,
                    left.source_text_sha256,
                    left.candidate_sha256,
                    left.contract_binding_sha256,
                    left.relation,
                )
                != (
                    right.requirement_id,
                    right.item_id,
                    right.source_id,
                    right.source_start,
                    right.source_end,
                    right.source_text_sha256,
                    right.candidate_sha256,
                    right.contract_binding_sha256,
                    right.relation,
                )
                for left, right in zip(review_matches, counter_matches, strict=True)
            )
        ):
            failures.append(TeachingRoleFailure(
                "teaching_inventory_role_disagreement",
                review_row.requirement_id,
            ))
    body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "review_binding_sha256": review.binding_sha256,
        "counter_binding_sha256": counter.binding_sha256,
        "requirement_ids": list(review_ids),
        "failures": [asdict(row) for row in failures],
    }
    return FinalTeachingAgreement(
        requirement_ids=review_ids if not failures else (),
        binding_sha256=_digest(body),
        failures=tuple(failures),
    )
