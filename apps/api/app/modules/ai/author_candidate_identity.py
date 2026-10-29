"""Server-owned identities for newly finalized, unproved author candidates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Sequence
from dataclasses import asdict, is_dataclass, replace
from typing import Any, TypeVar, cast

CandidateT = TypeVar("CandidateT")

_AUTHOR_ID_PREFIX = "auth-"
_AUTHOR_ID_DIGEST_CHARS = 16
_FULL_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_candidate_bytes(candidate: Any) -> bytes:
    if isinstance(candidate, type) or not is_dataclass(candidate):
        raise ValueError("author_candidate_identity_requires_dataclass")
    try:
        fields = asdict(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError("author_candidate_identity_invalid_dataclass") from exc
    if "question_id" not in fields or "learner_language" not in fields:
        raise ValueError("author_candidate_identity_missing_fields")
    if fields["learner_language"] is not None:
        raise ValueError("author_candidate_identity_language_proof_present")
    del fields["question_id"]
    del fields["learner_language"]
    try:
        canonical = json.dumps(
            fields,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("author_candidate_identity_noncanonical_content") from exc
    return canonical.encode("utf-8")


def assign_author_candidate_identities(
    candidates: Sequence[CandidateT],
    *,
    reserved_question_ids: Collection[str] = (),
) -> tuple[CandidateT, ...]:
    """Replace only temporary author IDs with deterministic server-owned IDs.

    Identity covers every finalized dataclass field except the temporary
    ``question_id`` and absent ``learner_language`` receipt. Existing language
    proof is rejected rather than carried across an identity assignment.
    """

    if isinstance(candidates, str | bytes) or not isinstance(candidates, Sequence):
        raise ValueError("author_candidate_identity_invalid_candidates")
    if isinstance(reserved_question_ids, str | bytes) or not isinstance(reserved_question_ids, Collection):
        raise ValueError("author_candidate_identity_invalid_reserved_ids")
    if any(not isinstance(question_id, str) or not question_id for question_id in reserved_question_ids):
        raise ValueError("author_candidate_identity_invalid_reserved_ids")

    reserved = set(reserved_question_ids)
    seen_content: set[bytes] = set()
    aliases: dict[str, tuple[str, bytes]] = {}
    assigned: list[CandidateT] = []
    for candidate in candidates:
        canonical = _canonical_candidate_bytes(candidate)
        if canonical in seen_content:
            raise ValueError("author_candidate_identity_duplicate_content")
        seen_content.add(canonical)

        full_digest = _sha256_hex(canonical)
        if not isinstance(full_digest, str) or _FULL_SHA256.fullmatch(full_digest) is None:
            raise ValueError("author_candidate_identity_invalid_digest")
        question_id = _AUTHOR_ID_PREFIX + full_digest[:_AUTHOR_ID_DIGEST_CHARS]
        if question_id in aliases:
            raise ValueError("author_candidate_identity_alias_collision")
        if question_id in reserved:
            raise ValueError("author_candidate_identity_reserved_collision")
        aliases[question_id] = (full_digest, canonical)
        try:
            assigned.append(cast(CandidateT, replace(cast(Any, candidate), question_id=question_id)))
        except (TypeError, ValueError) as exc:
            raise ValueError("author_candidate_identity_replace_failed") from exc
    return tuple(assigned)
