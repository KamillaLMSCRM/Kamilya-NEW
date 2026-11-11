"""Exact-address course edits; structural custody is not semantic approval."""
from __future__ import annotations

import copy
import hashlib
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest, _validate_course
from app.modules.ai.v3.simple_course_editor import (
    _editor_format,
    _fingerprint_valid,
    _format,
    _object,
    matches_simple_editor,
)


def delta_editor_format(ids: list[str], source_fp: str, draft_fp: str) -> dict[str, Any]:
    base = _editor_format(ids, source_fp, draft_fp)['json_schema']['schema']['properties']
    lesson = base['course']['properties']['lessons']['items']
    question = lesson['properties']['questions']['items']
    text = {'type': 'string'}
    body_edit = _object({'lesson_id': text, 'before': text, 'after': text})
    title_edit = _object({'lesson_id': text, 'title': text})
    question_edit = _object({'lesson_id': text, 'question': question})
    return _format('simple_course_delta_editor_v1', _object({
        'source_fingerprint': base['source_fingerprint'], 'draft_fingerprint': base['draft_fingerprint'],
        'body_edits': {'type': 'array', 'items': body_edit},
        'title_edits': {'type': 'array', 'items': title_edit},
        'question_edits': {'type': 'array', 'items': question_edit},
        'added_lessons': {'type': 'array', 'items': lesson},
        'lesson_sources': base['lesson_sources'], 'source_questions': base['source_questions']}))


def is_simple_delta_editor_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        ids = props['source_questions']['items']['properties']['source_refs']['items']['enum']
        source_fp = props['source_fingerprint']['enum'][0]
        draft_fp = props['draft_fingerprint']['enum'][0]
        return (type(ids) is list and bool(ids) and all(type(item) is str and item.strip() for item in ids)
                and len(set(ids)) == len(ids) and _fingerprint_valid(source_fp) and _fingerprint_valid(draft_fp)
                and fmt == delta_editor_format(ids, source_fp, draft_fp))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def matches_simple_delta_editor(value: Any, fmt: Any) -> bool:
    if not is_simple_delta_editor_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    if any(not row['lesson_id'].strip() or not row['before'] for row in value['body_edits']):
        return False
    if any(not row['lesson_id'].strip() or not row['title'].strip() for row in value['title_edits']):
        return False
    if any(not row['lesson_id'].strip() for row in value['question_edits']):
        return False
    return True


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def apply_simple_delta_editor(value: Any, original: dict[str, Any], ids: list[str],
                              source_fp: str, draft_fp: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fmt = delta_editor_format(ids, source_fp, draft_fp)
    if (not _fingerprint_valid(source_fp) or not _fingerprint_valid(draft_fp)
            or not is_simple_delta_editor_format(fmt) or not matches_simple_delta_editor(value, fmt)):
        raise ValueError('simple_delta_response_invalid')
    original = _validate_course(original, set(ids))
    if _digest(original) != draft_fp:
        raise ValueError('simple_delta_draft_stale')
    lessons = {lesson['id']: lesson for lesson in original['lessons']}
    spans: dict[str, list[tuple[int, int, str, str]]] = {}
    for row in value['body_edits']:
        lesson = lessons.get(row['lesson_id'])
        if lesson is None:
            raise ValueError('simple_delta_lesson_invalid')
        body, before = lesson['content'], row['before']
        start = body.find(before)
        if start < 0 or body.find(before, start + 1) >= 0:
            raise ValueError('simple_delta_anchor_invalid')
        spans.setdefault(row['lesson_id'], []).append((start, start + len(before), before, row['after']))
    for rows in spans.values():
        rows.sort(key=lambda item: (item[0], item[1]))
        if any(right[0] < left[1] for left, right in zip(rows, rows[1:], strict=False)):
            raise ValueError('simple_delta_overlap')
    title_ids = [row['lesson_id'] for row in value['title_edits']]
    if len(title_ids) != len(set(title_ids)) or any(key not in lessons for key in title_ids):
        raise ValueError('simple_delta_title_invalid')
    question_owners = {question['id']: lesson['id'] for lesson in original['lessons'] for question in lesson['questions']}
    question_ids = [row['question']['id'] for row in value['question_edits']]
    if (len(question_ids) != len(set(question_ids))
            or any(question_owners.get(row['question']['id']) != row['lesson_id'] for row in value['question_edits'])):
        raise ValueError('simple_delta_question_invalid')

    course = copy.deepcopy(original)
    output_lessons = {lesson['id']: lesson for lesson in course['lessons']}
    receipt_spans: list[dict[str, Any]] = []
    for lesson_id, rows in spans.items():
        body = lessons[lesson_id]['content']
        position = 0
        pieces: list[str] = []
        for start, end, before, after in rows:
            pieces.extend((body[position:start], after))
            position = end
            receipt_spans.append({'lesson_id': lesson_id, 'start': start, 'end': end,
                                  'before_sha256': _text_hash(before), 'after_sha256': _text_hash(after)})
        pieces.append(body[position:])
        output_lessons[lesson_id]['content'] = ''.join(pieces)
    for row in value['title_edits']:
        output_lessons[row['lesson_id']]['title'] = row['title']
    for row in value['question_edits']:
        questions = output_lessons[row['lesson_id']]['questions']
        index = next(i for i, question in enumerate(questions) if question['id'] == row['question']['id'])
        questions[index] = copy.deepcopy(row['question'])
    course['lessons'].extend(copy.deepcopy(value['added_lessons']))
    envelope = {'source_fingerprint': source_fp, 'draft_fingerprint': draft_fp, 'course': course,
                'lesson_sources': copy.deepcopy(value['lesson_sources']),
                'source_questions': copy.deepcopy(value['source_questions'])}
    if not matches_simple_editor(envelope, _editor_format(ids, source_fp, draft_fp)):
        raise ValueError('simple_delta_result_invalid')
    # Existing course validation is stricter than wire-format normalization and
    # prevents duplicate or colliding identities in newly added lessons.
    _validate_course(course, set(ids))
    receipt = {'source_fingerprint': source_fp, 'draft_fingerprint': draft_fp,
               'result_fingerprint': _digest(course), 'body_spans': receipt_spans,
               'title_lesson_ids': title_ids, 'question_ids': question_ids,
               'added_lesson_ids': [lesson['id'] for lesson in value['added_lessons']],
               'semantic_approval': False}
    return envelope, receipt
