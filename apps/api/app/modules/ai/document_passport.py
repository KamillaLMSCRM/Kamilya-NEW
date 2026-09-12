"""Deterministic learning profile for structured course sources.

The passport is navigation metadata, not a factual summary.  It keeps every
source section visible while preventing a large reference table from defining
course size only because it contains many rows.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

_WORKSHEET_PREFIX = "[Worksheet] "
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TABLE_SEPARATOR_RE = re.compile(r"^\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_REFERENCE_MARKERS = frozenset(
    {
        "sku",
        "артикул",
        "код",
        "цена",
        "price",
        "barcode",
        "штрихкод",
        "размер",
        "габарит",
        "id",
        "номенклатура",
        "номенклатурный",
        "каталог",
        "catalog",
        "article",
        "identifier",
        "идентификатор",
        "перечень",
        "список",
    }
)
_STRONG_REFERENCE_MARKERS = frozenset(
    {
        "sku",
        "артикул",
        "barcode",
        "штрихкод",
        "номенклатура",
        "номенклатурный",
        "каталог",
        "catalog",
        "identifier",
        "идентификатор",
        "перечень",
        "список",
    }
)
_STRONG_REFERENCE_PHRASE_RE = re.compile(
    r"\b(?:article\s+(?:numbers?|nos?\.?|#)|product\s+codes?|item\s+codes?)\b",
    re.IGNORECASE,
)
_PRIMARY_MARKERS = frozenset(
    {
        "коллекция",
        "коллекции",
        "collection",
        "knowledge",
        "знания",
        "описание",
        "description",
        "особенности",
        "преимущества",
        "инструкция",
        "instruction",
        "регламент",
        "процедура",
        "политика",
        "правила",
        "обучение",
        "guide",
        "руководство",
    }
)
_STRONG_PRIMARY_MARKERS = frozenset(
    {
        "коллекция",
        "коллекции",
        "collection",
        "knowledge",
        "знания",
        "особенности",
        "преимущества",
        "инструкция",
        "instruction",
        "регламент",
        "процедура",
        "политика",
        "правила",
        "обучение",
        "guide",
        "руководство",
    }
)


class _Chunk(Protocol):
    @property
    def headings(self) -> tuple[str, ...]: ...

    @property
    def text(self) -> str: ...


class _Document(Protocol):
    @property
    def doc_id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def chunks(self) -> tuple[_Chunk, ...]: ...


class _Corpus(Protocol):
    @property
    def documents(self) -> tuple[_Document, ...]: ...


class SectionRole(StrEnum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PassportSection:
    document_id: str
    name: str
    role: SectionRole
    chunk_count: int
    character_count: int
    distinct_rows: int
    repeated_row_share: float
    reference_signal_count: int
    primary_signal_count: int


@dataclass(frozen=True, slots=True)
class DocumentPassport:
    sections: tuple[PassportSection, ...]
    primary_sections: tuple[str, ...]
    supporting_sections: tuple[str, ...]
    unknown_sections: tuple[str, ...]
    teachable_units: int
    confidence: Literal["high", "medium", "low"]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _SectionAggregate:
    chunks: int = 0
    chars: int = 0
    rows: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _RawSection:
    document_id: str
    name: str
    chunks: int
    chars: int
    rows: int
    distinct_rows: int
    repeated_row_share: float
    reference_signals: int
    strong_reference_signals: int
    primary_signals: int
    strong_primary_signals: int


def _section_name(document: _Document, chunk: _Chunk) -> str:
    for heading in reversed(chunk.headings):
        if heading.startswith(_WORKSHEET_PREFIX):
            return heading.removeprefix(_WORKSHEET_PREFIX).strip() or document.title
    return document.title.strip() or "Document"


def _meaningful_rows(text: str) -> list[str]:
    rows: list[str] = []
    for raw in text.splitlines():
        value = re.sub(r"\s+", " ", raw).strip()
        if not value or value.startswith("#") or _TABLE_SEPARATOR_RE.fullmatch(value):
            continue
        rows.append(value.casefold())
    return rows


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(value)}


def build_document_passport(corpus: _Corpus) -> DocumentPassport:
    """Classify every source section and estimate bounded teachable capacity."""

    aggregates: dict[tuple[str, str], _SectionAggregate] = {}
    order: list[tuple[str, str]] = []
    for document in corpus.documents:
        for chunk in document.chunks:
            name = _section_name(document, chunk)
            key = (document.doc_id, name)
            if key not in aggregates:
                aggregates[key] = _SectionAggregate()
                order.append(key)
            aggregate = aggregates[key]
            aggregate.chunks += 1
            aggregate.chars += len(chunk.text)
            aggregate.rows.extend(_meaningful_rows(chunk.text))

    if not order:
        raise ValueError("document_passport_requires_source_sections")

    raw_sections: list[_RawSection] = []
    for document_id, name in order:
        aggregate = aggregates[(document_id, name)]
        rows = list(aggregate.rows)
        distinct_rows = list(dict.fromkeys(rows))
        # A short preamble is common in business workbooks, so sample enough
        # bounded rows to see the actual table vocabulary without scanning an
        # unbounded section into the classifier input.
        signal_text = " ".join((name, *distinct_rows[:25]))
        tokens = _tokens(signal_text)
        reference_signals = len(tokens & _REFERENCE_MARKERS)
        strong_reference_signals = len(tokens & _STRONG_REFERENCE_MARKERS) + len(
            _STRONG_REFERENCE_PHRASE_RE.findall(signal_text)
        )
        primary_signals = len(tokens & _PRIMARY_MARKERS)
        strong_primary_signals = len(tokens & _STRONG_PRIMARY_MARKERS)
        raw_sections.append(
            _RawSection(
                document_id=document_id,
                name=name,
                chunks=aggregate.chunks,
                chars=aggregate.chars,
                rows=len(rows),
                distinct_rows=len(distinct_rows),
                repeated_row_share=round(1 - (len(distinct_rows) / max(1, len(rows))), 4),
                reference_signals=reference_signals,
                strong_reference_signals=strong_reference_signals,
                primary_signals=primary_signals,
                strong_primary_signals=strong_primary_signals,
            )
        )

    if len(raw_sections) == 1:
        roles = [SectionRole.PRIMARY]
        confidence: Literal["high", "medium", "low"] = "high"
    else:
        smallest_rows = max(1, min(section.distinct_rows for section in raw_sections))
        strong_primary_documents = {
            section.document_id for section in raw_sections if section.primary_signals > section.reference_signals
        }
        roles = []
        for section in raw_sections:
            reference_signals = section.reference_signals
            strong_reference_signals = section.strong_reference_signals
            primary_signals = section.primary_signals
            strong_primary_signals = section.strong_primary_signals
            much_larger = section.distinct_rows >= smallest_rows * 3
            has_strong_primary_peer = section.document_id in strong_primary_documents
            reference_dominates = strong_reference_signals >= 1 and reference_signals - primary_signals >= 2
            balanced_large_reference = (
                has_strong_primary_peer
                and much_larger
                and strong_reference_signals >= 1
                and reference_signals >= primary_signals
                and strong_primary_signals == 0
            )
            if reference_dominates or balanced_large_reference:
                roles.append(SectionRole.SUPPORTING)
            elif (
                primary_signals >= reference_signals
                or (strong_primary_signals >= 1 and primary_signals + strong_primary_signals >= reference_signals)
            ) and primary_signals >= 1:
                roles.append(SectionRole.PRIMARY)
            else:
                roles.append(SectionRole.UNKNOWN)
        confidence = "high" if SectionRole.PRIMARY in roles and SectionRole.SUPPORTING in roles else "medium"
        if SectionRole.PRIMARY not in roles:
            candidate = min(
                range(len(raw_sections)),
                key=lambda index: (
                    -raw_sections[index].primary_signals,
                    raw_sections[index].reference_signals,
                    raw_sections[index].distinct_rows,
                    index,
                ),
            )
            roles[candidate] = SectionRole.PRIMARY
            confidence = "low"

    sections = tuple(
        PassportSection(
            document_id=section.document_id,
            name=section.name,
            role=role,
            chunk_count=section.chunks,
            character_count=section.chars,
            distinct_rows=section.distinct_rows,
            repeated_row_share=section.repeated_row_share,
            reference_signal_count=section.reference_signals,
            primary_signal_count=section.primary_signals,
        )
        for section, role in zip(raw_sections, roles, strict=True)
    )
    primary = tuple(section.name for section in sections if section.role is SectionRole.PRIMARY)
    supporting = tuple(section.name for section in sections if section.role is SectionRole.SUPPORTING)
    unknown = tuple(section.name for section in sections if section.role is SectionRole.UNKNOWN)
    primary_rows = sum(max(1, section.distinct_rows - 1) for section in sections if section.role is SectionRole.PRIMARY)
    teachable_units = max(len(primary), min(40, math.ceil(math.sqrt(max(1, primary_rows) * 2))))
    warnings = tuple(
        code
        for condition, code in (
            (confidence == "low", "section_roles_ambiguous"),
            (bool(unknown), "unclassified_sections_retained"),
            (bool(supporting), "supporting_sections_do_not_define_course_size"),
        )
        if condition
    )
    return DocumentPassport(
        sections=sections,
        primary_sections=primary,
        supporting_sections=supporting,
        unknown_sections=unknown,
        teachable_units=teachable_units,
        confidence=confidence,
        warnings=warnings,
    )


def render_passport_for_architect(passport: DocumentPassport) -> str:
    """Render bounded structural guidance without copying source payloads."""

    records = [
        " ".join(
            (
                f"document_id={section.document_id}",
                f"section={json.dumps(section.name, ensure_ascii=False)}",
                f"role={section.role.value}",
                f"distinct_rows={section.distinct_rows}",
                f"chunks={section.chunk_count}",
            )
        )
        for section in passport.sections
    ]
    return "\n".join(
        (
            "DOCUMENT PASSPORT (server-derived navigation metadata; not factual authority):",
            "UNTRUSTED_SOURCE_METADATA_BEGIN",
            f"confidence={passport.confidence}",
            f"teachable_units={passport.teachable_units}",
            *records,
            "Cover every primary section. Use supporting sections for evidence and examples; "
            "do not allocate lessons by supporting row count. Do not omit selected source sections.",
            "UNTRUSTED_SOURCE_METADATA_END",
        )
    )


__all__ = [
    "DocumentPassport",
    "PassportSection",
    "SectionRole",
    "build_document_passport",
    "render_passport_for_architect",
]
