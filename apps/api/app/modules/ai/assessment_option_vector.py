"""Recognize a narrowly repairable critic transport defect, never source truth."""

from collections.abc import Mapping
from typing import Any


def positive_review_shape_failure(
    row: Any, *, option_count: int, positive: str, negative: str,
    source_passages: Mapping[str, tuple[str, str]],
) -> bool:
    """Only a positive, source-bound row with one real key may repair its indices.

    A True result grants no receipt: discard the whole row and ask the SAME
    critic to classify the immutable candidate again. Unknowns and semantic
    vetoes are not transport defects, including unknowns on nonexistent indices.
    """
    if (not isinstance(row, dict) or row.get("validation_error")
            or any(row.get(flag) is not True for flag in (
                "educational", "lesson_answerable", "unambiguous", "explanation_supported"))):
        return False
    options = row.get("options")
    if not isinstance(options, list) or not options or any(not isinstance(item, dict) for item in options):
        return False
    for item in options:
        if item.get("relation") not in (positive, negative):
            return False
        reference = item.get("source_ref")
        if not isinstance(reference, str) or reference not in source_passages:
            return False
        source_id, quote = source_passages[reference]
        if item.get("source_id") != source_id or item.get("quote") != quote:
            return False
    keys = [item.get("index") for item in options if item["relation"] == positive]
    if len(keys) != 1 or type(keys[0]) is not int or not 0 <= keys[0] < option_count:
        return False
    language = row.get("option_language")
    if language is not None and (
        not isinstance(language, list) or not language
        or any(not isinstance(item, dict) or item.get("grammatical") is not True for item in language)
    ):
        return False
    indices = [item.get("index") for item in options]
    return (len(indices) != option_count or any(type(index) is not int for index in indices)
            or sorted(indices) != list(range(option_count)))
