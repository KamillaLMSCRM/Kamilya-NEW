"""Closed app-mediated literal lookup envelope; no tool or source authority."""

from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.batch_review_response_schema import _matches
from app.modules.ai.v3.simple_course_editor import _fingerprint_valid, _format, _object

PREFIX = "source_access_"


def access_format(
    inner: dict[str, Any], source: str, context: str, base_group: str, handles: list[str]
) -> dict[str, Any]:
    from app.modules.ai.v3.response_contracts import response_contract

    if (
        not isinstance(inner, dict)
        or inner.get("json_schema", {}).get("name", "").startswith(PREFIX)
        or response_contract(inner) is None
        or not _fingerprint_valid(source)
        or not _fingerprint_valid(context)
        or not isinstance(base_group, str)
        or not base_group.startswith("practical:simple:")
        or len(base_group.split(":")) < 5
        or base_group.split(":")[4] != source
        or type(handles) is not list
        or any(type(x) is not str or not x.strip() for x in handles)
        or len(set(handles)) != len(handles)
    ):
        raise ValueError("source_access_format_invalid")
    ids: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    if handles:
        ids["items"]["enum"] = handles
    else:
        ids["maxItems"] = 0
    return _format(
        PREFIX + inner["json_schema"]["name"],
        _object(
            {
                "source_fingerprint": {"type": "string", "enum": [source]},
                "context_fingerprint": {"type": "string", "enum": [context]},
                "base_group": {"type": "string", "enum": [base_group]},
                "lookup_ids": ids,
                "results": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 1,
                    "items": copy.deepcopy(inner["json_schema"]["schema"]),
                },
            }
        ),
    )


def inner_format(fmt: dict[str, Any]) -> dict[str, Any]:
    return _format(
        fmt["json_schema"]["name"].removeprefix(PREFIX),
        copy.deepcopy(fmt["json_schema"]["schema"]["properties"]["results"]["items"]),
    )


def is_access_format(fmt: Any) -> bool:
    try:
        if (
            type(fmt) is not dict
            or type(fmt.get("json_schema")) is not dict
            or type(fmt["json_schema"].get("name")) is not str
            or not fmt["json_schema"]["name"].startswith(PREFIX)
        ):
            return False
        props = fmt["json_schema"]["schema"]["properties"]
        return fmt == access_format(
            inner_format(fmt),
            props["source_fingerprint"]["enum"][0],
            props["context_fingerprint"]["enum"][0],
            props["base_group"]["enum"][0],
            props["lookup_ids"]["items"].get("enum", []),
        )
    except (KeyError, TypeError, ValueError, IndexError, RecursionError):
        return False


def matches_access(value: Any, fmt: Any) -> bool:
    if not is_access_format(fmt) or not _matches(value, fmt["json_schema"]["schema"]):
        return False
    ids = value["lookup_ids"]
    if len(set(ids)) != len(ids) or bool(ids) == bool(value["results"]):
        return False
    if ids:
        return True
    from app.modules.ai.v3.response_contracts import matches_transport_contract

    return matches_transport_contract(value["results"][0], inner_format(fmt))
