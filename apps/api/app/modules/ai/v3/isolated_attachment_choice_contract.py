"""Record-bound grammatical choices are unverified, never semantic truth."""
from __future__ import annotations

import json
import re
from typing import Any, cast

from app.modules.ai.v3.batch_review_response_schema import _matches

NAME = 'v3_isolated_attachment_choice_v1'
UNKNOWN = 'UNKNOWN'


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def attachment_choice_format(input_fp: str, source_fp: str, course_fp: str, role: str,
                             task_bindings: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Bind each task to the caller's current record, modifier and candidate IDs."""
    if any(type(fp) is not str or not re.fullmatch(r'[0-9a-f]{64}', fp)
           for fp in (input_fp, source_fp, course_fp)):
        raise ValueError('attachment_choice_fingerprint_invalid')
    if type(role) is not str or role not in ('source', 'learner'):
        raise ValueError('attachment_choice_role_invalid')
    if type(task_bindings) is not dict or not task_bindings:
        raise ValueError('attachment_choice_bindings_invalid')
    decisions: dict[str, Any] = {}
    seen: set[tuple[str, str]] = set()
    for task_id, binding in task_bindings.items():
        if (type(task_id) is not str or not task_id.strip() or type(binding) is not dict
                or set(binding) != {'record_id', 'modifier_token_id', 'allowed_head_token_ids'}
                or any(type(binding[key]) is not str or not binding[key].strip()
                       for key in ('record_id', 'modifier_token_id'))
                or type(binding['allowed_head_token_ids']) is not list
                or any(type(head) is not str or not head.strip() or head == UNKNOWN
                       for head in binding['allowed_head_token_ids'])
                or len(set(binding['allowed_head_token_ids'])) != len(binding['allowed_head_token_ids'])):
            raise ValueError('attachment_choice_bindings_invalid')
        identity = (binding['record_id'], binding['modifier_token_id'])
        if identity in seen:
            raise ValueError('attachment_choice_duplicate_binding')
        seen.add(identity)
        decisions[task_id] = _object({
            'record_id': {'type': 'string', 'enum': [binding['record_id']]},
            'modifier_token_id': {'type': 'string', 'enum': [binding['modifier_token_id']]},
            'selected_head_id': {'type': 'string', 'enum': [*binding['allowed_head_token_ids'], UNKNOWN]},
            'rationale': {'type': 'string'},
        })
    schema = _object({'input_fingerprint': {'type': 'string', 'enum': [input_fp]},
                      'source_fingerprint': {'type': 'string', 'enum': [source_fp]},
                      'course_fingerprint': {'type': 'string', 'enum': [course_fp]},
                      'role': {'type': 'string', 'enum': [role]}, 'decisions': _object(decisions)})
    fmt = {'type': 'json_schema', 'json_schema': {'name': NAME, 'strict': True, 'schema': schema}}
    try:
        encoded = json.dumps(fmt, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('attachment_choice_format_invalid') from exc
    if len(encoded) > 65536:
        raise ValueError('attachment_choice_format_too_large')
    return cast(dict[str, Any], json.loads(encoded))


def is_attachment_choice_format(value: object) -> bool:
    try:
        assert isinstance(value, dict)
        props = value['json_schema']['schema']['properties']
        decisions = props['decisions']
        bindings = {}
        for task_id in decisions['required']:
            task = decisions['properties'][task_id]['properties']
            heads = task['selected_head_id']['enum']
            if type(heads) is not list or not heads or heads[-1] != UNKNOWN:
                return False
            bindings[task_id] = {'record_id': task['record_id']['enum'][0],
                                 'modifier_token_id': task['modifier_token_id']['enum'][0],
                                 'allowed_head_token_ids': heads[:-1]}
        expected = attachment_choice_format(props['input_fingerprint']['enum'][0],
                                            props['source_fingerprint']['enum'][0],
                                            props['course_fingerprint']['enum'][0],
                                            props['role']['enum'][0], bindings)
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) == json.dumps(
            expected, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except (AssertionError, KeyError, TypeError, IndexError, ValueError, UnicodeError, RecursionError):
        return False


def matches_attachment_choice_response(value: object, fmt: object) -> bool:
    """Check only closed shape and identity; choices remain unverified hypotheses."""
    try:
        return bool(is_attachment_choice_format(fmt) and isinstance(fmt, dict)
                    and _matches(value, fmt['json_schema']['schema']))
    except (KeyError, TypeError, ValueError, RecursionError):
        return False
