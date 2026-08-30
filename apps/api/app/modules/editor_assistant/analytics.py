"""Analytics projection allowlist and persisted-metadata validation.

Cross-tenant analytics may contain only normalized categories, versions,
counts/durations, issue labels and outcome state. Raw instruction text and
other tenant content must never be projected or persisted as event metadata.

This module is the single canonical boundary:

- :func:`validate_event_metadata` validates the exact persisted shape. Only
  allowlisted keys survive; unknown keys and invalid values are rejected.
- :func:`project_request` / :func:`project_event` build the de-identified
  analytics views. Analytics builders must use them instead of serializing
  models directly.
"""

from __future__ import annotations

import re
from typing import Any

from .taxonomy import EditorQualityIssueLabel, EditorReasonCode

# Explicit field allowlist for the cross-tenant analytics projection of a
# request. Any field not listed here is tenant content or identity that must
# not leave the tenant boundary.
REQUEST_ANALYTICS_FIELDS: frozenset[str] = frozenset(
    {
        "intent_category",
        "outcome_state",
    }
)

_NORMALIZED_ANALYTICS_CODE_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$"
)

EVENT_ANALYTICS_FIELDS: frozenset[str] = frozenset(
    {
        "event_type",
    }
)

# Keys allowed to be PERSISTED in event ``metadata_json``. Everything else is
# rejected at the service boundary before insert.
EVENT_METADATA_ALLOWLIST: frozenset[str] = frozenset(
    {
        "issue_labels",
        "duration_ms",
        "attempt",
        "generator_version",
        "prompt_version",
        "model_id",
        "validator_version",
        "reason_code",
    }
)

_VERSION_METADATA_KEYS = frozenset(
    {
        "generator_version",
        "prompt_version",
        "model_id",
        "validator_version",
    }
)

_MAX_ISSUE_LABELS = 16
_MAX_DURATION_MS = 30 * 24 * 60 * 60 * 1000  # 30 days in milliseconds
_MAX_ATTEMPT = 1000
_MAX_VERSION_LENGTH = 120


class EditorMetadataValidationError(ValueError):
    """Event metadata contains an unknown key or an invalid normalized value."""


def _validate_issue_labels(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        raise EditorMetadataValidationError("issue_labels must be a list")
    labels = list(value)
    if len(labels) > _MAX_ISSUE_LABELS:
        raise EditorMetadataValidationError("issue_labels exceeds the bounded size")
    normalized: list[str] = []
    for label in labels:
        try:
            normalized.append(EditorQualityIssueLabel(label))
        except ValueError:
            raise EditorMetadataValidationError(
                "issue_labels contains an invalid taxonomy value"
            ) from None
    return [label.value for label in normalized]


def _validate_non_negative_int(value: Any, key: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EditorMetadataValidationError(f"{key} must be a non-negative integer")
    if value < 0 or value > maximum:
        raise EditorMetadataValidationError(f"{key} exceeds the bounded range")
    return value


def _validate_version_string(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise EditorMetadataValidationError(f"{key} must be a string")
    text_value = value.strip()
    if not text_value or len(text_value) > _MAX_VERSION_LENGTH:
        raise EditorMetadataValidationError(f"{key} must be a bounded non-empty string")
    if not _NORMALIZED_ANALYTICS_CODE_PATTERN.fullmatch(text_value):
        raise EditorMetadataValidationError(f"{key} must be a normalized code")
    return text_value


def _validate_reason_code(value: Any) -> str:
    if not isinstance(value, str):
        raise EditorMetadataValidationError("reason_code must be a string")
    try:
        return EditorReasonCode(value).value
    except ValueError:
        raise EditorMetadataValidationError("reason_code is not an allowed value") from None


def validate_event_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize event metadata to the persisted allowlist shape.

    Unknown keys are rejected rather than silently retained: the persisted
    ``metadata_json`` column can never hold free-text tenant content.
    """

    if not isinstance(metadata, dict):
        raise EditorMetadataValidationError("metadata must be a mapping")

    unknown = sorted(set(metadata) - EVENT_METADATA_ALLOWLIST)
    if unknown:
        raise EditorMetadataValidationError("metadata contains unsupported keys")

    validated: dict[str, Any] = {}
    if "issue_labels" in metadata:
        validated["issue_labels"] = _validate_issue_labels(metadata["issue_labels"])
    if "duration_ms" in metadata:
        validated["duration_ms"] = _validate_non_negative_int(
            metadata["duration_ms"], "duration_ms", _MAX_DURATION_MS
        )
    if "attempt" in metadata:
        validated["attempt"] = _validate_non_negative_int(metadata["attempt"], "attempt", _MAX_ATTEMPT)
    for key in _VERSION_METADATA_KEYS:
        if key in metadata:
            validated[key] = _validate_version_string(metadata[key], key)
    if "reason_code" in metadata:
        validated["reason_code"] = _validate_reason_code(metadata["reason_code"])
    return validated


def project_request(request: Any) -> dict[str, Any]:
    """Return the normalized, de-identified analytics view of one request."""

    return {
        field: getattr(request, field) for field in sorted(REQUEST_ANALYTICS_FIELDS)
    }


def project_event(event: Any) -> dict[str, Any]:
    """Return the normalized analytics view of one lifecycle event."""

    projected: dict[str, Any] = {
        field: getattr(event, field) for field in sorted(EVENT_ANALYTICS_FIELDS)
    }
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    try:
        validated_metadata = validate_event_metadata(metadata)
    except EditorMetadataValidationError:
        # A privileged or legacy writer must not smuggle arbitrary values
        # through an allowlisted key into cross-tenant analytics.
        validated_metadata = {}
    projected["metadata"] = {
        key: value
        for key, value in validated_metadata.items()
        if key in EVENT_METADATA_ALLOWLIST
    }
    return projected
