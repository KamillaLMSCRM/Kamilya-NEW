"""Validated, optional usage metadata for an owned direct response."""
from typing import Any

FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")


def checked_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"model", "usage"} or value["model"] != "gpt-6-luna":
        raise ValueError("direct_usage_metadata_invalid")
    usage = value["usage"]
    if not isinstance(usage, dict) or set(usage) != set(FIELDS):
        raise ValueError("direct_usage_metadata_invalid")
    if any(v is not None and (type(v) is not int or v < 0) for v in usage.values()):
        raise ValueError("direct_usage_metadata_invalid")
    normalized = {key: usage[key] for key in FIELDS}
    for part, total in (("cached_input_tokens", "input_tokens"), ("reasoning_tokens", "output_tokens")):
        if normalized[part] is not None and normalized[total] is not None and normalized[part] > normalized[total]:
            normalized[part] = None
    return {"model": "gpt-6-luna", "usage": normalized}
