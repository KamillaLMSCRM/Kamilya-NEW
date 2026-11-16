"""Conservative, literal-bound admission of existing editorial reviewer evidence.

The model judges necessity and grammar. Native code checks evidence custody and
unchanged attachment addresses; it never declares a sentence semantically true.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict
from difflib import SequenceMatcher
from typing import Any

from app.modules.ai.source_editorial import SourceEditorialPatch, SourceEditorialProposal

EVIDENCE_KEY = 'editorial_evidence'
_WORDS = re.compile(r'[^\W\d_]+', re.UNICODE)
_RELATIONS = frozenset({'subject', 'object', 'modifier', 'predicate', 'adverbial', 'standalone'})


def patch_context(source: str, patch: SourceEditorialPatch) -> tuple[str, str, int]:
    """Use a native paragraph window, never a model-selected shortened context."""
    start = source.rfind('\n\n', 0, patch.start) + 2
    if start == 1:
        start = 0
    end = source.find('\n\n', patch.end)
    if end < 0:
        end = len(source)
    start = max(start, patch.start - 2000)
    end = min(end, patch.end + 2000)
    original = source[start:end]
    edited = source[start:patch.start] + patch.after + source[patch.end:end]
    return original, edited, start


def review_patch_payload(source: str, patch: SourceEditorialPatch) -> dict[str, Any]:
    original, edited, _ = patch_context(source, patch)
    return {**asdict(patch), 'original_context': original, 'edited_context': edited}


def base_review(review: Mapping[str, Any]) -> dict[str, Any]:
    """Strip only the recognized new evidence field; preserve all invalid extras."""
    rows = review.get('rows')
    if not isinstance(rows, list):
        return dict(review)
    return {**review, 'rows': [
        {key: value for key, value in row.items() if key != EVIDENCE_KEY}
        if isinstance(row, Mapping) else row for row in rows
    ]}


def _span(context: str, quote: object) -> tuple[int, int] | None:
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 2000 or context.count(quote) != 1:
        return None
    start = context.index(quote)
    if (start and context[start - 1].isalnum() and quote[0].isalnum()) or (
            start + len(quote) < len(context) and context[start + len(quote)].isalnum() and quote[-1].isalnum()):
        return None
    return start, start + len(quote)


def _attachment_preserved(source: str, patch: SourceEditorialPatch, evidence: Mapping[str, Any]) -> bool:
    original, edited, offset = patch_context(source, patch)
    relation = evidence['relation_before']
    if not isinstance(relation, str) or relation not in _RELATIONS or relation != evidence['relation_after']:
        return False
    start, end = patch.start - offset, patch.end - offset
    delta = len(patch.after) - len(patch.before)
    if relation == 'standalone':
        return (evidence['head_before'] is None and evidence['head_after'] is None
                and (len(_WORDS.findall(original)) == len(_WORDS.findall(edited)) == 1
                     or _dictionary_transposition(original, edited)))
    head_before, head_after = _span(original, evidence['head_before']), _span(edited, evidence['head_after'])
    if head_before is None or head_after is None:
        return False
    hs, he = head_before
    if not (he <= start or hs >= end):
        return False
    expected = (hs, he) if he <= start else (hs + delta, he + delta)
    return head_after == expected and evidence['head_before'] == evidence['head_after']


def _dictionary_transposition(original: str, edited: str) -> bool:
    """A single unknown-to-known spelling permutation needs no new dependency."""
    left, right = _WORDS.findall(original), _WORDS.findall(edited)
    if len(left) != len(right):
        return False
    changed = [(a.casefold(), b.casefold()) for a,b in zip(left,right,strict=True) if a != b]
    if len(changed) != 1:
        return False
    before, after = changed[0]
    if sorted(before) != sorted(after):
        return False
    try:
        from app.modules.ai.assessment_preservation import _morph
        morph = _morph()
        return not morph.word_is_known(before) and morph.word_is_known(after)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def _inflection_risk(source: str, patch: SourceEditorialPatch) -> str | None:
    """Veto reattachment of an already possible adjective/participle reading.

    This is dictionary evidence of a possible reading, not a sentence parser or
    positive semantic approval. Abstaining leaves the recognized source intact.
    """
    try:
        from app.modules.ai.assessment_preservation import _morph
        morph = _morph()
        original, edited, offset = patch_context(source, patch)
        tokens = list(_WORDS.finditer(original))
        left = [token.group().casefold() for token in tokens]
        right = [token.group().casefold() for token in _WORDS.finditer(edited)]
        nouns = [p for token in tokens
                 if not (token.start() < patch.end - offset and token.end() > patch.start - offset)
                 and morph.word_is_known(token.group().casefold())
                 for p in morph.parse(token.group().casefold()) if p.tag.POS == 'NOUN']
        for op, i, end_i, j, end_j in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
            if op != 'replace' or end_i-i != end_j-j:
                continue
            for a, b in zip(left[i:end_i], right[j:end_j], strict=True):
                if not morph.word_is_known(a) or not morph.word_is_known(b):
                    continue
                first = [p for p in morph.parse(a) if p.tag.POS in {'ADJF','PRTF'}]
                second = [p for p in morph.parse(b) if p.tag.POS in {'ADJF','PRTF'}]
                for old in first:
                    old_case = getattr(old.tag,'case',None)
                    if old_case is None or not any(
                            new.normal_form == old.normal_form and getattr(new.tag,'case',None) != old_case
                            for new in second):
                        continue
                    for noun in nouns:
                        if (getattr(noun.tag,'case',None) == old_case
                                and getattr(noun.tag,'number',None) == getattr(old.tag,'number',None)
                                and (getattr(old.tag,'number',None) == 'plur'
                                     or getattr(noun.tag,'gender',None) == getattr(old.tag,'gender',None))):
                            return 'source_editorial_existing_inflection_reading'
        return None
    except (ImportError, OSError, RuntimeError, ValueError):
        return 'source_editorial_inflection_check_unavailable'


def admission_review(source: str, proposal: SourceEditorialProposal, review: Mapping[str, Any]) -> dict[str, Any]:
    """Withhold unproved lexical edits individually; never approve model evidence."""
    result = base_review(review)
    patches = {patch.alias: patch for patch in proposal.patches}
    raw_rows = {row['patch_alias']: row for row in review['rows']}
    for row in result['rows']:
        patch = patches[row['patch_alias']]
        # Only repeated whitespace is exempt: punctuation can change scope too.
        if re.sub(r'\s+', ' ', patch.before) == re.sub(r'\s+', ' ', patch.after):
            continue
        evidence = raw_rows[patch.alias].get(EVIDENCE_KEY)
        admitted = (isinstance(evidence, Mapping)
                    and set(evidence) == {'original_status', 'necessity', 'head_before', 'head_after',
                                          'relation_before', 'relation_after'}
                    and evidence['original_status'] == 'defective'
                    and evidence['necessity'] == 'required'
                    and _attachment_preserved(source, patch, evidence))
        if not admitted:
            row['relation'] = 'unknown'
            row['reason'] = 'source_editorial_necessity_or_attachment_unproved'
        else:
            risk = _inflection_risk(source, patch)
            if risk is not None:
                row['relation'] = 'unknown'
                row['reason'] = risk
    return result
