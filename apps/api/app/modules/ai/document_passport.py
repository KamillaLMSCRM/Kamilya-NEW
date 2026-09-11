"""Deterministic learning profile for structured course sources.

The passport is navigation metadata, not a factual summary.  It keeps every
source section visible while preventing a large reference table from defining
course size only because it contains many rows.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


_WORKSHEET_PREFIX = "[Worksheet] "
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TABLE_SEPARATOR_RE = re.compile(r"^\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_REFERENCE_MARKERS = frozenset(
    {
        "sku", "артикул", "код", "цена", "price", "barcode", "штрихкод",
        "размер", "габарит", "id", "номенклатура", "номенклатурный",
        "каталог", "catalog", "перечень", "список",
    }
)
_PRIMARY_MARKERS = frozenset(
    {
        "коллекция", "коллекции", "collection", "описание", "особенности",
        "преимущества", "инструкция", "instruction", "регламент", "процедура",
        "политика", "правила", "обучение", "guide", "руководство",
    }
)


class _Chunk(Protocol):
    headings: tuple[str, ...]
    text: str


class _Document(Protocol):
    doc_id: str
    title: str
    chunks: tuple[_Chunk, ...]


class _Corpus(Protocol):
    documents: tuple[_Document, ...]


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

    aggregates: dict[tuple[str, str], dict[str, object]] = {}
    order: list[tuple[str, str]] = []
    for document in corpus.documents:
        for chunk in document.chunks:
            name = _section_name(document, chunk)
            key = (document.doc_id, name)
            if key not in aggregates:
                aggregates[key] = {"chunks": 0, "chars": 0, "rows": []}
                order.append(key)
            aggregate = aggregates[key]
            aggregate["chunks"] = int(aggregate["chunks"]) + 1
            aggregate["chars"] = int(aggregate["chars"]) + len(chunk.text)
            rows = aggregate["rows"]
            assert isinstance(rows, list)
            rows.extend(_meaningful_rows(chunk.text))

    if not order:
        raise ValueError("document_passport_requires_source_sections")

    raw_sections: list[dict[str, object]] = []
    for document_id, name in order:
        aggregate = aggregates[(document_id, name)]
        rows = list(aggregate["rows"])
        distinct_rows = list(dict.fromkeys(rows))
        # A short preamble is common in business workbooks, so sample enough
        # bounded rows to see the actual table vocabulary without scanning an
        # unbounded section into the classifier input.
        signal_text = " ".join((name, *distinct_rows[:25]))
        tokens = _tokens(signal_text)
        reference_signals = len(tokens & _REFERENCE_MARKERS)
        primary_signals = len(tokens & _PRIMARY_MARKERS)
        raw_sections.append(
            {
                "document_id": document_id,
                "name": name,
                "chunks": int(aggregate["chunks"]),
                "chars": int(aggregate["chars"]),
                "rows": len(rows),
                "distinct_rows": len(distinct_rows),
                "repeated_row_share": round(1 - (len(distinct_rows) / max(1, len(rows))), 4),
                "reference_signals": reference_signals,
                "primary_signals": primary_signals,
            }
        )

    if len(raw_sections) == 1:
        roles = [SectionRole.PRIMARY]
        confidence: Literal["high", "medium", "low"] = "high"
    else:
        smallest_rows = max(1, min(int(section["distinct_rows"]) for section in raw_sections))
        roles = []
        for section in raw_sections:
            reference_signals = int(section["reference_signals"])
            primary_signals = int(section["primary_signals"])
            much_larger = int(section["distinct_rows"]) >= smallest_rows * 3
            if reference_signals >= 2 or (reference_signals >= 1 and much_larger):
                roles.append(SectionRole.SUPPORTING)
            elif primary_signals > reference_signals:
                roles.append(SectionRole.PRIMARY)
            else:
                roles.append(SectionRole.UNKNOWN)
        confidence = "high" if SectionRole.PRIMARY in roles and SectionRole.SUPPORTING in roles else "medium"
        if SectionRole.PRIMARY not in roles:
            candidate = min(
                range(len(raw_sections)),
                key=lambda index: (
                    int(raw_sections[index]["reference_signals"]),
                    -int(raw_sections[index]["primary_signals"]),
                    int(raw_sections[index]["distinct_rows"]),
                    index,
                ),
            )
            roles[candidate] = SectionRole.PRIMARY
            confidence = "low"

    sections = tuple(
        PassportSection(
            document_id=str(section["document_id"]),
            name=str(section["name"]),
            role=role,
            chunk_count=int(section["chunks"]),
            character_count=int(section["chars"]),
            distinct_rows=int(section["distinct_rows"]),
            repeated_row_share=float(section["repeated_row_share"]),
            reference_signal_count=int(section["reference_signals"]),
            primary_signal_count=int(section["primary_signals"]),
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
