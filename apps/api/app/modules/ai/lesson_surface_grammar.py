"""Closed candidate-only grammar normalization before fresh lesson review.

This module never reads or rewrites source facts and never grants semantic
approval.  It exposes exact candidate-byte changes for subsequent independent
surface and language review.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

_MAX_BLOCKS = 64
_MAX_BLOCK_TEXT_CHARS = 24_000
_MAX_OPERATIONS = 64
_RUSSIAN_HYPHENATED_NOUN = re.compile(
    r"(?<![\w-])(?P<left>[А-Яа-яЁё]+)-(?P<right>[А-Яа-яЁё]+)(?![\w-])"
)
_PRECEDING_RUSSIAN_WORD = re.compile(r"(?P<word>[А-Яа-яЁё]+)\s+$")
_CASES = frozenset({"nomn", "gent", "datv", "accs", "ablt", "loct"})
_NUMBERS = frozenset({"sing", "plur"})
_PROPER_GRAMMEMES = frozenset({"Name", "Surn", "Patr", "Geox", "Orgn"})
_COLLIDING_INNER_QUOTES = frozenset("„“‹›")
# Standard Russian government, not a document/target/entity allowlist. Unknown
# and compound prepositions deliberately abstain. Ambiguous government remains
# explicit so every surviving correction must converge to one spelling.
_PREPOSITION_CASES: Mapping[str, frozenset[str]] = {
    "без": frozenset({"gent"}),
    "близ": frozenset({"gent"}),
    "в": frozenset({"accs", "loct"}),
    "вне": frozenset({"gent"}),
    "во": frozenset({"accs", "loct"}),
    "вокруг": frozenset({"gent"}),
    "для": frozenset({"gent"}),
    "до": frozenset({"gent"}),
    "за": frozenset({"accs", "ablt"}),
    "из": frozenset({"gent"}),
    "к": frozenset({"datv"}),
    "ко": frozenset({"datv"}),
    "кроме": frozenset({"gent"}),
    "между": frozenset({"gent", "ablt"}),
    "на": frozenset({"accs", "loct"}),
    "над": frozenset({"ablt"}),
    "надо": frozenset({"ablt"}),
    "о": frozenset({"accs", "loct"}),
    "об": frozenset({"accs", "loct"}),
    "обо": frozenset({"accs", "loct"}),
    "около": frozenset({"gent"}),
    "от": frozenset({"gent"}),
    "перед": frozenset({"ablt"}),
    "по": frozenset({"datv", "accs", "loct"}),
    "под": frozenset({"accs", "ablt"}),
    "при": frozenset({"loct"}),
    "про": frozenset({"accs"}),
    "против": frozenset({"gent"}),
    "ради": frozenset({"gent"}),
    "с": frozenset({"gent", "accs", "ablt"}),
    "сквозь": frozenset({"accs"}),
    "со": frozenset({"gent", "accs", "ablt"}),
    "у": frozenset({"gent"}),
    "через": frozenset({"accs"}),
}


@dataclass(frozen=True, slots=True)
class LessonSurfaceGrammarOperation:
    block_index: int
    part: Literal["heading", "body"]
    code: str
    start: int
    end: int
    before: str
    after: str
    before_sha256: str
    after_sha256: str
    dictionary_proof: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LessonSurfaceGrammarResult:
    """Immutable normalized candidate text plus exact diagnostic custody."""

    block_headings: tuple[str, ...]
    block_texts: tuple[str, ...]
    before_sha256: str
    after_sha256: str
    changed_block_indices: tuple[int, ...]
    operations: tuple[LessonSurfaceGrammarOperation, ...]


@dataclass(frozen=True, slots=True)
class ProseGrammarComparisonView:
    """Raw-bound dictionary operations; this view never replaces evidence."""

    text: str
    raw_sha256: str
    comparison_sha256: str
    operations: tuple[LessonSurfaceGrammarOperation, ...]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _text_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _morphology() -> Any:
    from app.modules.ai.assessment_preservation import _morph

    return _morph()


def _known_common_animate_noun_parses(word: str) -> tuple[Any, ...]:
    analyzer = _morphology()
    if not analyzer.word_is_known(word):
        return ()
    parsed = tuple(analyzer.parse(word))
    if any(_PROPER_GRAMMEMES & frozenset(row.tag.grammemes) for row in parsed):
        return ()
    nouns = tuple(
        row
        for row in parsed
        if row.tag.POS == "NOUN" and "anim" in row.tag.grammemes
    )
    if not nouns or len({row.normal_form for row in nouns}) != 1:
        return ()
    return nouns


def _case_number_rows(parses: Sequence[Any]) -> frozenset[tuple[str, str]]:
    rows: set[tuple[str, str]] = set()
    for parsed in parses:
        cases = _CASES & frozenset(parsed.tag.grammemes)
        numbers = _NUMBERS & frozenset(parsed.tag.grammemes)
        rows.update((case, number) for case in cases for number in numbers)
    return frozenset(rows)


def _compatible_noun_genders(
    left_parses: Sequence[Any],
    right_parses: Sequence[Any],
) -> frozenset[str]:
    def genders(parses: Sequence[Any]) -> set[str]:
        values = {
            gender
            for parsed in parses
            for gender in {"masc", "femn", "neut", "ms-f"} & set(parsed.tag.grammemes)
        }
        if "ms-f" in values:
            values.update({"masc", "femn"})
        return values

    return frozenset(genders(left_parses) & genders(right_parses))


def _preserve_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper() and source[1:].islower():
        return replacement.capitalize()
    return replacement


def _inflected_forms(
    parses: Sequence[Any],
    *,
    case: str,
    number: str,
    source: str,
) -> frozenset[str]:
    forms: set[str] = set()
    for parsed in parses:
        inflected = parsed.inflect({case, number})
        if inflected is not None and inflected.normal_form == parsed.normal_form:
            forms.add(_preserve_case(source, inflected.word))
    return frozenset(forms)


def _external_case_targets(
    text: str,
    start: int,
    left_parses: Sequence[Any],
    right_parses: Sequence[Any],
    noun_genders: frozenset[str],
) -> tuple[frozenset[tuple[str, str]], str] | None:
    preceding = _PRECEDING_RUSSIAN_WORD.search(text[:start])
    if preceding is None:
        return None
    analyzer = _morphology()
    word = preceding["word"].casefold()
    if not analyzer.word_is_known(word):
        return None
    external_parses = tuple(analyzer.parse(word))
    if external_parses and external_parses[0].tag.POS == "PREP":
        licensed_cases = _PREPOSITION_CASES.get(external_parses[0].normal_form)
        if not licensed_cases:
            return None
        preposition_targets = frozenset(
            row
            for row in _case_number_rows(left_parses) | _case_number_rows(right_parses)
            if row[0] in licensed_cases
        )
        return (
            (preposition_targets, "external_preposition_government")
            if preposition_targets
            else None
        )
    modifier_parses = tuple(
        parsed
        for parsed in external_parses
        if parsed.tag.POS in {"ADJF", "PRTF"}
    )
    modifier_targets = frozenset(
        row
        for row in _case_number_rows(modifier_parses)
        if row[1] == "plur" or any(
            row[0] in parsed.tag.grammemes
            and row[1] in parsed.tag.grammemes
            and noun_genders & frozenset(parsed.tag.grammemes)
            for parsed in modifier_parses
        )
    )
    return (
        (modifier_targets, "external_modifier_case_number")
        if modifier_targets
        else None
    )


def _appositional_correction(
    text: str,
    match: re.Match[str],
) -> tuple[str, tuple[str, ...]] | None:
    analyzer = _morphology()
    original = match.group(0)
    if analyzer.word_is_known(original.casefold()):
        return None
    left, right = match["left"], match["right"]
    left_parses = _known_common_animate_noun_parses(left.casefold())
    right_parses = _known_common_animate_noun_parses(right.casefold())
    if not left_parses or not right_parses:
        return None
    noun_genders = _compatible_noun_genders(left_parses, right_parses)
    if not noun_genders:
        return None
    licensed = _external_case_targets(
        text,
        match.start(),
        left_parses,
        right_parses,
        noun_genders,
    )
    if licensed is None:
        return None
    targets, license_proof = licensed
    corrections: set[str] = set()
    for case, number in targets:
        left_forms = _inflected_forms(
            left_parses,
            case=case,
            number=number,
            source=left,
        )
        right_forms = _inflected_forms(
            right_parses,
            case=case,
            number=number,
            source=right,
        )
        if len(left_forms) != 1 or len(right_forms) != 1:
            continue
        corrected_left = next(iter(left_forms))
        corrected_right = next(iter(right_forms))
        changes = int(corrected_left != left) + int(corrected_right != right)
        if changes == 1:
            corrections.add(corrected_left + "-" + corrected_right)
    if len(corrections) != 1:
        return None
    corrected = next(iter(corrections))
    if corrected == original:
        return None
    return corrected, (
        "dictionary_animate_common_nouns",
        "distinct_stable_lexemes",
        license_proof,
        "single_convergent_inflection",
        "one_existing_part_already_agrees",
    )


def _normalize_appositions(
    text: str,
    *,
    block_index: int,
    part: Literal["heading", "body"],
) -> tuple[str, list[LessonSurfaceGrammarOperation]]:
    original = text
    operations: list[LessonSurfaceGrammarOperation] = []
    cursor = 0
    while True:
        match = _RUSSIAN_HYPHENATED_NOUN.search(text, cursor)
        if match is None:
            break
        correction = _appositional_correction(text, match)
        if correction is None:
            cursor = match.end()
            continue
        if len(operations) >= _MAX_OPERATIONS:
            return original, []
        after, proof = correction
        before = match.group(0)
        text = text[: match.start()] + after + text[match.end() :]
        end = match.start() + len(after)
        operations.append(
            LessonSurfaceGrammarOperation(
                block_index=block_index,
                part=part,
                code="animate_hyphen_apposition_agreement",
                start=match.start(),
                end=end,
                before=before,
                after=after,
                before_sha256=_text_digest(before),
                after_sha256=_text_digest(after),
                dictionary_proof=proof,
            )
        )
        cursor = end
    return text, operations


def _nested_guillemet_pairs(text: str) -> tuple[tuple[int, int], ...]:
    if any(character in text for character in _COLLIDING_INNER_QUOTES):
        return ()
    stack: list[int] = []
    inner: list[tuple[int, int]] = []
    maximum_depth = 0
    for index, character in enumerate(text):
        if character == "«":
            stack.append(index)
            maximum_depth = max(maximum_depth, len(stack))
        elif character == "»":
            if not stack:
                return ()
            opened = stack.pop()
            if len(stack) == 1:
                inner.append((opened, index))
    if stack or maximum_depth != 2 or not inner:
        return ()
    return tuple(inner)


def _normalize_nested_guillemets(
    text: str,
    *,
    block_index: int,
    part: Literal["heading", "body"],
) -> tuple[str, list[LessonSurfaceGrammarOperation]]:
    pairs = _nested_guillemet_pairs(text)
    if not pairs or len(pairs) > _MAX_OPERATIONS:
        return text, []
    characters = list(text)
    operations: list[LessonSurfaceGrammarOperation] = []
    for opened, closed in pairs:
        before = text[opened : closed + 1]
        after = "„" + text[opened + 1 : closed] + "“"
        characters[opened], characters[closed] = "„", "“"
        operations.append(
            LessonSurfaceGrammarOperation(
                block_index=block_index,
                part=part,
                code="balanced_nested_guillemets",
                start=opened,
                end=closed + 1,
                before=before,
                after=after,
                before_sha256=_text_digest(before),
                after_sha256=_text_digest(after),
                dictionary_proof=(
                    "balanced_outer_and_inner_guillemets",
                    "maximum_quote_depth_two",
                    "all_non_quote_characters_preserved",
                ),
            )
        )
    return "".join(characters), operations


def _normalize_part(
    value: str,
    *,
    block_index: int,
    part: Literal["heading", "body"],
) -> tuple[str, list[LessonSurfaceGrammarOperation]]:
    original = value
    value, agreement = _normalize_appositions(
        value,
        block_index=block_index,
        part=part,
    )
    value, quotes = _normalize_nested_guillemets(
        value,
        block_index=block_index,
        part=part,
    )
    operations = [*agreement, *quotes]
    return (original, []) if len(operations) > _MAX_OPERATIONS else (value, operations)


def _validated_blocks(
    blocks: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if (
        not isinstance(blocks, Sequence)
        or isinstance(blocks, str | bytes)
        or not 1 <= len(blocks) <= _MAX_BLOCKS
    ):
        raise ValueError("lesson_surface_grammar_invalid_blocks")
    validated: list[dict[str, object]] = []
    for block in blocks:
        if not isinstance(block, Mapping) or any(not isinstance(key, str) for key in block):
            raise ValueError("lesson_surface_grammar_invalid_block")
        heading = block.get("heading")
        text = block.get("text")
        fact_ids = block.get("fact_ids")
        if (
            not isinstance(heading, str)
            or not isinstance(text, str)
            or not heading
            or not text
            or max(len(heading), len(text)) > _MAX_BLOCK_TEXT_CHARS
            or not isinstance(fact_ids, Sequence)
            or isinstance(fact_ids, str | bytes)
            or not fact_ids
            or any(not isinstance(fact_id, str) or not fact_id for fact_id in fact_ids)
        ):
            raise ValueError("lesson_surface_grammar_invalid_block_fields")
        validated.append(dict(block))
    try:
        _digest(validated)
    except (TypeError, ValueError) as exc:
        raise ValueError("lesson_surface_grammar_invalid_block_json") from exc
    return validated


def prose_grammar_comparison_view(value: str) -> ProseGrammarComparisonView:
    """Expose the existing exact operations without adding a comparison alias."""
    if not isinstance(value, str) or not value or len(value) > _MAX_BLOCK_TEXT_CHARS:
        raise ValueError("authored_prose_grammar_invalid_text")
    normalized, operations = _normalize_part(value, block_index=0, part="body")
    return ProseGrammarComparisonView(normalized, _text_digest(value),
        _text_digest(normalized), tuple(operations))


def normalize_authored_prose(value: str) -> str:
    """Apply the same bounded grammar to authored prose before fresh review.

    This returns no source, key, semantic or language approval. The caller must
    bind all independent reviews to the returned candidate bytes.
    """
    return prose_grammar_comparison_view(value).text


def normalize_lesson_surface_grammar(
    blocks: Sequence[Mapping[str, object]],
) -> LessonSurfaceGrammarResult:
    """Return a candidate-only normalized view for mandatory fresh review."""
    original = _validated_blocks(blocks)
    normalized = [dict(block) for block in original]
    operations: list[LessonSurfaceGrammarOperation] = []
    for block_index, block in enumerate(normalized):
        heading, heading_operations = _normalize_part(
            str(block["heading"]),
            block_index=block_index,
            part="heading",
        )
        text, body_operations = _normalize_part(
            str(block["text"]),
            block_index=block_index,
            part="body",
        )
        block["heading"] = heading
        block["text"] = text
        operations.extend(heading_operations)
        operations.extend(body_operations)
    changed = tuple(
        index
        for index, (before, after) in enumerate(zip(original, normalized, strict=True))
        if (before["heading"], before["text"]) != (after["heading"], after["text"])
    )
    return LessonSurfaceGrammarResult(
        block_headings=tuple(str(block["heading"]) for block in normalized),
        block_texts=tuple(str(block["text"]) for block in normalized),
        before_sha256=_digest(original),
        after_sha256=_digest(normalized),
        changed_block_indices=changed,
        operations=tuple(operations),
    )
