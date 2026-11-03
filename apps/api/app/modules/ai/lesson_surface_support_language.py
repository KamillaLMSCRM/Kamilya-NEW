"""Support-bound language audit; independent source and release gates remain."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.lesson_prose_language import (
    LESSON_PROSE_LANGUAGE_PROMPT,
    LessonProseLanguageReceipt,
    PreparedLessonProseLanguage,
    parse_lesson_prose_language,
    parse_lesson_prose_language_batch,
    prepare_lesson_prose_language,
)
from app.modules.ai.lesson_surface_support import (
    PreparedSupportSurface,
    SupportSurfaceResponse,
    _digest,
    _strict_json,
    prepare_support_surface,
    support_response_valid,
)

POLICY = "supported-surface-language-v1"


@dataclass(frozen=True, slots=True)
class PreparedSupportLanguage:
    binding_sha256: str
    base: PreparedLessonProseLanguage
    support_request_sha256: str
    semantic_wrapper_sha256: str
    _batches_json: tuple[str, ...]
    _aliases: tuple[tuple[tuple[str, str], ...], ...]

    @property
    def request_batches(self) -> tuple[dict[str, Any], ...]:
        batches = tuple(json.loads(raw) for raw in self._batches_json)
        if any(not isinstance(batch, dict) for batch in batches):
            raise ValueError("supported_language_request")
        return batches


@dataclass(frozen=True, slots=True)
class SupportLanguageResponse:
    binding_sha256: str
    support_request_sha256: str
    semantic_response_sha256: str
    raw_batch_sha256: tuple[str, ...]
    provider_wire_sha256: tuple[str, ...]
    _result: LessonProseLanguageReceipt
    _raw_batch_json: tuple[str, ...]


def prepare_support_language(prepared: PreparedSupportSurface, response: SupportSurfaceResponse,
                             blocks: list[dict[str, Any]]) -> PreparedSupportLanguage:
    """Bind exact support and semantic wrapper to candidate-only language requests."""
    if not support_response_valid(prepared, response, positive=True):
        raise ValueError("supported_language_semantic_custody")
    bindings = {row["block_index"]: row["supporting_fact_ids"]
                for group in prepared.request_payload["groups"] for row in group["support_bindings"]}
    if (len(blocks) != len(prepared.base._candidate_blocks) or len(bindings) != len(blocks)
            or any(not isinstance(row, dict) or row.get("heading") != original.heading or row.get("text") != original.text
                   or row.get("fact_ids") != list(original.fact_ids)
                   or row.get("supporting_fact_ids") != bindings.get(index)
                   for index, (row, original) in enumerate(zip(blocks, prepared.base._candidate_blocks, strict=True)))):
        raise ValueError("supported_language_stale_candidate")
    base_blocks = [{key: row[key] for key in ("heading", "text", "fact_ids")} for row in blocks]
    base = prepare_lesson_prose_language(base_blocks)
    binding = _digest({"policy": POLICY, "support_request": prepared.request_payload,
                       "semantic_wrapper": asdict(response), "blocks": blocks,
                       "language_preparation_sha256": base.preparation_sha256})
    batches, aliases = [], []
    for batch in base.request_batches:
        current, mapping = deepcopy(batch), []
        current["policy"] = POLICY
        current["support_binding_sha256"] = binding
        for row in current["review_targets"]:
            previous = row["review_id"]
            alias = "SL-" + _digest({"binding": binding, "review_id": previous})[:20]
            mapping.append((alias, previous))
            row["review_id"] = alias
        batches.append(json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        aliases.append(tuple(mapping))
    return PreparedSupportLanguage(binding, base, prepared.request_sha256, _digest(asdict(response)),
                                   tuple(batches), tuple(aliases))


def _parse_batch(prepared: PreparedSupportLanguage, index: int, payload: Any) -> tuple[dict[str, Any], ...]:
    mapping = dict(prepared._aliases[index])
    if not isinstance(payload, dict) or set(payload) != {"language_reviews"}:
        raise ValueError("supported_language_response")
    rows = payload["language_reviews"]
    if (not isinstance(rows, list) or len(rows) != len(mapping)
            or any(not isinstance(row, dict) or not isinstance(row.get("review_id"), str)
                   or row["review_id"] not in mapping for row in rows)
            or len({row["review_id"] for row in rows}) != len(mapping)):
        raise ValueError("supported_language_response_inventory")
    adapted = {"language_reviews": [{**row, "review_id": mapping[row["review_id"]]} for row in rows]}
    return parse_lesson_prose_language_batch(prepared.base, index, adapted)


def parse_support_language(prepared: PreparedSupportLanguage, support_prepared: PreparedSupportSurface,
                           support_response: SupportSurfaceResponse, raw_batches: tuple[str, ...]) -> SupportLanguageResponse:
    """Reconstruct exact language custody; hashes do not authenticate providers."""
    if (not isinstance(prepared, PreparedSupportLanguage) or not support_response_valid(support_prepared, support_response, positive=True)
            or prepared.support_request_sha256 != support_prepared.request_sha256
            or prepared.semantic_wrapper_sha256 != _digest(asdict(support_response))
            or not isinstance(raw_batches, tuple) or len(raw_batches) != len(prepared._aliases)):
        raise ValueError("supported_language_semantic_custody")
    all_rows: list[dict[str, Any]] = []
    hashes = []
    canonical = []
    for index, raw in enumerate(raw_batches):
        try:
            payload = _strict_json(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("supported_language_response") from exc
        all_rows.extend(_parse_batch(prepared, index, payload))
        hashes.append(_digest(payload))
        canonical.append(raw)
    result = parse_lesson_prose_language(prepared.base, {"language_reviews": all_rows})
    return SupportLanguageResponse(prepared.binding_sha256, support_prepared.request_sha256,
        support_response.raw_response_sha256, tuple(hashes),
        tuple(hashlib.sha256(raw.encode("utf-8")).hexdigest() for raw in canonical), result, tuple(canonical))


def support_language_response_valid(prepared: PreparedSupportLanguage, support_prepared: PreparedSupportSurface,
                                    support_response: SupportSurfaceResponse, blocks: list[dict[str, Any]],
                                    response: SupportLanguageResponse) -> bool:
    """Check complete positive custody; this does not authenticate the provider."""
    if not isinstance(response, SupportLanguageResponse):
        return False
    try:
        if (prepare_support_language(support_prepared, support_response, blocks) != prepared
                or parse_support_language(prepared, support_prepared, support_response, response._raw_batch_json) != response
                or response._result.unproved):
            return False
        base_blocks = [{key: row[key] for key in ("heading", "text", "fact_ids")} for row in blocks]
        return response._result.reviewed_block_indices(blocks=base_blocks) == frozenset(range(len(blocks)))
    except (TypeError, ValueError, KeyError, IndexError):
        return False


async def review_supported_language(*, assessor: Any, lesson: Any, facts_by_id: dict[str, SourceFact],
                                    blocks: list[dict[str, Any]], support_prepared: PreparedSupportSurface,
                                    support_response: SupportSurfaceResponse, generation_client: Any,
                                    checkpoint: Any) -> SupportLanguageResponse:
    """Invoke candidate-only language review while retaining support custody."""
    candidate = deepcopy(blocks)

    async def current() -> PreparedSupportLanguage:
        context = await assessor.semantic_author_context(lesson, facts_by_id)
        if context is None:
            raise ValueError("supported_language_unverified_context")
        await assessor.validate_semantic_author_citations(lesson, facts_by_id, candidate)
        rebuilt = prepare_support_surface(lesson_id=lesson.lesson_id, owned_fact_ids=lesson.fact_ids,
            facts_by_id=facts_by_id, blocks=candidate, verified_context=context)
        if rebuilt != support_prepared:
            raise ValueError("supported_language_stale_context")
        return prepare_support_language(rebuilt, support_response, candidate)

    await checkpoint()
    prepared = await current()
    raw_batches = []
    for index, batch in enumerate(prepared.request_batches):
        def parser(raw: str, *, batch_index: int = index) -> Any:
            payload = _strict_json(raw)
            _parse_batch(prepared, batch_index, payload)
            return raw

        call = await generation_client.ainvoke_validated(
            [{"role": "system", "content": LESSON_PROSE_LANGUAGE_PROMPT},
             {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}],
            parser=parser, response_format={"type": "json_object"}, request_profile="course_generation")
        raw_batches.append(call.value)
    result = parse_support_language(prepared, support_prepared, support_response, tuple(raw_batches))
    await checkpoint()
    if await current() != prepared:
        raise ValueError("supported_language_stale_context")
    return result
