"""Prepare a source-bound support view; never grants review or coverage.

The caller must obtain and revalidate the context through the worker's trusted
selection boundary. This structural projection does not authenticate a caller.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.lesson_surface_review import (
    LESSON_SURFACE_REVIEW_PROMPT,
    MAX_LESSON_SURFACE_CHARS,
    LessonSurfaceReviewResult,
    PreparedLessonSurfaceReview,
    _block_custody,
    _review_result_valid,
    parse_lesson_surface_review,
    prepare_lesson_surface_review,
)

POLICY = "lesson-surface-support-v1"
SUPPORT_REVIEW_PROMPT = LESSON_SURFACE_REVIEW_PROMPT + "\n" + (
    "For this version only, each support_bindings row gives separately cited "
    "supporting_source_facts for that block. Use those exact facts as governing "
    "context alongside the block's owned fact_ids. They are not owned facts and "
    "cannot satisfy completeness for a different obligation. Preserve their "
    "conditions; do not infer an action or an unconditional applicability."
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedSupportSurface:
    base: PreparedLessonSurfaceReview
    context_sha256: str
    request_sha256: str
    _request_json: str
    _group_aliases: tuple[tuple[str, str], ...]

    @property
    def request_payload(self) -> dict[str, Any]:
        value = json.loads(self._request_json)
        if not isinstance(value, dict):
            raise ValueError("surface_support_request")
        return value


@dataclass(frozen=True, slots=True)
class SupportSurfaceResponse:
    request_sha256: str
    context_sha256: str
    raw_response_sha256: str
    _result: LessonSurfaceReviewResult
    _raw_response_json: str
    provider_wire_sha256: str
    _provider_wire_json: str


def prepare_support_surface(*, lesson_id: str, owned_fact_ids: Sequence[str],
                            facts_by_id: Mapping[str, SourceFact], blocks: Sequence[Mapping[str, Any]],
                            verified_context: Mapping[str, Any]) -> PreparedSupportSurface:
    """Bind distinct support to the existing owner-only surface groups.

    The result is a review request, not an independent review receipt. Keep the
    exact original context and revalidate it before interpreting any response.
    """
    context = deepcopy(dict(verified_context))
    stated = context.pop("context_sha256", None)
    if (context.get("policy") != "semantic-author-context-v1" or stated != _digest(context)
            or context.get("lesson_id") != lesson_id or context.get("owned_fact_ids") != list(owned_fact_ids)):
        raise ValueError("surface_support_context_identity")
    support_rows = context.get("supporting_facts")
    if not isinstance(support_rows, list):
        raise ValueError("surface_support_context_identity")
    support = {}
    for row in support_rows:
        if not isinstance(row, dict) or not isinstance(row.get("fact_id"), str):
            raise ValueError("surface_support_context_identity")
        fid = row["fact_id"]
        fact = facts_by_id.get(fid)
        if fid in support or fid in owned_fact_ids or fact is None:
            raise ValueError("surface_support_context_identity")
        if asdict(fact) != row:
            raise ValueError("surface_support_context_identity")
        support[fid] = row
    nodes = set(owned_fact_ids) | set(support)
    neighbors: dict[str, set[str]] = {fid: set() for fid in nodes}
    edges = context.get("dependencies")
    ancestors = context.get("ancestor_ids_by_fact")
    if not isinstance(edges, list) or not isinstance(ancestors, list):
        raise ValueError("surface_support_context_identity")
    for edge in edges:
        if (not isinstance(edge, dict) or edge.get("from_fact_id") not in nodes
                or edge.get("to_fact_id") not in nodes or edge.get("status") != "verified"):
            raise ValueError("surface_support_context_identity")
        neighbors[edge["from_fact_id"]].add(edge["to_fact_id"])
    for row in ancestors:
        if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], list)
                or row[0] not in nodes or any(fid not in nodes for fid in row[1])):
            raise ValueError("surface_support_context_identity")
        neighbors[row[0]].update(row[1])
    if not isinstance(blocks, Sequence) or isinstance(blocks, str | bytes) or not blocks:
        raise ValueError("surface_support_blocks")
    base_blocks = []
    support_by_index = []
    covered_owned: set[str] = set()
    for block in blocks:
        if not isinstance(block, Mapping) or set(block) != {"heading", "text", "fact_ids", "supporting_fact_ids"}:
            raise ValueError("surface_support_blocks")
        ids = block["supporting_fact_ids"]
        if (not isinstance(ids, list) or any(not isinstance(fid, str) for fid in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= set(support)):
            raise ValueError("surface_support_citations")
        primary = block["fact_ids"]
        if not isinstance(primary, list) or not primary or any(fid not in owned_fact_ids for fid in primary):
            raise ValueError("surface_support_citations")
        covered_owned.update(primary)
        reached, pending = set(primary), list(primary)
        while pending:
            for fid in neighbors[pending.pop()]:
                if fid not in reached:
                    reached.add(fid)
                    pending.append(fid)
        if set(ids) != reached & set(support):
            raise ValueError("surface_support_citations")
        base_blocks.append({k: deepcopy(block[k]) for k in ("heading", "text", "fact_ids")})
        support_by_index.append(tuple(ids))
    if covered_owned != set(owned_fact_ids):
        raise ValueError("surface_support_citations")
    base = prepare_lesson_surface_review(lesson_id=lesson_id, lesson_plan_fact_ids=owned_fact_ids,
                                         facts_by_id=facts_by_id, blocks=base_blocks)
    groups = []
    aliases = []
    for group, wire in zip(base.groups, base.request_payload["groups"], strict=True):
        cited = {fid for index in group.block_indices for fid in support_by_index[index]}
        grouped_support = [deepcopy(row) for fid, row in support.items() if fid in cited]
        binding = [{"block_index": index, "supporting_fact_ids": list(support_by_index[index])}
                   for index in group.block_indices]
        bound = {**wire, "supporting_source_facts": grouped_support, "support_bindings": binding}
        alias = "S-" + _digest({"context_sha256": stated, "group": bound})[:20]
        aliases.append((alias, group.request_alias))
        groups.append({**bound, "group_id": alias})
    request = {"task": "lesson_surface_support_review", "policy": POLICY, "lesson_id": lesson_id,
               "base_preparation_sha256": base.preparation_sha256, "context_sha256": stated,
               "dependencies": deepcopy(context.get("dependencies")), "groups": groups}
    request_json = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(request_json) > MAX_LESSON_SURFACE_CHARS:
        raise ValueError("surface_support_payload_too_large")
    return PreparedSupportSurface(base, stated, _digest(request), request_json, tuple(aliases))


def parse_support_surface(prepared: PreparedSupportSurface, raw_payload: Any, *, wire_raw: str | None = None) -> SupportSurfaceResponse:
    """Parse a response only; the caller must authenticate request and context again."""
    if not isinstance(prepared, PreparedSupportSurface) or not isinstance(raw_payload, dict):
        raise ValueError("surface_support_response")
    if set(raw_payload) != {"surface_reviews"} or not isinstance(raw_payload["surface_reviews"], list):
        raise ValueError("surface_support_response")
    aliases = dict(prepared._group_aliases)
    rows = raw_payload["surface_reviews"]
    if (len(rows) != len(aliases) or any(not isinstance(row, dict) or not isinstance(row.get("group_id"), str)
                                         or row["group_id"] not in aliases for row in rows)
            or len({row["group_id"] for row in rows}) != len(aliases)):
        raise ValueError("surface_support_response_inventory")
    adapted = {"surface_reviews": [{**deepcopy(row), "group_id": aliases[row["group_id"]]} for row in rows]}
    result = parse_lesson_surface_review(prepared.base, adapted)
    canonical = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    wire = canonical if wire_raw is None else wire_raw
    if not isinstance(wire, str) or _strict_json(wire) != raw_payload:
        raise ValueError("surface_support_wire")
    return SupportSurfaceResponse(prepared.request_sha256, prepared.context_sha256, _digest(raw_payload), result,
                                  canonical, hashlib.sha256(wire.encode("utf-8")).hexdigest(), wire)


def _strict_json(raw: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("surface_support_duplicate_key")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=unique)


def support_response_valid(prepared: PreparedSupportSurface, response: SupportSurfaceResponse, *, positive: bool) -> bool:
    """Check exact response/result consistency; not provider authentication."""
    if not isinstance(prepared, PreparedSupportSurface) or not isinstance(response, SupportSurfaceResponse):
        return False
    try:
        raw = _strict_json(response._provider_wire_json)
        rebuilt = parse_support_surface(prepared, raw, wire_raw=response._provider_wire_json)
        if rebuilt != response or not _review_result_valid(prepared.base, response._result):
            return False
        if positive:
            custody = _block_custody(prepared.base, response._result)
            return (not response._result.unproved and not response._result.block_gaps
                    and len(response._result.receipts) == len(prepared.base.groups)
                    and set(custody.healthy_block_ids) == {block.block_id for block in prepared.base._candidate_blocks})
        return True
    except (TypeError, ValueError, KeyError):
        return False


async def review_supported_surface(*, assessor: Any, lesson: Any, facts_by_id: dict[str, SourceFact],
                                   blocks: list[dict[str, Any]], generation_client: Any,
                                   checkpoint: Any) -> SupportSurfaceResponse:
    """Run one supported review with source revalidation on both sides of the call.

    The result is deliberately wrapped; no renderer/repair integration is
    implied. The caller owns the assessor and provider trust boundaries.
    """
    candidate = deepcopy(blocks)

    async def prepare_current() -> PreparedSupportSurface:
        context = await assessor.semantic_author_context(lesson, facts_by_id)
        if context is None:
            raise ValueError("surface_support_unverified_context")
        await assessor.validate_semantic_author_citations(lesson, facts_by_id, candidate)
        current = await assessor.semantic_author_context(lesson, facts_by_id)
        if current != context:
            raise ValueError("surface_support_stale_context")
        return prepare_support_surface(lesson_id=lesson.lesson_id, owned_fact_ids=lesson.fact_ids,
                                       facts_by_id=facts_by_id, blocks=candidate, verified_context=context)

    await checkpoint()
    prepared = await prepare_current()
    response = await generation_client.ainvoke_validated(
        [{"role": "system", "content": SUPPORT_REVIEW_PROMPT},
         {"role": "user", "content": json.dumps(prepared.request_payload, ensure_ascii=False)}],
        parser=lambda raw: parse_support_surface(prepared, _strict_json(raw), wire_raw=raw),
        response_format={"type": "json_object"}, request_profile="course_generation")
    await checkpoint()
    current = await prepare_current()
    if current != prepared or not isinstance(response.value, SupportSurfaceResponse):
        raise ValueError("surface_support_stale_context")
    if response.value.request_sha256 != prepared.request_sha256 or response.value.context_sha256 != prepared.context_sha256:
        raise ValueError("surface_support_stale_response")
    return response.value
