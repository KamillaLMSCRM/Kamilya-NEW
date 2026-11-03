"""Immutable source-block transport contract; never a semantic or release approval.

The caller owns source extraction, ancestry completeness and review attribution.
Facts, hashes, explicit edge status and review references establish structural
identity only: they cannot prove that all semantic dependencies were found.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from app.modules.ai.assessment_source_context import (
    _group_sections,
    _locator_ancestor_names,
    _parse_locator,
    _resolve_section_key,
)
from app.modules.ai.evidence_engine.models import SourceFact


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    document_id: str
    source_revision: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class SourceDependency:
    dependency_id: str
    from_fact_id: str
    to_fact_id: str
    relation: Literal["definition", "reference", "condition", "other"]
    source_quote: str
    from_locator: str
    to_locator: str
    status: Literal["verified", "uncertain"]
    condition: str | None = None
    review_evidence: str | None = None


@dataclass(frozen=True, slots=True)
class UnresolvedDependency:
    dependency_id: str
    from_fact_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SemanticBlock:
    identity: SourceIdentity
    block_id: str
    source_inventory_sha256: str
    owned_facts: tuple[SourceFact, ...]
    context_facts: tuple[SourceFact, ...]
    ancestor_ids_by_fact: tuple[tuple[str, tuple[str, ...]], ...]
    dependencies: tuple[SourceDependency, ...]
    unresolved: tuple[UnresolvedDependency, ...]
    closure_status: str
    closure_review_evidence: str | None
    requires_review: bool
    semantic_approval: bool = False
    publishable: bool = False
    corpus_identities: tuple[SourceIdentity, ...] = ()


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def build_semantic_block(
    *,
    identity: SourceIdentity,
    corpus_identities: tuple[SourceIdentity, ...] | None = None,
    block_id: str,
    facts: tuple[SourceFact, ...],
    owned_fact_ids: tuple[str, ...],
    ancestor_ids_by_fact: Mapping[str, tuple[str, ...]],
    dependencies: tuple[SourceDependency, ...] = (),
    unresolved: tuple[UnresolvedDependency, ...] = (),
    closure_status: Literal["not_reviewed", "uncertain", "reviewed"] = "not_reviewed",
    closure_review_evidence: str | None = None,
    max_chars: int = 60_000,
) -> SemanticBlock:
    """Build one exact, directed block; a reviewed label is not source proof."""
    if (
        not isinstance(identity, SourceIdentity)
        or not _nonempty(identity.document_id)
        or not isinstance(identity.source_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", identity.source_sha256)
        or identity.source_revision != "document:" + identity.source_sha256
        or not _nonempty(block_id)
    ):
        raise ValueError("semantic_block_identity")
    corpus = (identity,) if corpus_identities is None else corpus_identities
    if (
        not isinstance(corpus, tuple)
        or not corpus
        or len(corpus) > 512
        or any(
            not isinstance(doc, SourceIdentity)
            or not _nonempty(doc.document_id)
            or not isinstance(doc.source_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", doc.source_sha256)
            or doc.source_revision != "document:" + doc.source_sha256
            for doc in corpus
        )
        or len({doc.document_id for doc in corpus}) != len(corpus)
        or identity not in corpus
    ):
        raise ValueError("semantic_block_corpus_identity")
    documents = {doc.document_id: doc for doc in corpus}
    if (
        not isinstance(facts, tuple)
        or not facts
        or len(facts) > 512
        or any(not isinstance(f, SourceFact) for f in facts)
        or not isinstance(owned_fact_ids, tuple)
        or not owned_fact_ids
        or any(not _nonempty(fid) for fid in owned_fact_ids)
        or len(set(owned_fact_ids)) != len(owned_fact_ids)
        or type(max_chars) is not int
        or max_chars <= 0
    ):
        raise ValueError("semantic_block_inventory")
    by_id: dict[str, SourceFact] = {}
    locators = {}
    for fact in facts:
        if (
            not _nonempty(fact.fact_id)
            or fact.fact_id in by_id
            or not _nonempty(fact.value)
            or not _nonempty(fact.source_locator)
        ):
            raise ValueError("semantic_block_fact")
        locator = _parse_locator(fact)
        source = documents.get(locator.document_id)
        if source is None or locator.source_revision != source.source_revision:
            raise ValueError("semantic_block_foreign_source")
        by_id[fact.fact_id] = fact
        locators[fact.fact_id] = locator
    if not set(owned_fact_ids) <= set(by_id):
        raise ValueError("semantic_block_missing_owner")
    if tuple(dict.fromkeys(locators[fid].document_id for fid in by_id)) != tuple(
        doc.document_id for doc in corpus
    ) or any(locators[fid].document_id != identity.document_id for fid in owned_fact_ids):
        raise ValueError("semantic_block_corpus_inventory")
    if not isinstance(ancestor_ids_by_fact, Mapping) or set(ancestor_ids_by_fact) != set(by_id):
        raise ValueError("semantic_block_ancestor_inventory")
    graph: dict[str, list[str]] = {fid: [] for fid in by_id}
    sections = _group_sections(facts, locators)
    for fid, ancestors in ancestor_ids_by_fact.items():
        if (
            not isinstance(ancestors, tuple)
            or any(not _nonempty(a) for a in ancestors)
            or len(set(ancestors)) != len(ancestors)
            or not set(ancestors) <= set(by_id)
        ):
            raise ValueError("semantic_block_ancestor_inventory")
        if any(locators[ancestor].document_id != locators[fid].document_id for ancestor in ancestors):
            raise ValueError("semantic_block_cross_document_ancestor")
        required: set[str] = set()
        for name in _locator_ancestor_names(locators[fid]):
            key = _resolve_section_key(
                source_fact_id=fid, name=name, locator=locators[fid], sections=sections, relation="ancestor"
            )
            required.update(fact.fact_id for fact in sections[key])
        if not required <= set(ancestors):
            raise ValueError("semantic_block_ancestor_omitted")
        graph[fid].extend(ancestors)
    if (
        not isinstance(dependencies, tuple)
        or not isinstance(unresolved, tuple)
        or len(dependencies) + len(unresolved) > 4096
    ):
        raise ValueError("semantic_block_dependencies")
    ids: set[str] = set()
    for edge in dependencies:
        if (
            not isinstance(edge, SourceDependency)
            or not _nonempty(edge.dependency_id)
            or edge.dependency_id in ids
            or not _nonempty(edge.from_fact_id)
            or not _nonempty(edge.to_fact_id)
            or edge.from_fact_id not in by_id
            or edge.to_fact_id not in by_id
            or not _nonempty(edge.relation)
            or edge.relation not in {"definition", "reference", "condition", "other"}
            or not _nonempty(edge.status)
            or edge.status not in {"verified", "uncertain"}
            or not _nonempty(edge.source_quote)
            or edge.source_quote not in by_id[edge.from_fact_id].value
            or by_id[edge.from_fact_id].value.find(
                edge.source_quote, by_id[edge.from_fact_id].value.find(edge.source_quote) + 1
            )
            != -1
            or edge.from_locator != by_id[edge.from_fact_id].source_locator
            or edge.to_locator != by_id[edge.to_fact_id].source_locator
            or (edge.status == "verified" and not _nonempty(edge.review_evidence))
            or (edge.review_evidence is not None and not _nonempty(edge.review_evidence))
            or (
                edge.condition is not None
                and (not _nonempty(edge.condition) or edge.condition not in by_id[edge.from_fact_id].value)
            )
        ):
            raise ValueError("semantic_block_dependency")
        ids.add(edge.dependency_id)
        graph[edge.from_fact_id].append(edge.to_fact_id)
    for item in unresolved:
        if (
            not isinstance(item, UnresolvedDependency)
            or not _nonempty(item.dependency_id)
            or item.dependency_id in ids
            or not _nonempty(item.from_fact_id)
            or item.from_fact_id not in by_id
            or not _nonempty(item.reason)
        ):
            raise ValueError("semantic_block_unresolved")
        ids.add(item.dependency_id)
    if (
        not _nonempty(closure_status)
        or closure_status not in {"not_reviewed", "uncertain", "reviewed"}
        or (closure_status == "reviewed" and not _nonempty(closure_review_evidence))
        or (closure_review_evidence is not None and not _nonempty(closure_review_evidence))
    ):
        raise ValueError("semantic_block_closure_review")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(fid: str) -> None:
        if fid in visiting:
            raise ValueError("semantic_block_cycle")
        if fid in visited:
            return
        visiting.add(fid)
        for target in graph[fid]:
            visit(target)
        visiting.remove(fid)
        visited.add(fid)

    for fid in by_id:
        visit(fid)
    selected: set[str] = set()
    pending = list(owned_fact_ids)
    while pending:
        fid = pending.pop()
        if fid not in selected:
            selected.add(fid)
            pending.extend(graph[fid])
    selected_edges = tuple(edge for edge in dependencies if edge.from_fact_id in selected)
    if any(item.from_fact_id not in selected for item in unresolved):
        raise ValueError("semantic_block_unresolved_outside_block")
    if sum(len(by_id[fid].value) + len(by_id[fid].source_locator) for fid in selected) > max_chars:
        raise ValueError("semantic_block_atomic_oversize")
    digest = hashlib.sha256(
        json.dumps(
            [asdict(f) for f in facts], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return SemanticBlock(
        identity=identity,
        block_id=block_id,
        source_inventory_sha256=digest,
        owned_facts=tuple(by_id[fid] for fid in owned_fact_ids),
        context_facts=tuple(f for f in facts if f.fact_id in selected and f.fact_id not in owned_fact_ids),
        ancestor_ids_by_fact=tuple((fid, ancestor_ids_by_fact[fid]) for fid in by_id if fid in selected),
        dependencies=selected_edges,
        unresolved=unresolved,
        closure_status=closure_status,
        closure_review_evidence=closure_review_evidence,
        corpus_identities=corpus,
        requires_review=(
            closure_status != "reviewed"
            or bool(unresolved)
            or any(edge.status != "verified" for edge in selected_edges)
        ),
    )
