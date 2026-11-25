"""Reconcile final teaching and cards around source clauses the editor actually used."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from itertools import combinations
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_course_block_editor import (
    apply_simple_block_editor,
    block_editor_format,
    body_blocks,
    matches_simple_block_editor,
)
from app.modules.ai.v3.simple_course_editor import _changes
from app.modules.ai.v3.simple_course_editor_v3 import course_media_safe

_WORDS = re.compile(r'[^\W_]+')
_SENTENCE = re.compile(r'(?<=[.!?;])\s+')
_TASK = (
    'Read the quoted source clauses as evidence before reading the course. Identify the action for each '
    'applicable case, and whether the clauses genuinely conflict for the same case. Then check each supplied '
    'paragraph and each visible question and answer key independently. Correct only a lost or contradicted '
    'condition. If a card gives only one correct action for an underspecified scenario, specify the condition '
    'in its prompt or make its key account for both routes. Do not impose a new rule. In a paragraph that '
    'already names the exception, remove or qualify any wording that contradicts it, retaining independent '
    'sentences. If the provided same-lesson cards test the same decision under equivalent facts, preserve the '
    'clearer one and replace the duplicate with another decision taught in that lesson. Compare every '
    'replacement with the other cards shown. Preserve identifiers, language, '
    'images and correct text. Only an actual incompatibility in the quoted source belongs in source_questions. '
    'Use allowable source references, return complete same-ID question edits and exact BODY replacements, '
    'and leave title_edits, added_lessons and lesson_sources empty.'
)


def _words(text: str) -> set[str]:
    return {word[:5] for word in _WORDS.findall(text.casefold()) if len(word) >= 4 or word.isdecimal()}


def _nearest(rows: list[dict[str, Any]], clauses: list[dict[str, str]], limit: int) -> list[dict[str, Any]]:
    terms = [_words(clause['quote']) for clause in clauses]
    ranked = []
    for row in rows:
        segments = [_words(sentence) for sentence in _SENTENCE.split(row['text'])]
        best = max((len(part & source) / max(len(source), 1) for part in segments for source in terms
                    if len(part & source) >= 5), default=0.0)
        if best >= 0.20:
            ranked.append((best, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]['id']))
    return [row for _, row in ranked[:limit]]


async def reconcile_branch_outputs(packet: Any, result: Any, clauses: list[dict[str, str]], stage: Any,
                                   count_stage: Any) -> Any:
    if not clauses:
        return result
    original = result.course
    view = PracticalModelView(packet)
    blocks = body_blocks(original)
    chosen = _nearest([row for row in blocks if len(row['text']) <= 3500], clauses, 8)
    if not chosen:
        return result
    questions = [{'id': q['id'], 'text': q['prompt'] + ' ' + q['choices'][q['correct_index']],
                  'lesson_id': lesson['id'], 'question': q}
                 for lesson in original['lessons'] for q in lesson['questions']]
    cards = _nearest(questions, clauses, 6)
    chosen_ids = {row['id'] for row in cards}
    nearby_lessons = {row['lesson_id'] for row in chosen}
    duplicates = []
    for left, right in combinations(questions, 2):
        if left['lesson_id'] != right['lesson_id'] or left['lesson_id'] not in nearby_lessons:
            continue
        lhs, rhs = _words(left['text']), _words(right['text'])
        similarity = len(lhs & rhs) / max(1, len(lhs | rhs))
        if similarity >= 0.60:
            duplicates.append((similarity, left, right))
    duplicates.sort(key=lambda pair: (-pair[0], pair[1]['id'], pair[2]['id']))
    for _, left, right in duplicates[:2]:
        for card in (left, right):
            if card['id'] not in chosen_ids:
                cards.append(card)
                chosen_ids.add(card['id'])
    addresses = {f'BODY{index}': row['id'] for index, row in enumerate(chosen, 1)}
    evidence = list(dict.fromkeys(clause['source_ref'] for clause in clauses))
    card_ids = {row['id'] for row in cards}
    allowed = {view.alias_to_canonical[ref] for ref in evidence}
    allowed.update(ref for row in cards for ref in row['question']['source_refs'])
    sources = list(view.canonical_to_alias)
    selected = sorted(view.canonical_to_alias[ref] for ref in allowed)
    fingerprint = _digest(original)
    fmt = block_editor_format(selected, packet.fingerprint, fingerprint, list(addresses))
    payload = {
        'source_fingerprint': packet.fingerprint,
        'draft_fingerprint': fingerprint,
        'source_clauses': clauses,
        'paragraphs': [{'id': alias, 'lesson_id': row['lesson_id'], 'text': row['text']}
                       for alias, row in zip(addresses, chosen, strict=True)],
        'assessment_cards': view.encode(cards),
        'own_teaching': [{'id': row['id'], 'content': row['content']} for row in original['lessons']
                         if any(card['lesson_id'] == row['id'] for card in cards)],
        'other_cards_for_comparison': view.encode([row for row in questions if row['id'] not in card_ids
            and any(card['lesson_id'] == row['lesson_id'] for card in cards)]),
    }

    def apply(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        if (not matches_simple_block_editor(value, fmt)
                or any(value[key] for key in ('title_edits', 'added_lessons', 'lesson_sources'))
                or any(q['id'] not in card_ids for q in value['question_edits'])):
            raise ValueError('simple_branch_consistency_scope_invalid')
        decoded = view.decode(value)
        decoded['body_edits'] = [{**edit, 'block_id': addresses[edit['block_id']]}
                                 for edit in decoded['body_edits']]
        decoded['lesson_sources'] = copy.deepcopy(result.lesson_sources)
        envelope, receipt = apply_simple_block_editor(decoded, original, sources, packet.fingerprint, fingerprint)
        if not course_media_safe(original, envelope['course'], packet):
            raise ValueError('simple_branch_consistency_media_changed')
        return envelope, receipt

    messages = [{'role': 'system', 'content': _TASK},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
    await count_stage()
    group = f'practical:simple:branch-review:v12:{packet.fingerprint}:unit={fingerprint}'
    reply = await stage('repair', group, messages, fmt, apply)
    envelope, receipt = apply(reply)
    final = envelope['course']
    return replace(result, course=final, changes=_changes(result.draft, final),
                   source_questions=[*result.source_questions, *envelope['source_questions']],
                   review={**result.review, 'final_branch_consistency': receipt})
