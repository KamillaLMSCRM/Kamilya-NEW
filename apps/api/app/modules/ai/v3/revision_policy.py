"""Server-owned fresh revision protocol marker."""
from typing import Any

KEY = "v3_revision_policy"
LEGACY_POLICY = "v3-scoped-revision-v1"
POLICY = "v3-scoped-revision-v2"


def is_scoped_policy(value: object) -> bool:
    return type(value) is str and value in {LEGACY_POLICY, POLICY}


def stamp_policy(analysis: dict[str, Any]) -> dict[str, Any]:
    return {**analysis, KEY: POLICY}


def read_policy(analysis: Any) -> str | None:
    if not isinstance(analysis, dict):
        raise ValueError("v3_revision_analysis_invalid")
    if KEY not in analysis:
        return None
    if not is_scoped_policy(analysis[KEY]):
        raise ValueError("v3_revision_policy_invalid")
    return str(analysis[KEY])


def policy_matches(analysis: Any, expected: str | None) -> bool:
    try:
        return read_policy(analysis) == expected
    except ValueError:
        return False
