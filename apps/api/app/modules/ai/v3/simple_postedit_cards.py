"""Addressed post-edit card corrections; never semantic acceptance."""
from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_editorial_contract import compile_editorial_review
from app.modules.ai.v3.simple_course_block_editor import apply_simple_block_editor, block_editor_format, body_blocks
from app.modules.ai.v3.simple_course_editor import _course_valid
from app.modules.ai.v3.simple_course_editor_v2 import _current_context
from app.modules.ai.v3.simple_course_editor_v9 import _SCOPED_COMMON
from app.modules.ai.v3.simple_editor_findings import compile_finding_dispositions, inventory


def _bound_context(packet: Any, original: dict[str, Any], review: dict[str, Any], *,
                   allow_lesson_bodies: bool = False) -> dict[str, Any]:
    compile_editorial_review(review, packet, original)
    questions = {q['id'] for lesson in original['lessons'] for q in lesson['questions']}
    material = [row for row in review['findings'] if row['severity'] == 'material' and row['domain'] != 'source']
    lessons = {lesson['id'] for lesson in original['lessons']}
    def allowed(row: dict[str, Any]) -> bool:
        return bool(row['domain'] == 'assessment' and row['target']['kind'] == 'question'
            and row['target']['id'] in questions or allow_lesson_bodies and row['domain'] == 'content'
            and row['target']['kind'] == 'lesson' and row['target']['id'] in lessons)
    if not material or any(not allowed(row) for row in material):
        raise ValueError('simple_postedit_findings_invalid')
    findings = inventory(packet.fingerprint, _digest(original), [('postedit_bank', review)])
    context = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
            'review': copy.deepcopy(review), 'findings': findings,
            'allowed_question_ids': sorted({row['target']['id'] for row in material if row['target']['kind'] == 'question'}),
            'lesson_sources': [{'lesson_id': lesson['id'],
                'source_refs': copy.deepcopy(review['narrative_sources'][lesson['id']])}
                for lesson in original['lessons']]}
    if allow_lesson_bodies:
        context['allowed_lesson_ids'] = sorted({row['target']['id'] for row in material if row['target']['kind'] == 'lesson'})
    return context


def prepare_postedit_cards(packet: Any, corpus: Any, intent: Any, original: dict[str, Any],
                           editorial_review: dict[str, Any], *, allow_lesson_bodies: bool = False
                           ) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    view, source = _current_context(packet, corpus, intent)
    original = _course_valid(original, packet, view)
    context = _bound_context(packet, original, editorial_review, allow_lesson_bodies=allow_lesson_bodies)
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    fmt = view.schema(block_editor_format(ids, packet.fingerprint, _digest(original),
        [row['id'] for row in body_blocks(original)], [row['id'] for row in context['findings']]))
    allowed = set(context['allowed_question_ids'])
    cards = [{'lesson_id': lesson['id'], 'lesson_title': lesson['title'], 'question': copy.deepcopy(q)}
             for lesson in original['lessons'] for q in lesson['questions'] if q['id'] in allowed]
    payload = {**source, 'draft_fingerprint': _digest(original), 'flagged_cards': view.encode(cards),
               'editorial_review': view.encode(editorial_review), 'material_findings': view.encode(context['findings']),
               'lesson_sources': view.encode(context['lesson_sources'])}
    messages = [{'role': 'system', 'content': _SCOPED_COMMON + '\nCross-check each finding against the source and the complete visible card. '
        'Correct only the flagged cards when needed; preserve correct cards and do not blindly follow findings. '
        'Return complete same-ID question objects, no body, title or lesson edits. Keep lesson_sources and report '
        'source ambiguity in source_questions. For EACH material_findings ID give a finding_disposition: CORRECTED, '
        'ALREADY_SATISFIED, NOT_MATERIAL or UNRESOLVED. Give a reason, a short exact original source_quote with '
        'source_refs, and a short exact final_quote in the final field identified by target.kind/id/choice_index '
        '(0 unless a choice). Copy source_quote as one contiguous passage from one cited source block; do not '
        'combine passages, insert ellipses or paraphrase the evidence. CORRECTED means that field actually changes; '
        'ALREADY_SATISFIED means the evidence already existed. NOT_MATERIAL needs source and final-text evidence '
        'explaining why no substantive change is warranted. Unsupported or missing dispositions remain unverified; '
        'this is your editorial judgment, not independent approval.'},
        {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
    if allow_lesson_bodies:
        payload['flagged_body_blocks'] = view.encode([row for row in body_blocks(original)
            if row['lesson_id'] in context['allowed_lesson_ids']])
        messages[0]['content'] = messages[0]['content'].replace(
            'Return complete same-ID question objects, no body, title or lesson edits.',
            'Return complete same-ID edits only for flagged questions, and BODY-block edits only for flagged lesson bodies. '
            'No title edits or added lessons. Preserve every correct independent rule and source-owned illustration '
            'in each edited paragraph; alter only the substantive defect. Reject unsupported criticisms with NOT_MATERIAL. '
            'A correct nonexhaustive choice need not list the whole procedure unless the question asks for it. '
            'Questions, keys and explanations cannot prove teaching coverage in a lesson body.')
        messages[1]['content'] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return messages, fmt, context


def apply_postedit_cards(value: Any, packet: Any, original: dict[str, Any],
                         context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(context) is not dict or type(context.get('review')) is not dict:
        raise ValueError('simple_postedit_context_invalid')
    operational = 'allowed_lesson_ids' in context
    expected = _bound_context(packet, original, context['review'], allow_lesson_bodies=operational)
    if context != expected:
        raise ValueError('simple_postedit_context_stale')
    if (type(value) is not dict or any(value.get(key) != [] for key in ('title_edits', 'added_lessons'))
            or not operational and value.get('body_edits') != []
            or type(value.get('question_edits')) is not list
            or value.get('lesson_sources') != context['lesson_sources']):
        raise ValueError('simple_postedit_scope_invalid')
    for question in value['question_edits']:
        if type(question) is not dict or question.get('id') not in context['allowed_question_ids']:
            raise ValueError('simple_postedit_question_invalid')
    if operational:
        from app.modules.ai.v3.practical_owned_media_aliases import _images
        allowed_blocks = {row['id'] for row in body_blocks(original) if row['lesson_id'] in context['allowed_lesson_ids']}
        if type(value.get('body_edits')) is not list or any(
                type(row) is not dict or row.get('block_id') not in allowed_blocks for row in value['body_edits']):
            raise ValueError('simple_postedit_body_invalid')
        originals = {row['id']: row['text'] for row in body_blocks(original)}
        for edit in value['body_edits']:
            if ([row['markdown'] for row in _images(originals[edit['block_id']])]
                    != [row['markdown'] for row in _images(edit['after'])]):
                raise ValueError('simple_postedit_media_changed')
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    envelope, delta = apply_simple_block_editor(value, original, ids, packet.fingerprint, _digest(original),
                                                [row['id'] for row in context['findings']])
    if operational:
        from app.modules.ai.v3.simple_course_editor_v3 import course_media_safe
        if not course_media_safe(original, envelope['course'], packet):
            raise ValueError('simple_postedit_media_changed')
    dispositions = compile_finding_dispositions(context['findings'], value.get('finding_dispositions', []),
                                                 packet, original, envelope['course'],
                                                 allow_final_field_typography=operational)
    return envelope, {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
        'result_fingerprint': _digest(envelope['course']), 'review': copy.deepcopy(context['review']),
        'finding_dispositions': dispositions, 'delta_receipt': delta, 'semantic_approval': False}
