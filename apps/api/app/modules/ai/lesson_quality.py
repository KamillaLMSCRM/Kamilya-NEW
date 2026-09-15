"""Deterministic admission policy for generated lesson drafts.

The policy does not attempt semantic grading.  It rejects only observable
failure modes that should never reach a methodologist: source-free filler,
verbatim sentence repetition, and an implausibly thin response for a
substantive source excerpt.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_TOKEN_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_RELATIONSHIP_TOKEN_RE = re.compile(r"[\w./-]+", re.UNICODE)
_RELATIONSHIP_FRAGMENT_SPLIT_RE = re.compile(r"(?:[!?]+|\n+|\.(?!\w)|(?<!\w)\.)")
_SENTENCE_RE = re.compile(r"(?:\n+|(?<=[.!?])\s+)")
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_NUMERIC_FRAGMENT_SPLIT_RE = re.compile(r"(?:\n+|(?<=[!?])\s+|(?<!\d)\.(?!\d)\s+)")
_NUMERIC_VALUE_RE = re.compile(
    r"(?P<date>\b(?:\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{4})\b)"
    r"|(?P<percent>(?<![\w-])-?\d+(?:[.,]\d+)?\s*%)"
    r"|(?P<number>(?<![\w-])-?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)"
    r"(?:[.,]\d+)?(?:[^\W\d_]+)?)"
)
_NUMERIC_SUBJECT_RE = re.compile(
    r"\b(?:продукт|product|коллекция|collection|sku|кейс|case|артикул|article)\s+([^\s:;,.()]+)",
    re.IGNORECASE,
)
_SOURCE_IDENTIFIER_HEADER_RE = re.compile(
    r"^(?:артикул|article(?:\s+(?:number|no\.?))?|sku|код|code|product\s+id|идентификатор)$",
    re.IGNORECASE,
)
_SOURCE_IDENTIFIER_RE = re.compile(r"(?<!\w)(?:\d{5,}|(?=[\w.-]*\d)[A-ZА-ЯЁ0-9][\w.-]{3,})(?!\w)", re.IGNORECASE)
_ENTITY_SCOPE_RE = re.compile(
    r"\b(?:коллекци\w*|collection|систем\w*|system|модел\w*|model|сери\w*|series)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(r"\b(?:в\s+отличие|по\s+сравнению|compared\s+with|unlike)\b", re.IGNORECASE)
_SOURCE_CONFLICT_DISCLOSURE_RE = re.compile(
    r"\b(?:расхожд\w*|противореч\w*|конфликт\w*|неоднознач\w*|"
    r"уточн\w*|different|conflict\w*|contradict\w*|inconsisten\w*|clarif\w*)\b",
    re.IGNORECASE,
)
_GUIDE_CONTEXT_RE = re.compile(r"\b(?:направляющ\w*|guides?)\b", re.IGNORECASE)
_GUIDE_VALUE_PATTERNS = {
    "roller": re.compile(r"\b(?:роликов\w*|roller)\b", re.IGNORECASE),
    "ball_bearing": re.compile(r"\b(?:шариков\w*|ball[- ]bearing)\b", re.IGNORECASE),
}
_MARKETPLACE_TERM = r"(?:маркетплейс\w*|маркет-?плейс\w*|marketplaces?)"
_UNPROFESSIONAL_LEARNER_LANGUAGE_RE = re.compile(
    r"(?:\bсовременн\w*\s+look\b|\bне\s+[«\"']?игрушечн\w*[»\"']?\b|"
    rf"\bне\s+[«\"']?с\s+{_MARKETPLACE_TERM}[»\"']?\b|"
    rf"\bкомпакт\w*\s+с\s+{_MARKETPLACE_TERM}\b|"
    rf"\b(?:в\s+отличие\s+от|превосход\w*|не\s+назва\w*|не\s+как\s+у)"
    rf"[^.!?]{{0,120}}\b{_MARKETPLACE_TERM}\b)",
    re.IGNORECASE,
)
_MODERN_LOOK_RE = re.compile(r"\bсовременн\w*\s+look\b", re.IGNORECASE)
_TOY_SIZE_RE = re.compile(r",?\s*не\s+[«\"']?игрушечн\w*[»\"']?", re.IGNORECASE)
_MARKETPLACE_COMPACT_RE = re.compile(
    rf",?\s*(?:а\s+)?не\s+компакт\w*\s+с\s+{_MARKETPLACE_TERM}",
    re.IGNORECASE,
)
_MARKETPLACE_NEGATION_RE = re.compile(
    rf"\s*[«\"']?не\s+[«\"']?с\s+{_MARKETPLACE_TERM}[»\"']?",
    re.IGNORECASE,
)
_MARKETPLACE_CONTRAST_PREFIX_RE = re.compile(
    rf"\bв\s+отличие\s+от\s+[^,.!?;]{{0,120}}\b{_MARKETPLACE_TERM}\b\s*[,;:]?\s*",
    re.IGNORECASE,
)
_MARKETPLACE_RELATIVE_RE = re.compile(
    rf",?\s*котор\w*\s+не\s+назва\w*\s+[«\"']?с\s+{_MARKETPLACE_TERM}[»\"']?",
    re.IGNORECASE,
)
_MARKETPLACE_NOT_LIKE_RE = re.compile(
    rf",?\s*не\s+как\s+у\s+[^,.!?;]{{0,120}}\b{_MARKETPLACE_TERM}\b",
    re.IGNORECASE,
)
_MARKETPLACE_SUPERIORITY_RE = re.compile(
    rf"(\bпревосход\w*\s+[^.!?]{{0,120}}?)\s+(?:с\s+)?{_MARKETPLACE_TERM}\b",
    re.IGNORECASE,
)


def has_unprofessional_learner_language(text: str) -> bool:
    """Return whether learner-visible text contains a blocked sales-style phrase."""

    return bool(_UNPROFESSIONAL_LEARNER_LANGUAGE_RE.search(text))


def neutralize_unprofessional_source_language(text: str) -> str:
    """Remove known sales-style comparisons while preserving source facts."""

    if not has_unprofessional_learner_language(text):
        return text
    neutral = _MODERN_LOOK_RE.sub("современный внешний вид", text)
    neutral = _TOY_SIZE_RE.sub("", neutral)
    neutral = _MARKETPLACE_COMPACT_RE.sub("", neutral)
    neutral = _MARKETPLACE_NEGATION_RE.sub("", neutral)
    neutral = _MARKETPLACE_CONTRAST_PREFIX_RE.sub("", neutral)
    neutral = _MARKETPLACE_RELATIVE_RE.sub("", neutral)
    neutral = _MARKETPLACE_NOT_LIKE_RE.sub("", neutral)
    neutral = _MARKETPLACE_SUPERIORITY_RE.sub(r"\1", neutral)
    neutral = re.sub(r"\s+([,.!?])", r"\1", neutral)
    neutral = re.sub(r",\s*,", ",", neutral)
    neutral = re.sub(r"\s+", " ", neutral).strip()
    return neutral


_GUIDE_SCOPE_TOKENS = {
    "guide", "guides", "drawer", "drawers", "type",
    "направляющие", "направляющих", "направляющая", "тип",
    "роликовые", "роликовых", "роликовыми",
    "шариковые", "шариковых", "шариковыми",
    "телескопические", "телескопических",
    "ящики", "ящиков", "ящиках",
}
_ENTITY_GENERIC_TOKENS = frozenset(
    {
        "article", "артикул", "collection", "коллекция", "коллекции", "system", "система",
        "model", "модель", "series", "серия", "product", "продукт", "cabinet", "шкаф",
        "door", "doors", "дверь", "двери", "opening", "открывание", "uses", "with",
    }
)
_INCOMPLETE_FORMULA_PRESENTATION_RE = re.compile(
    r"(?:по\s+следующ\w*\s+формул\w*|using\s+the\s+following\s+formula)"
    r"\s*(?:[:,])\s*(?:\n\s*)*(?:где|where)\s*:",
    re.IGNORECASE,
)
_STOP_WORDS = frozenset(
    {
        "для",
        "или",
        "как",
        "это",
        "этот",
        "эта",
        "эти",
        "того",
        "при",
        "что",
        "чтобы",
        "который",
        "которая",
        "которые",
        "также",
        "есть",
        "уже",
        "можно",
        "нужно",
        "будет",
        "быть",
        "его",
        "она",
        "они",
        "and",
        "the",
        "this",
        "that",
        "with",
        "from",
        "into",
        "your",
        "мен",
        "бұл",
        "және",
        "немесе",
        "керек",
        "болып",
        "урок",
        "уроке",
        "курса",
        "курс",
        "раздел",
        "модуль",
        "материал",
    }
)
_GENERIC_MARKERS = (
    "в этом уроке мы разберем",
    "в данном уроке мы разберем",
    "в этом уроке вы узнаете",
    "давайте разберем",
    "материал поможет лучше понять",
    "подведем итоги",
    "теперь вы знаете",
    "in this lesson we will",
    "this lesson will help you",
    "let us explore",
    "to summarize",
)
_UNSUPPORTED_RELATIONSHIP_PATTERNS = (
    re.compile(r"\b(?:прямо|напрямую)\s+связан\w*\b"),
    re.compile(
        r"\b(?:связан\w*\s+с(?:о)?|links?\s+(?:to|with)|"
        r"(?:is\s+)?linked\s+(?:to|with)|(?:is\s+)?related\s+to|"
        r"relates?\s+to)\b"
    ),
    re.compile(r"\bоснов\w*\s+для\b"),
    re.compile(
        r"\b[\w./-]+\b.{0,80}\b(?:определя\w*|обусловлива\w*|" r"привод\w*|требу\w*|determines?|causes?|requires?)\b"
    ),
    re.compile(r"\bпоэтому\b.{0,100}\b(?:важно|нужно|следует|необходимо)\b"),
    re.compile(r"\bзначит\b.{0,140}\b(?:рабоч\w*\s+шаг\w*|важно|нужно|следует|необходимо)\b"),
    re.compile(
        r"\b(?:преимуществ\w*|материал\w*|размер\w*|каталог\w*)\b.{0,120}"
        r"\b(?:определя\w*|обусловлива\w*|привод\w*|требу\w*)\b"
    ),
    re.compile(r"\b(?:directly linked|directly related|basis for)\b"),
    re.compile(r"\btherefore\b.{0,100}\b(?:must|should|need)\b"),
    re.compile(r"\b(?:если\s+клиент\w*|if\s+(?:the\s+)?customer\w*)\b"),
    re.compile(r"\b(?:начн\w*\s+с|диалог\w*.{0,80}\bначина\w*|" r"start\w*\s+with|conversation\w*.{0,80}\bbegin\w*)\b"),
    re.compile(
        r"\b(?:используйте|можно\s+использовать|использовать.{0,40}\bкак|"
        r"построй\w*|подавай\w*|соотнес\w*|предложите|предлагайте|"
        r"предложить|use|can\s+be\s+used)\b"
    ),
    re.compile(
        r"(?:^|[.!?]\s+|\n)\s*(?:[-*+>]\s+|\d+[.)]\s+)?"
        r"(?:(?:action|recommendation)\s*[:\-—]\s*)?"
        r"(?:please\s+)?(?:\*\*|__)?(?:recommend|offer)(?:\*\*|__)?(?!\w)"
    ),
    re.compile(
        r"\b(?:(?:we|you)\s+(?:\w+\s+){0,2}|" r"(?:should|must|can|may)\s+(?:\w+\s+){0,2})" r"(?:recommend|offer)\b"
    ),
    re.compile(r"\b(?:ориентир\w*|serves?\s+as\s+(?:a\s+)?guide\w*)\b"),
)
_RELATIONSHIP_OPERATOR_ROOTS = (
    "определ",
    "обуслов",
    "привод",
    "требу",
    "связан",
    "поэтому",
    "значит",
    "важно",
    "нужно",
    "следует",
    "необходимо",
    "direct",
    "link",
    "relat",
    "basis",
    "therefore",
    "must",
    "should",
    "need",
    "если",
    "клиент",
    "начн",
    "диалог",
    "использ",
    "постро",
    "подава",
    "соотнес",
    "ориентир",
    "customer",
    "start",
    "conversation",
    "use",
    "guide",
    "предлож",
    "recommend",
    "offer",
)
_RELATIONSHIP_OPERATOR_RE = re.compile(
    r"\b(?:(?:прямо|напрямую)\s+связан\w*|основ\w*\s+для|"
    r"связан\w*\s+с(?:о)?|links?\s+(?:to|with)|"
    r"(?:is\s+)?linked\s+(?:to|with)|(?:is\s+)?related\s+to|"
    r"relates?\s+to|"
    r"определя\w*|обусловлива\w*|привод\w*|требу\w*|поэтому|значит|"
    r"directly\s+(?:linked|related)|basis\s+for|therefore|"
    r"determines?|causes?|requires?|must|should|need|"
    r"если\s+клиент\w*|if\s+(?:the\s+)?customer\w*|"
    r"начн\w*\s+с|диалог\w*.{0,80}\bначина\w*|"
    r"start\w*\s+with|conversation\w*.{0,80}\bbegin\w*|"
    r"используйте|можно\s+использовать|использовать.{0,40}\bкак|построй\w*|подавай\w*|"
    r"соотнес\w*|предложите|предлагайте|предложить|use\w*|can\s+be\s+used|"
    r"(?:\*\*|__)?(?:recommend\w*|offer)(?:\*\*|__)?|"
    r"ориентир\w*|serves?\s+as\s+(?:a\s+)?guide\w*)\b"
)
_RELATIONSHIP_SHORT_STOP_WORDS = frozenset(
    {
        "в",
        "во",
        "на",
        "по",
        "к",
        "ко",
        "с",
        "со",
        "о",
        "об",
        "от",
        "до",
        "из",
        "за",
        "у",
        "и",
        "а",
        "но",
        "не",
        "то",
        "же",
        "бы",
        "ли",
        "of",
        "to",
        "is",
        "as",
        "at",
        "by",
        "in",
        "on",
        "or",
        "an",
        "be",
        "if",
    }
)
LESSON_QUALITY_POLICY_VERSION = "lesson-quality-v20"


def _normalize(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold().replace("ё", "е")))


def _content_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _normalize(value).split() if token not in _STOP_WORDS)


def _without_approved_title_heading(content: str, title: str) -> str:
    """Remove only a Markdown heading identical to the approved lesson title.

    The architect title is validated before the writer runs. Repeating that
    title as H1/H2 must neither supply body grounding nor be reclassified as a
    new relationship claim. Other headings remain part of quality admission.
    """

    normalized_title = _normalize(title)
    retained: list[str] = []
    for line in content.splitlines():
        match = _MARKDOWN_HEADING_RE.fullmatch(line)
        if match is not None and _normalize(match.group(1)) == normalized_title:
            continue
        retained.append(line)
    return "\n".join(retained)


def _relationship_tokens(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    raw_tokens = _RELATIONSHIP_TOKEN_RE.findall(value.replace("ё", "е"))
    for raw_token in raw_tokens:
        token = raw_token.casefold().strip("._-/")
        if not token or token in _STOP_WORDS or token in _RELATIONSHIP_SHORT_STOP_WORDS:
            continue
        if any(character.isdigit() for character in token) or len(token) >= 2:
            tokens.append(token)
    return tuple(tokens)


def _sentences(value: str) -> tuple[str, ...]:
    cleaned = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    return tuple(normalized for raw in _SENTENCE_RE.split(cleaned) for normalized in [_normalize(raw)] if normalized)


def _numeric_fact_key(match: re.Match[str]) -> str:
    """Normalize only equivalent renderings of one explicit numeric fact."""

    value = match.group(0).strip()
    if match.group("date"):
        parts = re.split(r"[-./]", value)
        if len(parts[0]) == 4:
            year, month, day = parts
        else:
            day, month, year = parts
        return f"date:{int(year):04d}-{int(month):02d}-{int(day):02d}"
    kind = "percent" if match.group("percent") else "number"
    numeric_match = re.fullmatch(
        r"(?P<value>-?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?)"
        r"(?P<unit>[^\W\d_]+)?",
        value.rstrip("%").strip(),
    )
    if numeric_match is None:
        return f"{kind}:{value.casefold()}"
    numeric_value = numeric_match.group("value").replace(" ", "").replace("\u00a0", "").replace(",", ".")
    unit = (numeric_match.group("unit") or "").casefold()
    try:
        normalized_value = format(Decimal(numeric_value).normalize(), "f")
    except InvalidOperation:
        return f"{kind}:{value.casefold()}"
    return f"{kind}:{normalized_value}:{unit}"


def _is_numbered_list_marker(value: str, start: int) -> bool:
    line_prefix = value[value.rfind("\n", 0, start) + 1 : start]
    return bool(re.fullmatch(r"\s*(?:[-*+]\s+)?", line_prefix)) and bool(
        re.match(r"\d+[.)](?:\s|\ufff0|$)", value[start:])
    )


def _numeric_facts(value: str) -> tuple[tuple[str, str], ...]:
    facts: list[tuple[str, str]] = []
    for fragment in _NUMERIC_FRAGMENT_SPLIT_RE.split(value):
        for match in _NUMERIC_VALUE_RE.finditer(fragment):
            if match.group("number") and _is_numbered_list_marker(fragment, match.start()):
                continue
            facts.append((_numeric_fact_key(match), fragment))
    return tuple(facts)


def _numeric_subject_identifiers(value: str) -> set[str]:
    return {match.group(1).casefold() for match in _NUMERIC_SUBJECT_RE.finditer(value)}


def _markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _source_identity_records(source_chunks: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Collect complete converter-owned rows under their explicit article/SKU.

    A wide source row may be split across several Markdown tables.  Keeping every
    exact row for the same identifier lets later checks compare claims locally
    without pretending that tokens elsewhere in the document belong to it.
    """

    records: dict[str, list[str]] = {}
    for source in source_chunks:
        lines = source.splitlines()
        index = 0
        while index + 1 < len(lines):
            headers = _markdown_table_cells(lines[index])
            separator_index = index + 1
            while separator_index < len(lines) and not lines[separator_index].strip():
                separator_index += 1
            separators = _markdown_table_cells(lines[separator_index]) if separator_index < len(lines) else []
            if not (
                len(headers) >= 2
                and len(separators) == len(headers)
                and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators)
            ):
                index += 1
                continue
            identity_columns = [
                column for column, header in enumerate(headers) if _SOURCE_IDENTIFIER_HEADER_RE.fullmatch(header.strip())
            ]
            cursor = separator_index + 1
            while cursor < len(lines):
                if not lines[cursor].strip():
                    cursor += 1
                    continue
                cells = _markdown_table_cells(lines[cursor])
                if len(cells) != len(headers):
                    break
                for column in identity_columns:
                    identifier = cells[column].strip().casefold()
                    if identifier and _SOURCE_IDENTIFIER_RE.fullmatch(identifier):
                        rendered = " | ".join(
                            f"{header.strip()}: {cell.strip()}"
                            for header, cell in zip(headers, cells, strict=True)
                            if cell.strip()
                        )
                        if rendered and rendered not in records.setdefault(identifier, []):
                            records[identifier].append(rendered)
                cursor += 1
            index = max(index + 1, cursor)
    return {identifier: tuple(rows) for identifier, rows in records.items()}


def _claimed_entity_tokens(fragment: str) -> set[str]:
    if _COMPARISON_RE.search(fragment):
        return set()
    candidates: list[str] = []
    colon = fragment.find(":")
    identifier = _SOURCE_IDENTIFIER_RE.search(fragment)
    if 0 < colon <= 100 and (identifier is None or colon < identifier.start()):
        candidates.append(fragment[:colon])
    for marker in _ENTITY_SCOPE_RE.finditer(fragment):
        tail = fragment[marker.end() : marker.end() + 80]
        candidates.append(re.split(r"[:;,().]", tail, maxsplit=1)[0])
    return {
        token
        for candidate in candidates
        for token in _relationship_tokens(candidate)
        if len(token) >= 4
        and token not in _ENTITY_GENERIC_TOKENS
        and not any(character.isdigit() for character in token)
    }


def _has_source_identity_conflict(*, content: str, source_chunks: Sequence[str]) -> bool:
    records = _source_identity_records(source_chunks)
    if len(records) < 2:
        return False
    record_tokens = {
        identifier: set(_relationship_tokens("\n".join(rows))) for identifier, rows in records.items()
    }
    for fragment in _NUMERIC_FRAGMENT_SPLIT_RE.split(content):
        identifiers = {
            match.group(0).casefold()
            for match in _SOURCE_IDENTIFIER_RE.finditer(fragment)
            if match.group(0).casefold() in records
        }
        if not identifiers:
            continue
        claimed_tokens = _claimed_entity_tokens(fragment)
        for identifier in identifiers:
            other_tokens = set().union(
                *(tokens for other, tokens in record_tokens.items() if other != identifier)
            )
            if any(
                token not in record_tokens[identifier] and token in other_tokens
                for token in claimed_tokens
            ):
                return True
    return False


def _has_unresolved_source_attribute_conflict(*, content: str, source_chunks: Sequence[str]) -> bool:
    records = _source_identity_records(source_chunks)
    if not records:
        return False
    record_tokens = {
        identifier: set(_relationship_tokens("\n".join(rows)))
        for identifier, rows in records.items()
    }
    guide_conflicts = {
        identifier: {
            name
            for name, pattern in _GUIDE_VALUE_PATTERNS.items()
            if pattern.search("\n".join(rows))
        }
        for identifier, rows in records.items()
    }
    guide_conflicts = {
        identifier: values
        for identifier, values in guide_conflicts.items()
        if len(values) >= 2
    }
    if not guide_conflicts:
        return False
    for fragment in _NUMERIC_FRAGMENT_SPLIT_RE.split(content):
        if not _GUIDE_CONTEXT_RE.search(fragment):
            continue
        identifiers = {
            match.group(0).casefold()
            for match in _SOURCE_IDENTIFIER_RE.finditer(fragment)
            if match.group(0).casefold() in guide_conflicts
        }
        if not identifiers:
            claimed_tokens = _claimed_entity_tokens(fragment)
            if not claimed_tokens:
                claimed_tokens = {
                    token
                    for token in _relationship_tokens(fragment)
                    if len(token) >= 4
                    and token not in _ENTITY_GENERIC_TOKENS
                    and token not in _GUIDE_SCOPE_TOKENS
                    and not any(character.isdigit() for character in token)
                }
            identifiers = {
                identifier
                for identifier in guide_conflicts
                if claimed_tokens & record_tokens[identifier]
            }
        for identifier in identifiers:
            guide_values = guide_conflicts[identifier]
            disclosed = _SOURCE_CONFLICT_DISCLOSURE_RE.search(content) and all(
                _GUIDE_VALUE_PATTERNS[name].search(content) for name in guide_values
            )
            if not disclosed:
                return True
    return False


def _has_unsupported_numeric_fact(*, content: str, source: str) -> bool:
    """Require a source-local numeric equivalent and its known context anchors.

    This operates on extracted text only. It can establish that a figure is (or
    is not) present in that text, but cannot determine whether OCR transcribed a
    scanned glyph correctly.
    """

    source_facts = _numeric_facts(source)
    identity_records = _source_identity_records([source])
    record_fact_keys = {
        identifier: {key for key, _fragment in _numeric_facts("\n".join(rows))}
        for identifier, rows in identity_records.items()
    }
    for content_key, content_fragment in _numeric_facts(content):
        fragment_identifiers = {
            match.group(0).casefold()
            for match in _SOURCE_IDENTIFIER_RE.finditer(content_fragment)
            if match.group(0).casefold() in identity_records
        }
        for identifier in fragment_identifiers:
            identifier_keys = {key for key, _fragment in _numeric_facts(identifier)}
            if content_key in identifier_keys:
                continue
            other_keys = set().union(
                *(keys for other, keys in record_fact_keys.items() if other != identifier)
            )
            if content_key not in record_fact_keys[identifier] and content_key in other_keys:
                return True
        candidates = [
            source_fragment
            for source_key, source_fragment in source_facts
            if source_key == content_key
        ]
        if not candidates:
            return True
        content_subjects = _numeric_subject_identifiers(content_fragment)
        if content_subjects and not any(
            content_subjects.issubset(_numeric_subject_identifiers(candidate))
            for candidate in candidates
        ):
            if any(
                content_subjects & _numeric_subject_identifiers(source_fragment)
                for source_key, source_fragment in source_facts
                if source_key != content_key
            ):
                return True
    return False


def _has_incomplete_formula_presentation(content: str) -> bool:
    """Catch only an explicit formula introducer immediately followed by variables."""

    return bool(_INCOMPLETE_FORMULA_PRESENTATION_RE.search(content))


def _relationship_operator(value: str) -> str:
    normalized = value.casefold().replace("ё", "е")
    if re.search(r"(?:прямо|напрямую)\s+связан|directly\s+linked", normalized):
        return "direct_link"
    if re.search(
        r"связан\w*\s+с(?:о)?|links?\s+(?:to|with)|" r"(?:is\s+)?linked\s+(?:to|with)",
        normalized,
    ):
        return "link"
    if re.search(r"(?:is\s+)?related\s+to|relates?\s+to", normalized):
        return "relation"
    if "directly related" in normalized:
        return "direct_relation"
    if re.search(r"основ\w*\s+для|basis\s+for", normalized):
        return "basis"
    if re.search(r"определя\w*|determines?", normalized):
        return "determine"
    if re.search(r"обусловлива\w*", normalized):
        return "condition"
    if re.search(r"привод\w*|causes?", normalized):
        return "cause"
    if re.search(r"требу\w*|requires?", normalized):
        return "require"
    if re.search(r"поэтому|therefore", normalized):
        return "therefore"
    if "значит" in normalized:
        return "imply"
    if re.search(r"\bmust\b", normalized):
        return "must"
    if re.search(r"\bshould\b", normalized):
        return "should"
    if re.search(r"\bneed\b", normalized):
        return "need"
    if re.search(r"если\s+клиент\w*|if\s+(?:the\s+)?customer\w*", normalized):
        return "customer_condition"
    if re.search(
        r"начн\w*\s+с|диалог\w*.{0,80}\bначина\w*|" r"start\w*\s+with|conversation\w*.{0,80}\bbegin\w*",
        normalized,
    ):
        return "start_instruction"
    if re.search(
        r"используйте|можно\s+использовать|использовать.{0,40}\bкак|" r"\buse\b|can\s+be\s+used",
        normalized,
    ):
        return "use_instruction"
    if re.search(
        r"построй\w*|подавай\w*|соотнес\w*|предложите|предлагайте|"
        r"предложить|(?<!\w)(?:\*\*|__)?(?:recommend\w*|offer)"
        r"(?:\*\*|__)?(?!\w)",
        normalized,
    ):
        return "sales_instruction"
    if re.search(r"ориентир\w*|serves?\s+as\s+(?:a\s+)?guide\w*", normalized):
        return "guidance_claim"
    return ""


def _ordered_relationship_anchors(
    value: str,
) -> tuple[str, set[str], set[str]]:
    operator = _RELATIONSHIP_OPERATOR_RE.search(value)
    if operator is None:
        return "", set(_relationship_tokens(value)), set()

    def anchors(fragment: str) -> set[str]:
        return {
            token
            for token in _relationship_tokens(fragment)
            if not any(token.startswith(root) for root in _RELATIONSHIP_OPERATOR_ROOTS)
        }

    return (
        _relationship_operator(operator.group(0)),
        anchors(value[: operator.start()]),
        anchors(value[operator.end() :]),
    )


def _relationship_claim_supported(
    pattern: re.Pattern[str],
    *,
    content: str,
    source: str,
) -> bool:
    """Require the same relationship and its local anchors in one source fragment."""
    content_fragments = tuple(
        fragment.strip() for fragment in _RELATIONSHIP_FRAGMENT_SPLIT_RE.split(content) if pattern.search(fragment)
    )
    source_fragments = tuple(
        fragment.strip() for fragment in _RELATIONSHIP_FRAGMENT_SPLIT_RE.split(source) if pattern.search(fragment)
    )
    for claim in content_fragments:
        claim_operator, claim_subject, claim_endpoint = _ordered_relationship_anchors(claim)
        supported = False
        for source_fragment in source_fragments:
            source_operator, source_subject, source_endpoint = _ordered_relationship_anchors(source_fragment)
            if not claim_operator or claim_operator != source_operator:
                continue
            if claim_subject and claim_endpoint:
                supported = claim_subject.issubset(source_subject) and claim_endpoint.issubset(source_endpoint)
            else:
                claim_anchors = claim_subject | claim_endpoint
                supported = bool(claim_anchors) and claim_anchors.issubset(set(_relationship_tokens(source_fragment)))
            if supported:
                break
        if not supported:
            return False
    return bool(content_fragments)


def _has_unsupported_relationship_claim(*, content: str, source: str) -> bool:
    return any(
        pattern.search(content)
        and not _relationship_claim_supported(
            pattern,
            content=content,
            source=source,
        )
        for pattern in _UNSUPPORTED_RELATIONSHIP_PATTERNS
    )


def remove_unsupported_relationship_fragments(
    *,
    content: str,
    source_chunks: Sequence[str],
) -> str:
    """Drop only unsupported claim fragments while preserving grounded prose.

    The deterministic gate used to reject an entire lesson when a single
    sentence added an unsupported recommendation or relationship.  A removed
    fragment is never replaced or rewritten.  The caller must run the complete
    quality gate again and may accept the remainder only when it is independently
    grounded and substantive.
    """

    normalized_source = "\n".join(
        " ".join(line.casefold().replace("ё", "е").split())
        for chunk in source_chunks
        for line in chunk.splitlines()
    )
    list_marker_space = "\ufff0"
    protected_content = re.sub(
        r"(?m)^(\s*(?:[-*+]\s+)?\d+[.)])\s+",
        rf"\1{list_marker_space}",
        content,
    )
    parts = re.split(r"(\n+|(?<!\d)(?<=[.!?])\s+)", protected_content)
    retained: list[str] = []
    for part in parts:
        if not part or part.isspace():
            if retained and not retained[-1].isspace():
                retained.append(part)
            continue
        normalized_part = " ".join(part.casefold().replace("ё", "е").split())
        if normalized_part and (
            _has_unsupported_relationship_claim(
                content=normalized_part,
                source=normalized_source,
            )
            or _has_unsupported_numeric_fact(
                content=normalized_part,
                source=normalized_source,
            )
        ):
            if retained and retained[-1].isspace():
                retained.pop()
            continue
        retained.append(part)
    return "".join(retained).replace(list_marker_space, " ").strip()


@dataclass(frozen=True, slots=True)
class LessonQualityResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    source_anchor_matches: int
    required_source_anchor_matches: int
    generic_sentence_share: float
    repeated_sentence_count: int
    cross_lesson_repeated_sentence_count: int = 0


@dataclass(frozen=True, slots=True)
class LessonQualityEvaluation:
    lesson_identity: tuple[int, int] | None
    title: str
    content: str
    source_chunks: tuple[str, ...]
    result: LessonQualityResult


_LESSON_QUALITY_EVENTS: ContextVar[list[LessonQualityEvaluation] | None] = ContextVar(
    "lesson_quality_events", default=None
)


@contextmanager
def capture_lesson_quality_evaluations() -> Iterator[list[LessonQualityEvaluation]]:
    """Capture exact validator inputs only inside an explicit task context."""
    events: list[LessonQualityEvaluation] = []
    token = _LESSON_QUALITY_EVENTS.set(events)
    try:
        yield events
    finally:
        _LESSON_QUALITY_EVENTS.reset(token)


def evaluate_lesson_quality(
    *,
    title: str,
    content: str,
    source_chunks: Sequence[str],
    prior_lesson_contents: Sequence[str] = (),
    lesson_identity: tuple[int, int] | None = None,
) -> LessonQualityResult:
    """Evaluate one lesson against the exact excerpts supplied to its writer."""

    source_tokens = set(_content_tokens("\n".join(source_chunks)))
    body_content = _without_approved_title_heading(content, title)
    # The title comes from the architect and must not make an otherwise generic
    # lesson look grounded. Source anchors must occur in the lesson body.
    content_tokens = set(_content_tokens(body_content))
    anchor_matches = len(source_tokens & content_tokens)
    if len(source_tokens) <= 3:
        required_matches = 1
    elif len(source_tokens) <= 8:
        required_matches = 2
    else:
        required_matches = min(5, max(3, math.ceil(len(source_tokens) * 0.08)))

    sentences = _sentences(body_content)
    generic_count = sum(any(marker in sentence for marker in _GENERIC_MARKERS) for sentence in sentences)
    generic_share = generic_count / len(sentences) if sentences else 1.0
    counts: dict[str, int] = {}
    for sentence in sentences:
        if len(sentence.split()) >= 7:
            counts[sentence] = counts.get(sentence, 0) + 1
    repeated_count = sum(count - 1 for count in counts.values() if count > 1)
    substantive_sentences = {sentence for sentence in sentences if len(sentence.split()) >= 4}
    prior_substantive_sentences = {
        sentence
        for prior_content in prior_lesson_contents
        for sentence in _sentences(prior_content)
        if len(sentence.split()) >= 4
    }
    cross_lesson_repeated_count = len(substantive_sentences & prior_substantive_sentences)
    normalized_source_text = "\n".join(
        " ".join(line.casefold().replace("ё", "е").split()) for chunk in source_chunks for line in chunk.splitlines()
    )
    normalized_content_text = "\n".join(
        " ".join(line.casefold().replace("ё", "е").split()) for line in body_content.splitlines()
    )
    unsupported_relationship = _has_unsupported_relationship_claim(
        content=normalized_content_text,
        source=normalized_source_text,
    )
    unsupported_numeric = _has_unsupported_numeric_fact(
        content=body_content,
        source="\n".join(source_chunks),
    )
    source_identity_conflict = _has_source_identity_conflict(
        content=body_content,
        source_chunks=source_chunks,
    )
    source_attribute_conflict = _has_unresolved_source_attribute_conflict(
        content=body_content,
        source_chunks=source_chunks,
    )
    incomplete_formula = _has_incomplete_formula_presentation(body_content)
    unprofessional_learner_language = has_unprofessional_learner_language(body_content)

    reasons: list[str] = []
    if not body_content.strip() or anchor_matches < required_matches:
        reasons.append("insufficient_source_anchors")
    if generic_count >= 2 and generic_share >= 0.50:
        reasons.append("generic_filler_dominates")
    if repeated_count:
        reasons.append("repeated_lesson_sentence")
    if cross_lesson_repeated_count >= 3 and cross_lesson_repeated_count / max(1, len(substantive_sentences)) >= 0.20:
        reasons.append("repeated_across_lessons")
    if (
        len(source_tokens) >= 20
        and len(_content_tokens(body_content)) < 25
        and normalized_source_text not in normalized_content_text
    ):
        reasons.append("lesson_too_thin_for_source")
    if unsupported_relationship:
        reasons.append("unsupported_relationship_claim")
    if unsupported_numeric:
        reasons.append("unsupported_numeric_fact")
    if source_identity_conflict:
        reasons.append("source_identity_conflict")
    if source_attribute_conflict:
        reasons.append("source_attribute_conflict")
    if incomplete_formula:
        reasons.append("incomplete_formula_presentation")
    if unprofessional_learner_language:
        reasons.append("unprofessional_learner_language")

    result = LessonQualityResult(
        accepted=not reasons,
        reason_codes=tuple(reasons),
        source_anchor_matches=anchor_matches,
        required_source_anchor_matches=required_matches,
        generic_sentence_share=round(generic_share, 4),
        repeated_sentence_count=repeated_count,
        cross_lesson_repeated_sentence_count=cross_lesson_repeated_count,
    )
    events = _LESSON_QUALITY_EVENTS.get()
    if events is not None:
        events.append(
            LessonQualityEvaluation(
                lesson_identity=lesson_identity,
                title=title,
                content=content,
                source_chunks=tuple(source_chunks),
                result=result,
            )
        )
    return result


__all__ = [
    "LESSON_QUALITY_POLICY_VERSION",
    "LessonQualityResult",
    "LessonQualityEvaluation",
    "capture_lesson_quality_evaluations",
    "evaluate_lesson_quality",
    "has_unprofessional_learner_language",
    "remove_unsupported_relationship_fragments",
]
