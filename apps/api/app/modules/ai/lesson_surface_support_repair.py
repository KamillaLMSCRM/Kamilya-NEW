"""Support-bound repair proposal; no prior negative or approval is cleared."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.lesson_surface_review import (
    LESSON_SURFACE_REPAIR_PROMPT,
    MAX_LESSON_SURFACE_CHARS,
    apply_lesson_surface_repair,
    prepare_lesson_surface_repair,
)
from app.modules.ai.lesson_surface_support import (
    PreparedSupportSurface,
    SupportSurfaceResponse,
    _digest,
    prepare_support_surface,
    support_response_valid,
)

POLICY = "supported-surface-repair-v1"
REPAIR_PROMPT = LESSON_SURFACE_REPAIR_PROMPT + "\n" + (
    "For this version each replacement must include supporting_fact_ids exactly "
    "as bound to the original block; keep every governing condition. Use the "
    "supplied versioned group IDs. Return groups with blocks containing exactly "
    "block_id, heading, text, fact_ids and supporting_fact_ids. This proposes "
    "a change; a fresh source review and language review remain mandatory."
)


@dataclass(frozen=True, slots=True)
class PreparedSupportRepair:
    request_sha256: str
    semantic_response_sha256: str
    _request_json: str
    _aliases: tuple[tuple[str, str], ...]
    _support_by_block: tuple[tuple[str, tuple[str, ...]], ...]
    _prepared: PreparedSupportSurface
    _response: SupportSurfaceResponse

    @property
    def request_payload(self) -> dict[str, Any]:
        result = json.loads(self._request_json)
        if not isinstance(result, dict):
            raise ValueError("supported_repair_request")
        return result


@dataclass(frozen=True, slots=True)
class SupportRepairProposal:
    request_sha256: str
    raw_response_sha256: str
    prior_semantic_response_sha256: str
    blocks: tuple[dict[str, Any], ...]
    _prior_response: SupportSurfaceResponse
    _raw_response_json: str
    _request_json: str
    requires_fresh_review: bool = True
    publishable: bool = False


def prepare_support_repair(prepared: PreparedSupportSurface, response: SupportSurfaceResponse) -> PreparedSupportRepair:
    if not support_response_valid(prepared, response, positive=False):
        raise ValueError("supported_repair_semantic_custody")
    base = prepare_lesson_surface_repair(prepared.base, response._result)
    if not base["groups"]:
        raise ValueError("supported_repair_no_negative_scope")
    source_groups = prepared.request_payload["groups"]
    by_block: dict[str, tuple[str, ...]] = {}
    for group in source_groups:
        bindings = {row["block_index"]: tuple(row["supporting_fact_ids"]) for row in group["support_bindings"]}
        for block in group["candidate_blocks"]:
            by_block[block["block_id"]] = bindings[block["block_index"]]
    wrapper_sha = _digest(asdict(response))
    groups, aliases = [], []
    for group in base["groups"]:
        block_ids = {row["block_id"] for row in group["candidate_blocks"]}
        matches = [row for row in source_groups if {b["block_id"] for b in row["candidate_blocks"]} == block_ids]
        if len(matches) != 1 or any(fid not in by_block for fid in block_ids):
            raise ValueError("supported_repair_source_scope")
        support_group = matches[0]
        bound = {**group, "supporting_source_facts": deepcopy(support_group["supporting_source_facts"]),
                 "support_bindings": deepcopy(support_group["support_bindings"])}
        alias = "SR-" + _digest({"support_request": prepared.request_sha256,
                                  "semantic_wrapper": wrapper_sha, "group": bound})[:20]
        aliases.append((alias, group["group_id"]))
        groups.append({**bound, "group_id": alias})
    payload = {"task": "supported_surface_repair", "policy": POLICY,
               "support_request_sha256": prepared.request_sha256, "context_sha256": prepared.context_sha256,
               "semantic_wrapper_sha256": wrapper_sha, "prior_response_sha256": response.raw_response_sha256,
               "dependencies": deepcopy(prepared.request_payload["dependencies"]), "groups": groups}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) > MAX_LESSON_SURFACE_CHARS:
        raise ValueError("supported_repair_payload_too_large")
    return PreparedSupportRepair(_digest(payload), response.raw_response_sha256, encoded, tuple(aliases),
                                 tuple(by_block.items()), prepared, response)


def apply_support_repair(prepared: PreparedSupportRepair, raw_payload: Any) -> SupportRepairProposal:
    if not isinstance(prepared, PreparedSupportRepair) or not isinstance(raw_payload, dict) or set(raw_payload) != {"groups"}:
        raise ValueError("supported_repair_response")
    aliases, support = dict(prepared._aliases), dict(prepared._support_by_block)
    rows = raw_payload["groups"]
    if (not isinstance(rows, list) or len(rows) != len(aliases)
            or any(not isinstance(row, dict) or not isinstance(row.get("group_id"), str)
                   or row["group_id"] not in aliases for row in rows)
            or len({row["group_id"] for row in rows}) != len(aliases)):
        raise ValueError("supported_repair_group_inventory")
    adapted, support_by_candidate = [], {}
    for group in prepared._prepared.request_payload["groups"]:
        for row in group["candidate_blocks"]:
            key = (row["heading"], row["text"], tuple(row["fact_ids"]))
            if key in support_by_candidate:
                raise ValueError("supported_repair_ambiguous_support")
            support_by_candidate[key] = support[row["block_id"]]
    for row in rows:
        if set(row) != {"group_id", "blocks"} or not isinstance(row["blocks"], list):
            raise ValueError("supported_repair_response")
        replacements = []
        for block in row["blocks"]:
            if (not isinstance(block, dict) or set(block) != {"block_id", "heading", "text", "fact_ids", "supporting_fact_ids"}
                    or not isinstance(block["block_id"], str) or block["block_id"] not in support
                    or not isinstance(block["heading"], str) or not isinstance(block["text"], str)
                    or not isinstance(block["fact_ids"], list) or any(not isinstance(fid, str) for fid in block["fact_ids"])
                    or not isinstance(block["supporting_fact_ids"], list)
                    or tuple(block["supporting_fact_ids"]) != support[block["block_id"]]):
                raise ValueError("supported_repair_support_scope")
            key = (block["heading"], block["text"], tuple(block["fact_ids"]))
            if key in support_by_candidate and support_by_candidate[key] != support[block["block_id"]]:
                raise ValueError("supported_repair_ambiguous_support")
            support_by_candidate[key] = support[block["block_id"]]
            replacements.append({key: deepcopy(block[key]) for key in ("block_id", "heading", "text", "fact_ids")})
        adapted.append({"group_id": aliases[row["group_id"]], "blocks": replacements})
    repaired = apply_lesson_surface_repair(prepared._prepared.base, prepared._response._result, {"groups": adapted})
    result = []
    for block in repaired:
        key = (block["heading"], block["text"], tuple(block["fact_ids"]))
        if key not in support_by_candidate:
            raise ValueError("supported_repair_support_scope")
        result.append({**block, "supporting_fact_ids": list(support_by_candidate[key])})
    return SupportRepairProposal(prepared.request_sha256, _digest(raw_payload),
        prepared.semantic_response_sha256, tuple(result), prepared._response,
        json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), prepared._request_json)


async def repair_supported_surface(*, assessor: Any, lesson: Any, facts_by_id: dict[str, SourceFact],
                                   blocks: list[dict[str, Any]], support_prepared: PreparedSupportSurface,
                                   support_response: SupportSurfaceResponse, generation_client: Any,
                                   checkpoint: Any) -> SupportRepairProposal:
    """Revalidate source and full prior negative around one repair proposal."""
    original = deepcopy(blocks)

    async def current() -> PreparedSupportRepair:
        context = await assessor.semantic_author_context(lesson, facts_by_id)
        if context is None:
            raise ValueError("supported_repair_unverified_context")
        await assessor.validate_semantic_author_citations(lesson, facts_by_id, original)
        rebuilt = prepare_support_surface(lesson_id=lesson.lesson_id, owned_fact_ids=lesson.fact_ids,
            facts_by_id=facts_by_id, blocks=original, verified_context=context)
        if rebuilt != support_prepared:
            raise ValueError("supported_repair_stale_context")
        return prepare_support_repair(rebuilt, support_response)

    await checkpoint()
    prepared = await current()
    call = await generation_client.ainvoke_validated(
        [{"role": "system", "content": REPAIR_PROMPT},
         {"role": "user", "content": json.dumps(prepared.request_payload, ensure_ascii=False)}],
        parser=lambda raw: apply_support_repair(prepared, json.loads(raw)),
        response_format={"type": "json_object"}, request_profile="course_generation")
    if not isinstance(call.value, SupportRepairProposal) or call.value.request_sha256 != prepared.request_sha256:
        raise ValueError("supported_repair_stale_response")
    try:
        if apply_support_repair(prepared, json.loads(call.value._raw_response_json)) != call.value:
            raise ValueError("supported_repair_stale_response")
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("supported_repair_stale_response") from exc
    await checkpoint()
    if await current() != prepared:
        raise ValueError("supported_repair_stale_context")
    await assessor.validate_semantic_author_citations(lesson, facts_by_id, list(call.value.blocks))
    context = await assessor.semantic_author_context(lesson, facts_by_id)
    if context is None:
        raise ValueError("supported_repair_unverified_context")
    replacement = prepare_support_surface(lesson_id=lesson.lesson_id, owned_fact_ids=lesson.fact_ids,
        facts_by_id=facts_by_id, blocks=call.value.blocks, verified_context=context)
    if replacement.context_sha256 != support_prepared.context_sha256:
        raise ValueError("supported_repair_stale_context")
    return call.value
