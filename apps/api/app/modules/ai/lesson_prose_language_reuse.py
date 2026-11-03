"""Safe carry-forward for unchanged prose-language blocks after repair.

The module is candidate-language only.  A caller supplies server-owned context
digests solely to invalidate reuse; those digests confer no source, semantic,
coverage, dependency, or readiness credit.  Carried targets are removed from
the fresh critic request before that request exists, so an older positive vote
is never selected after observing a contradictory new vote.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.lesson_prose_language import (
    LESSON_PROSE_LANGUAGE_AXES,
    LESSON_PROSE_LANGUAGE_POLICY,
    MAX_LESSON_PROSE_BATCH_TARGETS,
    LessonProseLanguageReceipt,
    LessonProseLanguageTargetReview,
    PreparedLessonProseLanguage,
    parse_lesson_prose_language,
    prepare_lesson_prose_language,
    prose_language_receipt_valid,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


@dataclass(frozen=True, slots=True)
class LessonProseLanguageContextIdentity:
    """Invalidation-only server context for one block."""

    block_index: int
    context_sha256: str


@dataclass(frozen=True, slots=True)
class LessonProseLanguageCarryProvenance:
    """Exact proof that one prior positive whole block can be reissued."""

    policy: str
    block_index: int
    block_alias: str
    candidate_sha256: str
    prior_preparation_sha256: str
    current_preparation_sha256: str
    context_sha256: str
    neighborhood_sha256: str
    target_identity_sha256: str
    target_reviews_sha256: str
    prior_receipt_sha256: str
    provenance_sha256: str


@dataclass(frozen=True, slots=True)
class PreparedLessonProseLanguageReuse:
    """Validated prior state plus the current scoped fresh-review request."""

    policy: str
    prior_prepared: PreparedLessonProseLanguage
    prior_result: LessonProseLanguageReceipt
    current_prepared: PreparedLessonProseLanguage
    prior_contexts: tuple[LessonProseLanguageContextIdentity, ...]
    current_contexts: tuple[LessonProseLanguageContextIdentity, ...]
    carry_provenance: tuple[LessonProseLanguageCarryProvenance, ...]
    carried_block_indices: tuple[int, ...]
    fresh_block_indices: tuple[int, ...]
    state_sha256: str

    @property
    def request_batches(self) -> tuple[dict[str, Any], ...]:
        targets = [
            target
            for target in self.current_prepared.targets
            if target.block_index in self.fresh_block_indices
        ]
        if not targets:
            return ()
        batch_count = (
            len(targets) + MAX_LESSON_PROSE_BATCH_TARGETS - 1
        ) // MAX_LESSON_PROSE_BATCH_TARGETS
        blocks = [block.wire() for block in self.current_prepared.blocks]
        return tuple({
            "task": "lesson_prose_language_review",
            "policy": self.policy,
            "batch_index": batch_index,
            "batch_count": batch_count,
            "blocks": blocks,
            "review_targets": [target.wire() for target in targets[
                batch_index * MAX_LESSON_PROSE_BATCH_TARGETS:
                (batch_index + 1) * MAX_LESSON_PROSE_BATCH_TARGETS
            ]],
        } for batch_index in range(batch_count))


@dataclass(frozen=True, slots=True)
class LessonProseLanguageFreshRow:
    """Canonical untrusted row routed to one exact fresh target."""

    request_alias: str
    wire_json: str
    row_sha256: str


@dataclass(frozen=True, slots=True)
class LessonProseLanguageFreshBatch:
    policy: str
    state_sha256: str
    batch_index: int
    expected_aliases: tuple[str, ...]
    rows: tuple[LessonProseLanguageFreshRow, ...]
    batch_sha256: str


@dataclass(frozen=True, slots=True)
class LessonProseLanguageReuseResult:
    """A current native result plus auditable carry provenance."""

    policy: str
    state_sha256: str
    language_result: LessonProseLanguageReceipt
    carry_provenance: tuple[LessonProseLanguageCarryProvenance, ...]
    result_sha256: str


def _block_inputs(prepared: PreparedLessonProseLanguage) -> list[dict[str, str]]:
    return [
        {"heading": block.heading, "text": block.body}
        for block in prepared.blocks
    ]


def _context_tuple(
    values: Mapping[int, str],
    *,
    block_count: int,
) -> tuple[LessonProseLanguageContextIdentity, ...]:
    if (
        not isinstance(values, Mapping)
        or set(values) != set(range(block_count))
        or any(type(index) is not int or not _is_sha256(digest)
               for index, digest in values.items())
    ):
        raise ValueError("lesson_prose_language_reuse_invalid_context_inventory")
    return tuple(
        LessonProseLanguageContextIdentity(index, values[index])
        for index in range(block_count)
    )


def _context_map(
    values: Sequence[LessonProseLanguageContextIdentity],
) -> dict[int, str]:
    return {row.block_index: row.context_sha256 for row in values}


def _neighborhood_sha256(
    prepared: PreparedLessonProseLanguage,
    block_index: int,
) -> str:
    blocks = prepared.blocks
    return _sha256({
        "policy": prepared.policy,
        "block_count": len(blocks),
        "block_index": block_index,
        "previous_candidate_sha256": (
            blocks[block_index - 1].candidate_sha256 if block_index else ""
        ),
        "candidate_sha256": blocks[block_index].candidate_sha256,
        "next_candidate_sha256": (
            blocks[block_index + 1].candidate_sha256
            if block_index + 1 < len(blocks) else ""
        ),
    })


def _target_identity_wire(
    prepared: PreparedLessonProseLanguage,
    block_index: int,
) -> list[dict[str, Any]]:
    return [{
        "request_alias": target.request_alias,
        "block_index": target.block_index,
        "block_alias": target.block_alias,
        "kind": target.kind,
        "line_number": target.line_number,
        "indent": target.indent,
        "content": target.content,
        "newline": target.newline,
        "target_sha256": target.target_sha256,
    } for target in prepared.targets if target.block_index == block_index]


def _review_wire(review: LessonProseLanguageTargetReview) -> dict[str, Any]:
    return {
        "review_id": review.request_alias,
        **{axis: getattr(review, axis) for axis in LESSON_PROSE_LANGUAGE_AXES},
        "requires_unseen_context": review.requires_unseen_context,
        "reason": review.reason,
        "problem_part": review.problem_part,
        "problem_quote": review.problem_quote,
    }


def _carry_body(
    *,
    prior: PreparedLessonProseLanguage,
    current: PreparedLessonProseLanguage,
    block_index: int,
    context_sha256: str,
    prior_receipt: Any,
) -> dict[str, Any]:
    block = current.blocks[block_index]
    reviews = [_review_wire(review) for review in prior_receipt.target_reviews]
    return {
        "policy": LESSON_PROSE_LANGUAGE_POLICY,
        "block_index": block_index,
        "block_alias": block.block_alias,
        "candidate_sha256": block.candidate_sha256,
        "prior_preparation_sha256": prior.preparation_sha256,
        "current_preparation_sha256": current.preparation_sha256,
        "context_sha256": context_sha256,
        "neighborhood_sha256": _neighborhood_sha256(current, block_index),
        "target_identity_sha256": _sha256(_target_identity_wire(current, block_index)),
        "target_reviews_sha256": _sha256(reviews),
        "prior_receipt_sha256": prior_receipt.receipt_sha256,
    }


def _make_carry(
    *,
    prior: PreparedLessonProseLanguage,
    current: PreparedLessonProseLanguage,
    block_index: int,
    context_sha256: str,
    prior_receipt: Any,
) -> LessonProseLanguageCarryProvenance:
    body = _carry_body(
        prior=prior,
        current=current,
        block_index=block_index,
        context_sha256=context_sha256,
        prior_receipt=prior_receipt,
    )
    return LessonProseLanguageCarryProvenance(
        **body,
        provenance_sha256=_sha256(body),
    )


def _state_body(
    *,
    prior: PreparedLessonProseLanguage,
    prior_result: LessonProseLanguageReceipt,
    current: PreparedLessonProseLanguage,
    prior_contexts: Sequence[LessonProseLanguageContextIdentity],
    current_contexts: Sequence[LessonProseLanguageContextIdentity],
    carries: Sequence[LessonProseLanguageCarryProvenance],
    carried: Sequence[int],
    fresh: Sequence[int],
) -> dict[str, Any]:
    return {
        "policy": LESSON_PROSE_LANGUAGE_POLICY,
        "prior_preparation_sha256": prior.preparation_sha256,
        "prior_result_partition": {
            "receipts": [row.receipt_sha256 for row in prior_result.receipts],
            "unproved": [row.failure_sha256 for row in prior_result.unproved],
        },
        "current_preparation_sha256": current.preparation_sha256,
        "prior_contexts": [asdict(row) for row in prior_contexts],
        "current_contexts": [asdict(row) for row in current_contexts],
        "carry_provenance": [asdict(row) for row in carries],
        "carried_block_indices": list(carried),
        "fresh_block_indices": list(fresh),
    }


def _derive_reuse(
    *,
    prior_prepared: PreparedLessonProseLanguage,
    prior_result: LessonProseLanguageReceipt,
    current_prepared: PreparedLessonProseLanguage,
    prior_contexts: tuple[LessonProseLanguageContextIdentity, ...],
    current_contexts: tuple[LessonProseLanguageContextIdentity, ...],
) -> tuple[
    tuple[LessonProseLanguageCarryProvenance, ...],
    tuple[int, ...],
    tuple[int, ...],
]:
    prior_context_map = _context_map(prior_contexts)
    current_context_map = _context_map(current_contexts)
    prior_receipts = {row.block_index: row for row in prior_result.receipts}
    carries: list[LessonProseLanguageCarryProvenance] = []
    carried: list[int] = []
    fresh: list[int] = []
    for block_index, current_block in enumerate(current_prepared.blocks):
        prior_receipt = prior_receipts.get(block_index)
        same_block = (
            block_index < len(prior_prepared.blocks)
            and prior_prepared.blocks[block_index] == current_block
        )
        same_targets = (
            block_index < len(prior_prepared.blocks)
            and _target_identity_wire(prior_prepared, block_index)
            == _target_identity_wire(current_prepared, block_index)
        )
        same_context = (
            prior_context_map.get(block_index) == current_context_map.get(block_index)
        )
        same_neighborhood = (
            block_index < len(prior_prepared.blocks)
            and _neighborhood_sha256(prior_prepared, block_index)
            == _neighborhood_sha256(current_prepared, block_index)
        )
        if prior_receipt is not None and same_block and same_targets and same_context and same_neighborhood:
            carries.append(_make_carry(
                prior=prior_prepared,
                current=current_prepared,
                block_index=block_index,
                context_sha256=current_context_map[block_index],
                prior_receipt=prior_receipt,
            ))
            carried.append(block_index)
        else:
            fresh.append(block_index)
    return tuple(carries), tuple(carried), tuple(fresh)


def prepare_lesson_prose_language_reuse(
    *,
    prior_blocks: Sequence[Mapping[str, Any]],
    prior_result: LessonProseLanguageReceipt,
    current_blocks: Sequence[Mapping[str, Any]],
    prior_context_sha256_by_block: Mapping[int, str],
    current_context_sha256_by_block: Mapping[int, str],
) -> PreparedLessonProseLanguageReuse:
    """Choose all carries before a fresh request exists.

    Context hashes must be server-derived from every non-language dependency the
    caller wants to invalidate (for example source/semantic scope). They are not
    interpreted here and cannot create a positive receipt.
    """

    prior_prepared = prepare_lesson_prose_language(prior_blocks)
    current_prepared = prepare_lesson_prose_language(current_blocks)
    if not prose_language_receipt_valid(prior_result, blocks=prior_blocks):
        raise ValueError("lesson_prose_language_reuse_invalid_prior_result")
    prior_contexts = _context_tuple(
        prior_context_sha256_by_block,
        block_count=len(prior_prepared.blocks),
    )
    current_contexts = _context_tuple(
        current_context_sha256_by_block,
        block_count=len(current_prepared.blocks),
    )
    carries, carried, fresh = _derive_reuse(
        prior_prepared=prior_prepared,
        prior_result=prior_result,
        current_prepared=current_prepared,
        prior_contexts=prior_contexts,
        current_contexts=current_contexts,
    )
    body = _state_body(
        prior=prior_prepared,
        prior_result=prior_result,
        current=current_prepared,
        prior_contexts=prior_contexts,
        current_contexts=current_contexts,
        carries=carries,
        carried=carried,
        fresh=fresh,
    )
    return PreparedLessonProseLanguageReuse(
        policy=LESSON_PROSE_LANGUAGE_POLICY,
        prior_prepared=prior_prepared,
        prior_result=prior_result,
        current_prepared=current_prepared,
        prior_contexts=prior_contexts,
        current_contexts=current_contexts,
        carry_provenance=carries,
        carried_block_indices=carried,
        fresh_block_indices=fresh,
        state_sha256=_sha256(body),
    )


def _state_valid(state: Any) -> bool:
    if not isinstance(state, PreparedLessonProseLanguageReuse):
        return False
    try:
        prior = prepare_lesson_prose_language(_block_inputs(state.prior_prepared))
        current = prepare_lesson_prose_language(_block_inputs(state.current_prepared))
        prior_contexts = _context_tuple(
            _context_map(state.prior_contexts), block_count=len(prior.blocks),
        )
        current_contexts = _context_tuple(
            _context_map(state.current_contexts), block_count=len(current.blocks),
        )
    except (AttributeError, TypeError, ValueError):
        return False
    if (
        state.policy != LESSON_PROSE_LANGUAGE_POLICY
        or prior != state.prior_prepared
        or current != state.current_prepared
        or not prose_language_receipt_valid(
            state.prior_result,
            blocks=_block_inputs(prior),
        )
    ):
        return False
    carries, carried, fresh = _derive_reuse(
        prior_prepared=prior,
        prior_result=state.prior_result,
        current_prepared=current,
        prior_contexts=prior_contexts,
        current_contexts=current_contexts,
    )
    if (
        prior_contexts != state.prior_contexts
        or current_contexts != state.current_contexts
        or carries != state.carry_provenance
        or carried != state.carried_block_indices
        or fresh != state.fresh_block_indices
    ):
        return False
    body = _state_body(
        prior=prior,
        prior_result=state.prior_result,
        current=current,
        prior_contexts=prior_contexts,
        current_contexts=current_contexts,
        carries=carries,
        carried=carried,
        fresh=fresh,
    )
    return state.state_sha256 == _sha256(body)


def _fresh_row(alias: str, row: Mapping[str, Any]) -> LessonProseLanguageFreshRow:
    try:
        wire_json = _canonical_json(dict(row))
    except (TypeError, ValueError) as exc:
        raise ValueError("lesson_prose_language_reuse_invalid_review_fields") from exc
    body = {"request_alias": alias, "wire_json": wire_json}
    return LessonProseLanguageFreshRow(
        request_alias=alias,
        wire_json=wire_json,
        row_sha256=_sha256(body),
    )


def _batch_body(
    *,
    state: PreparedLessonProseLanguageReuse,
    batch_index: int,
    expected_aliases: Sequence[str],
    rows: Sequence[LessonProseLanguageFreshRow],
) -> dict[str, Any]:
    return {
        "policy": LESSON_PROSE_LANGUAGE_POLICY,
        "state_sha256": state.state_sha256,
        "batch_index": batch_index,
        "expected_aliases": list(expected_aliases),
        "rows": [asdict(row) for row in rows],
    }


def parse_lesson_prose_language_reuse_batch(
    state: PreparedLessonProseLanguageReuse,
    batch_index: int,
    raw_payload: Any,
) -> LessonProseLanguageFreshBatch:
    """Route one fresh subset; omissions become native invalid rows."""

    if not _state_valid(state):
        raise ValueError("lesson_prose_language_reuse_invalid_state")
    batches = state.request_batches
    if type(batch_index) is not int or not 0 <= batch_index < len(batches):
        raise ValueError("lesson_prose_language_reuse_invalid_batch_index")
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("lesson_prose_language_reuse_invalid_response") from exc
    else:
        payload = raw_payload
    if not isinstance(payload, dict) or set(payload) != {"language_reviews"}:
        raise ValueError("lesson_prose_language_reuse_invalid_response")
    raw_rows = payload["language_reviews"]
    expected_aliases = tuple(
        target["review_id"] for target in batches[batch_index]["review_targets"]
    )
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= len(expected_aliases):
        raise ValueError("lesson_prose_language_reuse_invalid_review_count")
    expected = set(expected_aliases)
    routed: dict[str, Mapping[str, Any]] = {}
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise ValueError("lesson_prose_language_reuse_invalid_review_fields")
        alias = row.get("review_id")
        if not isinstance(alias, str) or alias not in expected:
            raise ValueError("lesson_prose_language_reuse_unknown_review_id")
        if alias in routed:
            raise ValueError("lesson_prose_language_reuse_duplicate_review_id")
        routed[alias] = row
    rows = tuple(
        _fresh_row(alias, routed.get(alias, {"review_id": alias}))
        for alias in expected_aliases
    )
    body = _batch_body(
        state=state,
        batch_index=batch_index,
        expected_aliases=expected_aliases,
        rows=rows,
    )
    return LessonProseLanguageFreshBatch(
        policy=LESSON_PROSE_LANGUAGE_POLICY,
        state_sha256=state.state_sha256,
        batch_index=batch_index,
        expected_aliases=expected_aliases,
        rows=rows,
        batch_sha256=_sha256(body),
    )


def _fresh_batch_valid(
    state: PreparedLessonProseLanguageReuse,
    batch: Any,
) -> bool:
    if not isinstance(batch, LessonProseLanguageFreshBatch):
        return False
    batches = state.request_batches
    if (
        batch.policy != LESSON_PROSE_LANGUAGE_POLICY
        or batch.state_sha256 != state.state_sha256
        or type(batch.batch_index) is not int
        or not 0 <= batch.batch_index < len(batches)
    ):
        return False
    expected_aliases = tuple(
        row["review_id"]
        for row in batches[batch.batch_index]["review_targets"]
    )
    if batch.expected_aliases != expected_aliases or len(batch.rows) != len(expected_aliases):
        return False
    for alias, row in zip(expected_aliases, batch.rows, strict=True):
        if not isinstance(row, LessonProseLanguageFreshRow):
            return False
        if row.request_alias != alias or row.row_sha256 != _sha256({
            "request_alias": alias,
            "wire_json": row.wire_json,
        }):
            return False
        try:
            value = json.loads(row.wire_json)
        except (TypeError, ValueError):
            return False
        if not isinstance(value, dict) or value.get("review_id") != alias:
            return False
    body = _batch_body(
        state=state,
        batch_index=batch.batch_index,
        expected_aliases=expected_aliases,
        rows=batch.rows,
    )
    return batch.batch_sha256 == _sha256(body)


def _result_body(
    state: PreparedLessonProseLanguageReuse,
    language_result: LessonProseLanguageReceipt,
) -> dict[str, Any]:
    return {
        "policy": LESSON_PROSE_LANGUAGE_POLICY,
        "state_sha256": state.state_sha256,
        "language_result": asdict(language_result),
        "carry_provenance": [asdict(row) for row in state.carry_provenance],
    }


def merge_lesson_prose_language_reuse(
    state: PreparedLessonProseLanguageReuse,
    fresh_batches: Sequence[LessonProseLanguageFreshBatch],
) -> LessonProseLanguageReuseResult:
    """Rebuild one complete current result through the native parser."""

    if not _state_valid(state):
        raise ValueError("lesson_prose_language_reuse_invalid_state")
    if isinstance(fresh_batches, str | bytes) or not isinstance(fresh_batches, Sequence):
        raise ValueError("lesson_prose_language_reuse_invalid_fresh_batches")
    if (
        len(fresh_batches) != len(state.request_batches)
        or {batch.batch_index for batch in fresh_batches
            if isinstance(batch, LessonProseLanguageFreshBatch)}
        != set(range(len(state.request_batches)))
        or any(not _fresh_batch_valid(state, batch) for batch in fresh_batches)
    ):
        raise ValueError("lesson_prose_language_reuse_invalid_fresh_batches")

    fresh_rows: dict[str, dict[str, Any]] = {}
    for batch in sorted(fresh_batches, key=lambda row: row.batch_index):
        for fresh_row in batch.rows:
            value = json.loads(fresh_row.wire_json)
            fresh_rows[fresh_row.request_alias] = value

    prior_receipts = {row.block_index: row for row in state.prior_result.receipts}
    carried_rows: dict[str, dict[str, Any]] = {}
    for block_index in state.carried_block_indices:
        for review in prior_receipts[block_index].target_reviews:
            carried_rows[review.request_alias] = _review_wire(review)

    rows: list[dict[str, Any]] = []
    carried = set(state.carried_block_indices)
    for target in state.current_prepared.targets:
        selected_row = (
            carried_rows.get(target.request_alias)
            if target.block_index in carried
            else fresh_rows.get(target.request_alias)
        )
        if selected_row is None:
            raise ValueError("lesson_prose_language_reuse_missing_review_id")
        rows.append(selected_row)
    language_result = parse_lesson_prose_language(
        state.current_prepared,
        {"language_reviews": rows},
    )
    body = _result_body(state, language_result)
    return LessonProseLanguageReuseResult(
        policy=LESSON_PROSE_LANGUAGE_POLICY,
        state_sha256=state.state_sha256,
        language_result=language_result,
        carry_provenance=state.carry_provenance,
        result_sha256=_sha256(body),
    )


def lesson_prose_language_reuse_result_valid(
    state: Any,
    result: Any,
) -> bool:
    """Validate merged native output and every carry binding."""

    if (
        not _state_valid(state)
        or not isinstance(result, LessonProseLanguageReuseResult)
        or result.policy != LESSON_PROSE_LANGUAGE_POLICY
        or result.state_sha256 != state.state_sha256
        or result.carry_provenance != state.carry_provenance
        or not prose_language_receipt_valid(
            result.language_result,
            blocks=_block_inputs(state.current_prepared),
        )
    ):
        return False
    return result.result_sha256 == _sha256(_result_body(state, result.language_result))
