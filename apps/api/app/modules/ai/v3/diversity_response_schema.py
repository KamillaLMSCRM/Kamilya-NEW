"""Typed shape for a single source-bound diversity repair candidate."""
from __future__ import annotations

from typing import Any

from app.modules.ai.v3.models import DistractorCategory

NAME = 'v3_diversity_variant_author_v1'


def diversity_author_format(variant_id: str, source_quote: str) -> dict[str, Any]:
    if not isinstance(variant_id, str) or not variant_id.strip() or not isinstance(source_quote, str) or not source_quote.strip():
        raise ValueError('diversity_author_scope_invalid')
    text = {'type': 'string'}
    def obj(props: dict[str, Any]) -> dict[str, Any]:
        return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}
    row = obj({'text': text, 'category': {'type': 'string', 'enum': sorted(item.value for item in DistractorCategory)}})
    body = obj({'variant_id': {'type': 'string', 'enum': [variant_id]}, 'branch_context': text,
                'scenario_premise': text, 'prompt': text, 'correct': text,
                'distractors': {'type': 'array', 'items': row, 'minItems': 3, 'maxItems': 3},
                'explanation': text, 'source_quote': {'type': 'string', 'enum': [source_quote]}})
    return {'type': 'json_schema', 'json_schema': {'name': NAME, 'strict': True, 'schema': body}}


def is_diversity_author_format(value: object) -> bool:
    try:
        schema = value['json_schema']['schema']['properties']  # type: ignore[index]
        variant = schema['variant_id']['enum']
        quote = schema['source_quote']['enum']
        return (type(variant) is list and len(variant) == 1 and type(quote) is list and len(quote) == 1
                and value == diversity_author_format(variant[0], quote[0]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def is_diversity_author_response(value: object, response_format: object) -> bool:
    if not is_diversity_author_format(response_format) or type(value) is not dict:
        return False
    props = response_format['json_schema']['schema']['properties']  # type: ignore[index]
    if set(value) != set(props):
        return False
    if any(type(value[key]) is not str for key in props if key != 'distractors'):
        return False
    if value['variant_id'] not in props['variant_id']['enum'] or value['source_quote'] not in props['source_quote']['enum']:
        return False
    rows = value['distractors']
    categories = {item.value for item in DistractorCategory}
    return (type(rows) is list and len(rows) == 3 and all(type(row) is dict and set(row) == {'text', 'category'}
            and type(row['text']) is str and type(row['category']) is str and row['category'] in categories for row in rows))
