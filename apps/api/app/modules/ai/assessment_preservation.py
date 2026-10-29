"""Necessary lexical-preservation checks for mapped assessment components.

The check is deliberately narrower than semantic entailment.  It verifies that
material source tokens survive in the mapped candidate composition, using the
official Russian morphology dictionary for inflection only.

Exact Russian cardinal aliases use fixed standard lexemes and arithmetic groups
from zero through 999,999,999; ordinals, decimals, and larger scales are not
normalized.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import NotRequired, Protocol, TypedDict, cast

from app.modules.ai.assessment_facets import BRANCH_EFFECTS
from app.modules.ai.source_layout import (
    SOURCE_HORIZONTAL_SPACE,
    SourceMarker,
    parse_source_marker,
)

MAX_TEXT_CHARS = 2_000
MAX_SOURCE_CONTEXT_CHARS = 65_536
MAX_TOKENS = 256
MAX_CONTEXT_TOKENS = 32_768
MAX_TOKEN_CHARS = 128
MAX_NOMINAL_CATEGORY_CHARS = 64
MAX_NOMINAL_CATEGORY_TOKENS = 8
MAX_CONDITIONAL_TAIL_CHARS = 160
MAX_CONDITIONAL_TAIL_TOKENS = 24
MAX_SOURCE_EDIT_FRAGMENT_CHARS = 240
MAX_SOURCE_EDIT_FRAGMENT_TOKENS = 4

_TOKEN_RE = re.compile(
    r">=|<=|!=|>|<|=|[≥≤≠]|"
    r"[A-Za-z\u0400-\u04ff]+(?:-[A-Za-z\u0400-\u04ff]+)*|"
    r"\d+(?:[.,]\d+)?|[+\-−%‰°²³/:]"
)
_RUSSIAN_RE = re.compile(r"^[а-яё]+$", re.IGNORECASE)
_ACRONYM_RE = re.compile(r"^[A-ZА-ЯЁ]{2,10}$")
_DEFINITION_RE = re.compile(
    r"(?P<expansion>[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*(?:\s+[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*){0,7})"
    r"\s*\((?P<acronym>[А-ЯЁ]{2,10})\)"
)
_OPERATOR_IDENTITIES = {"≥": ">=", "≤": "<=", "≠": "!=", "−": "-"}
_NUMERIC_OPERATORS = frozenset(
    {">=", "<=", "!=", ">", "<", "=", "+", "-", "−", "≥", "≤", "≠"}
)
_UNIT_SYMBOLS = frozenset({"%", "‰", "°", "²", "³", "/", ":"})
_HORIZONTAL_SPACE_CHARS = frozenset(SOURCE_HORIZONTAL_SPACE)
_ENVELOPE_GAP_CHARS = _HORIZONTAL_SPACE_CHARS | frozenset("\"'«»„“”()[]{}")
_PROTECTED_LITERALS = frozenset(
    {
        "не",
        "ни",
        "без",
        "кроме",
        "только",
        "если",
        "либо",
        "или",
        "до",
        "от",
        "более",
        "менее",
        "свыше",
        "после",
        "перед",
        "вне",
        "внутри",
        "нет",
        "нельзя",
        "невозможно",
        "никто",
        "ничто",
        "никогда",
        "никакой",
    }
)
_PROTECTED_LEMMAS = frozenset(
    {
        "весь",
        "каждый",
        "любой",
        "оба",
        "условие",
        "нет",
        "нельзя",
        "невозможно",
        "никто",
        "ничто",
        "никогда",
        "никакой",
    }
)
_IGNORED_POS = frozenset({"PREP", "CONJ", "PRCL", "NPRO", "INTJ"})
_NOMINAL_CATEGORY_POS = frozenset(
    {"NOUN", "ADJF", "PRTF", "NUMR", "PREP", "CONJ", "PRCL"}
)
_NOMINAL_CONTRAST_POS = frozenset({"NOUN", "ADJF", "PRTF"})
_NOMINAL_CONTRAST_TAIL_POS = _NOMINAL_CONTRAST_POS | {"CONJ"}
_OPERATIONAL_PREDICATE_POS = frozenset({"INFN", "VERB", "PRTS"})
_NOMINAL_CONTRAST_CONDITION_MARKERS = frozenset(
    {"если", "когда", "при", "до", "после", "перед"}
)
_NOMINAL_CONTRAST_HARD_BOUNDARY_RE = re.compile(
    r"[.;!?\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029]"
)
_CARDINAL_UNITS = {
    "ноль": 0,
    "один": 1,
    "два": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
}
_CARDINAL_TEENS = {
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
}
_CARDINAL_TENS = {
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
}
_CARDINAL_HUNDREDS = {
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
}
_CARDINAL_SCALES = {"тысяча": 1_000, "миллион": 1_000_000}
_CARDINAL_LEXEMES = frozenset(
    _CARDINAL_UNITS
    | _CARDINAL_TEENS
    | _CARDINAL_TENS
    | _CARDINAL_HUNDREDS
    | _CARDINAL_SCALES
)
MAX_CARDINAL_TOKENS = 11
MAX_CARDINAL_VALUE = 999_999_999


class PreservationIssue(TypedDict):
    """A source-free failure safe to expose to a repair loop."""

    code: str
    token_type: str
    token_index: NotRequired[int]


class _MorphTag(Protocol):
    POS: str | None
    mood: str | None
    number: str | None
    grammemes: frozenset[str]


class _MorphParse(Protocol):
    normal_form: str
    tag: _MorphTag


class _MorphAnalyzer(Protocol):
    def parse(self, word: str) -> Sequence[_MorphParse]: ...

    def word_is_known(self, word: str) -> bool: ...


@dataclass(frozen=True)
class _WordInfo:
    known: bool
    lemmas: frozenset[str]
    pos: str | None
    parts_of_speech: frozenset[str]
    noun_lemmas: frozenset[str]


@dataclass(frozen=True)
class _Token:
    text: str
    index: int
    alias: int | None = None
    start: int = 0
    end: int = 0


@dataclass(frozen=True)
class NominalSpellingReceipt:
    """Necessary surface alignment, never a source correction or truth vote."""

    source_token: str
    dictionary_token: str
    start: int
    end: int
    component_sha256: str
    candidate_sha256: str
    source_sha256: str
    policy: str = "unique-nominal-substitution-v1"
    not_semantic_approval: bool = True


@dataclass(frozen=True)
class InstructionSurfaceReceipt:
    """Exact surface links for a required gerund and coordinated verb ellipsis."""

    component_sha256: str
    candidate_sha256: str
    source_sha256: str
    modal_gerund_pairs: tuple[tuple[int, int, int], ...]
    repeated_predicate_pairs: tuple[tuple[int, int], ...]
    policy: str = "positive-instruction-composition-v1"
    not_semantic_approval: bool = True


@dataclass(frozen=True)
class SourceGrammarRealizationReceipt:
    """Source-bound grammatical surface evidence with zero semantic credit."""

    family: str
    source_form: str
    candidate_form: str
    component_span: tuple[int, int]
    governor_span: tuple[int, int]
    source_id: str
    component_sha256: str
    comparison_component_sha256: str
    candidate_sha256: str
    source_sha256: str
    governing_bindings_sha256: str
    policy: str = "source-grammar-realization-v1"
    not_semantic_approval: bool = True


@dataclass(frozen=True)
class SourceGrammarComparisonView:
    """A receipt-validated comparison view; originals remain authoritative."""

    family: str
    comparison_component: str
    candidate: str
    actual_component_sha256: str
    comparison_component_sha256: str
    candidate_sha256: str
    source_sha256: str
    not_semantic_approval: bool = True


def _issue(code: str, token_type: str, token_index: int | None = None) -> PreservationIssue:
    issue: PreservationIssue = {"code": code, "token_type": token_type}
    if token_index is not None:
        issue["token_index"] = token_index
    return issue


@lru_cache(maxsize=1)
def _morph() -> _MorphAnalyzer:
    import pymorphy3  # type: ignore[import-untyped]

    return cast(_MorphAnalyzer, pymorphy3.MorphAnalyzer())


@lru_cache(maxsize=4_096)
def _word_info(word: str) -> _WordInfo:
    normalized = word.casefold()
    parses = _morph().parse(normalized)
    known = _morph().word_is_known(normalized)
    lemmas = frozenset(parse.normal_form for parse in parses) if known else frozenset()
    pos = parses[0].tag.POS if parses else None
    parts_of_speech = frozenset(
        parse.tag.POS for parse in parses if known and parse.tag.POS is not None
    )
    noun_lemmas = frozenset(
        parse.normal_form for parse in parses if known and parse.tag.POS == "NOUN"
    )
    return _WordInfo(
        known=known,
        lemmas=lemmas,
        pos=pos,
        parts_of_speech=parts_of_speech,
        noun_lemmas=noun_lemmas,
    )


_SOURCE_RULE_GOVERNMENT_MAX_CHARS = 240
_SOURCE_RULE_INVALID_GOVERNMENT_INPUT = "source_rule_invalid_government_input"
_SOURCE_RULE_UNPROVED_GOVERNMENT = "source_rule_unproved_government"
_SOURCE_RULE_LINE_BREAKS = frozenset("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_PRESENT_DUTY_MODALS = frozenset(
    {
        "должен",
        "должна",
        "должно",
        "должны",
        "обязан",
        "обязана",
        "обязано",
        "обязаны",
        "необходимо",
        "нужно",
        "следует",
        "требуется",
    }
)
_SOURCE_QUOTE_CHARS = frozenset("\"'«»‹›„“”‘’‚‛‟")


def _normalized_horizontal_space(value: str) -> str:
    pieces: list[str] = []
    in_space = False
    for character in value:
        if character in _HORIZONTAL_SPACE_CHARS:
            if not in_space:
                pieces.append(" ")
            in_space = True
        else:
            pieces.append(character)
            in_space = False
    return "".join(pieces)


def _source_verb_governor_span(base: object, focus: object) -> tuple[int, int] | None:
    """Find only the existing bounded dictionary-proved INFN+PREP shape."""
    values = (base, focus)
    if any(not isinstance(value, str) for value in values):
        return None
    base_text = cast(str, base)
    focus_text = cast(str, focus)
    if any(
        not value
        or value != value.strip()
        or len(value) > _SOURCE_RULE_GOVERNMENT_MAX_CHARS
        or any(character in _SOURCE_RULE_LINE_BREAKS for character in value)
        for value in (base_text, focus_text)
    ):
        return None
    if not _RUSSIAN_RE.fullmatch(focus_text):
        return None

    focus_pattern = re.compile(rf"(?<!\w){re.escape(focus_text)}(?!\w)")
    focus_matches = list(focus_pattern.finditer(base_text))
    if len(focus_matches) != 1:
        return None
    focus_match = focus_matches[0]

    try:
        focus_info = _word_info(focus_text.casefold())
        if not focus_info.known or focus_info.parts_of_speech != {"INFN"}:
            return None

        prep_start = focus_match.end()
        while (
            prep_start < len(base_text)
            and base_text[prep_start] in _HORIZONTAL_SPACE_CHARS
        ):
            prep_start += 1
        if prep_start == focus_match.end():
            return None

        prep_match = _TOKEN_RE.match(base_text, prep_start)
        if prep_match is None:
            return None
        prep_text = prep_match.group()
        prep_info = _word_info(prep_text.casefold())
        if not prep_info.known or prep_info.parts_of_speech != {"PREP"}:
            return None
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
    return focus_match.span()


def source_verb_government_edit_focus(base: object, verb_focus: object) -> str | None:
    """Return one source-leading dictionary-proved INFN PREP NOUN phrase.

    This is only an edit-slot shape. It does not prove that any replacement is
    grammatical, contradictory, educational, or otherwise acceptable.
    """
    span = _source_verb_governor_span(base, verb_focus)
    if span is None or span[0] != 0:
        return None
    base_text = cast(str, base)
    verb_text = cast(str, verb_focus)
    verb_match = _TOKEN_RE.match(base_text)
    if verb_match is None or verb_match.group() != verb_text:
        return None

    prep_start = verb_match.end()
    while prep_start < len(base_text) and base_text[prep_start] in _HORIZONTAL_SPACE_CHARS:
        prep_start += 1
    prep_match = _TOKEN_RE.match(base_text, prep_start)
    if prep_match is None:
        return None
    noun_start = prep_match.end()
    while noun_start < len(base_text) and base_text[noun_start] in _HORIZONTAL_SPACE_CHARS:
        noun_start += 1
    if noun_start == prep_match.end():
        return None
    noun_match = _TOKEN_RE.match(base_text, noun_start)
    if noun_match is None or _RUSSIAN_RE.fullmatch(noun_match.group()) is None:
        return None

    try:
        noun_info = _word_info(noun_match.group().casefold())
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
    if (
        not noun_info.known
        or noun_info.parts_of_speech != {"NOUN"}
        or len(noun_info.noun_lemmas) != 1
    ):
        return None

    phrase = base_text[: noun_match.end()]
    phrase_matches = list(
        re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", base_text)
    )
    return phrase if len(phrase_matches) == 1 else None


def source_verb_government_bound(base: object, focus: object) -> bool:
    """Source-derived author constraint, never a grammar/truth acceptance."""
    return _source_verb_governor_span(base, focus) is not None


def source_verb_government_issue(base: object, focus: object, alternative: object) -> str | None:
    """Return a source-free veto when a bounded edit drops a known verb governor."""
    if any(not isinstance(value, str) for value in (base, focus, alternative)):
        return _SOURCE_RULE_INVALID_GOVERNMENT_INPUT
    base_text, focus_text, alternative_text = cast(str, base), cast(str, focus), cast(str, alternative)
    if any(not value or value != value.strip() or len(value) > _SOURCE_RULE_GOVERNMENT_MAX_CHARS
           or any(character in _SOURCE_RULE_LINE_BREAKS for character in value)
           for value in (base_text, focus_text, alternative_text)):
        return _SOURCE_RULE_INVALID_GOVERNMENT_INPUT
    span = _source_verb_governor_span(base_text, focus_text)
    if span is None:
        return None
    prefix = base_text[:span[0]]
    suffix = base_text[span[1]:]
    if not alternative_text.startswith(prefix) or not alternative_text.endswith(suffix):
        return _SOURCE_RULE_INVALID_GOVERNMENT_INPUT
    if len(alternative_text) < len(prefix) + len(suffix):
        return _SOURCE_RULE_INVALID_GOVERNMENT_INPUT

    slot_end = len(alternative_text) - len(suffix) if suffix else len(alternative_text)
    slot = alternative_text[len(prefix) : slot_end]
    normalized_slot = _normalized_horizontal_space(slot).casefold()
    normalized_focus = focus_text.casefold()
    if normalized_slot in {normalized_focus, f"не {normalized_focus}"}:
        return None
    return _SOURCE_RULE_UNPROVED_GOVERNMENT


def source_predicate_supports_literal_negation(word: object, *, allow_short_participle: bool = False) -> bool:
    """Bounded syntactic eligibility only; never an option truth/grammar verdict."""
    if not isinstance(word, str) or not 1 <= len(word) <= 128 or not _RUSSIAN_RE.fullmatch(word):
        return False
    normalized = word.casefold()
    if normalized in {"должен", "должна", "должно", "должны", "обязан", "обязана", "обязано", "обязаны",
                      "необходимо", "нужно", "следует", "требуется"}:
        return True
    try:
        info = _word_info(normalized)
        return info.known and bool(info.parts_of_speech) and (
            info.parts_of_speech <= {"INFN", "VERB"}
            or (allow_short_participle and info.parts_of_speech <= {"PRTS"})
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def source_contains_unambiguous_positive_prescriptive_action(text: object) -> bool:
    """Detect one narrow source duty shape as a negative-only coverage signal.

    Any quote mark or standalone negation excludes the whole fact because this
    helper does not resolve quotation or negation scope.
    """
    if not isinstance(text, str) or not text or len(text) > MAX_TEXT_CHARS:
        return False
    if any(character in _SOURCE_QUOTE_CHARS for character in text):
        return False
    tokens = _tokenize(text)
    if not tokens:
        return False
    if any(token.text.casefold() == "не" for token in tokens):
        return False

    try:
        for index, modal in enumerate(tokens[:-1]):
            if modal.text.casefold() not in _PRESENT_DUTY_MODALS:
                continue
            if index:
                previous = tokens[index - 1]
                previous_gap = text[previous.end : modal.start]
                if previous_gap and all(
                    character in _HORIZONTAL_SPACE_CHARS
                    for character in previous_gap
                ):
                    previous_info = _word_info(previous.text.casefold())
                    if (
                        previous_info.known
                        and "быть" in previous_info.lemmas
                        and previous_info.parts_of_speech & {"INFN", "VERB"}
                    ):
                        continue
            action = tokens[index + 1]
            if not text[modal.end : action.start] or any(
                character not in _HORIZONTAL_SPACE_CHARS
                for character in text[modal.end : action.start]
            ):
                continue
            action_info = _word_info(action.text.casefold())
            if not action_info.known or action_info.parts_of_speech != {"INFN"}:
                continue
            if action.text.casefold() != "быть":
                return True
            if index + 2 >= len(tokens):
                continue
            predicate = tokens[index + 2]
            if not text[action.end : predicate.start] or any(
                character not in _HORIZONTAL_SPACE_CHARS
                for character in text[action.end : predicate.start]
            ):
                continue
            predicate_info = _word_info(predicate.text.casefold())
            if predicate_info.known and predicate_info.parts_of_speech == {"PRTS"}:
                return True
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return False


def source_edit_noun_signature(fragment: object) -> tuple[str, ...] | None:
    """Return bounded noun identities for one edited fragment, or fail closed."""
    if not isinstance(fragment, str):
        return None
    if (
        not fragment
        or fragment != fragment.strip()
        or len(fragment) > MAX_SOURCE_EDIT_FRAGMENT_CHARS
        or any(character in "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029" for character in fragment)
    ):
        return None
    if not 1 <= len(fragment.split()) <= MAX_SOURCE_EDIT_FRAGMENT_TOKENS:
        return None
    tokens = _tokenize(fragment)
    if not tokens:
        return None

    signature: list[str] = []
    try:
        for token in tokens:
            if token.text[0].isdigit() or token.text in _NUMERIC_OPERATORS | _UNIT_SYMBOLS:
                continue
            info = _word_info(token.text.casefold())
            if not info.known:
                signature.append(f"literal:{token.text.casefold()}")
                continue
            if not info.parts_of_speech:
                return None
            if info.pos in _IGNORED_POS:
                continue
            if info.noun_lemmas:
                if info.parts_of_speech != {"NOUN"} or len(info.noun_lemmas) != 1:
                    return None
                signature.append(f"noun:{next(iter(info.noun_lemmas))}")
        return tuple(signature)
    except (ImportError, OSError, RuntimeError, ValueError):
        return None


def is_bounded_nominal_category(category: object) -> bool:
    """Return whether a short phrase is affirmatively dictionary-backed nominal syntax."""
    if not isinstance(category, str):
        return False
    value = category.strip()
    if not value or len(value) > MAX_NOMINAL_CATEGORY_CHARS:
        return False
    matches = list(_TOKEN_RE.finditer(value))
    if not 1 <= len(matches) <= MAX_NOMINAL_CATEGORY_TOKENS:
        return False
    cursor = 0
    has_noun_head = False
    analyzer = _morph()
    for match in matches:
        if not value[cursor:match.start()].isspace() and match.start() != cursor:
            return False
        token = match.group()
        cursor = match.end()
        if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            continue
        if not re.fullmatch(r"[A-Za-z\u0400-\u04ff]+(?:-[A-Za-z\u0400-\u04ff]+)*", token):
            return False
        normalized = token.casefold()
        if not analyzer.word_is_known(normalized):
            return False
        parses = analyzer.parse(normalized)
        parts_of_speech = {parse.tag.POS for parse in parses}
        if not parts_of_speech or not parts_of_speech <= _NOMINAL_CATEGORY_POS:
            return False
        has_noun_head = has_noun_head or "NOUN" in parts_of_speech
    if cursor != len(value):
        return False
    return has_noun_head


def starts_with_known_infinitive_clause(value: str) -> bool:
    """Recognize a bounded RU action opening, not meaning, ownership or truth."""
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TEXT_CHARS:
        return False
    match = re.match(r"^(?:и\s+)?(?:не\s+)?([А-Яа-яЁё]{2,64})\b", value.strip(), re.IGNORECASE)
    if match is None:
        return False
    try:
        info = _word_info(match[1].casefold())
        return info.known and info.parts_of_speech == {"INFN"}
    except (ImportError, RuntimeError, ValueError):
        return False


def _unique_owned_token_start(
    owned_tokens: list[_Token],
    source_tokens: list[_Token],
    source_clause: str,
) -> int | None:
    starts = [
        start
        for start in range(len(source_tokens) - len(owned_tokens) + 1)
        if not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(
            source_clause[
                source_tokens[start].start :
                source_tokens[start + len(owned_tokens) - 1].end
            ]
        )
        and all(
            _morphological_match(source_tokens[start + offset], token)
            for offset, token in enumerate(owned_tokens)
        )
    ]
    return starts[0] if len(starts) == 1 else None


def _universal_nominal_relocation_unproved(
    supported_tokens: list[_Token],
    alternative_tokens: list[_Token],
    source_tokens: list[_Token],
    source_clause: str,
) -> bool:
    """Recognize one literal nominal phrase broadened with explicit ``любой``."""

    source_start = _unique_owned_token_start(
        supported_tokens,
        source_tokens,
        source_clause,
    )
    if source_start != 0 or len(source_tokens) != len(supported_tokens):
        return False

    universal_spans: list[tuple[int, int, frozenset[str]]] = []
    for index, token in enumerate(alternative_tokens):
        info = _word_info(token.text.casefold())
        if "любой" not in info.lemmas or index == 0 or index + 1 >= len(
            alternative_tokens
        ):
            continue
        preposition = _word_info(alternative_tokens[index - 1].text.casefold())
        noun = _word_info(alternative_tokens[index + 1].text.casefold())
        if preposition.pos == "PREP" and (
            noun.parts_of_speech == {"NOUN"} and len(noun.noun_lemmas) == 1
        ):
            universal_spans.append((index - 1, index + 2, noun.noun_lemmas))
    if len(universal_spans) != 1:
        return False
    alternative_start, alternative_end, noun_lemmas = universal_spans[0]

    source_spans: list[tuple[int, int]] = []
    for noun_index, token in enumerate(supported_tokens):
        noun = _word_info(token.text.casefold())
        if noun.noun_lemmas != noun_lemmas or noun_index < 2:
            continue
        preposition = _word_info(supported_tokens[noun_index - 2].text.casefold())
        modifier = _word_info(supported_tokens[noun_index - 1].text.casefold())
        if (
            preposition.pos == "PREP"
            and bool(modifier.parts_of_speech)
            and modifier.parts_of_speech <= {"ADJF", "PRTF"}
            and "любой" not in modifier.lemmas
        ):
            source_spans.append((noun_index - 2, noun_index + 1))
    if len(source_spans) != 1:
        return False
    supported_start, supported_end = source_spans[0]
    if (
        supported_start > 0
        and supported_tokens[supported_start - 1].text.casefold() == "только"
    ):
        return False

    def material_tokens(
        tokens: list[_Token],
        removed_start: int,
        removed_end: int,
    ) -> list[_Token]:
        return [
            token
            for index, token in enumerate(tokens)
            if not removed_start <= index < removed_end
            and token.text.casefold() != "и"
        ]

    supported_material = material_tokens(
        supported_tokens,
        supported_start,
        supported_end,
    )
    alternative_material = material_tokens(
        alternative_tokens,
        alternative_start,
        alternative_end,
    )
    if len(supported_material) != len(alternative_material) or not all(
        _morphological_match(source, replacement)
        for source, replacement in zip(
            supported_material,
            alternative_material,
            strict=True,
        )
    ):
        return False
    return any(
        token.text.casefold() not in _PRESENT_DUTY_MODALS
        and bool(
            _word_info(token.text.casefold()).parts_of_speech
            & _OPERATIONAL_PREDICATE_POS
        )
        for token in supported_material
    )


def _whole_clause_relational_nominal_contrast_unproved(
    supported: str,
    alternative: str,
    source_clause: str,
    supported_tokens: list[_Token],
    alternative_tokens: list[_Token],
) -> bool | None:
    """Recognize one exact-owned operational prefix plus relational role tails."""

    if len(supported_tokens) == len(alternative_tokens) and all(
        _morphological_match(left, right)
        for left, right in zip(supported_tokens, alternative_tokens, strict=True)
    ):
        return False  # No category change; language/truth still need their own proof.
    if any(
        _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(value)
        for value in (supported, alternative)
    ):
        return None
    if any(any(character not in _HORIZONTAL_SPACE_CHARS
               for character in value[tokens[-1].end:])
           for value, tokens in ((supported, supported_tokens), (alternative, alternative_tokens))):
        return None  # A dangling colon/bracket is not a complete governed role clause.
    occurrences = list(re.finditer(re.escape(supported), source_clause))
    if len(occurrences) != 1:
        return None
    occurrence = occurrences[0]
    prior_boundaries = list(
        _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.finditer(
            source_clause[: occurrence.start()]
        )
    )
    owner_prefix = source_clause[
        prior_boundaries[-1].end() if prior_boundaries else 0 : occurrence.start()
    ]
    if any(
        character not in _HORIZONTAL_SPACE_CHARS
        and character not in ",•-—–()0123456789"
        for character in owner_prefix
    ):
        return None
    owner_suffix = source_clause[occurrence.end() :]
    suffix_nonspace = next(
        (character for character in owner_suffix if character not in _HORIZONTAL_SPACE_CHARS),
        "",
    )
    if suffix_nonspace and not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.match(
        suffix_nonspace
    ):
        return None
    common = 0
    while (
        common < len(supported_tokens)
        and common < len(alternative_tokens)
        and supported_tokens[common].text == alternative_tokens[common].text
    ):
        common += 1
    split_candidates: list[int] = []
    for index in range(common):
        if _word_info(supported_tokens[index].text.casefold()).pos != "PREP":
            continue
        predicates = [
            token
            for token in supported_tokens[:index]
            if token.text.casefold() not in _PRESENT_DUTY_MODALS
            and bool(
                _word_info(token.text.casefold()).parts_of_speech
                & _OPERATIONAL_PREDICATE_POS
            )
        ]
        if len(predicates) != 1:
            continue
        source_tail_start = supported_tokens[index + 1].start if index + 1 < len(
            supported_tokens
        ) else len(supported)
        alternative_tail_start = alternative_tokens[index + 1].start if index + 1 < len(
            alternative_tokens
        ) else len(alternative)
        if supported[:source_tail_start] == alternative[:alternative_tail_start]:
            split_candidates.append(index + 1)
    if not split_candidates:
        return None
    split = split_candidates[0]
    source_tail = supported_tokens[split:]
    alternative_tail = alternative_tokens[split:]
    if not source_tail or not alternative_tail:
        return None

    if split >= 2 and supported_tokens[split - 2].text.casefold() == "только":
        return False
    source_tail_words = [token.text.casefold() for token in source_tail]
    exception_indexes = [
        index
        for index, token in enumerate(source_tail_words)
        if token == "кроме"
        or (
            token == "за"
            and index + 1 < len(source_tail_words)
            and source_tail_words[index + 1] == "исключением"
        )
    ]
    if exception_indexes and any(
        "весь" in _word_info(token.text.casefold()).lemmas
        for token in source_tail[: exception_indexes[0]]
    ):
        return False

    if len(source_tail) == len(alternative_tail):
        differences = [
            (source.text.casefold(), replacement.text.casefold())
            for source, replacement in zip(source_tail, alternative_tail, strict=True)
            if source.text.casefold() != replacement.text.casefold()
        ]
        if len(differences) == 1:
            left, right = differences[0]
            if (left.startswith("не") and left[2:] == right) or (
                right.startswith("не") and right[2:] == left
            ):
                return False

    def relational_tail(tokens: list[_Token], value: str) -> tuple[bool, bool] | None:
        if (
            len(tokens) > MAX_CONDITIONAL_TAIL_TOKENS
            or tokens[-1].end - tokens[0].start > MAX_CONDITIONAL_TAIL_CHARS
        ):
            return None
        material = value[tokens[0].start : tokens[-1].end]
        cursor = tokens[0].start
        noun_seen = False
        relation_seen = False
        for token in tokens:
            if any(
                character not in _HORIZONTAL_SPACE_CHARS and character != ","
                for character in value[cursor:token.start]
            ):
                return None
            normalized = token.text.casefold()
            info = _word_info(normalized)
            if (
                normalized in _PROTECTED_LITERALS
                or normalized in {"или", "либо"}
                or normalized in _NOMINAL_CONTRAST_CONDITION_MARKERS
                or bool(info.lemmas & _PROTECTED_LEMMAS)
                or not info.known
                or not info.parts_of_speech
                or not info.parts_of_speech
                <= {"NOUN", "ADJF", "PRTF", "PREP", "CONJ"}
            ):
                return None
            noun_seen = noun_seen or info.parts_of_speech == {"NOUN"}
            relation_seen = relation_seen or bool(
                info.parts_of_speech & {"PRTF", "PREP"}
            )
            cursor = token.end
        if not material or not noun_seen:
            return None
        return noun_seen, relation_seen

    source_shape = relational_tail(source_tail, supported)
    alternative_shape = relational_tail(alternative_tail, alternative)
    if source_shape is None or alternative_shape is None:
        return None
    if not source_shape[1] and not alternative_shape[1]:
        return None
    return True


def nominal_category_contrast_unproved(
    supported: str,
    alternative: str,
    *,
    source_clause: str,
) -> bool:
    """Reject a category-only edit as contradiction proof, without classifying it.

    The helper recognizes one bounded contiguous nominal/adjectival/participial
    replacement inside an otherwise unchanged option, or one exact nominal phrase
    relocated with an explicit ``любой`` modifier.  It requires a source-owned
    operational subspan containing that replacement.  Subspan lookup is bounded
    by the existing ``MAX_TOKENS`` predicate, source-window, and token axes.
    It intentionally cannot decide whether either category is broader, narrower,
    synonymous, or opposite.  Only a directly governing ``только`` or a same-
    clause exhaustive ``все ... кроме`` scope is a proved exclusivity exception;
    unsupported prohibition grammar remains conservatively unproved.  A sole
    dictionary-known noun/adjective changed only by an exact surface ``не``
    prefix is not treated as a category contrast; this does not classify either
    state or prove which option is true.
    """
    if any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_TEXT_CHARS
        for value in (supported, alternative, source_clause)
    ):
        return False
    supported_tokens = _tokenize(supported)
    alternative_tokens = _tokenize(alternative)
    source_tokens = _tokenize(source_clause)
    if not supported_tokens or not alternative_tokens or not source_tokens:
        return False

    try:
        if _universal_nominal_relocation_unproved(
            supported_tokens,
            alternative_tokens,
            source_tokens,
            source_clause,
        ):
            return True
        relational_fallback = _whole_clause_relational_nominal_contrast_unproved(
            supported,
            alternative,
            source_clause,
            supported_tokens,
            alternative_tokens,
        )
        if relational_fallback is not None:
            return relational_fallback
        prefix = 0
        while (
            prefix < len(supported_tokens)
            and prefix < len(alternative_tokens)
            and _morphological_match(
                supported_tokens[prefix], alternative_tokens[prefix]
            )
        ):
            prefix += 1
        suffix = 0
        while (
            suffix < len(supported_tokens) - prefix
            and suffix < len(alternative_tokens) - prefix
            and _morphological_match(
                supported_tokens[-1 - suffix], alternative_tokens[-1 - suffix]
            )
        ):
            suffix += 1
        supported_end = len(supported_tokens) - suffix
        alternative_end = len(alternative_tokens) - suffix
        supported_change = supported_tokens[prefix:supported_end]
        alternative_change = alternative_tokens[prefix:alternative_end]
        if not supported_change or not alternative_change:
            return False
        if any(
            len(change) > MAX_NOMINAL_CATEGORY_TOKENS
            or change[-1].end - change[0].start > MAX_NOMINAL_CATEGORY_CHARS
            for change in (supported_change, alternative_change)
        ):
            return False

        def is_nominal_change(change: list[_Token]) -> bool:
            for token in change:
                info = _word_info(token.text.casefold())
                if (
                    not info.known
                    or not info.parts_of_speech
                    or not info.parts_of_speech <= _NOMINAL_CONTRAST_POS
                ):
                    return False
            return True

        if not is_nominal_change(supported_change) or not is_nominal_change(
            alternative_change
        ):
            return False

        if len(supported_change) == len(alternative_change) == 1:
            supported_word = supported_change[0].text.casefold()
            alternative_word = alternative_change[0].text.casefold()
            unprefixed_word = ""
            if supported_word.startswith("не") and supported_word[2:] == alternative_word:
                unprefixed_word = alternative_word
            elif alternative_word.startswith("не") and alternative_word[2:] == supported_word:
                unprefixed_word = supported_word
            if unprefixed_word:
                supported_info = _word_info(supported_word)
                alternative_info = _word_info(alternative_word)
                privative_parts = {"NOUN", "ADJF"}
                if (
                    supported_info.known
                    and alternative_info.known
                    and bool(supported_info.parts_of_speech)
                    and bool(alternative_info.parts_of_speech)
                    and supported_info.parts_of_speech <= privative_parts
                    and alternative_info.parts_of_speech <= privative_parts
                    and bool(
                        supported_info.parts_of_speech
                        & alternative_info.parts_of_speech
                    )
                ):
                    return False

        def is_operational_predicate(token: _Token) -> bool:
            return (
                token.text.casefold() not in _PRESENT_DUTY_MODALS
                and bool(
                    _word_info(token.text.casefold()).parts_of_speech
                    & _OPERATIONAL_PREDICATE_POS
                )
            )

        shared_indexes = [
            *range(prefix),
            *range(supported_end, len(supported_tokens)),
        ]
        predicate_indexes = [
            index
            for index in shared_indexes
            if is_operational_predicate(supported_tokens[index])
            and not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(
                supported[
                    min(supported_tokens[index].end, supported_change[0].start) :
                    max(supported_tokens[index].start, supported_change[-1].end)
                ]
            )
        ]
        if not predicate_indexes:
            return False
        preceding_predicate_indexes = [
            index for index in predicate_indexes if index < prefix
        ]
        condition_window = supported_tokens[
            (
                preceding_predicate_indexes[0] + 1
                if preceding_predicate_indexes
                else 0
            ) : prefix
        ]
        if any(
            token.text.casefold() in _NOMINAL_CONTRAST_CONDITION_MARKERS
            for token in condition_window
        ) or any(
            left.text.casefold() == "в" and right.text.casefold() == "случае"
            for left, right in zip(
                condition_window, condition_window[1:], strict=False
            )
        ):
            return False

        nominal_head_index = next(
            (
                prefix + offset
                for offset, token in enumerate(supported_change)
                if _word_info(token.text.casefold()).parts_of_speech == {"NOUN"}
            ),
            None,
        )
        previous_end = supported_change[-1].end
        for index, token in enumerate(
            supported_tokens[supported_end : supported_end + 4],
            start=supported_end,
        ):
            if re.search(r"[.;!?]", supported[previous_end : token.start]):
                break
            info = _word_info(token.text.casefold())
            if (
                not info.known
                or not info.parts_of_speech <= _NOMINAL_CONTRAST_TAIL_POS
            ):
                break
            if info.parts_of_speech == {"NOUN"}:
                nominal_head_index = index
                break
            previous_end = token.end
        if nominal_head_index is None:
            return False

        source_binding: tuple[int, int, list[int]] | None = None
        # Prefer the complete clause so a leading source-owned ONLY/universal
        # remains visible with a postposed predicate. Use smaller exact spans
        # only when identical scenario wrappers prevent full-clause ownership.
        candidate_spans = [(0, len(supported_tokens)), *(
            (min(predicate_index, prefix), max(predicate_index + 1, supported_end, nominal_head_index + 1))
            for predicate_index in predicate_indexes
        )]
        for owned_start, owned_end in dict.fromkeys(candidate_spans):
            owned_tokens = supported_tokens[owned_start:owned_end]
            source_starts = [
                start
                for start in range(len(source_tokens) - len(owned_tokens) + 1)
                if not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(
                    source_clause[
                        source_tokens[start].start :
                        source_tokens[start + len(owned_tokens) - 1].end
                    ]
                )
                and all(
                    _morphological_match(source_tokens[start + offset], token)
                    for offset, token in enumerate(owned_tokens)
                )
            ]
            if source_starts:
                source_binding = (owned_start, owned_end, source_starts)
                break
        if source_binding is None:
            return False
        owned_start, _owned_end, source_starts = source_binding
        source_start = source_starts[0]
        source_match_is_unique = len(source_starts) == 1
        source_change_index = source_start + prefix - owned_start
        if source_match_is_unique and source_change_index > source_start:
            scope_operator = source_tokens[source_change_index - 1]
            scope_gap = source_clause[
                scope_operator.end : source_tokens[source_change_index].start
            ]
            if (
                scope_operator.text.casefold() == "только"
                and bool(scope_gap)
                and all(
                    character in _HORIZONTAL_SPACE_CHARS for character in scope_gap
                )
            ):
                return False
        for operator_index in range(source_start, source_change_index):
            operator_end = operator_index + 1
            if source_tokens[operator_index].text.casefold() == "кроме":
                pass
            elif (
                operator_index + 1 < source_change_index
                and source_tokens[operator_index].text.casefold() == "за"
                and source_tokens[operator_index + 1].text.casefold()
                == "исключением"
            ):
                operator_end += 1
            else:
                continue
            universal_indexes = [
                index
                for index in range(source_start, operator_index)
                if "весь"
                in _word_info(source_tokens[index].text.casefold()).lemmas
            ]
            scope_text = source_clause[
                source_tokens[operator_end - 1].end :
                source_tokens[source_change_index].start
            ]
            for universal_index in universal_indexes:
                # A narrowly recognized postposed passive clause has no other
                # operational predicate between its universal and actual PRTS.
                # The auxiliary быть is not a second task or a scope anchor.
                if source_match_is_unique and owned_start == 0 and _owned_end == len(supported_tokens):
                    postposed = [source_start + index for index in predicate_indexes
                        if index >= supported_end and "PRTS" in _word_info(supported_tokens[index].text.casefold()).parts_of_speech]
                    for passive_index in postposed:
                        if (not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(source_clause[
                            source_tokens[universal_index].end:source_tokens[passive_index].start])
                            and not any(is_operational_predicate(source_tokens[index])
                                and "быть" not in _word_info(source_tokens[index].text.casefold()).lemmas
                                for index in range(universal_index + 1, passive_index))):
                            return False
                predicate_scope_indexes = [
                    index
                    for index in range(source_start, universal_index)
                    if is_operational_predicate(source_tokens[index])
                ]
                if not predicate_scope_indexes:
                    continue
                predicate_index = predicate_scope_indexes[-1]
                predicate_to_operator = source_clause[
                    source_tokens[predicate_index].end :
                    source_tokens[operator_index].start
                ]
                intervening_predicate = any(
                    is_operational_predicate(source_tokens[index])
                    for index in range(predicate_index + 1, operator_index)
                )
                exception_tail_predicate = any(
                    is_operational_predicate(source_tokens[index])
                    for index in range(operator_end, source_change_index)
                )
                if (
                    source_match_is_unique
                    and not intervening_predicate
                    and not exception_tail_predicate
                    and not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(
                        predicate_to_operator
                    )
                    and not _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(scope_text)
                ):
                    return False
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return True


def exclusion_tail_policy_unproved(
    supported: str,
    alternative: str,
    *,
    source_clause: str,
) -> bool:
    """Veto contradiction inferred only from a source exemption.

    This recognizes either one exact positive universal duty whose complete
    nominal exemption is changed to ``включая``, or one source-owned
    ``за исключением ... а также ...`` list whose final nominal sibling becomes
    the subject of one added bounded positive policy.  The exemption removes the
    source duty; it does not forbid that duty or prove a stronger duty false.
    The helper supplies no truth or acceptance signal.
    """

    if any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_TEXT_CHARS
        for value in (supported, alternative, source_clause)
    ):
        return False
    if any(
        _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(value)
        for value in (supported, alternative)
    ):
        return False
    supported_tokens = _tokenize(supported)
    alternative_tokens = _tokenize(alternative)
    source_tokens = _tokenize(source_clause)
    if not supported_tokens or not alternative_tokens or not source_tokens:
        return False

    try:
        if len(source_tokens) != len(supported_tokens) or not all(
            source.text.casefold() == owned.text.casefold()
            for source, owned in zip(source_tokens, supported_tokens, strict=True)
        ):
            return False
        if _NOMINAL_CONTRAST_HARD_BOUNDARY_RE.search(
            source_clause[source_tokens[0].start : source_tokens[-1].end]
        ):
            return False

        def is_nominal_group(tokens: list[_Token]) -> bool:
            noun_seen = False
            for token in tokens:
                normalized = token.text.casefold()
                if normalized in {"и", "или", "либо", "а", "также"}:
                    continue
                info = _word_info(normalized)
                if (
                    not info.known
                    or not info.parts_of_speech
                    or bool(info.parts_of_speech & _OPERATIONAL_PREDICATE_POS)
                    or not info.parts_of_speech <= _NOMINAL_CATEGORY_POS
                ):
                    return False
                noun_seen = noun_seen or bool(info.noun_lemmas)
            return noun_seen

        def nominal_inflection_preserves_number(
            source: _Token,
            replacement: _Token,
        ) -> bool:
            if source.text.casefold() == replacement.text.casefold():
                return True
            source_parses = _morph().parse(source.text.casefold())
            replacement_parses = _morph().parse(replacement.text.casefold())
            return any(
                source_parse.normal_form == replacement_parse.normal_form
                and source_parse.tag.POS == replacement_parse.tag.POS
                and source_parse.tag.POS in _NOMINAL_CATEGORY_POS
                and source_parse.tag.number in {"sing", "plur"}
                and source_parse.tag.number == replacement_parse.tag.number
                for source_parse in source_parses
                for replacement_parse in replacement_parses
            )

        exclusion_spans = [
            (index, index + 2)
            for index in range(len(supported_tokens) - 1)
            if supported_tokens[index].text.casefold() == "за"
            and supported_tokens[index + 1].text.casefold() == "исключением"
        ]
        exclusion_spans.extend(
            (index, index + 1)
            for index, token in enumerate(supported_tokens)
            if token.text.casefold() == "кроме"
        )
        if len(exclusion_spans) == 1:
            exclusion_start, exclusion_end = exclusion_spans[0]
            prefix = supported_tokens[:exclusion_start]
            source_exemptions = supported_tokens[exclusion_end:]
            universal_indexes = [
                index
                for index, token in enumerate(prefix)
                if "весь" in _word_info(token.text.casefold()).lemmas
            ]
            positive_prefix = not any(
                token.text.casefold()
                in {"не", "ни", "нет", "нельзя", "невозможно"}
                for token in prefix
            )
            predicate_before_universal = bool(universal_indexes) and any(
                _word_info(token.text.casefold()).parts_of_speech
                & _OPERATIONAL_PREDICATE_POS
                for token in prefix[: universal_indexes[-1]]
            )
            object_after_universal = bool(universal_indexes) and any(
                _word_info(token.text.casefold()).noun_lemmas
                for token in prefix[universal_indexes[-1] + 1 :]
            )
            alternative_prefix_end = exclusion_start
            alternative_tail = alternative_tokens[alternative_prefix_end + 1 :]
            if (
                len(universal_indexes) == 1
                and positive_prefix
                and predicate_before_universal
                and object_after_universal
                and is_nominal_group(source_exemptions)
                and len(alternative_tokens) == len(prefix) + 1 + len(source_exemptions)
                and alternative_tokens[alternative_prefix_end].text.casefold()
                == "включая"
                and all(
                    source.text.casefold() == replacement.text.casefold()
                    for source, replacement in zip(
                        prefix,
                        alternative_tokens[:alternative_prefix_end],
                        strict=True,
                    )
                )
                and all(
                    nominal_inflection_preserves_number(source, replacement)
                    for source, replacement in zip(
                        source_exemptions,
                        alternative_tail,
                        strict=True,
                    )
                )
            ):
                return True

        exclusion_indexes = [
            index
            for index in range(len(supported_tokens) - 1)
            if supported_tokens[index].text.casefold() == "за"
            and supported_tokens[index + 1].text.casefold() == "исключением"
        ]
        connector_indexes = [
            index
            for index in range(len(supported_tokens) - 1)
            if supported_tokens[index].text.casefold() == "а"
            and supported_tokens[index + 1].text.casefold() == "также"
        ]
        if len(exclusion_indexes) != 1 or len(connector_indexes) != 1:
            return False
        exclusion_index = exclusion_indexes[0]
        connector_index = connector_indexes[0]
        if connector_index <= exclusion_index + 2:
            return False

        main_prefix = supported_tokens[:exclusion_index]
        if any(
            token.text.casefold() in {"не", "ни", "нет", "нельзя", "невозможно"}
            for token in main_prefix
        ):
            return False
        if not any(
            token.text.casefold() not in _PRESENT_DUTY_MODALS
            and _word_info(token.text.casefold()).parts_of_speech
            & _OPERATIONAL_PREDICATE_POS
            for token in main_prefix
        ):
            return False

        first_exempt_group = supported_tokens[exclusion_index + 2 : connector_index]
        final_exempt_group = supported_tokens[connector_index + 2 :]
        if not first_exempt_group or not final_exempt_group:
            return False
        if len(final_exempt_group) > MAX_NOMINAL_CATEGORY_TOKENS:
            return False

        if not is_nominal_group(first_exempt_group) or not is_nominal_group(
            final_exempt_group
        ):
            return False

        preserved_prefix_end = connector_index + 1
        if len(alternative_tokens) <= preserved_prefix_end + len(final_exempt_group):
            return False
        if not all(
            source.text.casefold() == replacement.text.casefold()
            for source, replacement in zip(
                supported_tokens[:preserved_prefix_end],
                alternative_tokens[:preserved_prefix_end],
                strict=True,
            )
        ):
            return False

        alternative_group_start = preserved_prefix_end
        alternative_group_end = alternative_group_start + len(final_exempt_group)
        if not all(
            nominal_inflection_preserves_number(source, replacement)
            for source, replacement in zip(
                final_exempt_group,
                alternative_tokens[alternative_group_start:alternative_group_end],
                strict=True,
            )
        ):
            return False

        added_policy = alternative_tokens[alternative_group_end:]
        if not 1 <= len(added_policy) <= MAX_NOMINAL_CATEGORY_TOKENS:
            return False
        if added_policy[-1].end - added_policy[0].start > MAX_CONDITIONAL_TAIL_CHARS:
            return False
        if added_policy[0].text.casefold() in _PRESENT_DUTY_MODALS:
            return False
        first_policy_info = _word_info(added_policy[0].text.casefold())
        if not first_policy_info.known or not (
            first_policy_info.parts_of_speech & _OPERATIONAL_PREDICATE_POS
        ):
            return False
        if any(
            token.text.casefold()
            in (_NOMINAL_CONTRAST_CONDITION_MARKERS | {"не", "ни"})
            or token.text in _NUMERIC_OPERATORS
            or token.text[0].isdigit()
            or not _word_info(token.text.casefold()).known
            or _word_info(token.text.casefold()).pos == "CONJ"
            for token in added_policy
        ):
            return False

        added_predicate_lemmas = set().union(
            *(
                _word_info(token.text.casefold()).lemmas
                for token in added_policy
                if _word_info(token.text.casefold()).parts_of_speech
                & _OPERATIONAL_PREDICATE_POS
            )
        )
        return bool(added_predicate_lemmas)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def is_bounded_source_condition(condition: object) -> bool:
    """Accept a bounded source nominal or single finite indicative condition."""
    if not isinstance(condition, str):
        return False
    value = condition.strip()
    if not value or len(value) > MAX_CONDITIONAL_TAIL_CHARS:
        return False
    try:
        if is_bounded_nominal_category(value):
            return True
        matches = list(_TOKEN_RE.finditer(value))
        if not 1 <= len(matches) <= MAX_CONDITIONAL_TAIL_TOKENS:
            return False
        cursor = 0
        finite_predicates = 0
        has_nominal = False
        analyzer = _morph()
        allowed_non_predicates = _NOMINAL_CATEGORY_POS | {"NPRO", "ADVB"}
        for match in matches:
            if not value[cursor:match.start()].isspace() and match.start() != cursor:
                return False
            token = match.group()
            cursor = match.end()
            if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
                has_nominal = True
                continue
            if not _RUSSIAN_RE.fullmatch(token):
                return False
            normalized = token.casefold()
            if not analyzer.word_is_known(normalized):
                return False
            parses = analyzer.parse(normalized)
            if not parses:
                return False
            parts_of_speech = {parse.tag.POS for parse in parses}
            if parts_of_speech == {"VERB"}:
                if any(getattr(parse.tag, "mood", None) != "indc" for parse in parses):
                    return False
                finite_predicates += 1
                continue
            if not parts_of_speech or not parts_of_speech <= allowed_non_predicates:
                return False
            has_nominal = has_nominal or bool(
                parts_of_speech & {"NOUN", "NPRO", "PRTF", "NUMR"}
            )
        return cursor == len(value) and finite_predicates == 1 and has_nominal
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def is_bounded_conditional_tail(tail: object) -> bool:
    """Accept a bounded nominal condition or one narrow polar complement."""
    if not isinstance(tail, str):
        return False
    value = tail.strip()
    if not value or len(value) > MAX_CONDITIONAL_TAIL_CHARS:
        return False
    try:
        grammar_value = value[:-1].rstrip() if value.endswith(".") else value
        if not grammar_value or grammar_value.endswith("."):
            return False
        if is_bounded_nominal_category(grammar_value):
            return True
        if len(list(_TOKEN_RE.finditer(grammar_value))) > MAX_CONDITIONAL_TAIL_TOKENS:
            return False
        complement = re.fullmatch(
            r"того\s*,\s*(?P<predicate>[а-яё]+)\s+ли\s+(?P<remainder>.+)",
            grammar_value,
            re.IGNORECASE,
        )
        if complement is None:
            return False
        predicate = complement["predicate"].casefold()
        analyzer = _morph()
        if not analyzer.word_is_known(predicate):
            return False
        parses = analyzer.parse(predicate)
        if (
            not parses
            or {parse.tag.POS for parse in parses} != {"VERB"}
            or any(getattr(parse.tag, "mood", None) != "indc" for parse in parses)
        ):
            return False
        return is_bounded_nominal_category(complement["remainder"])
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def _neighbor(text: str, position: int, step: int) -> str:
    while 0 <= position < len(text):
        if not text[position].isspace():
            return text[position]
        position += step
    return ""


def _keep_symbol(text: str, match: re.Match[str]) -> bool:
    symbol = match.group()
    if symbol not in _NUMERIC_OPERATORS | _UNIT_SYMBOLS:
        return True
    before = _neighbor(text, match.start() - 1, -1)
    after = _neighbor(text, match.end(), 1)
    if symbol in {">=", "<=", "!=", ">", "<", "=", "≥", "≤", "≠"}:
        return True
    if symbol in {"+", "-", "−"}:
        return after.isdigit() or (before.isdigit() and after.isdigit())
    if symbol in {"%", "‰", "°"}:
        return before.isdigit()
    if symbol in {"²", "³"}:
        return before.isalnum()
    if symbol == ":":
        return before.isdigit() and after.isdigit()
    return before.isalnum() and after.isalnum()


def _token_matches(text: str) -> Iterator[re.Match[str]]:
    for match in _TOKEN_RE.finditer(text):
        if _keep_symbol(text, match):
            yield match


def _tokenize(text: str) -> list[_Token] | None:
    matches = list(_token_matches(text))
    if len(matches) > MAX_TOKENS:
        return None
    tokens = [
        _Token(match.group(), index, start=match.start(), end=match.end())
        for index, match in enumerate(matches)
    ]
    if any(len(token.text) > MAX_TOKEN_CHARS for token in tokens):
        return None
    return tokens


def _tokenize_context(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    for match in _token_matches(text):
        if len(match.group()) > MAX_TOKEN_CHARS:
            continue
        if len(tokens) == MAX_CONTEXT_TOKENS:
            break
        tokens.append(
            _Token(
                match.group(),
                len(tokens),
                start=match.start(),
                end=match.end(),
            )
        )
    return tokens


def _normalize_exclusion_operators(tokens: list[_Token], text: str) -> list[_Token]:
    normalized: list[_Token] = []
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if cursor + 1 < len(tokens):
            following = tokens[cursor + 1]
            gap = text[token.end : following.start]
            if (
                token.text.casefold() == "за"
                and following.text.casefold() == "исключением"
                and bool(gap)
                and all(character in _HORIZONTAL_SPACE_CHARS for character in gap)
            ):
                normalized.append(
                    _Token(
                        "кроме",
                        token.index,
                        start=token.start,
                        end=following.end,
                    )
                )
                cursor += 2
                continue
        normalized.append(token)
        cursor += 1
    return normalized


def _without_inclusion_function_phrase(tokens: list[_Token], text: str) -> list[_Token]:
    """Disambiguate the fixed connective, not material nouns ``том``/``число``.

    This removes a lexical false veto only. Whether an authored proposition
    preserves inclusion/scope still requires both independent semantic proofs.
    Original source, positions and receipt text are never rewritten.
    """
    spans = tuple(re.finditer(r"\bв[ \t\u00a0]+том[ \t\u00a0]+числе\b", text, re.I))
    return [token for token in tokens if not any(
        span.start() <= token.start and token.end <= span.end() for span in spans
    )]


def _is_acronym(token: _Token) -> bool:
    return token.alias is None and bool(_ACRONYM_RE.fullmatch(token.text))


def _kind(token: _Token) -> str:
    if token.alias is not None:
        return "alias"
    normalized = token.text.casefold()
    if token.text in _NUMERIC_OPERATORS:
        return "numeric_operator"
    if token.text in _UNIT_SYMBOLS:
        return "unit"
    if token.text[0].isdigit():
        return "number"
    if _is_acronym(token):
        return "acronym"
    info = _word_info(normalized)
    if normalized in _PROTECTED_LITERALS or info.lemmas & _PROTECTED_LEMMAS:
        return "protected_operator"
    if not info.known:
        return "unknown"
    if info.pos in _IGNORED_POS:
        return "ignored"
    return "material"


def _morphological_match(left: _Token, right: _Token) -> bool:
    if left.alias is not None or right.alias is not None:
        return left.alias is not None and left.alias == right.alias
    if left.text.casefold() == right.text.casefold():
        return True
    left_info = _word_info(left.text.casefold())
    right_info = _word_info(right.text.casefold())
    return bool(left_info.known and right_info.known and left_info.lemmas & right_info.lemmas)


def _operator_identity(operator: str) -> str:
    return _OPERATOR_IDENTITIES.get(operator, operator)


def _expansion_signature(expansion: list[_Token]) -> tuple[tuple[str, ...], ...]:
    signature: list[tuple[str, ...]] = []
    for token in expansion:
        info = _word_info(token.text.casefold())
        signature.append(
            tuple(sorted(info.lemmas)) if info.known else (token.text.casefold(),)
        )
    return tuple(signature)


def _expansion_initials(expansion: list[_Token]) -> str:
    return "".join(
        part[0].upper()
        for token in expansion
        for part in token.text.split("-")
        if part
    )


def _definition_aliases(
    source_context: str,
) -> tuple[list[tuple[list[_Token], str]], PreservationIssue | None]:
    aliases: list[tuple[list[_Token], str]] = []
    acronym_signatures: dict[str, tuple[tuple[str, ...], ...]] = {}
    for match in _DEFINITION_RE.finditer(source_context):
        expansion = _tokenize(match.group("expansion"))
        acronym = match.group("acronym")
        if not expansion:
            continue
        matching_suffixes = [
            expansion[start:]
            for start in range(len(expansion))
            if _expansion_initials(expansion[start:]) == acronym
        ]
        if len(matching_suffixes) == 1:
            expansion = matching_suffixes[0]
            signature = _expansion_signature(expansion)
            previous = acronym_signatures.get(acronym)
            if previous is not None and previous != signature:
                return [], _issue("conflicting_acronym_definition", "acronym")
            if previous == signature:
                continue
            acronym_signatures[acronym] = signature
            aliases.append((expansion, acronym))
    return aliases, None


def _find_expansion(tokens: list[_Token], expansion: list[_Token]) -> tuple[int, int] | None:
    width = len(expansion)
    for start in range(len(tokens) - width + 1):
        if all(
            _morphological_match(expansion[offset], tokens[start + offset])
            for offset in range(width)
        ):
            return start, start + width
    return None


def _collapse(tokens: list[_Token], start: int, end: int, alias: int) -> list[_Token]:
    return [*tokens[:start], replace(tokens[start], alias=alias), *tokens[end:]]


def _apply_explicit_aliases(
    source: list[_Token],
    candidate: list[_Token],
    source_context: str,
) -> tuple[list[_Token], list[_Token], PreservationIssue | None]:
    aliases, definition_issue = _definition_aliases(source_context)
    if definition_issue is not None:
        return source, candidate, definition_issue
    for alias, (expansion, acronym) in enumerate(aliases):
        source_expansion = _find_expansion(source, expansion)
        candidate_acronym = next(
            (index for index, token in enumerate(candidate) if token.text == acronym),
            None,
        )
        if source_expansion is not None and candidate_acronym is not None:
            source = _collapse(source, *source_expansion, alias)
            candidate = _collapse(candidate, candidate_acronym, candidate_acronym + 1, alias)
            continue

        source_acronym = next(
            (index for index, token in enumerate(source) if token.text == acronym),
            None,
        )
        candidate_expansion = _find_expansion(candidate, expansion)
        if source_acronym is not None and candidate_expansion is not None:
            source = _collapse(source, source_acronym, source_acronym + 1, alias)
            candidate = _collapse(candidate, *candidate_expansion, alias)
    return source, candidate, None


def _complete_source_fragments(
    source: list[_Token], source_context: str
) -> tuple[list[_Token], PreservationIssue | None]:
    if not source_context:
        return source, None
    context_tokens = _normalize_exclusion_operators(
        _tokenize_context(source_context), source_context
    )
    context_words = {token.text.casefold(): token.text for token in context_tokens}
    completed: list[_Token] = []
    for token in source:
        normalized = token.text.casefold()
        if (
            token.alias is not None
            or len(normalized) < 4
            or not normalized.isalpha()
            or normalized in context_words
        ):
            completed.append(token)
            continue
        matches = {
            folded: original
            for folded, original in context_words.items()
            if folded.startswith(normalized) and len(folded) > len(normalized)
        }
        if len(matches) > 1:
            return source, _issue("ambiguous_source_fragment", "fragment", token.index)
        if len(matches) == 1:
            completed.append(replace(token, text=next(iter(matches.values()))))
        else:
            completed.append(token)
    return completed, None


def _cardinal_lemma(token: _Token) -> str | None:
    if token.alias is not None or not token.text.isalpha():
        return None
    recognized = _word_info(token.text.casefold()).lemmas & _CARDINAL_LEXEMES
    if len(recognized) != 1:
        return None
    return next(iter(recognized))


def _is_unknown_cardinal_form(token: _Token) -> bool:
    if token.alias is not None:
        return False
    normalized = token.text.casefold()
    info = _word_info(normalized)
    return (
        not info.known
        and bool(_RUSSIAN_RE.fullmatch(normalized))
        and any(_one_damerau_edit(normalized, lexeme) for lexeme in _CARDINAL_LEXEMES)
    )


def _parse_cardinal_below_hundred(lemmas: list[str]) -> int | None:
    if len(lemmas) == 1:
        lemma = lemmas[0]
        return (
            _CARDINAL_UNITS.get(lemma)
            if lemma in _CARDINAL_UNITS
            else _CARDINAL_TEENS.get(lemma, _CARDINAL_TENS.get(lemma))
        )
    if (
        len(lemmas) == 2
        and lemmas[0] in _CARDINAL_TENS
        and lemmas[1] in _CARDINAL_UNITS
        and _CARDINAL_UNITS[lemmas[1]] > 0
    ):
        return _CARDINAL_TENS[lemmas[0]] + _CARDINAL_UNITS[lemmas[1]]
    return None


def _parse_cardinal_below_thousand(lemmas: list[str]) -> int | None:
    if not lemmas:
        return None
    if lemmas[0] not in _CARDINAL_HUNDREDS:
        return _parse_cardinal_below_hundred(lemmas)
    hundreds = _CARDINAL_HUNDREDS[lemmas[0]]
    if len(lemmas) == 1:
        return hundreds
    remainder = _parse_cardinal_below_hundred(lemmas[1:])
    return None if remainder is None or remainder == 0 else hundreds + remainder


def _parse_cardinal(lemmas: list[str]) -> int | None:
    if not 1 <= len(lemmas) <= MAX_CARDINAL_TOKENS:
        return None
    if "ноль" in lemmas:
        return 0 if lemmas == ["ноль"] else None

    total = 0
    group: list[str] = []
    previous_scale = MAX_CARDINAL_VALUE + 1
    seen_scale = False
    for lemma in lemmas:
        scale = _CARDINAL_SCALES.get(lemma)
        if scale is None:
            group.append(lemma)
            continue
        if scale >= previous_scale:
            return None
        if not group and seen_scale:
            return None
        group_value = _parse_cardinal_below_thousand(group) if group else 1
        if group_value is None or group_value == 0:
            return None
        total += group_value * scale
        group = []
        previous_scale = scale
        seen_scale = True

    if group:
        group_value = _parse_cardinal_below_thousand(group)
        if group_value is None:
            return None
        total += group_value
    if not 0 <= total <= MAX_CARDINAL_VALUE:
        return None
    return total


def source_has_ambiguous_numeric_glyph(text: str) -> bool:
    """Flag a damaged numeral position, never replace its glyph or infer a value.

    Only a standalone one-like glyph followed by a parenthesized, dictionary-
    known Russian cardinal is covered. Roman ordinals, variable names and shell
    pipes are not inferred to be quantities from typography alone.
    """
    if not text or len(text) > MAX_SOURCE_CONTEXT_CHARS:
        return False
    for match in re.finditer(r"(?<!\w)[|¦IlІ]\s*\(\s*([А-Яа-яЁё\s]{1,128})\s*\)", text):
        tokens = _tokenize(match[1])
        if not tokens or len(tokens) > MAX_CARDINAL_TOKENS:
            continue
        try:
            lemmas = [_cardinal_lemma(token) for token in tokens]
            if all(lemma is not None for lemma in lemmas) and _parse_cardinal(
                [lemma for lemma in lemmas if lemma is not None]
            ) is not None:
                return True
        except (ImportError, OSError, RuntimeError, ValueError):
            continue  # Unproved language analysis never invents a quantity.
    return False


def _normalize_cardinals(
    tokens: list[_Token],
) -> tuple[list[_Token], PreservationIssue | None]:
    normalized: list[_Token] = []
    cursor = 0
    while cursor < len(tokens):
        if _is_unknown_cardinal_form(tokens[cursor]):
            return tokens, _issue(
                "unknown_cardinal_form", "number", tokens[cursor].index
            )
        lemma = _cardinal_lemma(tokens[cursor])
        if lemma is None:
            normalized.append(tokens[cursor])
            cursor += 1
            continue
        end = cursor + 1
        lemmas = [lemma]
        while end < len(tokens):
            next_lemma = _cardinal_lemma(tokens[end])
            if next_lemma is None:
                break
            lemmas.append(next_lemma)
            end += 1
        value = _parse_cardinal(lemmas)
        if value is None:
            return tokens, _issue("invalid_cardinal_sequence", "number", tokens[cursor].index)
        normalized.append(replace(tokens[cursor], text=str(value)))
        cursor = end
    return normalized, None


def _one_damerau_edit(left: str, right: str) -> bool:
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [
            index
            for index, pair in enumerate(zip(left, right, strict=True))
            if pair[0] != pair[1]
        ]
        if len(differences) == 1:
            return True
        return (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = long_index = mismatch_count = 0
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue
        mismatch_count += 1
        if mismatch_count > 1:
            return False
        long_index += 1
    return True


@lru_cache(maxsize=256)
def _unique_nominal_substitution(word: str) -> str | None:
    """Choose from the dictionary, never from a proposed learner answer.

    Only one internal character substitution in a lowercase unknown Russian
    nominal word is eligible. Known words, names, predicates, numerals, affix
    edits, insertion/deletion and several plausible spellings remain unproved.
    """
    if (not 6 <= len(word) <= 32 or not _RUSSIAN_RE.fullmatch(word)
            or word != word.lower() or _morph().word_is_known(word)):
        return None
    known: set[str] = set()
    for index in range(2, len(word) - 1):
        for character in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя":
            if character == word[index]:
                continue
            proposal = word[:index] + character + word[index + 1:]
            if _morph().word_is_known(proposal):
                known.add(proposal)
                if len(known) > 1:
                    return None
    if len(known) != 1:
        return None
    result = next(iter(known))
    info = _word_info(result)
    if (info.parts_of_speech != {"NOUN"} or len(info.noun_lemmas) != 1
            or info.lemmas & (_PROTECTED_LEMMAS | _CARDINAL_LEXEMES)
            or result in _PROTECTED_LITERALS
            or any(any(label in str(parse.tag) for label in ("Name", "Surn", "Patr", "Geox", "Orgn", "Trad"))
                   for parse in _morph().parse(result))):
        return None
    return result


def source_nominal_spelling_receipts(
    component: str, candidate: str, *, source_context: str,
) -> tuple[NominalSpellingReceipt, ...]:
    """Bind an optional dictionary-unique surface alias to immutable originals.

    This receipt cannot establish the source's actual spelling or the answer's
    meaning. It only avoids a lexical false veto AFTER independent semantic
    review; all other preservation checks still apply to the whole mapped view.
    """
    if (not all(isinstance(value, str) for value in (component, candidate, source_context))
            or not component or not candidate or len(component) > MAX_TEXT_CHARS
            or len(candidate) > MAX_TEXT_CHARS or len(source_context) > MAX_SOURCE_CONTEXT_CHARS
            or source_context.count(component) != 1):
        return ()
    source = _tokenize(component)
    destination = _tokenize(candidate)
    if not source or not destination:
        return ()
    try:
        # This surface policy never mediates a quantity, deadline or unit/value
        # correction. Even an unrelated numeral keeps the whole view strict.
        if any(any(char.isdigit() for char in token.text)
               or _cardinal_lemma(token) is not None for token in source):
            return ()
        receipts: list[NominalSpellingReceipt] = []
        for token in source:
            corrected = _unique_nominal_substitution(token.text)
            if corrected is None:
                continue
            normalized = replace(token, text=corrected)
            if not any(_morphological_match(normalized, other) for other in destination):
                continue
            receipts.append(NominalSpellingReceipt(
                token.text, corrected, token.start, token.end,
                hashlib.sha256(component.encode()).hexdigest(),
                hashlib.sha256(candidate.encode()).hexdigest(),
                hashlib.sha256(source_context.encode()).hexdigest(),
            ))
        return tuple(receipts)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ()  # Missing/ambiguous language evidence never supplies an alias.


def source_instruction_surface_receipts(
    component: str, candidate: str, *, source_context: str,
) -> tuple[InstructionSurfaceReceipt, ...]:
    """Recognize two bounded grammatical realizations, not arbitrary synonyms.

    Both views must start with the SAME positive infinitive instruction and
    identical optional adverbs. A parenthetical required infinitive may become
    its dictionary-identical gerund. A repeated infinitive after a conjunction
    may share the already realized same predicate. Every actor, argument, scope,
    operator, quantity and remaining source word still goes through the normal
    lexical floor; both independent semantic critics remain mandatory.
    """
    if (not all(isinstance(value, str) for value in (component, candidate, source_context))
            or not component or not candidate or len(component) > MAX_TEXT_CHARS
            or len(candidate) > MAX_TEXT_CHARS or len(source_context) > MAX_SOURCE_CONTEXT_CHARS
            or source_context.count(component) != 1):
        return ()
    source, destination = _tokenize(component), _tokenize(candidate)
    if not source or not destination:
        return ()
    forbidden = re.compile(r"\b(?:не|ни|без|нельзя|можно|вправе|необязательн\w*|"
        r"разреш\w*|желательн\w*|рекоменду\w*|возможн\w*)\b", re.IGNORECASE)
    if forbidden.search(component) or forbidden.search(candidate):
        return ()
    try:
        def opening(tokens: list[_Token]) -> int | None:
            for index, token in enumerate(tokens[:3]):
                info = _word_info(token.text)
                if info.known and info.parts_of_speech == {"INFN"}:
                    return index
                # Identical source/answer prefixes cannot change the instruction.
                # Russian adverbs can also have an adjectival dictionary parse;
                # require the primary adverb parse rather than parse unanimity.
                if not info.known or info.pos != "ADVB":
                    return None
            return None

        source_open, candidate_open = opening(source), opening(destination)
        if (source_open is None or candidate_open != source_open
                or any(left.text.casefold() != right.text.casefold() for left, right in
                       zip(source[:source_open], destination[:source_open], strict=True))
                or not _morphological_match(source[source_open], destination[source_open])):
            return ()
        modal_pairs: list[tuple[int, int, int]] = []
        if component.count("(") == component.count(")") == 1:
            left, right = component.index("("), component.index(")")
            for index, token in enumerate(source[:-1]):
                if (index <= source_open or token.text.casefold() not in {"необходимо", "нужно"}
                        or not left < token.start < source[index + 1].end <= right):
                    continue
                verb = source[index + 1]
                if _word_info(verb.text).parts_of_speech != {"INFN"}:
                    continue
                matches = [other for other in destination[candidate_open + 1:]
                           if _word_info(other.text).parts_of_speech == {"GRND"}
                           and _morphological_match(verb, other)]
                if len(matches) == 1:
                    modal_pairs.append((token.index, verb.index, matches[0].index))
        repeated_pairs: list[tuple[int, int]] = []
        for token in source[source_open + 1:]:
            if (_word_info(token.text).parts_of_speech != {"INFN"}
                    or not _morphological_match(source[source_open], token)):
                continue
            # Never let an object migrate to a different intervening predicate:
            # "report address, check document, report surname" cannot become
            # "report address, check document and surname". Explicitly realized
            # gerunds can still match their own source predicate normally.
            if any(_word_info(other.text).parts_of_speech & {"INFN", "GRND", "VERB", "PRTF", "PRTS"}
                   and not _morphological_match(source[source_open], other)
                   for other in source[source_open + 1:token.index]):
                continue
            between = component[source[source_open].end:token.start]
            # A conventional connective is not an applicability condition. No
            # source bytes are changed by this syntactic boundary inspection.
            between = re.sub(r"\bпри\s+эт(?:о|ом)\b", "", between, flags=re.IGNORECASE)
            if (not re.search(r"\b(?:и|также)\b", between, re.IGNORECASE)
                    or re.search(r"[.;!?\r\n]", between)
                    or re.search(r"\b(?:если|когда|при|до|после|перед|кроме|только|либо|или)\b",
                                 between, re.IGNORECASE)):
                continue
            repeated_pairs.append((token.index, destination[candidate_open].index))
        if not modal_pairs and not repeated_pairs:
            return ()
        return (InstructionSurfaceReceipt(
            hashlib.sha256(component.encode()).hexdigest(),
            hashlib.sha256(candidate.encode()).hexdigest(),
            hashlib.sha256(source_context.encode()).hexdigest(),
            tuple(modal_pairs), tuple(repeated_pairs),
        ),)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ()


_GRAMMAR_BINDING_KEYS = frozenset({
    "facet_id",
    "source_id",
    "quote",
    "role",
    "branch_effect",
    "quote_start",
    "quote_end",
})
_GRAMMAR_BINDING_ROLES = frozenset({"actor", "scope", "operator"})
_LOCAL_GRAMMAR_BINDING_ROLES = frozenset({
    "actor",
    "recipient",
    "timing",
    "condition",
    "exception",
    "scope",
    "quantity",
    "operator",
})
_POSITIVE_NORMATIVE_GOVERNORS = frozenset({
    "должен",
    "должна",
    "должно",
    "должны",
    "обязан",
    "обязана",
    "обязано",
    "обязаны",
    "следует",
    "необходимо",
    "нужно",
    "требуется",
})
_ACTION_NOMINAL_SUFFIXES = (
    ("ение", "ить"),
    ("ение", "ивать"),
    ("ание", "ать"),
)
_LOCAL_GRAMMAR_WORD_RE = re.compile(r"[А-Яа-яЁё]+")
_LOCAL_NOMINAL_POS = frozenset({"NOUN", "ADJF", "PRTF"})
_LOCAL_CASES = frozenset({"nomn", "gent", "datv", "accs", "ablt", "loct"})


def _exact_unique_span(owner: str, value: str) -> tuple[int, int] | None:
    if not value:
        return None
    start = owner.find(value)
    if start < 0 or owner.find(value, start + 1) >= 0:
        return None
    return start, start + len(value)


def _governing_bindings_receipt(
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
    *,
    allowed_roles: frozenset[str] = _GRAMMAR_BINDING_ROLES,
    allowed_effects: frozenset[str] = frozenset({"none", "scopes_action"}),
) -> tuple[tuple[dict[str, object], ...], str] | None:
    if (
        not isinstance(verified_governing_bindings, Sequence)
        or isinstance(verified_governing_bindings, str | bytes)
        or not verified_governing_bindings
    ):
        return None
    rows: list[dict[str, object]] = []
    for raw in verified_governing_bindings:
        if not isinstance(raw, dict) or set(raw) != _GRAMMAR_BINDING_KEYS:
            return None
        facet_id = raw.get("facet_id")
        owner = raw.get("source_id")
        quote = raw.get("quote")
        role = raw.get("role")
        effect = raw.get("branch_effect")
        start = raw.get("quote_start")
        end = raw.get("quote_end")
        if (
            not all(isinstance(value, str) and value for value in (
                facet_id,
                owner,
                quote,
                role,
                effect,
            ))
            or owner != source_id
            or role not in allowed_roles
            or effect not in allowed_effects
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(source_context)
            or source_context[start:end] != quote
            or _exact_unique_span(source_context, quote) != (start, end)
        ):
            return None
        rows.append(raw)
    rows.sort(key=lambda row: (
        cast(str, row["facet_id"]),
        cast(int, row["quote_start"]),
        cast(str, row["quote"]),
    ))
    digest = hashlib.sha256()
    for row in rows:
        for key in sorted(_GRAMMAR_BINDING_KEYS):
            encoded = str(row[key]).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return tuple(rows), digest.hexdigest()


def _local_grammar_bindings_receipt(
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
    *, allowed_effects: frozenset[str] = frozenset({"none", "scopes_action"}),
) -> tuple[tuple[dict[str, object], ...], str] | None:
    if (
        not isinstance(verified_governing_bindings, Sequence)
        or isinstance(verified_governing_bindings, str | bytes)
    ):
        return None
    if not verified_governing_bindings:
        return (), hashlib.sha256().hexdigest()
    return _governing_bindings_receipt(
        source_context,
        source_id,
        verified_governing_bindings,
        allowed_roles=_LOCAL_GRAMMAR_BINDING_ROLES,
        allowed_effects=allowed_effects,
    )


def _one_positive_normative_governor(
    rows: tuple[dict[str, object], ...],
) -> tuple[str, tuple[int, int]] | None:
    matches: list[tuple[str, tuple[int, int]]] = []
    for row in rows:
        quote = cast(str, row["quote"])
        tokens = _tokenize(quote)
        if not tokens:
            continue
        normalized = [token.text.casefold() for token in tokens]
        if any(token in {"не", "ни", "нельзя", "запрещается"} for token in normalized):
            continue
        governors = [
            token
            for token in tokens
            if token.text.casefold() in _POSITIVE_NORMATIVE_GOVERNORS
        ]
        if len(governors) == 1:
            start = cast(int, row["quote_start"])
            matches.append((quote, (start, cast(int, row["quote_end"]))))
    return matches[0] if len(matches) == 1 else None


def _one_prohibition_governor(
    rows: tuple[dict[str, object], ...],
) -> tuple[str, tuple[int, int]] | None:
    matches: list[tuple[str, tuple[int, int]]] = []
    for row in rows:
        quote = cast(str, row["quote"])
        tokens = _tokenize(quote)
        if not tokens:
            continue
        normalized = [token.text.casefold() for token in tokens]
        if normalized.count("запрещается") != 1 or any(
            token in {"не", "ни", "нельзя"} for token in normalized
        ):
            continue
        start = cast(int, row["quote_start"])
        matches.append((quote, (start, cast(int, row["quote_end"]))))
    return matches[0] if len(matches) == 1 else None


def _source_lines(source_context: str) -> tuple[tuple[int, int, str], ...]:
    rows: list[tuple[int, int, str]] = []
    cursor = 0
    for raw in source_context.splitlines(keepends=True):
        text = raw.rstrip("\r\n")
        rows.append((cursor, cursor + len(text), text))
        cursor += len(raw)
    if cursor < len(source_context):
        rows.append((cursor, len(source_context), source_context[cursor:]))
    return tuple(rows)


def _header_predicate_is_modal_only(header: str, governors: frozenset[str]) -> bool:
    """Do not erase 'ensure/prohibit/check/permit' between a modal and a leaf."""
    try:
        tokens = _tokenize(header)
        if not tokens:
            return False
        return not any(
            token.text.casefold() not in governors
            and _word_info(token.text.casefold()).parts_of_speech & {"INFN", "VERB", "GRND"}
            for token in tokens
        )
    except (ImportError, OSError, RuntimeError, ValueError):
        return False


def _directly_governed_marked_component_span(
    component: str,
    source_context: str,
    governor_span: tuple[int, int],
) -> tuple[int, int] | None:
    selected: list[int] = []
    lines = _source_lines(source_context)
    for index, (_start, _end, text) in enumerate(lines):
        marker = parse_source_marker(text)
        if marker is None or not marker.decoration:
            continue
        body = text[marker.content_start:].strip()
        if body.startswith(component) and body[len(component):] in {"", ".", ";", ","}:
            selected.append(index)
    if len(selected) != 1:
        return None
    # A directly governed item may be the third (or later) sibling, not only
    # the first leaf after the header. Never cross a different marker/indent,
    # free prose, blank separator inside the list, or an intervening heading.
    first = selected[0]
    selected_marker = parse_source_marker(lines[first][2])
    if selected_marker is None:
        return None
    while first > 0:
        previous = parse_source_marker(lines[first - 1][2])
        if (previous is None or not previous.decoration
                or previous.family != selected_marker.family
                or previous.raw_start != selected_marker.raw_start):
            break
        if lines[first - 1][2].rstrip().endswith(":"):
            return None  # Same-indent source may still encode a nested governor.
        first -= 1
    header_index = first - 1
    while header_index >= 0 and not lines[header_index][2].strip():
        header_index -= 1
    if header_index < 0:
        return None
    header_start, header_end, header = lines[header_index]
    if not header.rstrip().endswith(":") or not (
        header_start <= governor_span[0] < governor_span[1] <= header_end
    ):
        return None
    header_tokens = _tokenize(header)
    if not header_tokens:
        return None
    normalized = [token.text.casefold() for token in header_tokens]
    if (
        sum(token in _POSITIVE_NORMATIVE_GOVERNORS for token in normalized) != 1
        or any(token in {"не", "ни", "нельзя", "запрещается"} for token in normalized)
        or not _header_predicate_is_modal_only(header, _POSITIVE_NORMATIVE_GOVERNORS)
    ):
        return None
    return _exact_unique_span(source_context, component)


def _governed_positive_list_leaf_span(
    component: str,
    source_context: str,
    governor_span: tuple[int, int],
) -> tuple[int, int] | None:
    """Bind one exact positive leaf to its adjacent owned prohibition header."""
    lines = _source_lines(source_context)
    selected: list[tuple[int, SourceMarker]] = []
    for index, (_start, _end, text) in enumerate(lines):
        marker = parse_source_marker(text)
        if marker is None or not marker.decoration:
            continue
        body = text[marker.content_start:].strip()
        if body == component:
            selected.append((index, marker))
    if len(selected) != 1:
        return None
    selected_index, selected_marker = selected[0]
    marker_family = selected_marker.family
    marker_indent = selected_marker.raw_start

    def sibling(index: int) -> bool:
        marker = parse_source_marker(lines[index][2])
        return bool(
            marker is not None
            and marker.decoration
            and marker.family == marker_family
            and marker.raw_start == marker_indent
        )

    first = selected_index
    while first > 0 and sibling(first - 1):
        if lines[first - 1][2].rstrip().endswith(":"):
            return None
        first -= 1
    last = selected_index
    while last + 1 < len(lines) and sibling(last + 1):
        last += 1
    if last - first + 1 < 2:
        return None
    header_index = first - 1
    while header_index >= 0 and not lines[header_index][2].strip():
        header_index -= 1
    if header_index < 0:
        return None
    header_start, header_end, header = lines[header_index]
    if not header.rstrip().endswith(":"):
        return None
    if not (
        header_start <= governor_span[0] < governor_span[1] <= header_end
    ):
        return None
    header_tokens = _tokenize(header)
    if not header_tokens:
        return None
    header_normalized = [token.text.casefold() for token in header_tokens]
    if header_normalized.count("запрещается") != 1 or any(
        token in {"не", "ни", "нельзя"} for token in header_normalized
    ) or not _header_predicate_is_modal_only(header, frozenset({"запрещается"})):
        return None
    component_tokens = _tokenize(component)
    if not component_tokens:
        return None
    first_token = component_tokens[0]
    if _word_info(first_token.text.casefold()).parts_of_speech != {"INFN"}:
        return None
    normalized = [token.text.casefold() for token in component_tokens]
    if normalized[0] in {"не", "ни", "нельзя", "запрещается"}:
        return None
    if any(token in {"нельзя", "запрещается"} for token in normalized[1:]):
        return None
    for index, token in enumerate(normalized[:-1]):
        if token not in {"не", "ни"}:
            continue
        if _word_info(component_tokens[index + 1].text.casefold()).parts_of_speech & {
            "INFN",
            "VERB",
            "GRND",
        }:
            return None
    return _exact_unique_span(source_context, component)


def _action_nominal_realization(
    component: str,
    candidate: str,
) -> tuple[str, str] | None:
    source_match = _TOKEN_RE.match(component)
    candidate_match = _TOKEN_RE.match(candidate)
    if source_match is None or candidate_match is None:
        return None
    source_form = source_match.group()
    candidate_form = candidate_match.group()
    source_tail = component[source_match.end():]
    candidate_tail = candidate[candidate_match.end():]
    if (
        source_match.start() != 0
        or candidate_match.start() != 0
        or not (source_tail == candidate_tail
                or (source_tail.endswith(";") and source_tail[:-1] == candidate_tail))
        or source_form.casefold() == candidate_form.casefold()
        or not _RUSSIAN_RE.fullmatch(source_form)
        or not _RUSSIAN_RE.fullmatch(candidate_form)
    ):
        return None
    source_info = _word_info(source_form.casefold())
    candidate_info = _word_info(candidate_form.casefold())
    if (
        not source_info.known
        or source_info.parts_of_speech != {"NOUN"}
        or len(source_info.noun_lemmas) != 1
        or not candidate_info.known
        or candidate_info.parts_of_speech != {"INFN"}
    ):
        return None
    source_normalized = source_form.casefold()
    candidate_normalized = candidate_form.casefold()
    if not any(
        source_normalized.endswith(noun_suffix)
        and candidate_normalized.endswith(verb_suffix)
        and source_normalized[: -len(noun_suffix)]
        == candidate_normalized[: -len(verb_suffix)]
        for noun_suffix, verb_suffix in _ACTION_NOMINAL_SUFFIXES
    ):
        return None
    return source_form, candidate_form


def _local_word_alignment(
    component: str,
    candidate: str,
) -> tuple[list[re.Match[str]], list[re.Match[str]], bool] | None:
    source_words = list(_LOCAL_GRAMMAR_WORD_RE.finditer(component))
    candidate_words = list(_LOCAL_GRAMMAR_WORD_RE.finditer(candidate))
    if not source_words or len(source_words) != len(candidate_words):
        return None
    source_cursor = candidate_cursor = 0
    for source, replacement in zip(source_words, candidate_words, strict=True):
        if component[source_cursor:source.start()] != candidate[candidate_cursor:replacement.start()]:
            return None
        source_cursor, candidate_cursor = source.end(), replacement.end()
    source_suffix = component[source_cursor:]
    candidate_suffix = candidate[candidate_cursor:]
    terminal_comma_dropped = source_suffix == "," and candidate_suffix == ""
    if source_suffix != candidate_suffix and not terminal_comma_dropped:
        return None
    return source_words, candidate_words, terminal_comma_dropped


def _matching_local_parses(
    source_word: str,
    candidate_word: str,
    allowed_pos: frozenset[str],
) -> tuple[tuple[_MorphParse, _MorphParse], ...]:
    if not (_morph().word_is_known(source_word) and _morph().word_is_known(candidate_word)):
        return ()
    return tuple(
        (source, replacement)
        for source in _morph().parse(source_word)
        for replacement in _morph().parse(candidate_word)
        if source.tag.POS == replacement.tag.POS
        and source.tag.POS in allowed_pos
        and source.normal_form == replacement.normal_form
    )


def _matching_local_case_parses(
    source_word: str,
    candidate_word: str,
    allowed_pos: frozenset[str],
) -> tuple[tuple[_MorphParse, _MorphParse], ...]:
    return tuple(
        (source, replacement)
        for source, replacement in _matching_local_parses(
            source_word,
            candidate_word,
            allowed_pos,
        )
        if (source.tag.grammemes - _LOCAL_CASES)
        == (replacement.tag.grammemes - _LOCAL_CASES)
    )


def _case_number_signatures(word: str) -> frozenset[tuple[str, str]]:
    signatures: set[tuple[str, str]] = set()
    if not _morph().word_is_known(word):
        return frozenset()
    for parsed in _morph().parse(word):
        if parsed.tag.POS not in _LOCAL_NOMINAL_POS:
            continue
        cases = parsed.tag.grammemes & _LOCAL_CASES
        if len(cases) == 1 and parsed.tag.number in {"sing", "plur"}:
            signatures.add((next(iter(cases)), parsed.tag.number))
    return frozenset(signatures)


def _according_nominal_case_realization(
    component: str,
    candidate: str,
) -> tuple[str, str, tuple[int, int]] | None:
    aligned = _local_word_alignment(component, candidate)
    if aligned is None or aligned[2]:
        return None
    source_words, candidate_words, _ = aligned
    changed = [
        index
        for index, (source, replacement) in enumerate(
            zip(source_words, candidate_words, strict=True)
        )
        if source.group().casefold() != replacement.group().casefold()
    ]
    if not 1 <= len(changed) <= 3 or changed != list(range(changed[0], changed[-1] + 1)):
        return None
    governor_index = changed[0] - 1
    if governor_index < 0 or source_words[governor_index].group().casefold() != "согласно":
        return None
    if any(
        not _matching_local_case_parses(
            source_words[index].group().casefold(),
            candidate_words[index].group().casefold(),
            _LOCAL_NOMINAL_POS,
        )
        for index in changed
    ):
        return None
    candidate_signatures = set.intersection(*(
        set(_case_number_signatures(candidate_words[index].group().casefold()))
        for index in changed
    ))
    source_signatures = set.intersection(*(
        set(_case_number_signatures(source_words[index].group().casefold()))
        for index in changed
    ))
    if not any(case == "datv" for case, _number in candidate_signatures) or any(
        case == "datv" for case, _number in source_signatures
    ):
        return None
    if any(
        source.group() != replacement.group()
        for index, (source, replacement) in enumerate(zip(source_words, candidate_words, strict=True))
        if index not in changed
    ):
        return None
    start, end = source_words[changed[0]].start(), source_words[changed[-1]].end()
    governor = source_words[governor_index]
    return component[start:end], candidate[
        candidate_words[changed[0]].start():candidate_words[changed[-1]].end()
    ], governor.span()


def _from_compound_nominal_case_realization(
    component: str,
    candidate: str,
) -> tuple[str, str, tuple[int, int]] | None:
    aligned = _local_word_alignment(component, candidate)
    if aligned is None or aligned[2]:
        return None
    source_words, candidate_words, _ = aligned
    if len(source_words) < 5 or source_words[0].group().casefold() != "с":
        return None
    if component[source_words[1].end():source_words[2].start()] != "-":
        return None
    if not component[source_words[2].end():source_words[3].start()].startswith(","):
        return None
    changed = [
        index
        for index, (source, replacement) in enumerate(
            zip(source_words, candidate_words, strict=True)
        )
        if source.group().casefold() != replacement.group().casefold()
    ]
    if changed != [1] or any(
        source.group() != replacement.group()
        for index, (source, replacement) in enumerate(zip(source_words, candidate_words, strict=True))
        if index != 1
    ):
        return None
    if any(
        not _matching_local_case_parses(
            source_words[index].group().casefold(),
            candidate_words[index].group().casefold(),
            frozenset({"NOUN"}),
        )
        for index in (1, 2)
    ):
        return None
    candidate_signatures = set(_case_number_signatures(candidate_words[1].group().casefold()))
    candidate_signatures.intersection_update(
        _case_number_signatures(candidate_words[2].group().casefold())
    )
    source_signatures = set(_case_number_signatures(source_words[1].group().casefold()))
    source_signatures.intersection_update(
        _case_number_signatures(source_words[2].group().casefold())
    )
    if ("gent", "sing") not in candidate_signatures or ("gent", "sing") in source_signatures:
        return None
    predicates = []
    for index in range(3, len(source_words)):
        word = source_words[index].group().casefold()
        parses = _morph().parse(word)
        if any(
            parsed.tag.POS == "VERB" and parsed.normal_form == "браться"
            for parsed in parses
        ):
            predicates.append(index)
        elif any(parsed.tag.POS in {"VERB", "INFN"} for parsed in parses):
            return None
    if len(predicates) != 1:
        return None
    source_start, source_end = source_words[1].start(), source_words[2].end()
    candidate_start, candidate_end = candidate_words[1].start(), candidate_words[2].end()
    return (
        component[source_start:source_end],
        candidate[candidate_start:candidate_end],
        source_words[0].span(),
    )


def _finite_first_subject_structure(
    words: list[re.Match[str]],
    predicate_index: int,
    candidate_number: str,
    *, allow_number_safe_genitive: bool = False,
) -> bool:
    def is_preposition(word: re.Match[str]) -> bool:
        normalized = word.group().casefold()
        return _morph().word_is_known(normalized) and any(
            parsed.tag.POS == "PREP" for parsed in _morph().parse(normalized)
        )

    def nominal_cases(word: re.Match[str]) -> frozenset[str]:
        normalized = word.group().casefold()
        return frozenset(
            case
            for parsed in _morph().parse(normalized)
            if parsed.tag.POS in _LOCAL_NOMINAL_POS
            for case in parsed.tag.grammemes & _LOCAL_CASES
        )

    def nominative_noun_numbers(word: re.Match[str]) -> frozenset[str]:
        return frozenset(
            parsed.tag.number
            for parsed in _morph().parse(word.group().casefold())
            if parsed.tag.POS == "NOUN"
            and "nomn" in parsed.tag.grammemes
            and parsed.tag.number in {"sing", "plur"}
        )

    for index, word in enumerate(words[1:predicate_index], 1):
        cases = nominal_cases(word)
        if is_preposition(word):
            continue
        if not (cases - {"nomn"}):
            return False
        numbers = nominative_noun_numbers(word)
        if numbers:
            # Do not choose an ambiguous genitive parse as semantic truth. All
            # possible nominative heads must agree with the already-proved first
            # subject's number; otherwise this closed correction abstains.
            gap = word.string[words[index - 1].end():word.start()]
            if (not allow_number_safe_genitive or "gent" not in cases or numbers != {candidate_number} or not gap
                    or any(character not in SOURCE_HORIZONTAL_SPACE for character in gap)):
                return False

    tail = words[predicate_index + 1:]
    if not tail:
        return True
    if len(tail) < 2 or not is_preposition(tail[0]) or any(
        is_preposition(word) for word in tail[1:]
    ):
        return False
    first_cases = nominal_cases(tail[1])
    if not (first_cases - {"nomn"}):
        return False
    return all(
        "gent" in (cases := nominal_cases(word)) and "nomn" not in cases
        for word in tail[2:]
    )


def _finite_subject_verb_agreement_realization(
    component: str,
    candidate: str,
) -> tuple[str, str, tuple[int, int]] | None:
    aligned = _local_word_alignment(component, candidate)
    if aligned is None:
        return None
    source_words, candidate_words, _terminal_comma_dropped = aligned
    changed = [
        index
        for index, (source, replacement) in enumerate(
            zip(source_words, candidate_words, strict=True)
        )
        if source.group().casefold() != replacement.group().casefold()
    ]
    if len(changed) != 1 or source_words[0].start() != 0:
        return None
    predicate_index = changed[0]
    if predicate_index < 1 or any(
        source.group() != replacement.group()
        for index, (source, replacement) in enumerate(zip(source_words, candidate_words, strict=True))
        if index != predicate_index
    ):
        return None
    predicate_pairs = _matching_local_parses(
        source_words[predicate_index].group().casefold(),
        candidate_words[predicate_index].group().casefold(),
        frozenset({"VERB"}),
    )
    agreements: list[tuple[_MorphParse, _MorphParse]] = []
    variable = {"sing", "plur", "masc", "femn", "neut"}
    for source_parse, candidate_parse in predicate_pairs:
        if (
            source_parse.tag.number in {"sing", "plur"}
            and candidate_parse.tag.number in {"sing", "plur"}
            and source_parse.tag.number != candidate_parse.tag.number
            and (source_parse.tag.grammemes - variable)
            == (candidate_parse.tag.grammemes - variable)
        ):
            agreements.append((source_parse, candidate_parse))
    if len(agreements) != 1:
        return None
    candidate_number = agreements[0][1].tag.number
    if candidate_number is None:
        return None  # Defensive narrowing; the agreement pair already requires a number.
    subject = source_words[0]
    if not _morph().word_is_known(subject.group().casefold()):
        return None
    subject_numbers = {
        parsed.tag.number
        for parsed in _morph().parse(subject.group().casefold())
        if parsed.tag.POS == "NOUN"
        and "nomn" in parsed.tag.grammemes
        and parsed.tag.number in {"sing", "plur"}
    }
    if subject_numbers != {candidate_number}:
        return None
    source_predicate = agreements[0][0]
    lemma = source_predicate.normal_form
    # A transitive active verb may have an omitted actor and a leading direct
    # object ("Документы комиссии проверяет"). Never turn that object into a
    # subject. The new ambiguous-genitive route needs a dictionary-owned
    # intransitive reflexive with a transitive non-reflexive counterpart.
    counterpart = lemma[:-2] if lemma.endswith("ся") else ""
    counterpart_parses = [parsed for parsed in _morph().parse(counterpart)
                          if parsed.tag.POS == "INFN"] if counterpart and _morph().word_is_known(counterpart) else []
    number_safe_reflexive = ("intr" in source_predicate.tag.grammemes and bool(counterpart_parses)
        and all("tran" in parsed.tag.grammemes for parsed in counterpart_parses))
    if not _finite_first_subject_structure(
        source_words,
        predicate_index,
        candidate_number,
        allow_number_safe_genitive=number_safe_reflexive,
    ):
        return None
    between = component[subject.end():source_words[predicate_index].start()]
    if any(character in between for character in ",;:!?\r\n"):
        return None
    condition_words = {"если", "когда", "при", "до", "после", "перед"}
    if any(
        word.group().casefold() in condition_words | {"не", "ни", "либо", "или"}
        for word in source_words[:predicate_index]
    ):
        return None
    for index, word in enumerate(source_words):
        if index == predicate_index:
            continue
        if any(parsed.tag.POS in {"VERB", "INFN", "PRTS"} for parsed in _morph().parse(word.group().casefold())):
            return None
    return (
        source_words[predicate_index].group(),
        candidate_words[predicate_index].group(),
        subject.span(),
    )


def canonical_option_typography(value: str) -> str:
    """Key-blind display only: preserve all non-horizontal characters and lines."""
    return re.sub(f"[{re.escape(SOURCE_HORIZONTAL_SPACE)}]+", " ", value)


def unsupported_option_spacing(value: str) -> bool:
    """Unknown spacing/invisible controls are not a source display equivalence."""
    return any((char.isspace() and char not in SOURCE_HORIZONTAL_SPACE + "\r\n")
        or (unicodedata.category(char) in {"Cf", "Cc"} and char not in "\t\r\n") for char in value)


def _preposition_pronoun_case_realization(
    component: str, candidate: str,
) -> tuple[str, str, tuple[int, int]] | None:
    """Align one pronoun case after a locative-only preposition, not its lemma."""
    aligned = _local_word_alignment(component, candidate)
    if aligned is None or aligned[2]:
        return None
    source_words, candidate_words, _ = aligned
    changed = [index for index, (source, replacement) in enumerate(
        zip(source_words, candidate_words, strict=True)) if source.group() != replacement.group()]
    if len(changed) != 1 or changed[0] == 0:
        return None
    index = changed[0]
    governor = source_words[index - 1]
    if governor.group().casefold() not in {"при", "о", "об", "обо"}:
        return None  # в/на and other multi-case prepositions need meaning, not this proof.
    pairs = _matching_local_case_parses(
        source_words[index].group().casefold(), candidate_words[index].group().casefold(), frozenset({"NPRO"}))
    if not any("loct" in replacement.tag.grammemes and "loct" not in source.tag.grammemes
               for source, replacement in pairs):
        return None
    return source_words[index].group(), candidate_words[index].group(), governor.span()


def _local_grammar_realization(
    component: str,
    candidate: str,
) -> tuple[str, str, str, tuple[int, int]] | None:
    display = canonical_option_typography(component)
    if unsupported_option_spacing(component) or unsupported_option_spacing(candidate):
        return None
    initial = re.match(r"[а-яёәғқңөұүһі]{2,}(?![\w-])", display)
    if component != display and (candidate == display or (initial is not None
            and candidate == display[0].upper() + display[1:])):
        return "source_horizontal_typography", component, candidate, (0, len(component))
    # An ordinary Cyrillic word may start a standalone answer with a capital.
    # No lowercasing, acronym/unit rewriting, or second-byte change is allowed.
    initial = re.match(r"[а-яёәғқңөұүһі]{2,}(?![\w-])", component)
    if initial is not None and candidate == component[0].upper() + component[1:]:
        return "initial_cyrillic_capitalization", component[0], candidate[0], (0, 1)
    according = _according_nominal_case_realization(component, candidate)
    if according is not None:
        return "according_nominal_case_alignment", *according
    compound = _from_compound_nominal_case_realization(component, candidate)
    if compound is not None:
        return "from_compound_nominal_case_alignment", *compound
    pronoun = _preposition_pronoun_case_realization(component, candidate)
    if pronoun is not None:
        return "preposition_pronoun_case_alignment", *pronoun
    agreement = _finite_subject_verb_agreement_realization(component, candidate)
    if agreement is not None:
        return "finite_subject_verb_number_agreement", *agreement
    return None


def _one_component_binding(
    rows: tuple[dict[str, object], ...],
    component_span: tuple[int, int],
) -> bool:
    return sum(
        cast(int, row["quote_start"]) <= component_span[0]
        and component_span[1] <= cast(int, row["quote_end"])
        for row in rows
    ) == 1


def source_grammar_realization_receipts(
    component: str,
    candidate: str,
    *,
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
) -> tuple[SourceGrammarRealizationReceipt, ...]:
    """Prove one closed grammatical surface family with no semantic credit."""
    if (
        not all(isinstance(value, str) and value for value in (
            component,
            candidate,
            source_context,
            source_id,
        ))
        or component != component.strip()
        or candidate != candidate.strip()
        or len(component) > MAX_TEXT_CHARS
        or len(candidate) > MAX_TEXT_CHARS
        or len(source_context) > MAX_SOURCE_CONTEXT_CHARS
    ):
        return ()
    component_span = _exact_unique_span(source_context, component)
    if component_span is None:
        return ()
    try:
        realization = _action_nominal_realization(component, candidate)
        local_realization = _local_grammar_realization(component, candidate)
    except (ImportError, OSError, RuntimeError, ValueError):
        return ()
    binding_receipt = (
        _local_grammar_bindings_receipt(
            source_context,
            source_id,
            verified_governing_bindings,
            allowed_effects=(BRANCH_EFFECTS if local_realization is not None
                and local_realization[0] in {"initial_cyrillic_capitalization", "source_horizontal_typography"}
                else frozenset({"none", "scopes_action"})),
        )
        if local_realization is not None
        else _governing_bindings_receipt(
            source_context,
            source_id,
            verified_governing_bindings,
        )
    )
    if binding_receipt is None:
        return ()
    rows, bindings_sha256 = binding_receipt
    family = ""
    source_form = ""
    candidate_form = ""
    governor_span: tuple[int, int] | None = None
    comparison_component = ""
    terminal_comma_dropped = component.endswith(",") and not candidate.endswith(",")
    if (
        local_realization is not None
        and (not terminal_comma_dropped or _one_component_binding(rows, component_span))
    ):
        family, source_form, candidate_form, local_governor_span = local_realization
        governor_span = (
            component_span[0] + local_governor_span[0],
            component_span[0] + local_governor_span[1],
        )
        comparison_component = candidate
    positive_governor = _one_positive_normative_governor(rows)
    if not family and positive_governor is not None and realization is not None:
        _, governor_span = positive_governor
        if _directly_governed_marked_component_span(
            component,
            source_context,
            governor_span,
        ) is not None:
            source_form, candidate_form = realization
            family = "action_nominal_to_infinitive"
            comparison_component = candidate
    elif not family:
        prohibition_governor = _one_prohibition_governor(rows)
        if prohibition_governor is not None:
            _, prohibition_span = prohibition_governor
            leaf_span = _governed_positive_list_leaf_span(
                component,
                source_context,
                prohibition_span,
            )
            expected = {prefix + body for prefix in ("Не ", "не ")
                        for body in (component, component.removesuffix(";"))}
            if leaf_span is not None and candidate in expected:
                governor_span = prohibition_span
                source_form = component
                candidate_form = candidate
                family = "governed_positive_leaf_to_negative_clause"
                comparison_component = candidate
    if not family or governor_span is None:
        return ()
    return (
        SourceGrammarRealizationReceipt(
            family=family,
            source_form=source_form,
            candidate_form=candidate_form,
            component_span=component_span,
            governor_span=governor_span,
            source_id=source_id,
            component_sha256=hashlib.sha256(component.encode()).hexdigest(),
            comparison_component_sha256=hashlib.sha256(
                comparison_component.encode()
            ).hexdigest(),
            candidate_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
            source_sha256=hashlib.sha256(source_context.encode()).hexdigest(),
            governing_bindings_sha256=bindings_sha256,
            policy=("source-local-grammar-realization-v1" if family in {
                "according_nominal_case_alignment",
                "from_compound_nominal_case_alignment",
                "preposition_pronoun_case_alignment",
                "finite_subject_verb_number_agreement",
                "initial_cyrillic_capitalization",
                "source_horizontal_typography",
            } else "source-grammar-realization-v1"),
        ),
    )


def source_grammar_realization_receipt_valid(
    receipt: SourceGrammarRealizationReceipt,
    component: str,
    candidate: str,
    *,
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
) -> bool:
    """Recompute a receipt; stale or altered evidence never remains valid."""
    if not isinstance(receipt, SourceGrammarRealizationReceipt):
        return False
    return receipt in source_grammar_realization_receipts(
        component,
        candidate,
        source_context=source_context,
        source_id=source_id,
        verified_governing_bindings=verified_governing_bindings,
    )


def source_grammar_realization_comparison_view(
    receipt: SourceGrammarRealizationReceipt,
    component: str,
    candidate: str,
    *,
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
) -> SourceGrammarComparisonView | None:
    """Return a comparison-only view after recomputing all receipt evidence.

    Callers keep ``component`` and ``source_context`` as the authoritative
    originals.  Failure returns no alias or partially transformed value.
    """
    if not source_grammar_realization_receipt_valid(
        receipt,
        component,
        candidate,
        source_context=source_context,
        source_id=source_id,
        verified_governing_bindings=verified_governing_bindings,
    ):
        return None
    if receipt.family in {
        "action_nominal_to_infinitive",
        "according_nominal_case_alignment",
        "from_compound_nominal_case_alignment",
        "preposition_pronoun_case_alignment",
        "finite_subject_verb_number_agreement",
        "initial_cyrillic_capitalization",
        "source_horizontal_typography",
    }:
        comparison_component = candidate
    elif receipt.family == "governed_positive_leaf_to_negative_clause":
        comparison_component = candidate
    else:
        return None
    comparison_sha256 = hashlib.sha256(comparison_component.encode()).hexdigest()
    if comparison_sha256 != receipt.comparison_component_sha256:
        return None
    return SourceGrammarComparisonView(
        family=receipt.family,
        comparison_component=comparison_component,
        candidate=candidate,
        actual_component_sha256=hashlib.sha256(component.encode()).hexdigest(),
        comparison_component_sha256=comparison_sha256,
        candidate_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
        source_sha256=hashlib.sha256(source_context.encode()).hexdigest(),
    )


def _match_unknown(
    source: _Token,
    candidate: list[_Token],
    cursor: int,
) -> tuple[int | None, PreservationIssue | None]:
    normalized = source.text.casefold()
    exact = next(
        (
            index
            for index in range(cursor, len(candidate))
            if candidate[index].alias is None
            and candidate[index].text.casefold() == normalized
        ),
        None,
    )
    if exact is not None:
        return exact, None
    return None, _issue("missing_unknown_source_token", "unknown", source.index)


def _missing_issue(token: _Token, kind: str) -> PreservationIssue:
    codes = {
        "number": "missing_numeric_token",
        "numeric_operator": "missing_numeric_operator",
        "unit": "missing_unit_token",
        "acronym": "missing_acronym",
        "protected_operator": "missing_protected_operator",
    }
    return _issue(codes.get(kind, "missing_material_token"), kind, token.index)


def _unordered_candidate_indexes(
    token: _Token,
    kind: str,
    candidate: list[_Token],
) -> list[int]:
    if kind == "unknown":
        normalized = token.text.casefold()
        return [
            index
            for index, candidate_token in enumerate(candidate)
            if candidate_token.alias is None
            and candidate_token.text.casefold() == normalized
        ]

    matches: list[int] = []
    for index, candidate_token in enumerate(candidate):
        if _kind(candidate_token) == "ignored":
            continue
        if kind in {"material", "protected_operator", "alias"}:
            matches_token = _morphological_match(token, candidate_token)
        elif kind == "numeric_operator":
            matches_token = _operator_identity(token.text) == _operator_identity(
                candidate_token.text
            )
        else:
            matches_token = token.text.casefold() == candidate_token.text.casefold()
        if matches_token:
            matches.append(index)
    return matches


def _all_required_tokens_present_unordered(
    required: list[tuple[_Token, str]],
    candidate: list[_Token],
) -> bool:
    edges = [
        _unordered_candidate_indexes(token, kind, candidate)
        for token, kind in required
    ]
    if any(not indexes for indexes in edges):
        return False

    requirement_by_candidate: dict[int, int] = {}

    def assign(requirement_index: int, seen_candidates: set[int]) -> bool:
        for candidate_index in edges[requirement_index]:
            if candidate_index in seen_candidates:
                continue
            seen_candidates.add(candidate_index)
            previous = requirement_by_candidate.get(candidate_index)
            if previous is None or assign(previous, seen_candidates):
                requirement_by_candidate[candidate_index] = requirement_index
                return True
        return False

    return all(assign(index, set()) for index in range(len(required)))


def _is_envelope_gap(value: str) -> bool:
    return all(character in _ENVELOPE_GAP_CHARS for character in value)


def _owned_adjacent_operator_index(
    component: str,
    candidate: str,
    candidate_tokens: list[_Token],
    source_context: str,
    consumed_candidate_indexes: set[int],
) -> int | None:
    if not source_context or not consumed_candidate_indexes:
        return None
    occurrence = source_context.find(component)
    if occurrence < 0 or source_context.find(component, occurrence + 1) >= 0:
        return None

    context_tokens = _normalize_exclusion_operators(
        _tokenize_context(source_context), source_context
    )
    preceding = [token for token in context_tokens if token.end <= occurrence]
    if not preceding:
        return None
    governor = preceding[-1]
    if (
        _kind(governor) != "protected_operator"
        or not _is_envelope_gap(source_context[governor.end : occurrence])
    ):
        return None

    first_component_index = min(consumed_candidate_indexes)
    candidate_prefix = [
        (index, token)
        for index, token in enumerate(candidate_tokens[:first_component_index])
        if _kind(token) != "ignored"
    ]
    if not candidate_prefix:
        return None
    operator_index, operator = candidate_prefix[-1]
    if (
        _kind(operator) != "protected_operator"
        or not _morphological_match(governor, operator)
        or not _is_envelope_gap(
            candidate[operator.end : candidate_tokens[first_component_index].start]
        )
    ):
        return None
    return operator_index


def unmapped_protected_operator_issue(
    candidate: str,
    spans: Sequence[tuple[int, int]],
) -> PreservationIssue | None:
    """Find a protected word outside exact original ``[start, end)`` spans."""

    if (
        not isinstance(candidate, str)
        or len(candidate) > MAX_TEXT_CHARS
        or isinstance(spans, str | bytes)
        or not isinstance(spans, Sequence)
        or len(spans) > MAX_TOKENS
    ):
        return _issue("invalid_protected_operator_spans", "input")

    validated_spans: list[tuple[int, int]] = []
    for span in spans:
        if (
            not isinstance(span, tuple)
            or len(span) != 2
            or not all(isinstance(offset, int) and not isinstance(offset, bool) for offset in span)
        ):
            return _issue("invalid_protected_operator_spans", "input")
        start, end = span
        if not 0 <= start < end <= len(candidate):
            return _issue("invalid_protected_operator_spans", "input")
        validated_spans.append(span)

    tokens = _tokenize(candidate)
    if tokens is None:
        return _issue("invalid_protected_operator_spans", "input")
    tokens = _normalize_exclusion_operators(tokens, candidate)
    try:
        for token in tokens:
            if _kind(token) != "protected_operator":
                continue
            if not any(
                start <= token.start and token.end <= end
                for start, end in validated_spans
            ):
                return _issue(
                    "unmapped_protected_operator",
                    "protected_operator",
                    token.index,
                )
    except (ImportError, OSError, RuntimeError, ValueError):
        return _issue("preservation_analyzer_unavailable", "analyzer")
    return None


def _component_coverage_issue(
    component: str,
    candidate: str,
    *,
    source_context: str = "",
    ignore_extra_candidate_operators: bool,
    allow_nominal_spelling: bool = False,
    allow_instruction_ellipsis: bool = False,
) -> PreservationIssue | None:
    if (
        not isinstance(component, str)
        or not isinstance(candidate, str)
        or not isinstance(source_context, str)
        or not component.strip()
        or not candidate.strip()
        or len(component) > MAX_TEXT_CHARS
        or len(candidate) > MAX_TEXT_CHARS
        or len(source_context) > MAX_SOURCE_CONTEXT_CHARS
    ):
        return _issue("invalid_preservation_input", "input")

    source = _tokenize(component)
    candidate_tokens = _tokenize(candidate)
    if not source or candidate_tokens is None:
        return _issue("invalid_preservation_input", "input")
    source = _normalize_exclusion_operators(source, component)
    candidate_tokens = _normalize_exclusion_operators(candidate_tokens, candidate)
    source = _without_inclusion_function_phrase(source, component)
    candidate_tokens = _without_inclusion_function_phrase(candidate_tokens, candidate)
    if not source:
        return _issue("invalid_preservation_input", "input")

    try:
        instruction_receipts = (source_instruction_surface_receipts(
            component, candidate, source_context=source_context) if allow_instruction_ellipsis is True else ())
        modal_indexes = {row[0] for receipt in instruction_receipts for row in receipt.modal_gerund_pairs}
        reused_predicates = {row[0]: row[1] for receipt in instruction_receipts
                             for row in receipt.repeated_predicate_pairs}
        source = [token for token in source if token.index not in modal_indexes]
        if allow_nominal_spelling is True:
            aliases = {receipt.start: receipt.dictionary_token for receipt in
                       source_nominal_spelling_receipts(component, candidate, source_context=source_context)}
            source = [replace(token, text=aliases[token.start]) if token.start in aliases else token
                      for token in source]
        source, candidate_tokens, definition_issue = _apply_explicit_aliases(
            source, candidate_tokens, source_context
        )
        if definition_issue is not None:
            return definition_issue
        source, fragment_issue = _complete_source_fragments(source, source_context)
        if fragment_issue is not None:
            return fragment_issue
        source, source_cardinal_issue = _normalize_cardinals(source)
        if source_cardinal_issue is not None:
            return source_cardinal_issue
        candidate_tokens, candidate_cardinal_issue = _normalize_cardinals(candidate_tokens)
        if candidate_cardinal_issue is not None:
            return candidate_cardinal_issue

        required = [(token, _kind(token)) for token in source]
        required = [(token, kind) for token, kind in required if kind != "ignored"]
        cursor = 0
        consumed_candidate_indexes: set[int] = set()
        for token, kind in required:
            if kind == "unknown":
                match, unknown_issue = _match_unknown(token, candidate_tokens, cursor)
                if unknown_issue is not None:
                    if _all_required_tokens_present_unordered(
                        required, candidate_tokens
                    ):
                        return _issue(
                            "source_word_order_unproved", "word_order", token.index
                        )
                    return unknown_issue
                assert match is not None
                consumed_candidate_indexes.add(match)
                cursor = match + 1
                continue

            match = next(
                (
                    index
                    for index in range(cursor, len(candidate_tokens))
                    if (
                        _kind(candidate_tokens[index]) != "ignored"
                        and (
                            _morphological_match(token, candidate_tokens[index])
                            if kind in {"material", "protected_operator", "alias"}
                            else (
                                _operator_identity(token.text)
                                == _operator_identity(candidate_tokens[index].text)
                                if kind == "numeric_operator"
                                else token.text.casefold()
                                == candidate_tokens[index].text.casefold()
                            )
                        )
                    )
                ),
                None,
            )
            reused = False
            if match is None and token.index in reused_predicates:
                prior = reused_predicates[token.index]
                if prior in consumed_candidate_indexes and _morphological_match(token, candidate_tokens[prior]):
                    match, reused = prior, True
            if match is None:
                if _all_required_tokens_present_unordered(required, candidate_tokens):
                    return _issue(
                        "source_word_order_unproved", "word_order", token.index
                    )
                return _missing_issue(token, kind)
            consumed_candidate_indexes.add(match)
            if not reused:
                cursor = match + 1
        owned_operator_index = _owned_adjacent_operator_index(
            component,
            candidate,
            candidate_tokens,
            source_context,
            consumed_candidate_indexes,
        )
        for index, token in enumerate(candidate_tokens):
            if index in consumed_candidate_indexes or index == owned_operator_index:
                continue
            candidate_kind = _kind(token)
            if candidate_kind == "protected_operator":
                if ignore_extra_candidate_operators:
                    continue
                return _issue(
                    "added_protected_operator",
                    candidate_kind,
                    token.index,
                )
            if candidate_kind == "numeric_operator":
                if ignore_extra_candidate_operators:
                    continue
                return _issue("added_numeric_operator", candidate_kind, token.index)
            if candidate_kind == "unit":
                if ignore_extra_candidate_operators:
                    continue
                return _issue("added_unit_token", candidate_kind, token.index)
    except (ImportError, RuntimeError, ValueError):
        return _issue("preservation_analyzer_unavailable", "analyzer")
    return None


def component_preservation_issue(
    component: str,
    candidate: str,
    *,
    source_context: str = "",
    allow_nominal_spelling: bool = False,
    allow_instruction_ellipsis: bool = False,
) -> PreservationIssue | None:
    """Return the first strict necessary lexical-preservation failure, if any.

    ``candidate`` is the exact mapped stem/answer composition.  Source context
    may establish a literal fragment completion, acronym definition, or exact
    adjacent operator envelope, but it never supplies a missing realization.
    """

    return _component_coverage_issue(
        component,
        candidate,
        source_context=source_context,
        ignore_extra_candidate_operators=False,
        allow_nominal_spelling=allow_nominal_spelling,
        allow_instruction_ellipsis=allow_instruction_ellipsis,
    )


def universal_object_scope_issue(source: str, candidate: str) -> PreservationIssue | None:
    """Veto loss of an explicit universal bound to the same dictionary noun.

    This necessary lexical guard does not establish entailment or completeness.
    Unknown syntax/objects are left to independent semantic review, never guessed.
    A universal attached to another noun cannot satisfy the original binding.
    """
    if (not isinstance(source, str) or not isinstance(candidate, str)
            or len(source) > MAX_SOURCE_CONTEXT_CHARS or len(candidate) > MAX_SOURCE_CONTEXT_CHARS):
        return _issue("invalid_preservation_input", "input")

    def bindings(value: str) -> tuple[
        tuple[bool, str, frozenset[str], frozenset[str], frozenset[tuple[str, str]]],
        ...,
    ]:
        words = list(re.finditer(r"[^\W_]+", value, re.UNICODE))
        word_info = [_word_info(word.group()) for word in words]
        result: list[
            tuple[bool, str, frozenset[str], frozenset[str], frozenset[tuple[str, str]]]
        ] = []

        def same_clause(left: int, right: int) -> bool:
            start = min(words[left].end(), words[right].end())
            end = max(words[left].start(), words[right].start())
            return re.search(r"[.;!?\r\n\v\f\x1c-\x1e\x85\u2028\u2029]", value[start:end]) is None

        for index, word in enumerate(words):
            universals = word_info[index].lemmas & {"весь", "каждый", "любой", "оба"}
            if len(universals) != 1:
                continue
            negated = (index > 0 and words[index - 1].group().casefold() == "не"
                       and value[words[index - 1].end():word.start()].isspace())
            quantifier = next(iter(universals))
            quantifier_class = "both" if quantifier == "оба" else "universal"
            nouns: set[str] = set()
            modifiers: set[str] = set()
            previous = word
            saw_noun = False
            conjunction_pending = False
            for following_index, following in enumerate(
                words[index + 1:index + 10],
                index + 1,
            ):
                if not value[previous.end():following.start()].isspace():
                    break  # Never cross a clause, list punctuation or hyphen.
                token = following.group()
                info = word_info[following_index]
                if token.casefold() == "и":
                    if conjunction_pending or (not saw_noun and not modifiers):
                        break
                    conjunction_pending = True
                    previous = following
                    continue
                if info.known and info.pos == "NOUN" and len(info.noun_lemmas) == 1:
                    if saw_noun and not conjunction_pending:
                        break
                    nouns.add(next(iter(info.noun_lemmas)))
                    saw_noun = True
                    conjunction_pending = False
                    previous = following
                    continue
                if saw_noun and not conjunction_pending:
                    break
                if info.known and info.parts_of_speech and info.parts_of_speech <= {"ADJF", "PRTF"}:
                    modifiers.update(info.lemmas)
                    previous = following
                    continue
                if (token.isdigit() or _cardinal_lemma(_Token(token, 0)) is not None
                        or (info.known and info.parts_of_speech
                            and info.parts_of_speech <= {"NUMR"})):
                    previous = following
                    continue
                break
            if not nouns:
                continue

            role_anchors: set[tuple[str, str]] = set()
            predicates = [
                other_index
                for other_index, info in enumerate(word_info)
                if same_clause(index, other_index)
                and bool(info.parts_of_speech & _OPERATIONAL_PREDICATE_POS)
            ]
            for noun in nouns:
                occurrences = [
                    other_index
                    for other_index, info in enumerate(word_info)
                    if same_clause(index, other_index) and noun in info.noun_lemmas
                ]
                if len(occurrences) <= 1:
                    continue
                if not predicates:
                    role_anchors.add((noun, "unresolved"))
                    continue
                nearest_predicate = min(predicates, key=lambda other_index: abs(other_index - index))
                role_anchors.add((noun, "before" if index < nearest_predicate else "after"))
            result.append((
                negated,
                quantifier_class,
                frozenset(nouns),
                frozenset(modifiers),
                frozenset(role_anchors),
            ))
        return tuple(result)

    def preserved(
        source_binding: tuple[
            bool,
            str,
            frozenset[str],
            frozenset[str],
            frozenset[tuple[str, str]],
        ],
        candidate_bindings: tuple[
            tuple[bool, str, frozenset[str], frozenset[str], frozenset[tuple[str, str]]],
            ...,
        ],
    ) -> bool:
        source_negated, source_class, source_nouns, source_modifiers, source_roles = source_binding
        return any(
            source_negated == candidate_negated
            and source_class == candidate_class
            and source_nouns <= candidate_nouns
            and source_modifiers <= candidate_modifiers
            and source_roles <= candidate_roles
            for (
                candidate_negated,
                candidate_class,
                candidate_nouns,
                candidate_modifiers,
                candidate_roles,
            ) in candidate_bindings
        )

    try:
        source_bindings = bindings(source)
        candidate_bindings = bindings(candidate)
        if any(not preserved(binding, candidate_bindings) for binding in source_bindings):
            return _issue("universal_object_scope_not_preserved", "protected_operator")
    except (ImportError, OSError, RuntimeError, ValueError):
        return _issue("preservation_analyzer_unavailable", "analyzer")
    return None


def source_governed_nominal_issue(source: str, candidate: str) -> PreservationIssue | None:
    """Veto one bounded noun-role migration, not arbitrary missing vocabulary.

    A unique shared nominal head cannot lose a coordinated genitive sibling or
    replace its complement by a noun from that same line's relative qualifier.
    Unknown, repeated, removed or nested heads stay with independent reviewers.
    Absence of a veto grants neither semantic equivalence nor completeness.
    """
    if (not isinstance(source, str) or not isinstance(candidate, str)
            or len(source) > MAX_SOURCE_CONTEXT_CHARS or len(candidate) > MAX_SOURCE_CONTEXT_CHARS):
        return _issue("invalid_preservation_input", "input")

    def noun(word: str, *, genitive: bool = False) -> str | None:
        info = _word_info(word)
        if not info.known or info.parts_of_speech != {"NOUN"} or len(info.noun_lemmas) != 1:
            return None
        if genitive and any("gent" not in row.tag.grammemes for row in _morph().parse(word)):
            return None
        return next(iter(info.noun_lemmas))

    def horizontal(value: str) -> bool:
        return bool(value) and value.isspace() and not any(mark in value for mark in _SOURCE_RULE_LINE_BREAKS)

    def bindings(value: str) -> dict[str, tuple[tuple[str, ...], str | None]]:
        words = list(re.finditer(r"[^\W_]+", value, re.UNICODE))
        nouns = [noun(word.group()) for word in words]
        occurrences = Counter(nouns)
        result: dict[str, tuple[tuple[str, ...], str | None]] = {}
        for index, head in enumerate(nouns):
            if head is None or occurrences[head] != 1:
                continue
            position, previous = index + 1, words[index]
            while position < len(words) and position <= index + 4:
                item = words[position]
                info = _word_info(item.group())
                if not horizontal(value[previous.end():item.start()]):
                    break
                if info.known and info.parts_of_speech and info.parts_of_speech <= {"ADJF", "PRTF"}:
                    previous, position = item, position + 1
                    continue
                break
            if (position >= len(words) or position > index + 4
                    or not horizontal(value[previous.end():words[position].start()])):
                continue
            complement = noun(words[position].group(), genitive=True)
            if complement is None:
                continue
            complements = [complement]
            previous, position = words[position], position + 1
            while position < len(words) and len(complements) < 8:
                item = words[position]
                gap = value[previous.end():item.start()]
                if horizontal(gap) and item.group().casefold() == "и" and position + 1 < len(words):
                    next_item = words[position + 1]
                    if not horizontal(value[item.end():next_item.start()]):
                        break
                    next_complement = noun(next_item.group(), genitive=True)
                    if next_complement is None:
                        break
                    complements.append(next_complement)
                    previous, position = next_item, position + 2
                else:
                    break
            # An adjacent noun chain has unresolved dependency ownership here.
            if (position < len(words) and nouns[position] is not None
                    and horizontal(value[previous.end():words[position].start()])):
                continue
            donor = None
            if position + 1 < len(words):
                item, relative = words[position:position + 2]
                gap = value[previous.end():item.start()]
                if (gap.strip() == "," and not any(mark in gap for mark in _SOURCE_RULE_LINE_BREAKS)
                        and nouns[position] is not None
                        and horizontal(value[item.end():relative.start()])
                        and _word_info(relative.group()).lemmas == {"который"}):
                    donor = nouns[position]
            result[head] = (tuple(complements), donor)
        return result

    try:
        original, proposed = bindings(source), bindings(candidate)
        for head in original.keys() & proposed.keys():
            old, donor = original[head]
            new, _ = proposed[head]
            lost = any(old.count(lemma) > new.count(lemma) for lemma in old)
            if lost and (len(old) > 1 and set(new) <= set(old) or donor is not None and donor in new):
                return _issue("unproved_governed_nominal_substitution", "nominal_relation")
    except (ImportError, OSError, RuntimeError, ValueError):
        return _issue("preservation_analyzer_unavailable", "analyzer")
    return None


def source_nominal_relation_issue(source: str, candidate: str) -> PreservationIssue | None:
    """Veto unproved nominal substitutions; never infer a technical correction.

    Closed morphological relations only: a replaced known modifier on the same
    source noun, or an object inserted into an exact source verb/preposition
    ellipsis. Unknown syntax is left to the independent critic. Original source
    and dictionary lemmas are never rewritten or supplemented from world knowledge.
    """
    if (not isinstance(source, str) or not isinstance(candidate, str)
            or len(source) > MAX_SOURCE_CONTEXT_CHARS or len(candidate) > MAX_SOURCE_CONTEXT_CHARS):
        return _issue("invalid_preservation_input", "input")

    def tokens(value: str) -> list[tuple[re.Match[str], _WordInfo]]:
        return [(match, _word_info(match.group())) for match in re.finditer(r"[^\W_]+", value, re.UNICODE)]

    def adjacent(value: str, left: re.Match[str], right: re.Match[str]) -> bool:
        separator = value[left.end():right.start()]
        return separator.isspace() and not any(mark in separator for mark in _SOURCE_RULE_LINE_BREAKS)

    def nominal_phrases(value: str, words: list[tuple[re.Match[str], _WordInfo]]) -> dict[str, list[frozenset[str]]]:
        phrases: dict[str, list[frozenset[str]]] = {}
        for index, (word, info) in enumerate(words):
            if not info.known or info.pos != "NOUN" or len(info.noun_lemmas) != 1:
                continue
            modifiers: set[str] = set()
            right = word
            for previous, previous_info in reversed(words[max(0, index - 4):index]):
                if (not adjacent(value, previous, right) or not previous_info.known
                        or previous_info.pos not in {"ADJF", "PRTF"}):
                    break
                # Dictionary pronominal adjectives (e.g. "такого выхода")
                # are reference words, not replacement technical modifiers.
                if "Apro" not in _morph().parse(previous.group())[0].tag.grammemes:
                    modifiers.update(previous_info.lemmas)
                right = previous
            if modifiers:
                phrases.setdefault(next(iter(info.noun_lemmas)), []).append(frozenset(modifiers))
        return phrases

    try:
        source_words, candidate_words = tokens(source), tokens(candidate)
        source_lemmas = {lemma for _, info in source_words for lemma in info.lemmas}
        source_phrases = nominal_phrases(source, source_words)
        for noun, variants in nominal_phrases(candidate, candidate_words).items():
            originals = source_phrases.get(noun, [])
            if any(original <= variant for original in originals for variant in variants):
                continue  # A shorter heading has not replaced the exact taught term.
            for modifiers in variants:
                if (originals and modifiers - source_lemmas
                        and all(original - modifiers for original in originals)):
                    return _issue("unproved_nominal_modifier_substitution", "nominal_relation")

        # Do not resolve an omitted source object from another sentence merely
        # because a plausible noun occurs somewhere in the same source fact.
        def explicit_objects(value: str, words: list[tuple[re.Match[str], _WordInfo]]) -> dict[tuple[str, str], set[str]]:
            objects: dict[tuple[str, str], set[str]] = {}
            for index, (word, info) in enumerate(words):
                if not info.known or info.pos not in {"INFN", "VERB"}:
                    continue
                nominals: set[str] = set()
                previous = word
                for following, following_info in words[index + 1:index + 8]:
                    if not adjacent(value, previous, following):
                        break
                    if following_info.pos == "PREP":
                        for verb in info.lemmas:
                            for prep in following_info.lemmas:
                                objects.setdefault((verb, prep), set()).update(nominals)
                        break
                    if following_info.pos in {"NOUN", "NPRO"}:
                        nominals.update(following_info.lemmas)
                    elif following_info.pos not in {"ADJF", "PRTF"}:
                        break
                    previous = following
            return objects

        source_objects = explicit_objects(source, source_words)
        ellipses: dict[tuple[str, str], set[str]] = {}
        for (word, info), (following, following_info) in zip(source_words, source_words[1:], strict=False):
            if (info.known and info.pos in {"INFN", "VERB"}
                    and following_info.known and following_info.pos == "PREP"
                    and adjacent(source, word, following)):
                before = list(re.finditer(r"[.!?;\r\n]", source[:word.start()]))
                start = before[-1].end() if before else 0
                after = re.search(r"[.!?;\r\n]", source[following.end():])
                end = following.end() + after.start() if after else len(source)
                clause_nominals = {lemma for _, item in tokens(source[start:end])
                                   if item.pos in {"NOUN", "NPRO"} for lemma in item.lemmas}
                for verb in info.lemmas:
                    for prep in following_info.lemmas:
                        ellipses.setdefault((verb, prep), set()).update(clause_nominals)
        for index, (word, info) in enumerate(candidate_words):
            if not info.known or info.pos not in {"INFN", "VERB"}:
                continue
            expected = {prep for verb, prep in ellipses if verb in info.lemmas}
            if not expected:
                continue
            inserted: set[str] = set()
            previous = word
            for following, following_info in candidate_words[index + 1:index + 8]:
                if not adjacent(candidate, previous, following):
                    break
                if following_info.pos == "PREP":
                    for prep in expected & following_info.lemmas:
                        available = set().union(*(ellipses.get((verb, prep), set()) for verb in info.lemmas))
                        available.update(*(source_objects.get((verb, prep), set()) for verb in info.lemmas))
                        if inserted - available:
                            return _issue("unproved_inserted_ellipsis_object", "nominal_relation")
                    break
                if following_info.pos in {"NOUN", "NPRO"}:
                    inserted.update(following_info.lemmas)
                elif following_info.pos not in {"ADJF", "PRTF"}:
                    break
                previous = following
    except (ImportError, OSError, RuntimeError, ValueError):
        return _issue("preservation_analyzer_unavailable", "analyzer")
    return None


def component_repair_coverage_issue(
    component: str,
    candidate: str,
    *,
    source_context: str = "",
) -> PreservationIssue | None:
    """Probe source-token coverage for repair routing, never admission.

    Unlike the strict check, this probe ignores extra candidate protected,
    numeric-operator, and unit tokens belonging to other mapped components.
    Every source token remains required in canonical source order.
    """

    return _component_coverage_issue(
        component,
        candidate,
        source_context=source_context,
        ignore_extra_candidate_operators=True,
    )
