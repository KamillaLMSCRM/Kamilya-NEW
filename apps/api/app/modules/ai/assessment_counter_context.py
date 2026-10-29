"""Lossless bounded counter-context transport and conjunctive receipt validation.

The producer's small working set is not evidence that remote sections are safe.
Every declared source must appear in a bounded counter shard, and every shard
must independently accept the unchanged candidate before it can be retained.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.ai.lesson_cycle import LessonPacket, ReviewedQuestion, SourceExcerpt

MAX_COUNTER_SHARDS = 4


@dataclass(frozen=True)
class FullCounterScope:
    protocol: str
    tenant_id: str
    lesson_id: str
    source_inventory_sha256: str
    semantic_block_sha256: str
    source_sha256: str


def full_counter_scope(tenant_id: str, lesson_id: str, source_inventory_sha256: str,
                       semantic_block_sha256: str, sources: tuple[SourceExcerpt, ...]) -> FullCounterScope:
    """Bind a server-selected full corpus; callers must authenticate its origin."""
    identity = {"tenant_id": tenant_id, "lesson_id": lesson_id,
                "source_inventory_sha256": source_inventory_sha256,
                "semantic_block_sha256": semantic_block_sha256,
                "sources": [asdict(source) for source in sources]}
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return FullCounterScope("semantic-full-counter-v1", tenant_id, lesson_id,
                            source_inventory_sha256, semantic_block_sha256, digest)


def single_counter_packet(packet: LessonPacket, sources: tuple[SourceExcerpt, ...]) -> LessonPacket:
    return replace(packet, sources=sources, counter_source_shards=(), counter_source_coverage=(), semantic_full_counter=None)


def validate_counter_context(
    packet: LessonPacket, validate: Callable[[LessonPacket], None], *, raw_limit: int,
) -> None:
    shards, coverage = packet.counter_source_shards, packet.counter_source_coverage
    scope = packet.semantic_full_counter
    if not shards:
        if coverage or scope is not None:
            raise ValueError("lesson_cycle_counter_context_coverage_without_shards")
        return
    if (not isinstance(shards, tuple | list) or not (2 <= len(shards) <= MAX_COUNTER_SHARDS or len(shards) == 1 and scope is not None)
            or not isinstance(coverage, tuple | list) or not coverage
            or any(not isinstance(sid, str) for sid in coverage) or len(set(coverage)) != len(coverage)):
        raise ValueError("lesson_cycle_counter_context_bounds")
    if scope is not None:
        if (len(shards) != 1 or not isinstance(scope, FullCounterScope) or scope.protocol != "semantic-full-counter-v1"
                or scope.tenant_id != packet.tenant_id or scope.lesson_id != packet.lesson_id
                or any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{64}", x)
                       for x in (scope.source_inventory_sha256, scope.semantic_block_sha256, scope.source_sha256))
                or scope != full_counter_scope(packet.tenant_id, packet.lesson_id, scope.source_inventory_sha256,
                                               scope.semantic_block_sha256, tuple(shards[0]))
                or tuple(source.source_id for source in shards[0]) != tuple(coverage)):
            raise ValueError("lesson_cycle_counter_context_full_scope")
    union: dict[str, SourceExcerpt] = {}
    for sources in shards:
        if (not isinstance(sources, tuple | list)
                or tuple(sources[:len(packet.sources)]) != tuple(packet.sources)):
            raise ValueError("lesson_cycle_counter_context_local_prefix")
        validate(single_counter_packet(packet, tuple(sources)))
        # Raw and rendered budgets are independent; neither may be raised by
        # moving a complete document from the producer to the counter stage.
        if sum(len(source.original_text or source.text) for source in sources) > raw_limit:
            raise ValueError("lesson_cycle_counter_context_raw_bounds")
        for source in sources:
            if source.source_id in union and union[source.source_id] != source:
                raise ValueError("lesson_cycle_counter_context_source_conflict")
            union[source.source_id] = source
    if set(union) != set(coverage):
        raise ValueError("lesson_cycle_counter_context_union_incomplete")


def counter_context_failure(
    packet: LessonPacket,
    question: ReviewedQuestion,
    audit: dict[str, Any],
    validate_audit: Callable[[LessonPacket, ReviewedQuestion, dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """A missing, substituted, failed or stale shard is never a positive audit."""
    failure = {"code": "counter_context_not_proven", "target_ids": list(question.target_ids)}
    rows = audit.get("context_shards")
    if (not isinstance(rows, list) or len(rows) != len(packet.counter_source_shards)
            or audit.get("context_source_ids") != list(packet.counter_source_coverage)):
        return failure
    retained_targets: set[str] | None = None
    for index, (row, sources) in enumerate(zip(rows, packet.counter_source_shards, strict=True)):
        if (not isinstance(row, dict) or set(row) != {"source_ids", "audit"}
                or row["source_ids"] != [source.source_id for source in sources]
                or not isinstance(row["audit"], dict)
                or {"context_shards", "context_source_ids"} & row["audit"].keys()):
            return failure
        if index == 0 and audit != {**row["audit"], "context_shards": rows,
                                   "context_source_ids": list(packet.counter_source_coverage)}:
            return failure
        rejected = validate_audit(single_counter_packet(packet, tuple(sources)), question, row["audit"])
        if rejected is not None:
            return {**failure, "shard_index": index, "shard_failure": rejected}
        proofs = row["audit"].get("target_proofs")
        if not isinstance(proofs, list) or any(not isinstance(proof, dict)
                or not isinstance(proof.get("target_id"), str) for proof in proofs):
            return failure
        targets = {proof["target_id"] for proof in proofs}
        if not targets or (retained_targets is not None and targets != retained_targets):
            return {**failure, "shard_index": index, "shard_failure": "target_coverage_disagreement"}
        retained_targets = targets
    return None
