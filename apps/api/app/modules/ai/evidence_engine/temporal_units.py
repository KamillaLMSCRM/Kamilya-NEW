"""Whole Russian duration units shared by source and assessment classifiers."""

import re

# A unit is a complete inflected word: час is not частичная, день is not
# деньги, and дн is not дневник. Normalize ё in both source paths consistently.
_TEMPORAL_UNIT = re.compile(
    r"\b(?:минут(?:а|ы|у|е|ой|ам|ами|ах)?|"
    r"час(?:а|у|е|ом|ы|ов|ам|ами|ах)?|"
    r"день|дня|дней|дню|днем|дни|дням|днями|днях|"
    r"месяц(?:а|у|е|ем|ы|ев|ам|ами|ах)?)\b"
)


def has_temporal_unit(value: str) -> bool:
    return bool(_TEMPORAL_UNIT.search(value.casefold().replace("ё", "е")))
