"""Pure, lossless transport repair for the registered practical author schema.

Every accepted artifact has a receipt, including unchanged input (empty paths).
This is structural normalization only and never implies semantic approval.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from app.modules.ai.v3.practical_contract import is_practical_course_format, matches_practical_course_response

VERSION = "practical-author-null-extras-v1"


def is_practical_author_stage(stage: Any, group: Any) -> bool:
    if stage == 'repair' and type(group) is str and re.fullmatch(
            r'practical:simple:editor:v1:[0-9a-f]{64}(?::output=[1-9][0-9]*)?', group):
        return True
    return stage == 'lesson' and type(group) is str and re.fullmatch(
        r'practical:(?:author:(?:v1|editorial:v31|editorial:v33)|focused:author:v36:[0-9a-f]{64}|simple:author:v1:[0-9a-f]{64})(?::output=[1-9][0-9]*)?',
        group,
    ) is not None


@dataclass(frozen=True, slots=True)
class AuthorNormalizationReceipt:
    version: str
    removed_paths: tuple[str, ...]
    raw_sha256: str
    normalized_sha256: str
    format_sha256: str


@dataclass(frozen=True, slots=True)
class PracticalAuthorArtifact:
    raw_text: str = field(repr=False)
    normalized_text: str = field(repr=False)
    receipt: AuthorNormalizationReceipt

    @property
    def normalized_value(self) -> dict[str, Any]:
        # Return a fresh value so callers cannot mutate the frozen artifact.
        return cast(dict[str, Any], json.loads(self.normalized_text))


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("practical_author_duplicate_key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("practical_author_nonfinite")
    return parsed


def _constant(_: str) -> None:
    raise ValueError("practical_author_nonfinite")


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _normalize(value: Any, schema: dict[str, Any], path: str, removed: list[str]) -> Any:
    if schema.get("type") == "object" and type(value) is dict:
        properties = schema["properties"]
        result = {}
        for key, item in value.items():
            child_path = path + "/" + _pointer_token(key)
            if key not in properties:
                if item is None:
                    removed.append(child_path)
                else:
                    result[key] = item
            else:
                result[key] = _normalize(item, properties[key], child_path, removed)
        return result
    if schema.get("type") == "array" and type(value) is list:
        return [_normalize(item, schema["items"], path + "/" + str(index), removed) for index, item in enumerate(value)]
    return value


def normalize_practical_author(raw_text: str, response_format: Any) -> PracticalAuthorArtifact:
    from app.modules.ai.v3.simple_course_editor import is_simple_editor_format, matches_simple_editor
    simple_editor = is_simple_editor_format(response_format)
    if type(raw_text) is not str or not (is_practical_course_format(response_format) or simple_editor):
        raise ValueError("practical_author_transport_format_invalid")
    try:
        parsed = json.loads(raw_text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_finite_float)
        if type(parsed) is not dict:
            raise ValueError("practical_author_transport_not_object")
        removed: list[str] = []
        normalized = _normalize(parsed, response_format["json_schema"]["schema"], "", removed)
        if not (matches_simple_editor(normalized, response_format) if simple_editor
                else matches_practical_course_response(normalized, response_format)):
            raise ValueError("practical_author_transport_invalid")
        text = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        raw_sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        normalized_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        format_text = json.dumps(
            response_format, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        format_sha = hashlib.sha256(format_text.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise ValueError("practical_author_transport_invalid") from error
    return PracticalAuthorArtifact(
        raw_text, text, AuthorNormalizationReceipt(VERSION, tuple(sorted(removed)), raw_sha, normalized_sha, format_sha)
    )


def validate_practical_author_artifact(artifact: Any, response_format: Any) -> bool:
    """Recompute from original bytes and exact schema; never trust receipt alone."""
    if type(artifact) is not PracticalAuthorArtifact or type(artifact.receipt) is not AuthorNormalizationReceipt:
        return False
    try:
        return normalize_practical_author(artifact.raw_text, response_format) == artifact
    except (ValueError, TypeError, RecursionError):
        return False


def author_custody(artifact: PracticalAuthorArtifact, response_format: Any) -> dict[str, Any]:
    if not validate_practical_author_artifact(artifact, response_format):
        raise ValueError('practical_author_custody_invalid')
    # The immutable in-memory receipt uses tuples; the stored JSON protocol uses
    # arrays. Canonicalize before pending finalization compares its readback.
    receipt = {**asdict(artifact.receipt), 'removed_paths': list(artifact.receipt.removed_paths)}
    return {'raw_text': artifact.raw_text, 'normalized_text': artifact.normalized_text,
            'format': json.loads(json.dumps(response_format)), 'receipt': receipt}


def validate_author_custody(value: Any, response: Any, response_format: Any = None) -> bool:
    try:
        if type(value) is not dict or set(value) != {'raw_text', 'normalized_text', 'format', 'receipt'}:
            return False
        fmt = value['format']
        if response_format is not None and json.dumps(fmt, sort_keys=True) != json.dumps(response_format, sort_keys=True):
            return False
        artifact = normalize_practical_author(value['raw_text'], fmt)
        return (artifact.normalized_text == value['normalized_text']
                and asdict(artifact.receipt) == {**value['receipt'], 'removed_paths': tuple(value['receipt']['removed_paths'])}
                and artifact.normalized_value == response)
    except (ValueError, TypeError, KeyError, RecursionError):
        return False
