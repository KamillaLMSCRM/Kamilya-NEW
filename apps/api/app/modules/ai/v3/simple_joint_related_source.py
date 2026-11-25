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

# These markers select literal evidence for comparison. The editor decides
# whether the texts describe the same action and whether any change is needed.
_BRANCH = re.compile(
    r"\b(?:либо|кроме|за исключением|при отсутствии|в противном случае|"
    r"unless|except|otherwise|or if|немесе|болмаса|қоспағанда)\b", re.IGNORECASE
)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")
_BRANCH_LIMIT = 10


def _keywords(text: str) -> set[str]:
    return {word[:5] for word in _WORDS.findall(text.casefold()) if len(word) >= 4 or word.isdecimal()}


def companion_branch_targets(payload: dict[str, Any], proposal: dict[str, Any]) -> list[tuple[float, dict[str, Any]]]:
    """Find likely omitted scope details without judging the course or source."""
    related = set(payload.get('companion_source_refs', ()))
    if not related:
        return []
    passages = []
    for block in payload['source_blocks']:
        if block['id'] not in related:
            continue
        for segment in block['segments']:
            if segment.get('asset_id'):
                continue
            for line in segment['text'].splitlines():
                branch = _BRANCH.search(line)
                if branch is None or line.lstrip().startswith('|') or len(line) > 1000:
                    continue
                prefix, suffix = _keywords(line[:branch.start()]), _keywords(line[branch.end():])
                if len(prefix) >= 5 and len(suffix) >= 3:
                    passages.append((block['id'], line.strip(), prefix, suffix))
    edits = {row['block_id']: row['after'] for row in proposal['body_edits']}
    targets = []
    for lesson in payload['original_course']['lessons']:
        for paragraph in lesson['body_blocks']:
            text = edits.get(paragraph['id'], paragraph['text'])
            if len(text) > 3500:
                continue
            whole = _keywords(text)
            sentence_words = [_keywords(sentence) for sentence in _SENTENCE_END.split(text)]
            matches = []
            for ref, quote, prefix, suffix in passages:
                unheard = suffix - whole
                if len(unheard) < 3:
                    continue
                length = len(prefix)
                overlap = max((len(words & prefix) for words in sentence_words), default=0)
                shared_digits = sum(word.isdecimal() for word in prefix & whole)
                if overlap >= 5 and (overlap / length >= 0.30 or shared_digits >= 2):
                    matches.append((overlap / length + overlap / 35 + min(shared_digits, 2) / 10, ref, quote))
            if matches:
                matches.sort(key=lambda item: (-item[0], item[1]))
                # Different repetitions may expose complementary conditions.
                quotes = list(dict.fromkeys((ref, quote) for _, ref, quote in matches))[:3]
                targets.append((matches[0][0], {
                    'lesson_id': lesson['id'], 'lesson_title': lesson['title'], 'block_id': paragraph['id'],
                    'current_paragraph': text,
                    'companion_clauses': [{'source_ref': ref, 'quote': quote} for ref, quote in quotes],
                }))
    return targets


def select_branch_targets(rows: list[tuple[float, dict[str, Any]]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (-row[0], row[1]['block_id']))
    chosen = []
    size = 0
    for _, row in ranked:
        char_count = len(row['current_paragraph']) + sum(len(clause['quote']) for clause in row['companion_clauses'])
        if size + char_count > 16000:
            continue
        chosen.append(row)
        size += char_count
        if len(chosen) == _BRANCH_LIMIT:
            break
    return chosen
