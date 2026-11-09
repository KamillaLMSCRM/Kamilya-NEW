"""Source-bound editorial findings and one revision; no semantic acceptance heuristic."""
from __future__ import annotations

import copy
from typing import Any, cast

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import (
    PracticalSourcePacket,
    _digest,
    course_response_format,
    validate_practical_course,
)

REVIEW_NAME = 'v3_practical_editorial_review_v1'
REVISION_NAME = 'v3_practical_editorial_revision_v1'


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def _review_format(sources: list[str], lessons: list[str], questions: list[str],
                   source_fp: str, course_fp: str) -> dict[str, Any]:
    for ids in (sources, lessons, questions):
        if not ids or len(set(ids)) != len(ids) or any(not isinstance(key, str) or not key for key in ids):
            raise ValueError('editorial_review_identity_invalid')
    refs = {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'enum': sources}}
    text = {'type': 'string'}
    # Domain and target are separate: assessment can concern a question OR a lesson.
    targets = [_obj({'kind': {'type': 'string', 'enum': [kind]},
                     'id': {'type': 'string', 'enum': ids}})
               for kind, ids in (('course', ['course']), ('lesson', lessons),
                                 ('question', questions), ('source', sources))]
    finding = _obj({'domain': {'type': 'string', 'enum': ['content', 'assessment', 'source']},
        'severity': {'type': 'string', 'enum': ['material', 'advisory']},
        'target': {'anyOf': targets}, 'problem': text, 'basis': text, 'correction': text, 'source_refs': refs})
    return {'type': 'json_schema', 'json_schema': {'name': REVIEW_NAME, 'strict': True, 'schema': _obj({
        'source_fingerprint': {'type': 'string', 'enum': [source_fp]},
        'course_fingerprint': {'type': 'string', 'enum': [course_fp]},
        'summary': text, 'findings': {'type': 'array', 'items': finding},
        'source_notes': {'type': 'array', 'items': _obj({'note': text, 'source_refs': refs})},
        'narrative_sources': _obj({key: copy.deepcopy(refs) for key in lessons})})}}


def editorial_review_format(packet: PracticalSourcePacket, course: dict[str, Any]) -> dict[str, Any]:
    validate_practical_course(course, packet)
    return _review_format([b.block_id for b in packet.blocks if b.text.strip()],
        [row['id'] for row in course['lessons']],
        [q['id'] for row in course['lessons'] for q in row['questions']], packet.fingerprint, _digest(course))


def is_editorial_review_format(fmt: Any) -> bool:
    try:
        props = fmt['json_schema']['schema']['properties']
        targets = props['findings']['items']['properties']['target']['anyOf']
        return bool(fmt == _review_format(
            props['source_notes']['items']['properties']['source_refs']['items']['enum'],
            targets[1]['properties']['id']['enum'], targets[2]['properties']['id']['enum'],
            props['source_fingerprint']['enum'][0], props['course_fingerprint']['enum'][0]))
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def matches_editorial_review(value: Any, fmt: Any) -> bool:
    if not is_editorial_review_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    rows = value['findings']
    return bool(value['summary'].strip()
        and all(all(row[key].strip() for key in ('problem', 'basis', 'correction')) for row in rows)
        and all(row['note'].strip() for row in value['source_notes'])
        and all(len(refs) == len(set(refs)) for refs in [
            *(r['source_refs'] for r in rows), *(r['source_refs'] for r in value['source_notes']),
            *value['narrative_sources'].values()]))


def compile_editorial_review(value: Any, packet: PracticalSourcePacket, course: dict[str, Any]) -> dict[str, Any]:
    if not matches_editorial_review(value, editorial_review_format(packet, course)):
        raise ValueError('editorial_review_response_invalid')
    result = cast(dict[str, Any], copy.deepcopy(value))
    unique = {}
    for row in result['findings']:
        identity = 'issue-' + _digest(row)[:20]
        unique[identity] = {'issue_id': identity, **row}
    result['findings'] = list(unique.values())
    return result


def _revision_format(source_fp: str, course_fp: str, course_schema: dict[str, Any]) -> dict[str, Any]:
    sources = course_schema['properties']['lessons']['items']['properties']['questions']['items']['properties']['source_refs']['items']['enum']
    return {'type': 'json_schema', 'json_schema': {'name': REVISION_NAME, 'strict': True, 'schema': _obj({
        'source_fingerprint': {'type': 'string', 'enum': [source_fp]},
        'course_fingerprint': {'type': 'string', 'enum': [course_fp]}, 'course': course_schema,
        'lesson_sources': {'type': 'array', 'items': _obj({'lesson_id': {'type': 'string'},
            'source_refs': {'type': 'array', 'minItems': 1, 'items': {'type': 'string', 'enum': sources}}})}})}}


def editorial_revision_format(packet: PracticalSourcePacket, course: dict[str, Any]) -> dict[str, Any]:
    validate_practical_course(course, packet)
    return _revision_format(packet.fingerprint, _digest(course), course_response_format(packet)['json_schema']['schema'])


def is_editorial_revision_format(fmt: Any) -> bool:
    try:
        from app.modules.ai.v3.practical_contract import is_practical_course_format

        props = fmt['json_schema']['schema']['properties']
        schema = props['course']
        wrapped = {'type': 'json_schema', 'json_schema': {'name': 'practical_course', 'strict': True, 'schema': schema}}
        return bool(is_practical_course_format(wrapped) and fmt == _revision_format(
            props['source_fingerprint']['enum'][0], props['course_fingerprint']['enum'][0], schema))
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def matches_editorial_revision(value: Any, fmt: Any) -> bool:
    if not is_editorial_revision_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    from app.modules.ai.v3.practical_contract import matches_practical_course_response

    schema = fmt['json_schema']['schema']['properties']['course']
    ids = [row['lesson_id'] for row in value['lesson_sources']]
    return (matches_practical_course_response(value['course'],
        {'type': 'json_schema', 'json_schema': {'name': 'practical_course', 'strict': True, 'schema': schema}})
        and len(ids) == len(set(ids)) and set(ids) <= {row['id'] for row in value['course']['lessons']}
        and all(len(row['source_refs']) == len(set(row['source_refs'])) for row in value['lesson_sources']))


def editorial_edit_authority(course: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Compose verified edit intents as a union; a child cannot freeze its parent.

    This grants owned editing scope, never establishes a finding's semantic truth.
    The revision compiler independently retains its existing ownership boundary.
    """
    lessons = {lesson['id']: lesson for lesson in course['lessons']}
    owners = {q['id']: lesson['id'] for lesson in course['lessons'] for q in lesson['questions']}
    all_editable = False
    prose: set[str] = set()
    questions: set[str] = set()
    for row in findings:
        target = row.get('target', {})
        kind, key = target.get('kind'), target.get('id')
        if row.get('domain') == 'source' or row.get('severity') != 'material':
            raise ValueError('editorial_edit_authority_invalid')
        if kind == 'course' and key == 'course':
            all_editable = True
        elif kind == 'lesson' and key in lessons:
            prose.add(key)
        elif kind == 'question' and key in owners:
            questions.add(key)
        else:
            raise ValueError('editorial_edit_authority_invalid')
    return {'course_title_editable': all_editable, 'lessons': [
        {'lesson_id': lesson['id'], 'title_editable': all_editable or lesson['id'] in prose,
         'content_editable': all_editable or lesson['id'] in prose,
         'editable_question_ids': [q['id'] for q in lesson['questions']
             if all_editable or lesson['id'] in prose or q['id'] in questions]}
        for lesson in course['lessons'] if all_editable or lesson['id'] in prose
            or any(q['id'] in questions for q in lesson['questions'])]}


def compile_editorial_revision(value: Any, packet: PracticalSourcePacket, original: dict[str, Any],
                               review: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if review.get('source_fingerprint') != packet.fingerprint or review.get('course_fingerprint') != _digest(original):
        raise ValueError('editorial_revision_review_identity_invalid')
    material = [row for row in review['findings'] if row['severity'] == 'material' and row['domain'] != 'source']
    targets: dict[str, set[str]] = {row['target']['kind']: set() for row in material}
    for row in material:
        targets[row['target']['kind']].add(row['target']['id'])
    return _merge_editorial_revision(value, packet, original, targets)


def compile_lesson_alignment_revision(value: Any, packet: PracticalSourcePacket,
        original: dict[str, Any], lesson_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Owned edit intent is independent from a finding's severity or truth."""
    known = {row['id'] for row in original['lessons']}
    if (type(lesson_ids) is not list or not lesson_ids
            or any(type(key) is not str or key not in known for key in lesson_ids)
            or len(lesson_ids) != len(set(lesson_ids))):
        raise ValueError('editorial_alignment_scope_invalid')
    course, metadata = _merge_editorial_revision(value, packet, original, {'lesson': set(lesson_ids)})
    return course, {**metadata, 'edit_intent': 'SOURCE_INTERPRETATION_ALIGNMENT',
        'course_error_asserted': False, 'semantic_resolution': 'REQUIRES_AUTOMATED_CONTENT_REVIEW'}


def _merge_editorial_revision(value: Any, packet: PracticalSourcePacket, original: dict[str, Any],
        targets: dict[str, set[str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not matches_editorial_revision(value, editorial_revision_format(packet, original)):
        raise ValueError('editorial_revision_response_invalid')
    all_editable = bool(targets.get('course'))
    proposed = validate_practical_course(value['course'], packet)
    candidates = {row['id']: row for row in proposed['lessons']}
    merged = copy.deepcopy(original)
    ignored = []
    missing = []
    for index, before in enumerate(original['lessons']):
        after = candidates.get(before['id'])
        if after is None:
            missing.append(before['id'])
            continue
        if all_editable or before['id'] in targets.get('lesson', set()):
            selected = copy.deepcopy(after)
            returned_ids = {q['id'] for q in selected['questions']}
            for question in before['questions']:
                if question['id'] not in returned_ids:
                    selected['questions'].append(copy.deepcopy(question))
                    missing.append(question['id'])
            merged['lessons'][index] = selected
        else:
            after_questions = {q['id']: q for q in after['questions']}
            for qi, question in enumerate(before['questions']):
                if question['id'] in targets.get('question', set()):
                    if question['id'] in after_questions:
                        merged['lessons'][index]['questions'][qi] = copy.deepcopy(after_questions[question['id']])
                    else:
                        missing.append(question['id'])
            if after != merged['lessons'][index]:
                ignored.append(before['id'])
    if all_editable:
        existing = {row['id'] for row in merged['lessons']}
        merged['lessons'].extend(copy.deepcopy(row) for row in proposed['lessons'] if row['id'] not in existing)
        merged['title'] = proposed['title']
    elif proposed['title'] != original['title']:
        ignored.append('course_title')
    if not all_editable:
        ignored.extend(row['id'] for row in proposed['lessons'] if row['id'] not in {r['id'] for r in original['lessons']})
    try:
        merged = validate_practical_course(merged, packet)
    except ValueError:
        # A structurally valid proposal can collide with a sibling retained above.
        # Preserve the complete original draft and expose this unsuccessful edit.
        merged = copy.deepcopy(original)
        missing.append('revision_merge_identity_conflict')
    before_questions = {q['id']: q for row in original['lessons'] for q in row['questions']}
    changed_questions = [q['id'] for row in merged['lessons'] for q in row['questions']
                         if before_questions.get(q['id']) != q]
    before_lessons = {row['id']: row for row in original['lessons']}
    changed_lessons = [row['id'] for row in merged['lessons'] if before_lessons.get(row['id']) != row]
    return merged, {'revision_applied': merged != original, 'ignored_unrequested_changes': ignored,
                    'retained_missing_targets': missing, 'changed_question_ids': changed_questions,
                    'changed_lesson_ids': changed_lessons,
                    'narrative_source_proposals': {row['lesson_id']: row['source_refs'] for row in value['lesson_sources']},
                    'semantic_resolution': 'REQUIRES_HUMAN_REVIEW'}
