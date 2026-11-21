"""Matching questions store alternating left/right choices in the authoring key."""

from collections.abc import Iterable, Sequence

MATCHING_PAIRS = "matching_pairs"


def validate_pair_labels(labels: Iterable[str]) -> None:
    values = [label.strip().casefold() for label in labels]
    if not 4 <= len(values) <= 50 or len(values) % 2 or "" in values:
        raise ValueError("Matching requires 2 to 25 complete pairs")
    for side in (values[::2], values[1::2]):
        if len(set(side)) != len(side):
            raise ValueError("Matching labels must be distinct on each side")


def pair_key(author_order: Sequence[str]) -> dict[str, str]:
    return dict(zip(author_order[::2], author_order[1::2], strict=True))


def normalize_pair_answer(
    author_order: Sequence[str], submitted: Sequence[str], *, complete: bool = False,
) -> list[str]:
    key = pair_key(author_order)
    if len(submitted) % 2 or len(set(submitted)) != len(submitted):
        raise ValueError("Each matching choice can be used only once and must have a partner")
    proposed = pair_key(submitted)
    if not proposed.keys() <= key.keys() or not set(proposed.values()) <= set(key.values()):
        raise ValueError("Match a left choice with a right choice from this question")
    if complete and len(proposed) != len(key):
        raise ValueError("Complete all pairs before submitting")
    return [choice for pair in sorted(proposed.items()) for choice in pair]


def public_pair_choices(choices: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Use opaque ID order so neither the positions nor adjacent rows expose the key."""
    return sorted(
        [
            {"id": choice["id"], "text": choice["text"], "match_side": "right" if i % 2 else "left"}
            for i, choice in enumerate(choices)
        ],
        key=lambda choice: choice["id"],
    )
