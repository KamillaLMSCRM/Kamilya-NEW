"""Typed batch transport shape; independent review validators remain authoritative."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, cast

NAME = 'v3_batch_review_v1'


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'array', 'items': items}


def batch_review_response_format() -> dict[str, Any]:
    text = {'type': 'string'}
    number = {'type': 'number'}
    integer = {'type': 'integer'}
    claim = _object({'claim': text, 'status': text, 'reason': text})
    entailment = _object({'verdict': text, 'claims': _array(claim), 'summary': text})
    option = _object({'index': integer, 'verdict': text, 'omitted_required_elements': _array(text),
                      'claims': _array(claim), 'summary': text})
    defect = _object({'scope': text, 'question_id': text, 'issue': text, 'recommendation': text})
    lesson = _object({'verdict': text, 'factual_score': number, 'alignment_score': number,
                      'didactic_score': number, 'summary': text, 'defects': _array(defect)})
    completeness = _object({'answers': _array(_object({'index': integer, 'omissions': _array(text)})),
                            'explanation_review': entailment})
    options = _object({'options': _array(option)})
    item = _object({'id': text, 'review': {'anyOf': [lesson, entailment, options, completeness]}})
    value = {'type': 'json_schema', 'json_schema': {'name': NAME, 'strict': True,
                                                     'schema': _object({'items': _array(item)})}}
    return cast(dict[str, Any], json.loads(json.dumps(value, ensure_ascii=False)))


def batch_review_schema_hash() -> str:
    value = json.dumps(batch_review_response_format(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(value.encode()).hexdigest()


def is_batch_review_response_format(value: object) -> bool:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) == json.dumps(
            batch_review_response_format(), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return False


def _matches(item: Any, schema: dict[str, Any]) -> bool:
    if 'anyOf' in schema:
        return any(_matches(item, branch) for branch in schema['anyOf'])
    kind = schema['type']
    if kind == 'string':
        return type(item) is str and ('enum' not in schema or item in schema['enum'])
    if kind == 'integer':
        return type(item) is int and ('enum' not in schema or item in schema['enum'])
    if kind == 'number':
        return type(item) is int or (type(item) is float and math.isfinite(item))
    if kind == 'array':
        return (type(item) is list and len(item) >= schema.get('minItems', 0)
                and ('maxItems' not in schema or len(item) <= schema['maxItems'])
                and all(_matches(x, schema['items']) for x in item))
    if kind == 'object':
        props = schema['properties']
        return type(item) is dict and set(item) == set(props) and all(_matches(item[k], v) for k, v in props.items())
    return False


def is_batch_review_response(value: object) -> bool:
    return _matches(value, batch_review_response_format()['json_schema']['schema'])


def is_batch_review_for_method(value: object, method: str) -> bool:
    """Check the method's exact transport shape; this does not assess correctness."""
    branches = {'review_lesson': 0, 'review_answer': 1, 'review_question_options': 2,
                'review_question_compatibility': 2, 'review_answer_completeness': 3}
    if not isinstance(method, str) or method not in branches:
        return False
    schema = batch_review_response_format()['json_schema']['schema']
    options = schema['properties']['items']['items']['properties']['review']['anyOf']
    return _matches(value, options[branches[method]])
