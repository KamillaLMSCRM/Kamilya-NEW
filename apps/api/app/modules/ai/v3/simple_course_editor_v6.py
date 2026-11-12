"""One connected lesson per source-planned semantic unit, then addressed editing.

Source slices are navigation and provenance, never semantic certification.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_owned_media_aliases import _images
from app.modules.ai.v3.simple_course_delta_editor import apply_simple_delta_editor, delta_editor_format
from app.modules.ai.v3.simple_course_editor import _COMMON, SimpleCourseResult, _changes, _course_valid
from app.modules.ai.v3.simple_course_editor_v2 import _current_context
from app.modules.ai.v3.simple_course_editor_v3 import course_media_safe
from app.modules.ai.v3.simple_semantic_source_plan import (
    build_semantic_slices,
    compile_semantic_plan,
    semantic_plan_request,
    semantic_unit_request,
)
from app.modules.ai.v3.simple_source_unit import compile_source_unit
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision


async def run_simple_course_editor_v6(packet: PracticalSourcePacket, corpus: DirectSourceCorpus,
    intent: Any, stage: Any, *, reference_decisions: tuple[SourceReferenceDecision, ...] = (),
    planned_callback: Any = None, course_editor: Any = None,
    retain_unit_title_context: bool = False) -> SimpleCourseResult:
    view = PracticalModelView(packet)
    messages, fmt = semantic_plan_request(packet, corpus, intent)

    def plan_valid(value: Any) -> dict[str, Any]:
        return compile_semantic_plan(value, packet, corpus)

    wire = await stage('review', 'practical:simple:plan:v6:' + packet.fingerprint, messages, fmt, plan_valid)
    plan = plan_valid(wire)
    if planned_callback:
        await planned_callback(len(plan['units']) + 3)
    plan_fp = _digest(plan)
    lessons, selections, initial_sources = [], [], []
    for unit in plan['units']:
        messages, fmt, selected = semantic_unit_request(packet, corpus, intent, plan, unit['id'],
            reference_decisions=reference_decisions)

        def unit_valid(value: Any, selected: Any = selected) -> dict[str, Any]:
            result = compile_source_unit(view.decode(value), packet,
                selected['primary_refs'], selected['supporting_refs'])
            if not course_media_safe({'lessons': []}, result, packet):
                raise ValueError('simple_v6_unit_media_invalid')
            return result

        group = 'practical:simple:author-unit:v6:' + packet.fingerprint + ':unit=' + selected['selection_fingerprint']
        authored = unit_valid(await stage('lesson', group, messages, fmt, unit_valid))
        lesson = copy.deepcopy(authored['lessons'][0])
        if retain_unit_title_context:
            lesson['title'] = unit_lesson_title(unit['title'], lesson['title'])
        # Model-local q1 IDs must not collide between independently authored units.
        lesson['id'] = 'lesson-' + _digest([plan_fp, unit['id']])[:24]
        for question in lesson['questions']:
            question['id'] = 'question-' + _digest([lesson['id'], question['id']])[:24]
        lessons.append(lesson)
        initial_sources.append({'lesson_id': lesson['id'],
            'source_refs': list(selected['primary_refs']) + list(selected['supporting_refs'])})
        selection_receipt = {**copy.deepcopy(selected), 'slices': [
            {key: value for key, value in row.items() if key not in {'text', 'origins'}} | {
                'text_sha256': hashlib.sha256(row['text'].encode('utf-8')).hexdigest(),
                'origins': [{key: value for key, value in origin.items() if key != 'text'}
                    for origin in row['origins']]} for row in selected['slices']]}
        selections.append({'lesson_id': lesson['id'], 'unit_id': unit['id'], **selection_receipt})
    original = _course_valid({'title': plan['title'], 'lessons': lessons}, packet, view)
    selected_editor = edit_semantic_course if course_editor is None else course_editor
    body, cards, body_receipt, card_receipt = await selected_editor(
        packet, corpus, intent, original, plan, selections, stage)
    refs: dict[str, list[str]] = {}
    for row in initial_sources + body['lesson_sources'] + cards['lesson_sources']:
        selected_refs = refs.setdefault(row['lesson_id'], [])
        selected_refs.extend(ref for ref in row['source_refs'] if ref not in selected_refs)
    sources = [{'lesson_id': lesson['id'], 'source_refs': refs[lesson['id']]}
        for lesson in cards['course']['lessons']]
    questions = list({_digest(row): row for row in body['source_questions'] + cards['source_questions']}.values())
    review = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
        'proposals': [], 'source_questions': questions,
        'method': 'semantic-slices-per-unit-addressed-editors-v1',
        'unit_editor_records': selections, 'editor_delta_receipts': {'body': body_receipt, 'cards': card_receipt},
        'editor_proposed_lesson_sources': sources,
        'unverified_illustrations': unrepresented_source_images(packet, corpus, plan, cards['course'])}
    return SimpleCourseResult(original, cards['course'], plan, questions,
        _changes(original, cards['course']), review, sources)


def unit_lesson_title(planned: str, authored: str) -> str:
    """Retain the planned topic alongside the author's label, without certifying either."""
    return authored if planned == authored else planned + ' — ' + authored


def unrepresented_source_images(packet: PracticalSourcePacket, corpus: DirectSourceCorpus,
    plan: dict[str, Any], course: dict[str, Any]) -> list[dict[str, Any]]:
    """Presence is mechanical; a retained marker does not prove relevance or placement."""
    primary = {identity for unit in plan['units'] for identity in unit['primary_slices']}
    shown = {image['url'] for lesson in course['lessons'] for image in _images(lesson['content'])}
    missing: dict[str, list[str]] = {}
    for row in build_semantic_slices(packet, corpus):
        if row['id'] in primary:
            for image in _images(row['text']):
                if image['url'] not in shown:
                    refs = missing.setdefault(image['url'], [])
                    if row['source_ref'] not in refs:
                        refs.append(row['source_ref'])
    return [{'asset_url': url, 'source_refs': refs, 'status': 'UNVERIFIED'}
        for url, refs in sorted(missing.items())]


async def edit_semantic_course(packet: PracticalSourcePacket, corpus: DirectSourceCorpus,
    intent: Any, original: dict[str, Any], plan: dict[str, Any], selections: list[dict[str, Any]],
    stage: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The same two addressed editorial stages for new or retained course drafts."""
    view = PracticalModelView(packet)
    original = _course_valid(original, packet, view)
    plan = compile_semantic_plan(plan, packet, corpus)
    plan_fp = _digest(plan)
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    _, context = _current_context(packet, corpus, intent)
    context.pop('source_blocks', None)
    payload = {**context, 'source_slices': [{**row,
        'source_ref': view.canonical_to_alias[row['source_ref']],
        'origins': [{key: value for key, value in origin.items() if key != 'text'}
                    for origin in row['origins']]} for row in build_semantic_slices(packet, corpus)
            if row['source_ref'] in view.canonical_to_alias],
        'semantic_outline': plan, 'unit_selections': [
            {'lesson_id': row['lesson_id'], 'unit_id': row['unit_id']} for row in selections]}

    async def edit(base: dict[str, Any], role: str) -> tuple[dict[str, Any], dict[str, Any]]:
        fingerprint = _digest(base)
        if role == 'body':
            current = {'teaching_units': [{key: lesson[key] for key in ('id', 'title', 'content')}
                for lesson in base['lessons']]}
            instruction = (
                'Act as a practical teaching editor. Compare the complete approved literal source with these '
                'lesson bodies and the source-only semantic outline. The outline is navigation, not authority. '
                'Correct material omissions and wrong actors, actions, conditions, branches or relationships '
                'yourself. Preserve useful teaching and all identities. Question cards and explanations are '
                'intentionally unavailable and cannot count as teaching. Return exact uniquely anchored, '
                'nonoverlapping addressed body edits and necessary title edits; no existing question edits. '
                'A genuinely missing practical topic may be added as a complete lesson with new IDs. '
                'Preserve source-owned illustrations by their actual operations. Provide lesson_sources for '
                'every final lesson. Do not turn image labels or examples into normative duties. '
                'Use literal structural row labels and headers to resolve scoped references in source excerpts; '
                'ensure the learner can identify every limiting scope without another lesson. The image inventory '
                'reports presence only: restore relevant missing original illustrations in their proper operations. '
                'Write learner instructions, not discussion of a source fragment or internal source aliases. '
                'Only unresolved incompatible source meanings belong in source_questions, not course omissions.')
        else:
            current = {'current_learning_units': view.encode(base)}
            instruction = (
                'Act as a question-card editor. Compare each stem, alternatives, key and explanation with '
                'the complete approved literal source and revised lesson. A card shows its lesson title but '
                'not other cards. Correct material actor, action, scope and key errors yourself with complete '
                'same-ID question_edits. Preserve good cards. Do not edit bodies, titles or add lessons. '
                'Questions and explanations must use learner language, without internal source aliases or '
                'questions about what an available fragment does not contain. '
                'Read the complete bank for redundant checks of the same skill; revise such repetitions '
                'toward other substantive actions already taught in that lesson. '
                'Provide lesson_sources for every lesson. Only unresolved incompatible source meanings '
                'belong in source_questions; a defective question is your correction task.')
        role_messages = [{'role': 'system', 'content': _COMMON + '\n' + instruction},
            {'role': 'user', 'content': json.dumps({**payload, **current,
                'unrepresented_primary_illustrations': view.encode(unrepresented_source_images(packet, corpus, plan, base)),
                'draft_fingerprint': fingerprint}, ensure_ascii=False)}]
        role_fmt = view.schema(delta_editor_format(ids, packet.fingerprint, fingerprint))

        def validate(value: Any) -> dict[str, Any]:
            value = view.decode(value)
            if role == 'body' and value.get('question_edits'):
                raise ValueError('simple_v6_body_question_edit_forbidden')
            if role == 'cards' and any(value.get(key) for key in ('body_edits', 'title_edits', 'added_lessons')):
                raise ValueError('simple_v6_cards_body_edit_forbidden')
            envelope, _ = apply_simple_delta_editor(value, base, ids, packet.fingerprint, fingerprint)
            envelope['course'] = _course_valid(envelope['course'], packet, view)
            if any(not 3 <= len(lesson['questions']) <= 4 for lesson in envelope['course']['lessons']):
                raise ValueError('simple_v6_question_count_invalid')
            if not course_media_safe(base, envelope['course'], packet):
                raise ValueError('simple_v6_editor_media_changed')
            return envelope

        group = 'practical:simple:editor-' + role + ':v6:' + packet.fingerprint + ':unit=' + plan_fp
        value = await stage('repair', group, role_messages, role_fmt, validate)
        envelope = validate(value)
        _, receipt = apply_simple_delta_editor(view.decode(value), base, ids, packet.fingerprint, fingerprint)
        return envelope, receipt

    body, body_receipt = await edit(original, 'body')
    cards, card_receipt = await edit(body['course'], 'cards')
    return body, cards, body_receipt, card_receipt
