"""Immutable physical body-block addresses; structural custody, not approval."""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest, _validate_course
from app.modules.ai.v3.simple_course_delta_editor import apply_simple_delta_editor
from app.modules.ai.v3.simple_course_editor import (
    _editor_format,
    _fingerprint_valid,
    _format,
    _object,
    matches_simple_editor,
)

_BLANK_SEPARATOR = re.compile(r'(?:\r\n|\n|\r(?!\n))[ \t]*(?:\r\n|\n|\r(?!\n))(?:[ \t]*(?:\r\n|\n|\r(?!\n)))*')


def body_blocks(course: Any) -> list[dict[str, Any]]:
    if type(course) is not dict or type(course.get('lessons')) is not list:
        raise ValueError('simple_block_course_invalid')
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lesson in course['lessons']:
        if (type(lesson) is not dict or type(lesson.get('id')) is not str or not lesson['id'].strip()
                or lesson['id'] in seen or type(lesson.get('content')) is not str):
            raise ValueError('simple_block_course_invalid')
        seen.add(lesson['id'])
        body = lesson['content']
        position = 0
        for match in _BLANK_SEPARATOR.finditer(body):
            if body[position:match.start()].strip():
                blocks.append({'id': f'BODY{len(blocks) + 1}', 'lesson_id': lesson['id'],
                               'start': position, 'end': match.start(), 'text': body[position:match.start()]})
            position = match.end()
        if body[position:].strip():
            blocks.append({'id': f'BODY{len(blocks) + 1}', 'lesson_id': lesson['id'],
                           'start': position, 'end': len(body), 'text': body[position:]})
    return blocks


def block_editor_format(ids: list[str], source_fp: str, draft_fp: str, block_ids: list[str],
                        finding_ids: list[str] | None = None) -> dict[str, Any]:
    base = _editor_format(ids, source_fp, draft_fp)['json_schema']['schema']['properties']
    lesson = base['course']['properties']['lessons']['items']
    question = lesson['properties']['questions']['items']
    properties = {
        'source_fingerprint': base['source_fingerprint'], 'draft_fingerprint': base['draft_fingerprint'],
        'body_edits': {'type': 'array', 'items': _object({'block_id': {'type': 'string', 'enum': block_ids},
                                                         'after': {'type': 'string'}})},
        'title_edits': {'type': 'array', 'items': _object({'lesson_id': {'type': 'string'}, 'title': {'type': 'string'}})},
        'question_edits': {'type': 'array', 'items': question}, 'added_lessons': {'type': 'array', 'items': lesson},
        'lesson_sources': base['lesson_sources'], 'source_questions': base['source_questions']}
    if finding_ids is not None:
        from app.modules.ai.v3.simple_editor_findings import finding_disposition_schema
        properties['finding_dispositions'] = finding_disposition_schema(finding_ids, ids)
    return _format('simple_course_block_editor_v1' if finding_ids is None else 'simple_course_block_editor_v2',
                   _object(properties))


def is_simple_block_editor_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        ids = props['source_questions']['items']['properties']['source_refs']['items']['enum']
        block_ids = props['body_edits']['items']['properties']['block_id']['enum']
        source_fp, draft_fp = props['source_fingerprint']['enum'][0], props['draft_fingerprint']['enum'][0]
        finding_ids = (props['finding_dispositions']['items']['properties']['finding_id'].get('enum', [])
                       if 'finding_dispositions' in props else None)
        return (type(ids) is list and bool(ids) and all(type(item) is str and item.strip() for item in ids)
                and len(ids) == len(set(ids)) and type(block_ids) is list and bool(block_ids)
                and block_ids == [f'BODY{i}' for i in range(1, len(block_ids) + 1)]
                and _fingerprint_valid(source_fp) and _fingerprint_valid(draft_fp)
                and (finding_ids is None or type(finding_ids) is list and len(set(finding_ids)) == len(finding_ids)
                     and all(type(item) is str and item.strip() for item in finding_ids))
                and fmt == block_editor_format(ids, source_fp, draft_fp, block_ids, finding_ids))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def matches_simple_block_editor_shape(value: Any, fmt: Any) -> bool:
    """Transport shape, never permission to apply conflicting addresses."""
    return bool(is_simple_block_editor_format(fmt) and _matches(value, fmt['json_schema']['schema']))


def matches_simple_block_editor(value: Any, fmt: Any) -> bool:
    if not matches_simple_block_editor_shape(value, fmt):
        return False
    block_ids = [row['block_id'] for row in value['body_edits']]
    question_ids = [row['id'] for row in value['question_edits']]
    return (len(block_ids) == len(set(block_ids)) and len(question_ids) == len(set(question_ids))
            and all(row['lesson_id'].strip() and row['title'].strip() for row in value['title_edits']))


def apply_simple_block_editor(value: Any, original: dict[str, Any], ids: list[str], source_fp: str,
                              draft_fp: str, finding_ids: list[str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    original = _validate_course(original, set(ids))
    if _digest(original) != draft_fp:
        raise ValueError('simple_block_draft_stale')
    blocks = body_blocks(original)
    fmt = block_editor_format(ids, source_fp, draft_fp, [row['id'] for row in blocks], finding_ids)
    if not matches_simple_block_editor(value, fmt):
        raise ValueError('simple_block_response_invalid')
    owners = {question['id']: lesson['id'] for lesson in original['lessons'] for question in lesson['questions']}
    if any(question['id'] not in owners for question in value['question_edits']):
        raise ValueError('simple_block_question_invalid')
    delta = {**copy.deepcopy(value), 'body_edits': [],
             'question_edits': [{'lesson_id': owners[q['id']], 'question': copy.deepcopy(q)}
                                for q in value['question_edits']]}
    delta.pop('finding_dispositions', None)
    envelope, receipt = apply_simple_delta_editor(delta, original, ids, source_fp, draft_fp)
    by_id = {block['id']: block for block in blocks}
    spans: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for edit in value['body_edits']:
        block = by_id[edit['block_id']]
        spans.setdefault(block['lesson_id'], []).append((block, edit['after']))
    original_lessons = {lesson['id']: lesson for lesson in original['lessons']}
    result_lessons = {lesson['id']: lesson for lesson in envelope['course']['lessons']}
    trace: list[dict[str, Any]] = []
    for lesson_id, changes in spans.items():
        changes.sort(key=lambda item: item[0]['start'])
        position = 0
        pieces: list[str] = []
        text = original_lessons[lesson_id]['content']
        for block, after in changes:
            if block['start'] < position or text[block['start']:block['end']] != block['text']:
                raise ValueError('simple_block_overlap_invalid')
            pieces.extend((text[position:block['start']], after))
            position = block['end']
            trace.append({'block_id': block['id'], 'lesson_id': lesson_id, 'start': block['start'], 'end': block['end'],
                          'before_sha256': hashlib.sha256(block['text'].encode('utf-8')).hexdigest(),
                          'after_sha256': hashlib.sha256(after.encode('utf-8')).hexdigest()})
        pieces.append(text[position:])
        result_lessons[lesson_id]['content'] = ''.join(pieces)
    _validate_course(envelope['course'], set(ids))
    if not matches_simple_editor(envelope, _editor_format(ids, source_fp, draft_fp)):
        raise ValueError('simple_block_result_invalid')
    receipt['body_spans'] = trace
    receipt['result_fingerprint'] = _digest(envelope['course'])
    return envelope, receipt
