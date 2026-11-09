"""Compile literal evidence custody for a follow-up editorial review.

Literal anchors establish provenance, not whether an issue is semantically fixed.
"""
from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.practical_contract import PracticalSourcePacket
from app.modules.ai.v3.practical_editorial_contract import (
    _obj,
    compile_editorial_review,
    editorial_review_format,
    is_editorial_review_format,
    matches_editorial_review,
)

NAME = 'v3_practical_editorial_verification_v1'
DISPOSITIONS = ['FIXED', 'ALREADY_COVERED', 'NOT_MATERIAL', 'NEEDS_REVISION', 'UNRESOLVED', 'SOURCE_AMBIGUITY']


def _format(base: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    if len(ids) != len(set(ids)) or any(type(i) is not str or not i for i in ids):
        raise ValueError('editorial_verification_identity_invalid')
    result = copy.deepcopy(base)
    result['json_schema']['name'] = NAME
    text = {'type': 'string'}
    result['json_schema']['schema']['properties']['resolutions'] = {'type': 'array', 'items': _obj({
        'issue_id': {'type': 'string', 'enum': ids},
        'disposition': {'type': 'string', 'enum': DISPOSITIONS},
        'reason': text, 'source_refs': {'type': 'array', 'items': text},
        'source_quote': text, 'course_quote': text, 'source_question': text,
    })}
    result['json_schema']['schema']['required'].append('resolutions')
    return result


def editorial_verification_format(packet: PracticalSourcePacket, course: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        ids = [row['issue_id'] for row in findings if row['severity'] == 'material']
    except (KeyError, TypeError) as exc:
        raise ValueError('editorial_verification_identity_invalid') from exc
    return _format(editorial_review_format(packet, course), ids)


def is_editorial_verification_format(fmt: Any) -> bool:
    try:
        base = copy.deepcopy(fmt)
        props = base['json_schema']['schema']['properties']
        ids = props.pop('resolutions')['items']['properties']['issue_id']['enum']
        base['json_schema']['schema']['required'].remove('resolutions')
        base['json_schema']['name'] = 'v3_practical_editorial_review_v1'
        return bool(is_editorial_review_format(base) and fmt == _format(base, ids))
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def matches_editorial_verification_shape(value: Any, fmt: Any) -> bool:
    """Typed owned observations; an incomplete inventory is never semantic approval."""
    if not is_editorial_verification_format(fmt) or not _matches(value, fmt['json_schema']['schema']):
        return False
    base = copy.deepcopy(fmt)
    ids = base['json_schema']['schema']['properties'].pop('resolutions')['items']['properties']['issue_id']['enum']
    base['json_schema']['schema']['required'].remove('resolutions')
    base['json_schema']['name'] = 'v3_practical_editorial_review_v1'
    review = {k: v for k, v in value.items() if k != 'resolutions'}
    actual = [row['issue_id'] for row in value['resolutions']]
    return len(actual) == len(set(actual)) and set(actual) <= set(ids) and matches_editorial_review(review, base)


def matches_editorial_verification(value: Any, fmt: Any) -> bool:
    if not matches_editorial_verification_shape(value, fmt):
        return False
    ids = fmt['json_schema']['schema']['properties']['resolutions']['items']['properties']['issue_id']['enum']
    return {row['issue_id'] for row in value['resolutions']} == set(ids)


def literal_course_texts(course: dict[str, Any], finding: dict[str, Any]) -> list[str]:
    """Return the exact owned text scope, never evidence of semantic correctness."""
    target = finding['target']
    if finding['domain'] == 'assessment' and target['kind'] in ('course', 'lesson'):
        return [text for lesson in course['lessons']
            if target['kind'] == 'course' or lesson['id'] == target['id']
            for question in lesson['questions']
            for text in (question['prompt'], *question['choices'], question['explanation'])]
    if target['kind'] == 'course':
        return [lesson['content'] for lesson in course['lessons']]
    if target['kind'] == 'lesson':
        return [lesson['content'] for lesson in course['lessons'] if lesson['id'] == target['id']]
    if target['kind'] == 'question':
        texts = []
        for lesson in course['lessons']:
            for question in lesson['questions']:
                if question['id'] == target['id']:
                    texts = [question['prompt'], *question['choices'], question['explanation']]
        return texts
    return []


def compile_editorial_verification(value: Any, packet: PracticalSourcePacket, course: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    fmt = editorial_verification_format(packet, course, findings)
    if not matches_editorial_verification(value, fmt):
        raise ValueError('editorial_verification_response_invalid')
    review = compile_editorial_review({k: v for k, v in value.items() if k != 'resolutions'}, packet, course)
    by_id = {row['issue_id']: row for row in findings if row['severity'] == 'material'}
    blocks = {block.block_id: block.text for block in packet.blocks}
    resolutions = []
    for row in value['resolutions']:
        finding = by_id[row['issue_id']]
        errors = []
        if not row['reason'].strip():
            errors.append('reason_missing')
        refs = row['source_refs']
        if not refs or len(refs) != len(set(refs)) or any(ref not in blocks for ref in refs):
            errors.append('source_refs_invalid')
        if not row['source_quote'].strip() or not any(row['source_quote'] in blocks.get(ref, '') for ref in refs):
            errors.append('source_quote_invalid')
        disposition = row['disposition']
        if disposition == 'NEEDS_REVISION' and (finding['domain'] == 'source' or finding['target']['kind'] == 'source'):
            errors.append('source_finding_cannot_authorize_course_revision')
        if disposition == 'NEEDS_REVISION':
            target = finding['target']
            owned = (target['kind'] == 'course' and target['id'] == 'course'
                or target['kind'] == 'lesson' and any(target['id'] == lesson['id'] for lesson in course['lessons'])
                or target['kind'] == 'question' and any(target['id'] == q['id']
                    for lesson in course['lessons'] for q in lesson['questions']))
            if not owned:
                errors.append('current_target_invalid')
        if (disposition in ('FIXED', 'ALREADY_COVERED')
                or disposition == 'NEEDS_REVISION' and finding['target']['kind'] == 'question'):
            texts = literal_course_texts(course, finding)
            if not row['course_quote'].strip() or not any(row['course_quote'] in text for text in texts):
                errors.append('course_quote_invalid')
            if finding['domain'] == 'source':
                errors.append('source_finding_cannot_be_fixed_by_course')
        if disposition == 'SOURCE_AMBIGUITY' and not row['source_question'].strip():
            errors.append('source_question_missing')
        if disposition == 'UNRESOLVED':
            errors.append('unresolved')
        result_row = copy.deepcopy(row)
        if disposition != 'SOURCE_AMBIGUITY':
            result_row['source_question'] = ''
        resolutions.append({**result_row, 'verified': not errors, 'verification_errors': errors})
    return {'review': review, 'resolutions': resolutions}
