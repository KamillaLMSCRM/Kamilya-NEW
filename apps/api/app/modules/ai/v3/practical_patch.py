"""Edit only reviewer-identified parts; keep checked siblings and stable identities."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import PracticalSourcePacket, _course_format, validate_practical_course
from app.modules.ai.v3.practical_review import PracticalReviewDecision

NAME = 'v3_practical_patch_v3'


def _object(props: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}


def _fingerprint(course: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(course, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _fragments(content: str) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    start = 0
    for separator in re.finditer(r'(?:\r?\n[ \t]*){2,}', content):
        if content[start:separator.start()].strip():
            result.append((f'F{len(result) + 1}', start, separator.start()))
        start = separator.end()
    if content[start:].strip():
        result.append((f'F{len(result) + 1}', start, len(content)))
    return result


def practical_patch_course_view(course: dict[str, Any], decision: PracticalReviewDecision) -> dict[str, Any]:
    result = copy.deepcopy(course)
    lessons = {lesson['id']: lesson for lesson in result['lessons']}
    if not set(decision.lesson_ids) <= set(lessons):
        raise ValueError('practical_patch_scope_invalid')
    for lid in decision.lesson_ids:
        lesson = lessons[lid]
        content = lesson.pop('content')
        lesson['content_fragments'] = [{'fragment_id': key, 'text': content[start:end]}
                                       for key, start, end in _fragments(content)]
    return result


def _format(sources: list[str], lessons: list[str], edit_lessons: dict[str, list[str]], edit_questions: list[str],
            additions: bool, fingerprint: str) -> dict[str, Any]:
    if (type(additions) is not bool or not lessons or len(set(lessons)) != len(lessons)
            or type(edit_lessons) is not dict or not re.fullmatch('[0-9a-f]{64}', fingerprint)
            or any(type(x) is not str or not x.strip() for x in lessons + list(edit_lessons) + edit_questions)
            or any(not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r'F[1-9]\d*', i) for i in ids)
                   for ids in edit_lessons.values()) or len(set(edit_questions)) != len(edit_questions)
            or not set(edit_lessons) <= set(lessons) or not (edit_lessons or edit_questions or additions)):
        raise ValueError('practical_patch_scope_invalid')
    base = _course_format(sources)['json_schema']['schema']['properties']['lessons']['items']
    question = base['properties']['questions']['items']
    new_lessons: dict[str, Any] = {'type': 'array', 'items': base}
    new_questions: dict[str, Any] = {'type': 'array', 'items': _object({
        'lesson_id': {'type': 'string', 'enum': lessons}, 'question': copy.deepcopy(question)})}
    if not additions:
        new_lessons['maxItems'] = new_questions['maxItems'] = 0
    props = {'course_fingerprint': {'type': 'string', 'enum': [fingerprint]},
             'new_lessons': new_lessons, 'new_questions': new_questions}
    if edit_lessons:
        props['lesson_updates'] = _object({key: _object({'title': {'type': 'string'},
            'replacements': {'type': 'array', 'items': _object({
                'fragment_id': {'type': 'string', 'enum': ids}, 'new_text': {'type': 'string'}})}})
            for key, ids in edit_lessons.items()})
    if edit_questions:
        updates = {}
        for key in edit_questions:
            item = copy.deepcopy(question)
            item['properties']['id'] = {'type': 'string', 'enum': [key]}
            updates[key] = item
        props['question_updates'] = _object(updates)
    return {'type': 'json_schema', 'json_schema': {'name': NAME, 'strict': True, 'schema': _object(props)}}


def practical_patch_format(packet: PracticalSourcePacket, course: dict[str, Any],
                           decision: PracticalReviewDecision) -> dict[str, Any]:
    validate_practical_course(course, packet)
    if decision.accepted or decision.source_uncertain and not (decision.lesson_ids or decision.question_ids):
        raise ValueError('practical_patch_scope_invalid')
    if (len(set(decision.lesson_ids)) != len(decision.lesson_ids)
            or not set(decision.lesson_ids) <= {lesson['id'] for lesson in course['lessons']}):
        raise ValueError('practical_patch_scope_invalid')
    questions = {q['id'] for lesson in course['lessons'] for q in lesson['questions']}
    if not set(decision.question_ids) <= questions:
        raise ValueError('practical_patch_scope_invalid')
    editable = {lesson['id']: [key for key, _start, _end in _fragments(lesson['content'])]
                for lesson in course['lessons'] if lesson['id'] in decision.lesson_ids}
    return _format([b.block_id for b in packet.blocks if b.text.strip()], [lesson['id'] for lesson in course['lessons']],
                   editable, list(decision.question_ids),
                   decision.allow_new_lessons and not decision.source_uncertain, _fingerprint(course))


def _reconstruct(value: Any) -> dict[str, Any]:
    try:
        props = value['json_schema']['schema']['properties']
        sources = props['new_lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum']
        lessons = props['new_questions']['items']['properties']['lesson_id']['enum']
        editable = {key: row['properties']['replacements']['items']['properties']['fragment_id']['enum']
                    for key, row in props.get('lesson_updates', {}).get('properties', {}).items()}
        result = _format(sources, lessons, editable, list(props.get('question_updates', {}).get('properties', {})),
                         'maxItems' not in props['new_lessons'], props['course_fingerprint']['enum'][0])
        if result != value:
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError):
        raise ValueError('practical_patch_format_invalid') from None


def is_practical_patch_format(value: object) -> bool:
    try:
        _reconstruct(value)
        return True
    except ValueError:
        return False


def matches_practical_patch(value: Any, response_format: Any) -> bool:
    try:
        fmt = _reconstruct(response_format)
        if not _matches(value, fmt['json_schema']['schema']):
            return False
        sources = fmt['json_schema']['schema']['properties']['new_lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum']
        from app.modules.ai.v3.practical_contract import matches_practical_course_response
        candidate_lessons = copy.deepcopy(value['new_lessons'])
        updates = list(value.get('question_updates', {}).values()) + [x['question'] for x in value['new_questions']]
        if updates:
            internal_id = '__patch_questions__'
            while internal_id in {row['id'] for row in candidate_lessons}:
                internal_id += '_'
            candidate_lessons.append({'id': internal_id, 'title': 'Patch', 'content': 'Patch', 'questions': updates})
        if candidate_lessons and not matches_practical_course_response(
                {'title': 'Patch', 'lessons': candidate_lessons}, _course_format(sources)):
            return False
        return all(row['title'].strip() and len({edit['fragment_id'] for edit in row['replacements']}) == len(row['replacements'])
                   for row in value.get('lesson_updates', {}).values())
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def merge_practical_patch(course: dict[str, Any], packet: PracticalSourcePacket,
                          decision: PracticalReviewDecision, patch: dict[str, Any]) -> dict[str, Any]:
    fmt = practical_patch_format(packet, course, decision)
    if not matches_practical_patch(patch, fmt):
        raise ValueError('practical_patch_response_invalid')
    result = copy.deepcopy(course)
    lessons = {lesson['id']: lesson for lesson in result['lessons']}
    question_ids = {q['id'] for lesson in course['lessons'] for q in lesson['questions']}
    updates = patch.get('question_updates', {})
    for lid, values in patch.get('lesson_updates', {}).items():
        original = lessons[lid]['content']
        fragments = {key: (start, end) for key, start, end in _fragments(original)}
        replacements = []
        for edit in values['replacements']:
            start, end = fragments[edit['fragment_id']]
            replacements.append((start, end, edit['new_text']))
        replacements.sort()
        if any(right[0] < left[1] for left, right in zip(replacements, replacements[1:], strict=False)):
            raise ValueError('practical_patch_prose_overlap')
        updated = original
        for start, end, new_text in reversed(replacements):
            updated = updated[:start] + new_text + updated[end:]
        lessons[lid]['title'] = values['title']
        lessons[lid]['content'] = updated
    for lesson in result['lessons']:
        lesson['questions'] = [copy.deepcopy(updates.get(q['id'], q)) for q in lesson['questions']]
    for row in patch['new_questions']:
        if row['question']['id'] in question_ids:
            raise ValueError('practical_patch_identity_collision')
        question_ids.add(row['question']['id'])
        lessons[row['lesson_id']]['questions'].append(copy.deepcopy(row['question']))
    for lesson in patch['new_lessons']:
        if lesson['id'] in lessons or any(q['id'] in question_ids for q in lesson['questions']):
            raise ValueError('practical_patch_identity_collision')
        lessons[lesson['id']] = lesson
        question_ids.update(q['id'] for q in lesson['questions'])
        result['lessons'].append(copy.deepcopy(lesson))
    return validate_practical_course(result, packet)
