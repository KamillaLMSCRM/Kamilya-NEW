"""Whole-lesson prose proposals; acceptance and media custody remain external."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import _digest

NAME = 'v3_practical_prose_revision_v1'


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def prose_revision_format(source_fp: str, course_fp: str, lesson_ids: list[str]) -> dict[str, Any]:
    if any(type(fp) is not str or not re.fullmatch(r'[0-9a-f]{64}', fp) for fp in (source_fp, course_fp)):
        raise ValueError('prose_revision_fingerprint_invalid')
    if (type(lesson_ids) is not list or not lesson_ids or any(type(x) is not str or not x.strip() for x in lesson_ids)
            or len(lesson_ids) != len(set(lesson_ids))):
        raise ValueError('prose_revision_lesson_inventory_invalid')
    schema = _object({'source_fingerprint': {'type': 'string', 'enum': [source_fp]},
        'course_fingerprint': {'type': 'string', 'enum': [course_fp]},
        'updates': {'type': 'array', 'items': _object({'lesson_id': {'type': 'string', 'enum': list(lesson_ids)},
                                                      'content': {'type': 'string'}})}})
    fmt = {'type': 'json_schema', 'json_schema': {'name': NAME, 'strict': True, 'schema': schema}}
    if len(json.dumps(fmt, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')) > 65536:
        raise ValueError('prose_revision_format_too_large')
    return fmt


def is_prose_revision_format(fmt: object) -> bool:
    try:
        if not isinstance(fmt, dict) or fmt['json_schema']['name'] != NAME:
            return False
        props = fmt['json_schema']['schema']['properties']
        return bool(fmt == prose_revision_format(props['source_fingerprint']['enum'][0],
            props['course_fingerprint']['enum'][0], props['updates']['items']['properties']['lesson_id']['enum']))
    except (KeyError, IndexError, TypeError, ValueError, RecursionError, AttributeError):
        return False


def matches_prose_revision(value: object, fmt: object) -> bool:
    try:
        if not is_prose_revision_format(fmt) or not isinstance(fmt, dict) or not _matches(value, fmt['json_schema']['schema']):
            return False
        assert isinstance(value, dict)
        rows = value['updates']
        return bool(len({row['lesson_id'] for row in rows}) == len(rows)
                    and all(row['content'].strip() for row in rows))
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def compile_prose_revision(value: object, packet: Any, course: dict[str, Any],
                           allowed_lesson_ids: list[str]) -> dict[str, Any]:
    """Apply owned content fields only; caller verifies/restores original media."""
    if not isinstance(course, dict) or not isinstance(course.get('lessons'), list):
        raise ValueError('prose_revision_course_invalid')
    lessons = course['lessons']
    if any(not isinstance(row, dict) or type(row.get('id')) is not str or type(row.get('content')) is not str
           for row in lessons):
        raise ValueError('prose_revision_course_invalid')
    ids = [row['id'] for row in lessons]
    fmt = prose_revision_format(packet.fingerprint, _digest(course), allowed_lesson_ids)
    if len(ids) != len(set(ids)) or not set(allowed_lesson_ids) <= set(ids):
        raise ValueError('prose_revision_scope_invalid')
    if not matches_prose_revision(value, fmt):
        raise ValueError('prose_revision_response_invalid')
    assert isinstance(value, dict)
    result = copy.deepcopy(course)
    by_id = {row['id']: row for row in result['lessons']}
    for update in value['updates']:
        by_id[update['lesson_id']]['content'] = update['content']
    return {'course': result, 'source_fingerprint': packet.fingerprint, 'before_fingerprint': _digest(course),
            'updated_lesson_ids': [row['lesson_id'] for row in value['updates']], 'semantic_acceptance': False}
