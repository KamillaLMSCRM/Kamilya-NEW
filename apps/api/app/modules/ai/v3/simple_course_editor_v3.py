"""Literal source units, connected lesson/cards, then ordinary editorial correction."""
from __future__ import annotations

import copy
import json
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _course_format, _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_owned_media_aliases import _images
from app.modules.ai.v3.simple_course_editor import (
    _COMMON,
    SimpleCourseResult,
    _changes,
    _course_valid,
    _editor_format,
    matches_simple_editor,
)
from app.modules.ai.v3.simple_course_revision_v2 import _media_safe
from app.modules.ai.v3.simple_source_origin import source_origin_blocks
from app.modules.ai.v3.simple_source_unit import LiteralTeachingUnit, compile_source_unit, source_unit_request
from app.modules.ai.v3.simple_source_unit_plan import (
    compile_source_unit_plan,
    decode_source_unit_plan,
    source_unit_plan_request,
)
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision


def compile_unit_editor(value: Any, packet: PracticalSourcePacket, original: dict[str, Any],
                        primary: tuple[str, ...], supporting: tuple[str, ...]) -> dict[str, Any]:
    fmt = _editor_format(list(primary + supporting), packet.fingerprint, _digest(original))
    if not matches_simple_editor(value, fmt):
        raise ValueError('simple_unit_editor_invalid')
    candidate: dict[str, Any] = copy.deepcopy(value)
    candidate['course'] = compile_source_unit(candidate['course'], packet, primary, supporting)
    before, after = original['lessons'][0], candidate['course']['lessons'][0]
    if (before['id'] != after['id']
            or [q['id'] for q in before['questions']] != [q['id'] for q in after['questions']]):
        raise ValueError('simple_unit_editor_identity_changed')
    selected = set(primary + supporting)
    source_media = {image['markdown'] for block in packet.blocks if block.block_id in selected
                    for image in _images(block.text)}
    if not _media_safe(before['content'], after['content'], source_media):
        raise ValueError('simple_unit_editor_media_changed')
    return candidate


def course_media_safe(before: dict[str, Any], after: dict[str, Any], packet: PracticalSourcePacket) -> bool:
    """Preserve original asset identities while permitting editorial relocation."""
    owned = {image['url'] for block in packet.blocks for image in _images(block.text)}
    previous = {image['url'] for lesson in before['lessons'] for image in _images(lesson['content'])}
    current = {image['url'] for lesson in after['lessons'] for image in _images(lesson['content'])}
    return previous <= current <= owned


async def run_simple_course_editor_v3(packet: PracticalSourcePacket, corpus: DirectSourceCorpus,
                                      intent: Any, stage: Any, *,
                                      reference_decisions: tuple[SourceReferenceDecision, ...] = ()
                                      ) -> SimpleCourseResult:
    view = PracticalModelView(packet)
    messages, fmt = source_unit_plan_request(packet, corpus, intent)

    def plan_valid(wire: Any) -> dict[str, Any]:
        return compile_source_unit_plan(decode_source_unit_plan(wire, view), packet)

    wire = await stage('review', 'practical:simple:plan:v3:' + packet.fingerprint, messages, fmt, plan_valid)
    plan = plan_valid(wire)
    selections: dict[str, LiteralTeachingUnit] = {}
    units = []
    for number, proposed in enumerate(plan['units'], 1):
        unit_messages, _, selected = source_unit_request(packet, corpus, intent,
            proposed['primary_refs'], proposed['supporting_refs'], reference_decisions=reference_decisions)
        context = json.loads(unit_messages[1]['content'])
        lesson_id = f'unit-{number}-lesson'
        selections[lesson_id] = selected
        units.append({'lesson_id': lesson_id, 'title': proposed['title'],
            'primary_refs': [view.canonical_to_alias[ref] for ref in selected.primary_refs],
            'supporting_refs': [view.canonical_to_alias[ref] for ref in selected.supporting_refs],
            'documents': context['documents'], 'reference_context': context['reference_context']})
    # The plan is navigation, not a normative access boundary. The author/editor
    # can recover a missing common rule from the same approved source, once.
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    literal_blocks = {view.canonical_to_alias[row['id']]: {**row, 'id': view.canonical_to_alias[row['id']]}
        for row in source_origin_blocks(packet, corpus) if row['id'] in view.canonical_to_alias}
    payload = {'source_blocks': [literal_blocks[view.canonical_to_alias[ref]] for ref in ids],
        'units': units, 'intent': context['intent'], 'title': plan['title'],
        'source_fingerprint': packet.fingerprint, 'plan_fingerprint': _digest(plan)}
    author_instruction = (
        'Write a connected practical employee course with 3–4 nonredundant questions per lesson. '
        'The supplied units are a proposed topic outline: combine related topics or refine lesson '
        'boundaries where that makes the source understandable without losing operative content. '
        'Use stable lesson/question identities. The primary_refs identify proposed topics; supporting_refs provide the '
        'literal parent context, definitions and reference targets needed to understand that unit. '
        'Each source block is supplied once. The map is proposed navigation, not a prohibition on '
        'reading other supplied source: recover applicable common rules and missing dependencies '
        'from the current approved source when necessary for that lesson. '
        'Teach applicable actors, actions, conditions and exceptions so the employee can perform the work. '
        'Do not leave a needed cross-reference unexplained or assume another lesson supplies its procedure. '
        'Keep necessary scope visible in the lesson/quiz title and individual question stem. '
        'Each card has one wholly supported best answer; use plausible work mistakes with comparable '
        'specificity as alternatives, avoid length giveaways and vary correct positions. '
        'Preserve meaningful original source-asset illustrations with exact addresses beside relevant text. '
        'A storage block may mix topics; place each illustration by its actual operation, not merely '
        'the unit that owns that block in the proposed plan. '
        'Do not invent obligations from example forms. Source and approved interpretations govern, '
        'not field labels alone. The literal source is segmented by origin: visual_ocr and '
        'visual_description are observations of embedded illustrations. Use them to explain what is '
        'shown, with duties and actors established by surrounding document instructions or approved '
        'interpretations; origin alone does not make every form field a learner requirement. '
        'not the proposed navigation titles or proposed lesson count. Return the complete usable course.')
    messages = [{'role': 'system', 'content': _COMMON + '\n' + author_instruction},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    fmt = view.schema(_course_format(ids))

    def course_valid(value: Any) -> dict[str, Any]:
        course = _course_valid(view.decode(value), packet, view)
        if any(not 3 <= len(lesson['questions']) <= 4 for lesson in course['lessons']):
            raise ValueError('simple_unit_question_count_invalid')
        if not course_media_safe({'lessons': []}, course, packet):
            raise ValueError('simple_unit_batch_foreign_media')
        return course

    group = 'practical:simple:author-batch:v3:' + packet.fingerprint + ':unit=' + _digest(plan)
    original = course_valid(await stage('lesson', group, messages, fmt, course_valid))
    editor_payload = {**payload, 'current_learning_units': view.encode(original),
                      'draft_fingerprint': _digest(original)}
    instruction = (
        'Act as an experienced course editor. Read the COMPLETE approved source FIRST, then the actual course. '
        'Keep segment provenance in view: visual_ocr/visual_description describe illustrations; '
        'field labels or sample values alone do not assign duties. Check the surrounding document '
        'instructions or approved context before prescribing an action inferred from an example. '
        'Compare the source and all actual lessons, '
        'using the proposed literal topic mapping as navigation. Check missing teaching content as well '
        'as correctness. The learner can see that lesson and its questions, not the source '
        'or another lesson. Revise the complete course so each lesson faithfully teaches its practical '
        'topic, applicable conditions, actors and needed reference procedures. Read all questions, keys '
        'and explanations; each separate card must have one wholly supported best answer, using its '
        'persistently visible lesson title but not hidden context from other cards. '
        'The plan is a proposal. Repair missing common-rule or parent-context links using any '
        'relevant supplied approved source, and cite the actual sources used for each lesson. '
        'Preserve good content, all lesson/question identities and meaningful original illustrations '
        'with exact source-asset addresses. Move an illustration to its correct operation when needed; '
        'a mixed source-storage block does not determine its lesson. Do not invent hypothetical obligations or universal duties '
        'from example labels. Correct substantive mistakes yourself; do not reopen replaced history. '
        'Only genuinely incompatible source meanings unresolved by context/approved decisions go in '
        'source_questions. A course omission is your editorial task, not source ambiguity. '
        'You may add needed lessons/questions with new identities to explain missing operative material; '
        'do not delete existing identities to conceal omissions. Provide proposed lesson_sources for '
        'each actual lesson and return the complete usable course. Proposed topic count is not a quota.')
    editor_messages = [{'role': 'system', 'content': _COMMON + '\n' + instruction},
                       {'role': 'user', 'content': json.dumps(editor_payload, ensure_ascii=False)}]
    editor_fmt = view.schema(_editor_format(ids, packet.fingerprint, _digest(original)))

    def editor_valid(value: Any) -> dict[str, Any]:
        candidate: dict[str, Any] = view.decode(value)
        if not matches_simple_editor(candidate, _editor_format(ids, packet.fingerprint, _digest(original))):
            raise ValueError('simple_unit_batch_editor_invalid')
        # Each unit retains the same local editor custody/media boundary.
        candidate['course'] = course_valid(view.encode(candidate['course']))
        proposed_sources = {row['lesson_id']: set(row['source_refs']) for row in candidate['lesson_sources']}
        after_by_id = {lesson['id']: lesson for lesson in candidate['course']['lessons']}
        if any(not refs <= set(ids) for refs in proposed_sources.values()):
            raise ValueError('simple_unit_batch_editor_provenance_invalid')
        for before in original['lessons']:
            if before['id'] not in after_by_id:
                raise ValueError('simple_unit_editor_identity_changed')
            after = after_by_id[before['id']]
            if not {question['id'] for question in before['questions']} <= {question['id'] for question in after['questions']}:
                raise ValueError('simple_unit_editor_identity_changed')
        if not course_media_safe(original, candidate['course'], packet):
            raise ValueError('simple_unit_editor_media_changed')
        return candidate

    group = 'practical:simple:editor-batch:v3:' + packet.fingerprint + ':unit=' + _digest(plan)
    edited = editor_valid(await stage('repair', group, editor_messages, editor_fmt, editor_valid))
    final = edited['course']
    sources = copy.deepcopy(edited['lesson_sources'])
    questions = edited['source_questions']
    receipts = [{'planned_lesson_id': key, 'selection_fingerprint': unit.selection_fingerprint,
                 'primary_refs': list(unit.primary_refs), 'supporting_refs': list(unit.supporting_refs)}
                for key, unit in selections.items()]
    review = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': _digest(original),
        'proposals': [], 'source_questions': questions, 'unit_editor_records': receipts,
        'method': 'literal-source-unit-batch-author-editor-v1',
        'editor_proposed_lesson_sources': copy.deepcopy(edited['lesson_sources'])}
    return SimpleCourseResult(original, final, plan, questions, _changes(original, final), review, sources)
