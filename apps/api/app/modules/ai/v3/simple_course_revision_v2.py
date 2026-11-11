"""Scoped editorial revision and source-question custody, without semantic approval."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import PracticalSourcePacket, validate_practical_course
from app.modules.ai.v3.practical_editorial_contract import editorial_review_format, matches_editorial_review
from app.modules.ai.v3.practical_owned_media_aliases import _images, _plain_mentions
from app.modules.ai.v3.simple_course_editor import (
    _digest,
    _editor_format,
    _fingerprint_valid,
    _object,
    _review_format,
    _source_context,
    matches_simple_editor,
    matches_simple_review,
)


def editor_format(ids: list[str], source_fp: str, draft_fp: str, question_ids: list[str]) -> dict[str, Any]:
    if (type(question_ids) is not list or any(type(x) is not str or not x.strip() for x in question_ids)
            or len(set(question_ids)) != len(question_ids)):
        raise ValueError('simple_revision_question_ids_invalid')
    fmt = _editor_format(ids, source_fp, draft_fp)
    fmt['json_schema']['name'] = 'simple_course_editor_v2'
    properties = fmt['json_schema']['schema']['properties']
    question_id = {'type': 'string', 'enum': question_ids} if question_ids else {'type': 'string'}
    decision = _object({'question_id': question_id,
        'status': {'type': 'string', 'enum': ['RESOLVED_FROM_SOURCE', 'SOURCE_AMBIGUITY', 'UNVERIFIED']},
        'reason': {'type': 'string'}, 'source_refs': {'type': 'array', 'items': {'type': 'string', 'enum': ids}},
        'source_quote': {'type': 'string'}})
    properties['source_question_decisions'] = {'type': 'array', 'items': decision}
    fmt['json_schema']['schema']['required'].append('source_question_decisions')
    return fmt


def is_simple_revision_v2_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        ids = props['source_questions']['items']['properties']['source_refs']['items']['enum']
        source_fp = props['source_fingerprint']['enum'][0]
        draft_fp = props['draft_fingerprint']['enum'][0]
        question_ids = props['source_question_decisions']['items']['properties']['question_id'].get('enum', [])
        return (type(ids) is list and bool(ids) and all(type(x) is str and x.strip() for x in ids)
                and len(set(ids)) == len(ids) and _fingerprint_valid(source_fp) and _fingerprint_valid(draft_fp)
                and fmt == editor_format(ids, source_fp, draft_fp, question_ids))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def matches_simple_revision_v2(value: Any, fmt: Any) -> bool:
    if not is_simple_revision_v2_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    props = fmt['json_schema']['schema']['properties']
    ids = props['source_questions']['items']['properties']['source_refs']['items']['enum']
    question_ids = props['source_question_decisions']['items']['properties']['question_id'].get('enum', [])
    base = {key: item for key, item in value.items() if key != 'source_question_decisions'}
    if not matches_simple_editor(base, _editor_format(ids, props['source_fingerprint']['enum'][0], props['draft_fingerprint']['enum'][0])):
        return False
    decisions = value['source_question_decisions']
    keys = [row['question_id'] for row in decisions]
    return (len(keys) == len(set(keys)) and all(key in question_ids for key in keys)
            and all(len(row['source_refs']) == len(set(row['source_refs'])) for row in decisions))


@dataclass(frozen=True, slots=True)
class SimpleRevisionResult:
    course: dict[str, Any]
    lesson_sources: list[dict[str, Any]]
    source_questions: list[dict[str, Any]]
    receipt: dict[str, Any]


def _media_safe(before: str, after: str, source_media: set[str]) -> bool:
    old = _images(before)
    new = _images(after)
    if _plain_mentions(before, old) != _plain_mentions(after, new):
        return False
    old_markup = [item['markdown'] for item in old]
    cursor = 0
    for item in new:
        if cursor < len(old_markup) and item['markdown'] == old_markup[cursor]:
            cursor += 1
        elif item['markdown'] not in source_media or not str(item['url']).startswith('source-asset:'):
            return False
    return cursor == len(old_markup)


def source_question_inventory(packet: PracticalSourcePacket, original: dict[str, Any],
                              content_review: dict[str, Any], assessment_review: dict[str, Any]) -> list[dict[str, Any]]:
    original = validate_practical_course(original, packet)
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    questions = [q['id'] for lesson in original['lessons'] for q in lesson['questions']]
    fingerprint = _digest(original)
    if not matches_editorial_review(content_review, editorial_review_format(packet, original)):
        raise ValueError('simple_revision_content_review_invalid')
    if not matches_simple_review(assessment_review, _review_format(ids, questions, packet.fingerprint, fingerprint)):
        raise ValueError('simple_revision_assessment_review_invalid')
    rows = [{'question': row['problem'], 'source_refs': row['source_refs']}
            for row in content_review['findings'] if row['domain'] == 'source']
    rows.extend(assessment_review['source_questions'])
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = 'source-question-' + _digest([packet.fingerprint, fingerprint, row['question'], row['source_refs']])[:24]
        unique[identity] = {'id': identity, 'question': row['question'], 'source_refs': copy.deepcopy(row['source_refs'])}
    return list(unique.values())


def compile_simple_revision_v2(value: Any, *, packet: PracticalSourcePacket, corpus: DirectSourceCorpus,
                               original: dict[str, Any], content_review: dict[str, Any],
                               assessment_review: dict[str, Any], source_questions: list[dict[str, Any]]) -> SimpleRevisionResult:
    _source_context(packet, corpus, {})
    original = validate_practical_course(original, packet)
    ids = [block.block_id for block in packet.blocks if block.text.strip()]
    lessons = [lesson['id'] for lesson in original['lessons']]
    fingerprint = _digest(original)
    expected_inventory = source_question_inventory(packet, original, content_review, assessment_review)
    if type(source_questions) is not list or source_questions != expected_inventory:
        raise ValueError('simple_revision_source_questions_invalid')
    inventory = {row['id']: copy.deepcopy(row) for row in source_questions}
    if len(inventory) != len(source_questions):
        raise ValueError('simple_revision_source_questions_invalid')
    fmt = editor_format(ids, packet.fingerprint, fingerprint, list(inventory))
    if not matches_simple_revision_v2(value, fmt):
        raise ValueError('simple_revision_response_invalid')
    proposed = validate_practical_course(value['course'], packet)
    content_ids = {row['target']['id'] for row in content_review['findings']
                   if row['severity'] == 'material' and row['domain'] == 'content'
                   and row['target']['kind'] == 'lesson' and row['target']['id'] in lessons}
    unapplied = {}
    for finding in content_review['findings']:
        if (finding['severity'] == 'material' and finding['domain'] != 'source' and not (finding['domain'] == 'content'
                and finding['target']['kind'] == 'lesson' and finding['target']['id'] in lessons)):
            identity = 'simple-unapplied-' + _digest([packet.fingerprint, fingerprint, finding])[:24]
            unapplied[identity] = {'id': identity, 'status': 'UNVERIFIED', 'source_fingerprint': packet.fingerprint,
                                   'draft_fingerprint': fingerprint, 'finding': copy.deepcopy(finding)}
    question_ids = {row['target_id'] for row in assessment_review['proposals']}
    source_media = {image['markdown'] for doc in corpus.documents for image in _images(doc.source_text or '')}
    result = copy.deepcopy(original)
    proposed_lessons = {lesson['id']: lesson for lesson in proposed['lessons']}
    ignored = []
    for lesson in result['lessons']:
        update = proposed_lessons.get(lesson['id'])
        if update is None:
            continue
        if update['title'] != lesson['title']:
            ignored.append('lesson_title:' + lesson['id'])
        if update['content'] != lesson['content']:
            if lesson['id'] in content_ids and _media_safe(lesson['content'], update['content'], source_media):
                lesson['content'] = update['content']
            else:
                ignored.append('lesson_content:' + lesson['id'])
        updates = {question['id']: question for question in update['questions']}
        for index, question in enumerate(lesson['questions']):
            candidate = updates.get(question['id'])
            if candidate is not None and candidate != question:
                if question['id'] in question_ids:
                    lesson['questions'][index] = copy.deepcopy(candidate)
                else:
                    ignored.append('question:' + question['id'])
    if proposed['title'] != original['title']:
        ignored.append('course_title')
    if [row['id'] for row in proposed['lessons']] != lessons:
        ignored.append('lesson_structure')
    for lesson in original['lessons']:
        candidate = proposed_lessons.get(lesson['id'])
        if candidate is not None and [q['id'] for q in candidate['questions']] != [q['id'] for q in lesson['questions']]:
            ignored.append('question_structure:' + lesson['id'])
    validate_practical_course(result, packet)
    proposed_sources = {row['lesson_id']: row['source_refs'] for row in value['lesson_sources']}
    original_lessons = {lesson['id']: lesson for lesson in original['lessons']}
    lesson_sources = [{'lesson_id': lesson['id'], 'source_refs': copy.deepcopy(
        proposed_sources[lesson['id']] if lesson['content'] != original_lessons[lesson['id']]['content']
        else content_review['narrative_sources'][lesson['id']])} for lesson in result['lessons']]
    blocks = {block.block_id: block.text for block in packet.blocks}
    decisions = {row['question_id']: row for row in value['source_question_decisions']}
    dispositions, genuine, unverified = [], copy.deepcopy(value['source_questions']), []
    for key, row in inventory.items():
        decision = decisions.get(key)
        verified = bool(decision and decision['reason'].strip() and decision['source_quote'].strip()
                        and decision['source_refs'] and any(decision['source_quote'] in blocks[ref] for ref in decision['source_refs']))
        status = decision['status'] if decision is not None and verified else 'UNVERIFIED'
        reason = decision['reason'] if decision else ''
        dispositions.append({'question': row, 'status': status, 'decision': copy.deepcopy(decision)})
        if status == 'UNVERIFIED':
            unverified.append({**copy.deepcopy(row), 'status': status, 'reason': reason})
        if status == 'SOURCE_AMBIGUITY':
            genuine.append({'question': row['question'], 'source_refs': copy.deepcopy(row['source_refs'])})
    return SimpleRevisionResult(result, lesson_sources, genuine,
        {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': fingerprint,
         'ignored_unrequested_changes': sorted(set(ignored)), 'source_question_decisions': dispositions,
         'unverified_source_questions': unverified,
         'unapplied_review_findings': list(unapplied.values()),
         'semantic_approval': False})
