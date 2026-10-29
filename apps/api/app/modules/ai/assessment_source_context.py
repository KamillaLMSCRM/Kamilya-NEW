"""Deterministic source-context selection for assessment creation and review.

The module selects transport views only.  It never repairs source text, infers
an exception, grants assessment credit, or treats a projected view as evidence
that the original document is complete.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.source_literal import source_context_fields

if TYPE_CHECKING:
    from app.modules.ai.evidence_engine.semantic_blocks import SemanticBlock

MAX_CONTEXT_SHARDS = 4
_SECTION_MARKER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\b")
_LABELED_SECTION_MARKER_RE = re.compile(
    r"^\s*(?:section|chapter|раздел|глава|бөлім|тарау)\s+"
    r"(\d+(?:\.\d+)*)\b", re.IGNORECASE,
)
_TEXT_REFERENCE_RES = (
    re.compile(
        r"\b(?:п\.|пункт(?:а|е|ом|у)?|подпункт(?:а|е|ом|у)?)\s*"
        r"\d+(?:\.\d+)*\s+(?:главы|главе|глава|раздела|разделе|раздел)\s*"
        r"(?P<section>\d+(?:\.\d+)*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:clause|part|paragraph)\s+\d+(?:\.\d+)*\s+of\s+"
        r"(?:section|chapter)\s+(?P<section>\d+(?:\.\d+)*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:section|chapter)\s+(?P<section>\d+(?:\.\d+)*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:раздел(?:а|е|ом|у)?|глав(?:а|ы|е|ой|у)?)\s*"
        r"(?P<section>\d+(?:\.\d+)*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<section>\d+(?:\.\d+)*)\s*[- ]?бөлім(?:нің|де|ге)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<section>\d+(?:\.\d+)*)\s*[- ]?тарау(?:дың|да|ға)?\b",
        re.IGNORECASE,
    ),
)
_EXTERNAL_REFERENCE_SUFFIX_RE = re.compile(
    r"^\s*(?:"
    r"закона|кодекса|постановления|приказа|правил\s+(?!настоящ)|"
    r"of\s+(?:the\s+)?(?:act|law|code|regulation)\b"
    r")",
    re.IGNORECASE,
)


def _immutable_ledger(values: dict[str, Any]) -> Mapping[str, Any]:
    """Expose JSON-shaped coverage metadata without mutable shared state."""

    return MappingProxyType(values)


@dataclass(frozen=True, slots=True)
class ContextSelection:
    local_facts: tuple[SourceFact, ...]
    counter_shards: tuple[tuple[SourceFact, ...], ...]
    ledger: Mapping[str, Any]
    semantic_block: SemanticBlock | None = None


class ContextProjectionError(ValueError):
    def __init__(self, code: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = _immutable_ledger(evidence or {})


@dataclass(frozen=True, slots=True)
class _Locator:
    document_id: str
    source_revision: str
    section: str
    fields: tuple[tuple[str, str], ...]

    @property
    def section_key(self) -> tuple[str, str, str]:
        return self.document_id, self.source_revision, self.section

    def get(self, key: str) -> str:
        return dict(self.fields).get(key, "")


def _budget(facts: tuple[SourceFact, ...]) -> tuple[int, int, int]:
    return (
        sum(len(fact.value) for fact in facts),
        sum(len("\n".join(source_context_fields(fact))) for fact in facts),
        len(facts),
    )


def _fits(
    facts: tuple[SourceFact, ...], *, raw_limit: int, rendered_limit: int, max_sources: int
) -> bool:
    raw, rendered, sources = _budget(facts)
    return raw <= raw_limit and rendered <= rendered_limit and sources <= max_sources


def _source_digest(facts: tuple[SourceFact, ...]) -> str:
    payload = json.dumps(
        [asdict(fact) for fact in facts],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_locator(fact: SourceFact) -> _Locator:
    fields: dict[str, str] = {}
    for item in fact.source_locator.split(";"):
        key, separator, raw = item.partition("=")
        if (
            not separator
            or not key
            or key in fields
            or re.search(r"%(?![0-9A-Fa-f]{2})", raw)
        ):
            raise ContextProjectionError(
                "source_context_locator_unresolved", {"fact_id": fact.fact_id}
            )
        try:
            fields[key] = unquote(raw, errors="strict")
        except UnicodeError as exc:
            raise ContextProjectionError(
                "source_context_locator_unresolved", {"fact_id": fact.fact_id}
            ) from exc
    required = ("doc_id", "source_revision", "section")
    if any(not fields.get(key) for key in required):
        raise ContextProjectionError(
            "source_context_locator_unresolved", {"fact_id": fact.fact_id}
        )
    return _Locator(
        fields["doc_id"], fields["source_revision"], fields["section"], tuple(fields.items())
    )


def _group_sections(
    facts: tuple[SourceFact, ...], locators: dict[str, _Locator]
) -> dict[tuple[str, str, str], tuple[SourceFact, ...]]:
    grouped: dict[tuple[str, str, str], list[SourceFact]] = {}
    for fact in facts:
        grouped.setdefault(locators[fact.fact_id].section_key, []).append(fact)
    return {key: tuple(value) for key, value in grouped.items()}


def _section_marker(value: str) -> str:
    match = _SECTION_MARKER_RE.match(value) or _LABELED_SECTION_MARKER_RE.match(value)
    return match.group(1) if match else ""


def _heading_kind(value: str) -> str | None:
    match = re.match(r"^\s*(section|chapter|раздел|глава|бөлім|тарау)\b", value, re.IGNORECASE)
    if not match:
        return None
    return "section" if match.group(1).casefold() in {"section", "раздел", "бөлім"} else "chapter"


def _reference_kind(value: str) -> str | None:
    if re.search(r"\b(?:section|раздел(?:а|е|ом|у)?|бөлім(?:нің|де|ге)?)\b", value, re.IGNORECASE):
        return "section"
    if re.search(r"\b(?:chapter|глав(?:а|ы|е|ой|у)?|тарау(?:дың|да|ға)?)\b", value, re.IGNORECASE):
        return "chapter"
    return None


def _locator_ancestor_names(locator: _Locator) -> tuple[str, ...]:
    names: list[str] = []
    parent = locator.get("parent_section") or locator.get("ancestor")
    if parent:
        names.append(parent)
    ancestors = locator.get("ancestor_sections")
    if ancestors:
        names.extend(part.strip() for part in ancestors.split("|") if part.strip())
    path = locator.get("section_path")
    if path:
        parts = tuple(part.strip() for part in path.split(">") if part.strip())
        names.extend(part for part in parts if part != locator.section)
    marker = _section_marker(locator.section)
    if marker and "." in marker:
        marker_parts = marker.split(".")
        names.extend(".".join(marker_parts[:index]) for index in range(1, len(marker_parts)))
    return tuple(dict.fromkeys(names))


def _explicit_reference_names(
    fact: SourceFact, locator: _Locator
) -> tuple[tuple[str, ...], bool]:
    names: list[str] = []
    external = False
    encoded = locator.get("internal_refs") or locator.get("internal_ref")
    if encoded:
        names.extend(part.partition("#")[0].strip() for part in encoded.split("|") if part.strip())
    for pattern in _TEXT_REFERENCE_RES:
        for match in pattern.finditer(fact.value):
            if _EXTERNAL_REFERENCE_SUFFIX_RE.match(fact.value[match.end() :]):
                external = True
            else:
                kind = _reference_kind(match.group(0))
                names.append(f"{kind}:{match.group('section')}" if kind else match.group("section"))
    return tuple(dict.fromkeys(name for name in names if name)), external


def _resolve_section_key(
    *,
    source_fact_id: str,
    name: str,
    locator: _Locator,
    sections: dict[tuple[str, str, str], tuple[SourceFact, ...]],
    relation: str,
) -> tuple[str, str, str]:
    kind, separator, marker = name.partition(":")
    if not separator or kind not in {"section", "chapter"}:
        kind, marker = "", name
    candidates = tuple(
        key
        for key in sections
        if key[:2] == (locator.document_id, locator.source_revision)
        and (key[2] == marker or _section_marker(key[2]) == marker)
        and (not kind or _heading_kind(key[2]) in (None, kind))
    )
    if len(candidates) != 1:
        raise ContextProjectionError(
            f"source_context_{relation}_unresolved",
            {"fact_id": source_fact_id, "reference": name, "candidate_count": len(candidates)},
        )
    return candidates[0]


def _dependency_graph(
    *,
    facts: tuple[SourceFact, ...],
    locators: dict[str, _Locator],
    sections: dict[tuple[str, str, str], tuple[SourceFact, ...]],
) -> tuple[
    dict[tuple[str, str, str], set[tuple[str, str, str]]],
    tuple[tuple[tuple[str, str, str], tuple[str, str, str]], ...],
    tuple[str, ...],
]:
    graph: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {
        key: set() for key in sections
    }
    reference_edges: list[tuple[tuple[str, str, str], tuple[str, str, str]]] = []
    external_fact_ids: list[str] = []
    for key, section_facts in sections.items():
        for fact in section_facts:
            locator = locators[fact.fact_id]
            for name in _locator_ancestor_names(locator):
                target = _resolve_section_key(
                    source_fact_id=fact.fact_id,
                    name=name,
                    locator=locator,
                    sections=sections,
                    relation="ancestor",
                )
                graph[key].add(target)
                graph[target].add(key)
            reference_names, has_external = _explicit_reference_names(fact, locator)
            if has_external:
                external_fact_ids.append(fact.fact_id)
            for name in reference_names:
                target = _resolve_section_key(
                    source_fact_id=fact.fact_id,
                    name=name,
                    locator=locator,
                    sections=sections,
                    relation="reference",
                )
                graph[key].add(target)
                graph[target].add(key)
                reference_edges.append((key, target))
    return graph, tuple(reference_edges), tuple(dict.fromkeys(external_fact_ids))


def _scoped_dependency_graph(
    *, facts: tuple[SourceFact, ...], locators: dict[str, _Locator],
    sections: dict[tuple[str, str, str], tuple[SourceFact, ...]],
) -> tuple[dict[tuple[str, str, str], set[tuple[str, str, str]]],
           tuple[tuple[tuple[str, str, str], tuple[str, str, str]], ...], tuple[str, ...],
           tuple[tuple[str, str, str, tuple[tuple[str, str, str], ...]], ...],
           set[tuple[str, str, str]]]:
    """Inventory unresolved edges; candidate links remain conservative, not evidence."""
    graph: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {key: set() for key in sections}
    references: list[tuple[tuple[str, str, str], tuple[str, str, str]]] = []
    external: list[str] = []
    unresolved: list[tuple[str, str, str, tuple[tuple[str, str, str], ...]]] = []
    affected: set[tuple[str, str, str]] = set()
    for key, section_facts in sections.items():
        for fact in section_facts:
            locator = locators[fact.fact_id]
            names, has_external = _explicit_reference_names(fact, locator)
            if has_external:
                external.append(fact.fact_id)
                unresolved.append((fact.fact_id, "external", "", ()))
            for relation, values in (("ancestor", _locator_ancestor_names(locator)), ("reference", names)):
                for name in values:
                    kind, separator, marker = name.partition(":")
                    if not separator or kind not in {"section", "chapter"}:
                        kind, marker = "", name
                    matches = tuple(candidate for candidate in sections if candidate[:2] == key[:2]
                        and (candidate[2] == marker or _section_marker(candidate[2]) == marker)
                        and (not kind or _heading_kind(candidate[2]) in (None, kind)))
                    if len(matches) != 1:
                        unresolved.append((fact.fact_id, relation, name, matches))
                        affected.add(key)
                        affected.update(matches)
                        # Preserve all possible incoming edges for affected-component detection.
                        for target in matches:
                            graph[key].add(target)
                            graph[target].add(key)
                        continue
                    target = matches[0]
                    graph[key].add(target)
                    graph[target].add(key)
                    if relation == "reference":
                        references.append((key, target))
    return graph, tuple(references), tuple(dict.fromkeys(external)), tuple(unresolved), affected


def _connected_keys(
    starts: set[tuple[str, str, str]],
    graph: dict[tuple[str, str, str], set[tuple[str, str, str]]],
) -> set[tuple[str, str, str]]:
    connected = set(starts)
    pending = list(starts)
    while pending:
        key = pending.pop(0)
        for target in graph[key]:
            if target not in connected:
                connected.add(target)
                pending.append(target)
    return connected


def _source_closure(
    *,
    facts: tuple[SourceFact, ...],
    seed_ids: tuple[str, ...],
    locators: dict[str, _Locator],
    sections: dict[tuple[str, str, str], tuple[SourceFact, ...]],
    graph: dict[tuple[str, str, str], set[tuple[str, str, str]]],
    reference_edges: tuple[
        tuple[tuple[str, str, str], tuple[str, str, str]], ...
    ],
) -> tuple[tuple[SourceFact, ...], tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    seed_keys = {locators[fact_id].section_key for fact_id in seed_ids}
    closure_keys = _connected_keys(seed_keys, graph)
    reference_keys = {
        target for source, target in reference_edges if source in closure_keys
    }
    local_facts = tuple(
        fact for fact in facts if locators[fact.fact_id].section_key in closure_keys
    )
    reference_ids = tuple(
        fact.fact_id
        for fact in facts
        if locators[fact.fact_id].section_key in reference_keys
        and locators[fact.fact_id].section_key not in seed_keys
    )
    ordered_keys = tuple(key for key in sections if key in closure_keys)
    return local_facts, reference_ids, ordered_keys


def _remote_dependency_groups(
    *,
    facts: tuple[SourceFact, ...],
    locators: dict[str, _Locator],
    sections: dict[tuple[str, str, str], tuple[SourceFact, ...]],
    graph: dict[tuple[str, str, str], set[tuple[str, str, str]]],
    local_section_keys: set[tuple[str, str, str]],
) -> tuple[tuple[SourceFact, ...], ...]:
    visited = set(local_section_keys)
    groups: list[tuple[SourceFact, ...]] = []
    for key in sections:
        if key in visited:
            continue
        component = _connected_keys({key}, graph) - local_section_keys
        visited.update(component)
        groups.append(
            tuple(
                fact
                for fact in facts
                if locators[fact.fact_id].section_key in component
            )
        )
    return tuple(groups)


def _pack_counter_shards(
    *,
    facts: tuple[SourceFact, ...],
    local_facts: tuple[SourceFact, ...],
    remote_sections: tuple[tuple[SourceFact, ...], ...],
    raw_limit: int,
    rendered_limit: int,
    max_sources: int,
    max_shards: int,
) -> tuple[tuple[SourceFact, ...], ...]:
    if not _fits(
        local_facts,
        raw_limit=raw_limit,
        rendered_limit=rendered_limit,
        max_sources=max_sources,
    ):
        raise ContextProjectionError(
            "source_context_local_oversize", {"local_budget": _budget(local_facts)}
        )
    local_ids = {fact.fact_id for fact in local_facts}
    position = {fact.fact_id: index for index, fact in enumerate(facts)}
    ordered_groups = sorted(
        remote_sections,
        key=lambda group: (
            -max(
                _budget(group)[0] / raw_limit,
                _budget(group)[1] / rendered_limit,
                _budget(group)[2] / max_sources,
            ),
            min(position[fact.fact_id] for fact in group),
        ),
    )
    bins: list[list[tuple[SourceFact, ...]]] = []
    for group in ordered_groups:
        candidate = (*local_facts, *group)
        if not _fits(
            candidate,
            raw_limit=raw_limit,
            rendered_limit=rendered_limit,
            max_sources=max_sources,
        ):
            raise ContextProjectionError(
                "source_context_section_oversize",
                {
                    "section_fact_ids": tuple(fact.fact_id for fact in group),
                    "combined_budget": _budget(candidate),
                },
            )
        placed = False
        for bucket in bins:
            bucket_ids = {
                fact.fact_id for existing_group in bucket for fact in existing_group
            }
            remote = tuple(
                fact
                for fact in facts
                if fact.fact_id in bucket_ids or fact.fact_id in {row.fact_id for row in group}
            )
            if _fits(
                (*local_facts, *remote),
                raw_limit=raw_limit,
                rendered_limit=rendered_limit,
                max_sources=max_sources,
            ):
                bucket.append(group)
                placed = True
                break
        if not placed:
            if len(bins) >= max_shards:
                raise ContextProjectionError(
                    "source_context_shard_limit",
                    {"maximum": max_shards, "remaining_section_count": len(ordered_groups)},
                )
            bins.append([group])
    shards: list[tuple[SourceFact, ...]] = []
    for bucket in bins:
        remote_ids = {
            fact.fact_id for group in bucket for fact in group if fact.fact_id not in local_ids
        }
        remote = tuple(fact for fact in facts if fact.fact_id in remote_ids)
        shards.append((*local_facts, *remote))
    return tuple(shards)


def _validate_limits(
    *, raw_limit: int, rendered_limit: int, max_sources: int, max_shards: int
) -> None:
    values = (raw_limit, rendered_limit, max_sources, max_shards)
    if any(type(value) is not int or value <= 0 for value in values):
        raise ContextProjectionError("source_context_invalid_limit")
    if max_shards > MAX_CONTEXT_SHARDS:
        raise ContextProjectionError(
            "source_context_invalid_shard_limit",
            {"maximum": MAX_CONTEXT_SHARDS, "received": max_shards},
        )


def _validate_inputs(
    lesson: LessonDraft, facts_by_id: dict[str, SourceFact]
) -> tuple[tuple[SourceFact, ...], tuple[str, ...]]:
    if not isinstance(lesson, LessonDraft) or not isinstance(facts_by_id, dict) or not facts_by_id:
        raise ContextProjectionError("source_context_invalid_input")
    facts = tuple(facts_by_id.values())
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(fact, SourceFact)
        or fact.fact_id != key
        or not fact.value
        for key, fact in facts_by_id.items()
    ):
        raise ContextProjectionError("source_context_invalid_fact_map")
    seed_ids = tuple(dict.fromkeys((*lesson.fact_ids, *lesson.supporting_fact_ids)))
    if not seed_ids:
        raise ContextProjectionError("source_context_seed_required")
    missing = tuple(fact_id for fact_id in seed_ids if fact_id not in facts_by_id)
    if missing:
        raise ContextProjectionError(
            "source_context_seed_missing", {"missing_fact_ids": missing}
        )
    return facts, seed_ids


def select_assessment_context(
    lesson: LessonDraft,
    facts_by_id: dict[str, SourceFact],
    *,
    raw_limit: int = 60_000,
    rendered_limit: int = 65_536,
    max_sources: int = 256,
    max_shards: int = MAX_CONTEXT_SHARDS,
) -> ContextSelection:
    """Return source-preserving local and global-counter transport views."""

    _validate_limits(
        raw_limit=raw_limit,
        rendered_limit=rendered_limit,
        max_sources=max_sources,
        max_shards=max_shards,
    )
    facts, seed_ids = _validate_inputs(lesson, facts_by_id)
    full_budget = _budget(facts)
    digest = _source_digest(facts)
    if _fits(
        facts,
        raw_limit=raw_limit,
        rendered_limit=rendered_limit,
        max_sources=max_sources,
    ):
        try:
            full_locators = {fact.fact_id: _parse_locator(fact) for fact in facts}
            full_sections = _group_sections(facts, full_locators)
            _, _, _, full_unresolved, _ = _scoped_dependency_graph(
                facts=facts, locators=full_locators, sections=full_sections)
        except ContextProjectionError as exc:
            if exc.code != "source_context_locator_unresolved":
                raise
            full_unresolved = (("", "unscopable_locator", "", ()),)
        ledger = _immutable_ledger(
            {
                "mode": "full",
                "unresolved_dependency_edges": full_unresolved,
                "unresolved_dependency_inventory_sha256": digest,
                "source_fact_ids": tuple(fact.fact_id for fact in facts),
                "source_digest_sha256": digest,
                "seed_fact_ids": seed_ids,
                "local_fact_ids": tuple(fact.fact_id for fact in facts),
                "resolved_reference_fact_ids": (),
                "external_reference_fact_ids": (),
                "remote_dependency_group_fact_ids": (),
                "counter_shard_fact_ids": (tuple(fact.fact_id for fact in facts),),
                "counter_remote_fact_ids": ((),),
                "counter_union_fact_ids": tuple(fact.fact_id for fact in facts),
                "full_budget": full_budget,
                "local_budget": full_budget,
                "counter_shard_budgets": (full_budget,),
                "coverage_complete": True,
            }
        )
        return ContextSelection(facts, (facts,), ledger)
    locators = {fact.fact_id: _parse_locator(fact) for fact in facts}
    sections = _group_sections(facts, locators)
    graph, reference_edges, external_fact_ids, unresolved_edges, affected_sections = _scoped_dependency_graph(
        facts=facts, locators=locators, sections=sections,
    )
    local_facts, reference_ids, ordered_local_keys = _source_closure(
        facts=facts,
        seed_ids=seed_ids,
        locators=locators,
        sections=sections,
        graph=graph,
        reference_edges=reference_edges,
    )
    local_section_keys = set(ordered_local_keys)
    if local_section_keys & affected_sections:
        fact_id, relation, name, matches = next(edge for edge in unresolved_edges if edge[1] != "external"
            and (locators[edge[0]].section_key in local_section_keys or set(edge[3]) & local_section_keys))
        raise ContextProjectionError(f"source_context_{relation}_unresolved",
            {"fact_id": fact_id, "reference": name, "candidate_count": len(matches)})
    remote_sections = _remote_dependency_groups(
        facts=facts,
        locators=locators,
        sections=sections,
        graph=graph,
        local_section_keys=local_section_keys,
    )
    shards = _pack_counter_shards(
        facts=facts,
        local_facts=local_facts,
        remote_sections=remote_sections,
        raw_limit=raw_limit,
        rendered_limit=rendered_limit,
        max_sources=max_sources,
        max_shards=max_shards,
    )
    if not shards:
        raise ContextProjectionError("source_context_counter_shards_empty")
    local_ids = {fact.fact_id for fact in local_facts}
    remote_by_shard = tuple(
        tuple(fact.fact_id for fact in shard if fact.fact_id not in local_ids)
        for shard in shards
    )
    remote_union = {fact_id for ids in remote_by_shard for fact_id in ids}
    expected_remote = {fact.fact_id for fact in facts if fact.fact_id not in local_ids}
    if remote_union != expected_remote or sum(map(len, remote_by_shard)) != len(expected_remote):
        raise ContextProjectionError("source_context_counter_union_incomplete")
    ledger = _immutable_ledger(
        {
            "mode": "projected",
            "unresolved_dependency_edges": unresolved_edges,
            "unresolved_dependency_inventory_sha256": digest,
            "source_fact_ids": tuple(fact.fact_id for fact in facts),
            "source_digest_sha256": digest,
            "seed_fact_ids": seed_ids,
            "local_fact_ids": tuple(fact.fact_id for fact in local_facts),
            "local_section_keys": tuple(
                key for key in sections if key in local_section_keys
            ),
            "resolved_reference_fact_ids": reference_ids,
            "external_reference_fact_ids": external_fact_ids,
            "remote_dependency_group_fact_ids": tuple(
                tuple(fact.fact_id for fact in group) for group in remote_sections
            ),
            "counter_shard_fact_ids": tuple(
                tuple(fact.fact_id for fact in shard) for shard in shards
            ),
            "counter_remote_fact_ids": remote_by_shard,
            "counter_union_fact_ids": tuple(fact.fact_id for fact in facts),
            "full_budget": full_budget,
            "local_budget": _budget(local_facts),
            "counter_shard_budgets": tuple(_budget(shard) for shard in shards),
            "coverage_complete": True,
        }
    )
    return ContextSelection(local_facts, shards, ledger)



def require_owned_internal_references_resolved(
    lesson: LessonDraft, facts_by_id: dict[str, SourceFact],
) -> None:
    """Hold only explicitly cited missing internal sections in lesson-owned facts.

    This does not infer implicit dependencies or certify semantic completeness.
    """
    owned_ids = tuple(dict.fromkeys((*lesson.fact_ids, *lesson.supporting_fact_ids)))
    for fact_id in owned_ids:
        fact = facts_by_id.get(fact_id)
        if fact is None:
            raise ContextProjectionError("source_context_seed_missing", {"missing_fact_ids": (fact_id,)})
        if not any(pattern.search(fact.value) for pattern in _TEXT_REFERENCE_RES) and "internal_ref" not in fact.source_locator:
            continue
        locator = _parse_locator(fact)
        reference_names, _ = _explicit_reference_names(fact, locator)
        if not reference_names:
            continue
        parsed = {}
        for candidate in facts_by_id.values():
            try:
                parsed[candidate.fact_id] = _parse_locator(candidate)
            except ContextProjectionError:
                # A malformed locator may conceal another candidate section.
                # Its claimed document identity is not independently trusted.
                raise ContextProjectionError("source_context_reference_unresolved", {"fact_id": fact_id}) from None
        sections = _group_sections(tuple(facts_by_id[fid] for fid in parsed), parsed)
        for name in reference_names:
            _resolve_section_key(source_fact_id=fact_id, name=name, locator=locator,
                                 sections=sections, relation="reference")


def select_semantic_assessment_context(
    lesson: LessonDraft,
    facts_by_id: dict[str, SourceFact],
    *,
    block: Any = None,
    closure_verifier: Any = None,
    raw_limit: int = 60_000,
    rendered_limit: int = 65_536,
    max_sources: int = 256,
    max_shards: int = MAX_CONTEXT_SHARDS,
) -> ContextSelection:
    """Narrow only with an internally authenticated exact closure; retain counter coverage.

    A callback is an integration trust boundary, not proof of independent review.
    No verifier or an unresolved block preserves the existing source selection.
    """
    legacy: ContextSelection | None = None
    legacy_error: ContextProjectionError | None = None
    try:
        legacy = select_assessment_context(lesson, facts_by_id, raw_limit=raw_limit,
            rendered_limit=rendered_limit, max_sources=max_sources, max_shards=max_shards)
    except ContextProjectionError as exc:
        if (block is None or closure_verifier is None or exc.code not in {
                "source_context_local_oversize", "source_context_section_oversize", "source_context_shard_limit"}):
            raise
        legacy_error = exc

    def fallback() -> ContextSelection:
        if legacy is not None:
            return legacy
        assert legacy_error is not None
        raise legacy_error

    if block is None or closure_verifier is None:
        return fallback()
    from dataclasses import replace

    from app.modules.ai.evidence_engine.semantic_blocks import SemanticBlock, build_semantic_block

    if not isinstance(block, SemanticBlock):
        raise ContextProjectionError("semantic_block_invalid", {})
    if block.requires_review or block.closure_status != "reviewed":
        return fallback()
    if not callable(closure_verifier):
        raise ContextProjectionError("semantic_block_verifier_invalid", {})
    facts = tuple(facts_by_id.values())
    digest = hashlib.sha256(json.dumps([asdict(f) for f in facts], ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    if digest != block.source_inventory_sha256 or tuple(f.fact_id for f in block.owned_facts) != tuple(lesson.fact_ids):
        raise ContextProjectionError("semantic_block_identity", {})
    selected_ids = {f.fact_id for f in block.owned_facts + block.context_facts}
    if (len(selected_ids) != len(block.owned_facts) + len(block.context_facts)
            or not set(lesson.supporting_fact_ids) <= selected_ids
            or any(facts_by_id.get(f.fact_id) != f for f in block.owned_facts + block.context_facts)):
        raise ContextProjectionError("semantic_block_identity", {})
    selected = tuple(f for f in facts if f.fact_id in selected_ids)
    try:
        corpus = block.corpus_identities
        if not corpus:
            raise ValueError("semantic_block_corpus_identity")
        documents = {doc.document_id: doc for doc in corpus}
        all_locators = tuple(_parse_locator(fact) for fact in facts)
        if (len(documents) != len(corpus) or tuple(dict.fromkeys(loc.document_id for loc in all_locators)) != tuple(doc.document_id for doc in corpus)
                or any(loc.source_revision != documents[loc.document_id].source_revision for loc in all_locators)):
            raise ValueError("semantic_block_corpus_identity")
        selected_doc_ids = {_parse_locator(fact).document_id for fact in selected}
        selected_corpus = tuple(doc for doc in corpus if doc.document_id in selected_doc_ids)
        rebuilt = build_semantic_block(identity=block.identity, block_id=block.block_id, facts=selected,
            corpus_identities=selected_corpus,
            owned_fact_ids=tuple(f.fact_id for f in block.owned_facts),
            ancestor_ids_by_fact=dict(block.ancestor_ids_by_fact), dependencies=block.dependencies,
            unresolved=block.unresolved, closure_status="reviewed",
            closure_review_evidence=block.closure_review_evidence,
            max_chars=raw_limit + sum(len(f.source_locator) for f in selected))
    except (ValueError, TypeError) as exc:
        raise ContextProjectionError("semantic_block_invalid", {}) from exc
    if replace(rebuilt, source_inventory_sha256=block.source_inventory_sha256, corpus_identities=block.corpus_identities) != block:
        raise ContextProjectionError("semantic_block_identity", {})
    if not _fits(selected, raw_limit=raw_limit, rendered_limit=rendered_limit, max_sources=max_sources):
        raise ContextProjectionError("semantic_block_oversize", {})
    if closure_verifier(block, facts) is not True:
        raise ContextProjectionError("semantic_block_untrusted", {})
    # Rebuild counters around this exact local prefix. Full-corpus one-shard
    # mode is separately bound by the worker to the trusted source inventory.
    locators = {fact.fact_id: _parse_locator(fact) for fact in facts}
    sections = _group_sections(facts, locators)
    graph, reference_edges, external_refs = _dependency_graph(facts=facts, locators=locators, sections=sections)
    selected_sections = {locators[fid].section_key for fid in selected_ids}
    if any(fid in selected_ids for fid in external_refs):
        raise ContextProjectionError("semantic_block_external_reference_unresolved", {})
    required_sections = {target for source, target in reference_edges if source in selected_sections}
    required_facts = {fact.fact_id for key in required_sections for fact in sections[key]}
    if not required_facts <= selected_ids:
        raise ContextProjectionError("semantic_block_explicit_reference_omitted", {})
    remote_ids = {fact.fact_id for fact in facts} - selected_ids
    remote_keys = {locators[fid].section_key for fid in remote_ids}
    remaining = set(remote_keys)
    groups = []
    for key in sections:
        if key not in remaining:
            continue
        component = {key}
        pending = [key]
        while pending:
            for neighbor in graph[pending.pop()] & remote_keys:
                if neighbor not in component:
                    component.add(neighbor)
                    pending.append(neighbor)
        remaining -= component
        groups.append(tuple(fact for fact in facts if fact.fact_id in remote_ids
                            and locators[fact.fact_id].section_key in component))
    if not remote_ids:
        fallback_selection = fallback()
        if len(fallback_selection.counter_shards) > 1:
            raise ContextProjectionError("semantic_block_joint_context_unavailable", {})
        return replace(fallback_selection, semantic_block=block)
    full_counter = _fits(facts, raw_limit=raw_limit, rendered_limit=rendered_limit, max_sources=max_sources)
    shards: tuple[tuple[SourceFact, ...], ...]
    if full_counter:
        shards = ((*selected, *(fact for fact in facts if fact.fact_id in remote_ids)),)
    else:
        if len(groups) < 2 or max_shards < 2:
            fallback_selection = fallback()
            if len(fallback_selection.counter_shards) > 1:
                raise ContextProjectionError("semantic_block_joint_context_unavailable", {})
            return replace(fallback_selection, semantic_block=block)
        shards = _pack_counter_shards(facts=facts, local_facts=selected, remote_sections=tuple(groups),
            raw_limit=raw_limit, rendered_limit=rendered_limit, max_sources=max_sources, max_shards=max_shards)
        if len(shards) < 2:
            raise ContextProjectionError("semantic_block_counter_partition_invalid", {})
        # A union of individually reviewed shards cannot establish implicit
        # relationships spanning shards, even with a verified local closure.
        raise ContextProjectionError("semantic_block_joint_context_unavailable", {})
    remote_by_shard = tuple(tuple(f.fact_id for f in shard if f.fact_id not in selected_ids) for shard in shards)
    if ({fid for group in remote_by_shard for fid in group} != remote_ids
            or sum(map(len, remote_by_shard)) != len(remote_ids)):
        raise ContextProjectionError("semantic_block_counter_union_incomplete", {})
    block_digest = hashlib.sha256(json.dumps(asdict(block), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    base = dict(legacy.ledger) if legacy is not None else {
        "source_fact_ids": tuple(f.fact_id for f in facts), "source_digest_sha256": _source_digest(facts),
        "seed_fact_ids": tuple(dict.fromkeys((*lesson.fact_ids, *lesson.supporting_fact_ids))),
        "full_budget": _budget(facts), "coverage_complete": True,
        "legacy_projection_error": legacy_error.code if legacy_error is not None else None,
    }
    ledger = _immutable_ledger({**base, "mode": "semantic_block", "local_fact_ids": tuple(f.fact_id for f in selected),
        "semantic_block_sha256": block_digest, "semantic_source_inventory_sha256": digest,
        "semantic_counter_retained": True, "semantic_full_counter": full_counter,
        "counter_shard_fact_ids": tuple(tuple(f.fact_id for f in shard) for shard in shards),
        "external_reference_fact_ids": external_refs,
        "counter_remote_fact_ids": remote_by_shard, "counter_union_fact_ids": tuple(f.fact_id for f in facts),
        "remote_dependency_group_fact_ids": tuple(tuple(f.fact_id for f in group) for group in groups),
        "local_budget": _budget(selected), "counter_shard_budgets": tuple(_budget(shard) for shard in shards)})
    return ContextSelection(selected, shards, ledger, block)
