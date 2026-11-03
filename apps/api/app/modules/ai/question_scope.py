"""Negative-only source-grounded question-scope vetoes.

This module never proves an answer, changes a key, supplies a missing actor, or rewrites an
option.  A returned code can only cause the caller to withhold the question.
"""

from __future__ import annotations

import re

from app.modules.ai.assessment_preservation import source_predicate_supports_literal_negation
from app.modules.ai.atomic_polarity import is_literal_polarity_opposite
from app.modules.ai.source_literal import literal_source_span

_PURPOSE_RE = re.compile(
    r"^(?P<prefix>.+?\bдля)\s+(?P<complement>[^.;!?]+)(?P<terminal>[.;!?]?)$",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"(?<!\w)[А-Яа-яЁё]+(?!\w)")
_FREQUENCY_RE = re.compile(r"(?<!\w)(систематически|периодически)(?!\w)", re.IGNORECASE)
_COMPOUND_COORDINATOR_RE = re.compile(r",\s+а\s+также\s+", re.IGNORECASE)
_GENERIC_RULE_STEM_RE = re.compile(
    r"^какой\s+(?:из\s+)?вариант(?:ов)?(?:\s+полностью)?\s+соответствует\s+"
    r"(?:правилу|требованию|норме)\?$",
    re.IGNORECASE,
)
_EXPLICIT_EXCLUSIVITY_RE = re.compile(
    r"(?<!\w)(?:только|исключительно)(?!\w)",
    re.IGNORECASE,
)
_NEGATIVE_SCOPE_RE = re.compile(
    r"(?<!\w)(?:не\s+(?:долж\w*|обязан\w*|допуска\w*|разреша\w*)|"
    r"запрещ\w*|нельзя)(?!\w)",
    re.IGNORECASE,
)
_LEADING_MODAL_RE = re.compile(
    r"^(?:не\s+)?(?:должен|должна|должно|должны|обязан|обязана|обязано|обязаны|"
    r"может|могут|подлежит|подлежат)(?!\w)",
    re.IGNORECASE,
)
_MAX_OPTION_CHARS = 1_000
_MAX_SOURCE_CHARS = 65_536

_REPAIR_HINTS = {
    "modal_complement_contrast_unproved": (
        "An alternative merely changes an unregulated purpose/location under the same modality. "
        "Absence from the source is not contradiction. Keep the exact actor and condition; use only "
        "source-contradicted alternatives, or two options if no third contradiction is proved."
    ),
    "compatible_frequency_contrast_unproved": (
        "Systematic and periodic performance can coexist. Do not grade periodic performance false "
        "solely because the source says systematic. Test another source-owned decision or a genuinely "
        "contradicted state, preserving actor, action and scope."
    ),
    "singular_compound_prohibition_scope": (
        "A singular action stem leaves a prohibited action true in each mixed alternative. Ask for "
        "the COMPLETE rule formulation, or test one atomic source-owned action. Never mark a partly "
        "true prohibited-action bundle false under a singular-action stem."
    ),
    "missing_visible_modal_subject": (
        "The generic stem does not supply the modal options' subject. State the exact source-owned "
        "subject in the visible question or complete options. Use the ordinary author path if the "
        "fixed source-proposition constructor cannot carry it; do not invent an actor."
    ),
}


def scope_repair_hint(code: str) -> str:
    return _REPAIR_HINTS.get(code, "")


def starts_with_modal_predicate(value: str) -> bool:
    """Shape only: subject ownership still requires an independent contract."""
    return _LEADING_MODAL_RE.match(" ".join(value.casefold().split())) is not None


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _has_explicit_exclusivity(value: str) -> bool:
    return _EXPLICIT_EXCLUSIVITY_RE.search(value) is not None


def _has_negative_scope(value: str) -> bool:
    return _NEGATIVE_SCOPE_RE.search(value) is not None


def _owned_source(key_option: str, source_quotes: tuple[str, ...]) -> str | None:
    """Return literal custody only when the occurrence keeps its visible polarity."""
    for quote in source_quotes:
        literal = literal_source_span(key_option, quote)
        if literal is None:
            continue
        for match in re.finditer(re.escape(literal), quote, re.IGNORECASE):
            preceding = quote[:match.start()].rstrip()
            preceded_by_negation = re.search(r"(?<!\w)не$", preceding, re.IGNORECASE) is not None
            key_starts_negative = re.match(r"^не(?!\w)", key_option.strip(), re.IGNORECASE) is not None
            if not preceded_by_negation or key_starts_negative:
                return quote
    return None


def _source_mentions(option: str, source_quotes: tuple[str, ...]) -> bool:
    return any(literal_source_span(option, quote) is not None for quote in source_quotes)


def _unproved_purpose_contrast(
    key_option: str,
    alternatives: tuple[str, ...],
    source_quotes: tuple[str, ...],
) -> bool:
    key_match = _PURPOSE_RE.fullmatch(_fold(key_option))
    if (
        key_match is None
        or not _has_negative_scope(key_match.group("prefix"))
        or _has_explicit_exclusivity(key_option)
        or not 1 <= len(_WORD_RE.findall(key_match.group("complement"))) <= 4
    ):
        return False
    for alternative in alternatives:
        match = _PURPOSE_RE.fullmatch(_fold(alternative))
        if (
            match is not None
            and match.group("prefix") == key_match.group("prefix")
            and match.group("terminal") == key_match.group("terminal")
            and match.group("complement") != key_match.group("complement")
            and 1 <= len(_WORD_RE.findall(match.group("complement"))) <= 4
            and not _source_mentions(alternative, source_quotes)
        ):
            return True
    return False


def _unproved_location_contrast(
    key_option: str,
    alternatives: tuple[str, ...],
    source_quotes: tuple[str, ...],
) -> bool:
    def split(value: str) -> tuple[str, str, str] | None:
        folded = _fold(value)
        for relation in ("вплотную к", "вдали от"):
            marker = f" {relation} "
            if folded.count(marker) == 1:
                prefix, object_ = folded.split(marker)
                return prefix, relation, object_
        return None

    def object_signature_matches(left: tuple[str, str, str], right: tuple[str, str, str]) -> bool:
        by_relation = {left[1]: left[2].split(), right[1]: right[2].split()}
        dative_words, genitive_words = by_relation["вплотную к"], by_relation["вдали от"]
        if not dative_words or len(dative_words) != len(genitive_words):
            return False

        def same_lexeme(dative: str, genitive: str) -> bool:
            dative_core = dative.rstrip(".,;:!?")
            genitive_core = genitive.rstrip(".,;:!?")
            if dative_core == genitive_core:
                return True
            suffix_pairs = (
                (("ам", "ям"), ("ов", "ев", "ей")),
                (("ым",), ("ых",)),
                (("им",), ("их",)),
            )
            return any(
                len(dative_core) - len(dative_suffix) >= 4
                and dative_core.removesuffix(dative_suffix) == genitive_core.removesuffix(genitive_suffix)
                for dative_suffixes, genitive_suffixes in suffix_pairs
                for dative_suffix in dative_suffixes
                for genitive_suffix in genitive_suffixes
                if dative_core.endswith(dative_suffix) and genitive_core.endswith(genitive_suffix)
            )

        return all(same_lexeme(dative, genitive)
                   for dative, genitive in zip(dative_words, genitive_words, strict=True))

    key_parts = split(key_option)
    if (
        key_parts is None
        or not _has_negative_scope(key_parts[0])
        or _has_explicit_exclusivity(key_option)
    ):
        return False
    for alternative in alternatives:
        parts = split(alternative)
        if (
            parts is not None
            and parts[0] == key_parts[0]
            and {parts[1], key_parts[1]} == {"вплотную к", "вдали от"}
            and object_signature_matches(key_parts, parts)
            and not _source_mentions(alternative, source_quotes)
        ):
            return True
    return False


def _compatible_frequency_contrast(
    key_option: str,
    alternatives: tuple[str, ...],
    source_quotes: tuple[str, ...],
) -> bool:
    def signature(value: str) -> tuple[str, str] | None:
        folded = _fold(value)
        matches = list(_FREQUENCY_RE.finditer(folded))
        if len(matches) != 1:
            return None
        match = matches[0]
        return match.group(1), folded[:match.start()] + "<frequency>" + folded[match.end():]

    key_signature = signature(key_option)
    if key_signature is None:
        return False
    other_frequency = ({"систематически", "периодически"} - {key_signature[0]}).pop()
    # Only the exact owned option supplies exclusivity for this closed contrast.
    # Neither another source row nor a coordinated clause in the same sentence
    # can classify this alternative. Neutral here still grants no approval.
    if _has_explicit_exclusivity(key_option):
        return False
    for alternative in alternatives:
        alternative_signature = signature(alternative)
        if (
            alternative_signature is not None
            and alternative_signature[0] == other_frequency
            and alternative_signature[1] == key_signature[1]
            and not _source_mentions(alternative, source_quotes)
        ):
            return True
    return False


def _singular_compound_prohibition_issue(
    stem: str,
    key_option: str,
    alternatives: tuple[str, ...],
    *,
    prohibition_scope: bool,
) -> bool:
    if (
        not prohibition_scope
        or re.search(r"(?<!\w)какое\s+действие(?!\w)", stem, re.IGNORECASE) is None
    ):
        return False
    coordinators = list(_COMPOUND_COORDINATOR_RE.finditer(key_option))
    if len(coordinators) != 1:
        return False
    coordinator = coordinators[0]
    left, right = key_option[:coordinator.start()], key_option[coordinator.end():]

    def atomic_opposite(base: str, candidate: str) -> bool:
        for word in _WORD_RE.finditer(base):
            if not source_predicate_supports_literal_negation(
                word.group(), allow_short_participle=True
            ):
                continue
            prefix = base[:word.start()]
            negative = re.search(r"(?<!\w)не\s+$", prefix, re.IGNORECASE)
            focus = base[negative.start():word.end()] if negative is not None else word.group()
            if is_literal_polarity_opposite(base, focus, candidate):
                return True
        return False

    for alternative in alternatives:
        alternative_coordinators = list(_COMPOUND_COORDINATOR_RE.finditer(alternative))
        if len(alternative_coordinators) != 1:
            continue
        alternative_coordinator = alternative_coordinators[0]
        alternative_left = alternative[:alternative_coordinator.start()]
        alternative_right = alternative[alternative_coordinator.end():]
        if (
            atomic_opposite(left, alternative_left) and alternative_right == right
        ) or (
            alternative_left == left and atomic_opposite(right, alternative_right)
        ):
            return True
    return False


def _missing_visible_modal_subject(
    stem: str,
    options: tuple[str, ...],
    *,
    visible_subject_proven: bool,
) -> bool:
    """Recognize only the visible fragment shape; never recover an actor."""
    visible_lines = [line.strip() for line in stem.splitlines() if line.strip()]
    question = visible_lines[-1] if visible_lines else ""
    return (
        _GENERIC_RULE_STEM_RE.fullmatch(_fold(question)) is not None
        and all(_LEADING_MODAL_RE.match(_fold(option)) is not None for option in options)
        and not visible_subject_proven
    )


def question_scope_issue(
    stem: str,
    options: tuple[str, ...],
    key: int,
    source_quotes: tuple[str, ...],
    *,
    prohibition_scope: bool = False,
    visible_subject_proven: bool = False,
) -> str | None:
    """Return one finite withholding reason; never determine semantic truth."""
    if (
        not isinstance(options, tuple)
        or not 2 <= len(options) <= 8
        or type(key) is not int
        or not 0 <= key < len(options)
        or any(not isinstance(option, str) or not option.strip() or len(option) > _MAX_OPTION_CHARS for option in options)
        or not isinstance(source_quotes, tuple)
        or not source_quotes
        or any(not isinstance(quote, str) or not quote or len(quote) > _MAX_SOURCE_CHARS for quote in source_quotes)
    ):
        return None
    key_option = options[key]
    owned_source = _owned_source(key_option, source_quotes)
    if owned_source is None:
        return None
    alternatives = tuple(option for index, option in enumerate(options) if index != key)
    if _missing_visible_modal_subject(stem, options, visible_subject_proven=visible_subject_proven):
        return "missing_visible_modal_subject"
    if _singular_compound_prohibition_issue(
        stem, key_option, alternatives, prohibition_scope=prohibition_scope
    ):
        return "singular_compound_prohibition_scope"
    if _compatible_frequency_contrast(key_option, alternatives, source_quotes):
        return "compatible_frequency_contrast_unproved"
    if _unproved_purpose_contrast(key_option, alternatives, source_quotes) or _unproved_location_contrast(
        key_option, alternatives, source_quotes
    ):
        return "modal_complement_contrast_unproved"
    return None
