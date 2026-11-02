"""Server-owned fresh revision protocol marker."""
from typing import Any

KEY = "v3_revision_policy"
POLICY = "v3-scoped-revision-v1"


def stamp_policy(analysis: dict[str, Any]) -> dict[str, Any]:
    return {**analysis, KEY: POLICY}


def read_policy(analysis: Any) -> str | None:
    if not isinstance(analysis, dict):
        raise ValueError("v3_revision_analysis_invalid")
    if KEY not in analysis:
        return None
    if analysis[KEY] != POLICY or not isinstance(analysis[KEY], str):
        raise ValueError("v3_revision_policy_invalid")
    return POLICY


def policy_matches(analysis: Any, expected: str | None) -> bool:
    try:
        return read_policy(analysis) == expected
    except ValueError:
        return False
