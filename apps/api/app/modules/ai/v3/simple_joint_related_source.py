"""Find literal companion clauses for scoped course edits."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

_WORDS = re.compile(r"[^\W_]+")
_PHRASE_LENGTH = 5
_MAX_PASSAGES = 12
_MAX_BYTES = 16_000


@dataclass(frozen=True)
class _Passage:
    source_ref: str
    words: tuple[str, ...]
    phrases: frozenset[tuple[str, ...]]


def _passages(block: dict[str, Any]) -> list[_Passage]:
    passages = []
    for segment in block["segments"]:
        if segment.get("asset_id"):
            continue
        for line in segment["text"].splitlines():
            if line.lstrip().startswith("|"):
                continue
            words = tuple(_WORDS.findall(line.casefold()))
            if len(words) < 8:
                continue
            phrases = frozenset(
                words[i:i + _PHRASE_LENGTH] for i in range(len(words) - _PHRASE_LENGTH + 1)
            )
            passages.append(_Passage(block["id"], words, phrases))
    return passages


def related_source_blocks(blocks: list[dict[str, Any]], owned_refs: set[str]) -> list[dict[str, Any]]:
    """Return bounded evidence from the same approved document as a matching passage."""
    by_ref = {block["id"]: block for block in blocks}
    by_document: dict[str, list[_Passage]] = defaultdict(list)
    for block in blocks:
        by_document[block["document_id"]].extend(_passages(block))

    scores: dict[str, float] = {}
    for passages in by_document.values():
        owned = [passage for passage in passages if passage.source_ref in owned_refs]
        if not owned:
            continue
        known = {passage.words for passage in owned}
        frequency = Counter(phrase for passage in passages for phrase in passage.phrases)
        index: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for i, passage in enumerate(passages):
            if passage.source_ref in owned_refs or passage.words in known:
                continue
            for phrase in passage.phrases:
                if 2 <= frequency[phrase] <= 8:
                    index[phrase].append(i)
        for query in owned:
            matches = Counter(i for phrase in query.phrases for i in index.get(phrase, ()))
            for i, hits in matches.items():
                candidate = passages[i]
                density = hits / min(len(query.phrases), len(candidate.phrases))
                if hits >= 4 and density >= 0.28:
                    scores[candidate.source_ref] = max(scores.get(candidate.source_ref, 0), hits * density)

    chosen = []
    remaining = _MAX_BYTES
    for ref in sorted(scores, key=lambda ref: (-scores[ref], ref)):
        block = by_ref[ref]
        size = sum(len(segment["text"].encode("utf-8")) for segment in block["segments"])
        if size <= remaining:
            chosen.append(block)
            remaining -= size
            if len(chosen) == _MAX_PASSAGES:
                break
    return chosen
