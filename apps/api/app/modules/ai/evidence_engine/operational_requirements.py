"""Conservative projections for compound source-owned operational requirements.

This module only recognizes two narrowly bounded Russian sentence forms. It
does not decide truth, create answer choices, or invert a requirement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceRequirementContract:
    kind: str
    required_prompt: str
    source_scope: str
    required_components: tuple[str, ...]


_TEXT = r"[А-ЯЁа-яё0-9№-]+(?:[ А-ЯЁа-яё0-9№-]*[А-ЯЁа-яё0-9№-]+)?"
_EXCLUSION = re.compile(
    rf"(?P<subject>{_TEXT}) (?P<modal>должно|должна|должны|должен) исключать "
    rf"(?P<first>{_TEXT}), (?P<second>{_TEXT}), а также "
    rf"(?P<negative>они не должны|оно не должно|она не должна|он не должен) "
    rf"(?P<third>{_TEXT})\.",
    re.IGNORECASE,
)
_PROVISIONING = re.compile(
    rf"Все (?P<scope>{_TEXT}) "
    r"(?P<verb>оснащаются|оборудуются|снабжаются|обеспечиваются) "
    rf"(?P<instrument>{_TEXT}), в соответствии с которыми в случае "
    rf"(?P<condition>{_TEXT}) обеспечивается (?P<purpose>{_TEXT})\.",
    re.IGNORECASE,
)
_QUALIFIER = re.compile(
    r"\b(?:не|только|лишь|исключительно|кроме|если|при|после|до|пока|"
    r"при условии|за исключением|в зависимости от)\b",
    re.IGNORECASE,
)


def _clean_capture(value: str) -> bool:
    """Reject conditional/exception-bearing captures outside the explicit grammar."""
    return not _QUALIFIER.search(value)


def project_source_requirement(value: str) -> SourceRequirementContract | None:
    """Project one complete, exact sentence into a bounded requirement contract.

    Unrecognized, qualified, quoted, negated, or compound sentence forms fail
    closed. Captured components remain source spans rather than paraphrases.
    """
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if any(mark in value for mark in ('"', "'", "«", "»", ";", "!", "?", "\n", "\r")):
        return None

    exclusion = _EXCLUSION.fullmatch(value)
    if exclusion:
        subject = exclusion.group("subject")
        modal = exclusion.group("modal")
        first = exclusion.group("first")
        second = exclusion.group("second")
        negative = exclusion.group("negative")
        third = exclusion.group("third")
        if not all(_clean_capture(item) for item in (subject, first, second, third)):
            return None
        return SourceRequirementContract(
            kind="compound_exclusion_with_additional_negative",
            required_prompt=(
                f"Какие последствия нужно исключить и какое дополнительное "
                f"ограничение соблюдать для объекта «{subject}»?"
            ),
            source_scope=subject,
            required_components=(
                f"{modal} исключать {first}",
                second,
                f"{negative} {third}",
            ),
        )

    provisioning = _PROVISIONING.fullmatch(value)
    if provisioning:
        scope = provisioning.group("scope")
        instrument = provisioning.group("instrument")
        condition = provisioning.group("condition")
        purpose = provisioning.group("purpose")
        if not all(
            _clean_capture(item)
            for item in (scope, instrument, condition, purpose)
        ):
            return None
        return SourceRequirementContract(
            kind="all_scope_provisioning_with_purpose",
            required_prompt=(
                f"Каково полное правило для объектов «{scope}»: чем их "
                "обеспечивают, в каких случаях и с какой целью?"
            ),
            source_scope=f"Все {scope}",
            required_components=(
                f"{provisioning.group('verb')} {instrument}",
                f"в соответствии с которыми в случае {condition} обеспечивается {purpose}",
            ),
        )
    return None
