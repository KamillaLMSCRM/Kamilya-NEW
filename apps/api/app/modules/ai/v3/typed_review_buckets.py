"""Request-bound review buckets: transport shape only, never semantic approval."""
from __future__ import annotations

import json
import re
from typing import Any, cast

from app.modules.ai.v3.batch_review_response_schema import batch_review_response_format, is_batch_review_for_method

FORMAT_NAME = 'v3_batch_review_v2'
BUCKETS = {'review_lesson': 'lesson_reviews', 'review_answer': 'answer_reviews',
           'review_question_options': 'option_reviews', 'review_question_compatibility': 'compatibility_reviews',
           'review_answer_completeness': 'completeness_reviews'}
BRANCHES = {'review_lesson': 0, 'review_answer': 1, 'review_question_options': 2,
            'review_question_compatibility': 2, 'review_answer_completeness': 3}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def build_typed_review_format(expected: dict[str, list[str]]) -> dict[str, Any]:
    if type(expected) is not dict or set(expected) != set(BUCKETS):
        raise ValueError('typed_review_methods_invalid')
    seen: set[str] = set()
    schema = batch_review_response_format()['json_schema']['schema']
    branches = schema['properties']['items']['items']['properties']['review']['anyOf']
    properties: dict[str, Any] = {}
    for method, bucket in BUCKETS.items():
        ids = expected[method]
        if (type(ids) is not list or any(type(item) is not str or re.fullmatch(r'[0-9a-f]{64}', item) is None for item in ids)
                or len(ids) != len(set(ids)) or seen.intersection(ids)):
            raise ValueError('typed_review_ids_invalid')
        seen.update(ids)
        id_schema: dict[str, Any] = {'type': 'string'}
        if ids:
            id_schema['enum'] = sorted(ids)
        properties[bucket] = {'type': 'array', 'minItems': len(ids), 'maxItems': len(ids),
                              'items': _object({'id': id_schema, 'review': branches[BRANCHES[method]]})}
    return {'type': 'json_schema', 'json_schema': {'name': FORMAT_NAME, 'strict': True, 'schema': _object(properties)}}


def _expected_from_format(value: object) -> dict[str, list[str]]:
    try:
        props = value['json_schema']['schema']['properties']  # type: ignore[index]
        expected = {}
        for method, bucket in BUCKETS.items():
            array = props[bucket]
            ids = array['items']['properties']['id'].get('enum', [])
            if type(ids) is not list:
                raise ValueError
            expected[method] = ids
        rebuilt = build_typed_review_format(expected)
        if json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) != json.dumps(
                rebuilt, sort_keys=True, separators=(',', ':'), allow_nan=False):
            raise ValueError
        return expected
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise ValueError('typed_review_format_invalid') from None


def is_typed_review_format(value: object) -> bool:
    try:
        _expected_from_format(value)
        return True
    except ValueError:
        return False


def normalize_typed_reviews(value: object, response_format: object) -> dict[str, Any]:
    expected = _expected_from_format(response_format)
    if type(value) is not dict or set(value) != set(BUCKETS.values()):
        raise ValueError('typed_review_response_invalid')
    output: list[dict[str, Any]] = []
    for method, bucket in BUCKETS.items():
        entries = value[bucket]
        if type(entries) is not list or len(entries) != len(expected[method]):
            raise ValueError('typed_review_response_invalid')
        found: set[str] = set()
        for entry in entries:
            if (type(entry) is not dict or set(entry) != {'id', 'review'} or type(entry['id']) is not str
                    or entry['id'] not in expected[method] or entry['id'] in found
                    or not is_batch_review_for_method(entry['review'], method)):
                raise ValueError('typed_review_response_invalid')
            found.add(entry['id'])
            output.append({'id': entry['id'], 'review': entry['review']})
        if found != set(expected[method]):
            raise ValueError('typed_review_response_invalid')
    return cast(dict[str, Any], json.loads(json.dumps({'items': output}, ensure_ascii=False, allow_nan=False)))


def is_typed_review_response(value: object, response_format: object) -> bool:
    try:
        normalize_typed_reviews(value, response_format)
        return True
    except (ValueError, TypeError, RecursionError):
        return False
