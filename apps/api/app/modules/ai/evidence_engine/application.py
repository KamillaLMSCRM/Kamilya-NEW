"""Production-shaped application seam for the evidence-first generation engine."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Literal, Protocol
from urllib.parse import quote, unquote

from app.modules.ai.architect_schema import CourseStructure, LearningObjective
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import (
    CourseAssessment,
    LessonAssessment,
    MCQOption,
    MCQQuestion,
)
from app.modules.ai.direct_source import (
    DirectSourceCorpus,
    merged_direct_source_worksheet_tables,
)
from app.modules.ai.document_passport import SectionRole, build_document_passport
from app.modules.ai.ingestion import is_sentence_like_ordinal_heading
from app.modules.ai.lesson_quality import neutralize_unprofessional_source_language
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedCallFailureReason
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent

from .engine import EvidenceCourseEngine
from .models import (
    AssessmentDraft,
    CourseDraft,
    CourseIntent,
    LessonDraft,
    QuestionDraft,
    SourceDocument,
    SourceFact,
    SourceSection,
    StageTiming,
)
from .provider_engine import ProviderBackedEvidenceEngine, _normalize
from .provider_models import GroundedBlock, ProviderBackedResult, RetrievalMeasurement
from .providers import EVIDENCE_REALIZER_SYSTEM_PROMPT
from .quality import (
    EVIDENCE_QUALITY_POLICY_VERSION,
    evaluate_plan_preflight,
    evaluate_publishability,
)
from .semantic_assessment import generate_block_assessment
from .source_blocks import is_navigation_heading, split_narrative_blocks

ProgressCallback = Callable[[str, int, int, str | None, int | None], Awaitable[None] | None]
CancellationCallback = Callable[[], Awaitable[None] | None]


class GenerationClient(Protocol):
    async def ainvoke_validated(
        self,
        messages: str | list[dict[str, Any]],
        parser: Callable[[str], Any],
        config: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Any: ...


class EmbeddingClient(Protocol):
    async def embed_documents_with_provenance(
        self, texts: list[str], *, on_progress: Callable[..., Awaitable[None]] | None = None
    ) -> Any: ...
    async def embed_queries_with_provenance(
        self, texts: list[str], *, on_progress: Callable[..., Awaitable[None]] | None = None
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class EvidenceSourceBundle:
    document: SourceDocument

    @property
    def all_facts(self) -> tuple[SourceFact, ...]:
        return tuple(fact for section in self.document.sections for fact in section.facts)


@dataclass(frozen=True, slots=True)
class EvidenceGenerationOutput:
    result: ProviderBackedResult
    corpus: DirectSourceCorpus


@dataclass(frozen=True, slots=True)
class GenerationArtifacts:
    structure: CourseStructure
    content: CourseContent
    assessment: CourseAssessment
    diagnostics: dict[str, Any]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-")
    return normalized[:80] or "item"


def _stable_id(prefix: str, *parts: str) -> str:
    body = "\x1f".join(" ".join(part.casefold().split()) for part in parts)
    return f"{prefix}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"


def _locator(**values: str | int) -> str:
    return ";".join(f"{key}={quote(str(value), safe=':-_.')}" for key, value in values.items())


def _locator_values(value: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in value.split(";"):
        key, separator, raw = item.partition("=")
        if separator and key:
            parsed[key] = unquote(raw)
    return parsed


def _section_role(value: SectionRole) -> str:
    return "primary" if value is SectionRole.PRIMARY else "supporting"


def _narrative_section_role(
    *,
    document_id: str,
    section_name: str,
    role_by_section: dict[tuple[str, str], SectionRole],
) -> SectionRole:
    if is_navigation_heading(section_name):
        return SectionRole.SUPPORTING
    exact = role_by_section.get((document_id, section_name.casefold().strip()))
    if exact is not None:
        return exact
    normalized = section_name.casefold().strip()
    if normalized.startswith(("содержание", "приложение", "contents", "appendix")):
        return SectionRole.SUPPORTING
    document_roles = [
        role for (doc_id, _name), role in role_by_section.items() if doc_id == document_id
    ]
    if SectionRole.PRIMARY in document_roles:
        return SectionRole.PRIMARY
    return SectionRole.SUPPORTING


def _narrative_attribute(value: str) -> str:
    normalized = value.casefold().replace("ё", "е")
    if re.search(
        r"\b(?:минут|день|дня|дней|месяц|месяца|месяцев|час|часов|срок)\w*\b",
        normalized,
    ):
        return "срок"
    if re.search(r"\b(?:процент|ставк|вознагражден|тенге|сумм)\w*\b", normalized):
        return "финансовое условие"
    if re.search(r"\b(?:вправе|право)\w*\b", normalized):
        return "право"
    if re.search(r"\b(?:обязан|должен|необходимо)\w*\b", normalized):
        return "обязанность"
    if re.search(
        r"(?:\bнельзя\b|\bзапрещен\w*\b|\bне допускается\b|\bне вправе\b)",
        normalized,
    ):
        return "запрет"
    return "положение"


_FORMULA_DEFINITION_RE = re.compile(
    r"^\s*[A-Za-zА-Яа-яЁё0-9|]{1,3}\s*[-—]\s*"
    r"(?:порядков\w*\s+номер|период\w*\s+времени|сумм\w*|"
    r"годов\w*\s+эффективн\w*\s+ставк\w*)\b",
    flags=re.IGNORECASE,
)


def _narrative_fact_metadata(value: str) -> dict[str, float | str]:
    """Mark source-boundary and formula OCR risk without guessing repairs."""
    stripped = value.strip()
    if _FORMULA_DEFINITION_RE.match(stripped):
        return {"confidence": 0.6, "uncertainty": "ambiguous_formula_symbol"}
    if re.match(r"^\d{1,3}:\s+", stripped):
        return {"confidence": 0.0, "uncertainty": "ocr_numbering_prefix"}
    if re.match(r"^[)\]}]", stripped):
        return {"confidence": 0.0, "uncertainty": "truncated_source_boundary"}
    if re.search(r"(?:^|[.!?]\s+)(?:др\.\s*)?\)\s+[А-ЯЁ]", stripped):
        return {"confidence": 0.0, "uncertainty": "truncated_source_boundary"}
    if re.fullmatch(
        r"(?:условие|поле|параметр|характеристика)\s*\|\s*(?:описание|значение)",
        stripped,
        flags=re.IGNORECASE,
    ):
        return {"confidence": 0.0, "uncertainty": "table_header_fragment"}
    if stripped.endswith(":"):
        return {"confidence": 0.0, "uncertainty": "incomplete_source_clause"}
    first_letter = next((character for character in stripped if character.isalpha()), "")
    if first_letter and first_letter.islower():
        return {"confidence": 0.0, "uncertainty": "truncated_source_boundary"}
    # Production PDF conversion occasionally cuts a paragraph at a page or
    # column boundary. Complete prose emitted by Docling retains sentence/list
    # punctuation; an alphanumeric tail is unsafe evidence for autonomous
    # question keys because the missing continuation can change the rule.
    if stripped and stripped[-1].isalnum():
        return {"confidence": 0.0, "uncertainty": "incomplete_source_clause"}
    return {"confidence": 1.0, "uncertainty": ""}


def _split_narrative_chunk(text: str) -> list[str]:
    cleaned = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)
    cleaned = re.sub(
        r"(?is)^\s*.{0,160}\bутвержден[оа]?\b.{0,320}?"
        r"\b(?:правила|положение|инструкция|регламент)\b[^\n]*\n+",
        "",
        cleaned,
        count=1,
    )
    # A paragraph/list rule is the assessment evidence unit. Splitting each
    # sentence detached exceptions from their rule and lost short prohibitions.
    parts = split_narrative_blocks(cleaned)
    cleaned_parts: list[str] = []
    for part in parts:
        normalized = " ".join(part.casefold().replace("ё", "е").split())
        if (
            "утвержден" in normalized
            and "правила предоставления микрокредитов" in normalized
        ):
            continue
        cleaned = part.translate(str.maketrans("®©°™„‚", '    ",'))
        cleaned = re.sub(r"\s+[тТ]\s+(?=строке\b)", " ", cleaned)
        cleaned = re.sub(r"\s*\(ст\.\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = " ".join(cleaned.split()).strip(" =\\|#")
        letter_count = sum(character.isalpha() for character in cleaned)
        page_footer = (
            len(cleaned.split()) <= 20
            and re.search(r"\b(?:page|страница)\s+\d+\s*$", cleaned, re.IGNORECASE)
            and not _APPENDIX_MARKER_RE.search(cleaned)
        )
        if cleaned and letter_count >= 8 and not page_footer:
            cleaned_parts.append(cleaned)
    return cleaned_parts


_PLAIN_NUMBERED_SECTION_RE = re.compile(
    r"(?m)^\s*(?P<number>\d{1,3})(?P<separator>[.)])\s+(?P<title>[^\n]{3,120}?)\s*$"
)
_NUMBERED_SECTION_PREFIX_RE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)*[.)])\s+")
_WRAPPED_MARKDOWN_HEADING_RE = re.compile(
    r"(?m)^\s*#{1,6}\s*(?P<number>\d{1,3}(?:\.\d+)*[.)]\s+[^\n]+?)\s*\n"
    r"\s*\n\s*#{1,6}\s*(?P<fragment>[^\n]+?)\s*$"
)


def _is_plain_numbered_section_heading(match: re.Match[str]) -> bool:
    return not is_sentence_like_ordinal_heading(match.group(0))


def _is_wrapped_heading_extension(previous: str, current: str) -> bool:
    """Recognize one adjacent conversion heading continued onto a later chunk."""

    previous_prefix = _NUMBERED_SECTION_PREFIX_RE.match(previous)
    current_prefix = _NUMBERED_SECTION_PREFIX_RE.match(current)
    if previous_prefix is None or current_prefix is None:
        return False
    if previous_prefix.group(1) != current_prefix.group(1):
        return False
    normalized_previous = " ".join(previous.casefold().split())
    normalized_current = " ".join(current.casefold().split())
    return (
        normalized_current.startswith(f"{normalized_previous} ")
        and len(normalized_current) > len(normalized_previous)
    )


def _initial_navigation_prefix_end(chunks: list[Any]) -> int:
    """Return the first numbered body chunk after an initial explicit contents marker."""

    navigation_index = next(
        (
            index
            for index, chunk in enumerate(chunks)
            if any(is_navigation_heading(heading) for heading in chunk.headings)
        ),
        None,
    )
    if navigation_index is None or navigation_index == 0:
        return 0
    prefix_text = "\n".join(str(chunk.text) for chunk in chunks[:navigation_index])
    prefix_text = re.sub(r"<!--\s*image\s*-->", "", prefix_text, flags=re.IGNORECASE)
    prefix_text = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", prefix_text)
    prefix_lines = [
        " ".join(line.split())
        for line in prefix_text.splitlines()
        if line.strip()
    ]
    # A contents page can follow one dated cover line and its sequential
    # heading-only entries, but never authorizes discarding source prose.
    expected_number = 1
    seen_numbered_entry = False
    prefix_titles: dict[int, str] = {}
    for line in prefix_lines:
        numbered = re.match(r"^(\d+)[.)]\s+\S", line)
        if numbered is not None:
            if int(numbered.group(1)) != expected_number:
                return 0
            expected_number += 1
            seen_numbered_entry = True
            prefix_titles[int(numbered.group(1))] = re.sub(r"^\d+[.)]\s+", "", line).casefold()
            continue
        if (
            not seen_numbered_entry
            and len(line.split()) <= 12
            and re.search(r"\b\d{4}(?:\s*[а-яёa-z])?\.?$", line, re.IGNORECASE)
        ):
            continue
        if seen_numbered_entry and re.match(r"^приложение\s+\S", line, re.IGNORECASE):
            continue
        return 0
    if not seen_numbered_entry:
        return 0
    for index, chunk in enumerate(chunks[navigation_index + 1 :], start=navigation_index + 1):
        heading = next(reversed(chunk.headings), "")
        if _NUMBERED_SECTION_PREFIX_RE.match(heading):
            body_index = index
            break
    else:
        return 0
    body_titles: dict[int, set[str]] = {}
    last_body_number: int | None = None
    for chunk in chunks[body_index:]:
        heading = _chunk_section_name(chunk, "")
        match = _NUMBERED_SECTION_PREFIX_RE.match(heading)
        if match is not None:
            last_body_number = int(match.group(1).rstrip(".)"))
            body_titles.setdefault(last_body_number, set()).update(
                re.findall(r"[^\W\d_]+", heading[match.end() :].casefold(), re.UNICODE)
            )
        elif last_body_number is not None and _is_uppercase_heading_fragment(heading):
            body_titles[last_body_number].update(re.findall(r"[^\W\d_]+", heading.casefold(), re.UNICODE))
        else:
            last_body_number = None
    for title in prefix_titles.values():
        prefix_tokens = set(re.findall(r"[^\W\d_]+", title, re.UNICODE))
        # OCR can duplicate a numeric label and shift later TOC ordinals. Only
        # title correspondence is evidence of navigation, not those ordinals.
        if not prefix_tokens and re.fullmatch(r"[\d\s.)]+", title):
            continue
        if not prefix_tokens or not any(
            len(prefix_tokens & body_tokens) >= 0.8 * max(len(prefix_tokens), len(body_tokens))
            for body_tokens in body_titles.values()
        ):
            return 0
    return body_index


def _trim_to_first_numbered_markdown_heading(text: str) -> str:
    match = re.search(r"(?m)^\s*#{1,6}\s+\d{1,3}(?:\.\d+)*[.)]\s+", text)
    return text[match.start() :] if match is not None else text


def _chunk_section_name(chunk: Any, fallback_title: str) -> str:
    """Return a section heading, rejoining one Docling split Markdown heading."""

    section_name = next(reversed(chunk.headings), fallback_title)
    for match in _WRAPPED_MARKDOWN_HEADING_RE.finditer(chunk.text):
        fragment = " ".join(match.group("fragment").split())
        letters = "".join(character for character in fragment if character.isalpha())
        if (
            section_name.casefold() == fragment.casefold()
            and len(letters) >= 3
            and fragment == fragment.upper()
            and not fragment.endswith((".", ":", ";", "!", "?"))
        ):
            return f"{' '.join(match.group('number').split())} {fragment}"
    return section_name


def _is_uppercase_heading_fragment(value: str) -> bool:
    letters = "".join(character for character in value if character.isalpha())
    return (
        len(value) <= 120
        and len(letters) >= 3
        and not any(character.isdigit() for character in value)
        and value == value.upper()
        and not value.endswith((".", ":", ";", "!", "?"))
    )


def _merge_overlapping_chunks(chunks: list[Any]) -> str:
    """Reconstruct source text from deterministic overlapping ingestion chunks."""

    merged = ""
    for chunk in chunks:
        text = str(chunk.text).strip()
        if not text:
            continue
        if not merged:
            merged = text
            continue
        overlap = 0
        maximum = min(len(merged), len(text), 500)
        for size in range(maximum, 19, -1):
            if merged.endswith(text[:size]):
                overlap = size
                break
        if overlap:
            merged += text[overlap:]
        else:
            merged = f"{merged}\n\n{text}"
    return merged.strip()


def _plain_numbered_sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    """Recover major ``1. Heading`` sections from plain text without Markdown metadata."""

    matches = [
        match
        for match in _PLAIN_NUMBERED_SECTION_RE.finditer(text)
        if _is_plain_numbered_section_heading(match)
    ]
    if len(matches) < 2:
        return []
    sections: list[tuple[str, str]] = []
    prefix = text[: matches[0].start()].strip()
    if prefix and len(prefix.split()) >= 12 and prefix != prefix.upper():
        sections.append((fallback_title, prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if not body:
            continue
        title = (
            f"{match.group('number')}{match.group('separator')} "
            f"{' '.join(match.group('title').split())}"
        )
        sections.append((title, body))
    return sections


def _narrative_section(
    *,
    document: Any,
    section_name: str,
    text: str,
    role: SectionRole,
    section_index: int,
) -> SourceSection | None:
    fact_values = _split_narrative_chunk(text)
    facts = tuple(
        SourceFact(
            fact_id=_stable_id(
                "source-fact",
                document.doc_id,
                section_name,
                str(part_index),
                value,
            ),
            subject=section_name,
            attribute=_narrative_attribute(value),
            value=value,
            source_locator=_locator(
                doc_id=document.doc_id,
                source_revision=document.source_revision,
                section=section_name,
                section_index=section_index,
                part=part_index,
            ),
            confidence=float(_narrative_fact_metadata(value)["confidence"]),
            uncertainty=str(_narrative_fact_metadata(value)["uncertainty"]),
        )
        for part_index, value in enumerate(fact_values, start=1)
    )
    if not facts:
        return None
    return SourceSection(
        section_id=f"{document.doc_id}:section:{section_index}:{_slug(section_name)}",
        title=section_name,
        role=_section_role(role),  # type: ignore[arg-type]
        facts=facts,
    )


_APPENDIX_MARKER_RE = re.compile(
    r"\b(?:appendix|приложение)\s+(?P<label>[A-ZА-Я0-9]+)\s*[.:]",
    re.IGNORECASE,
)


def _supporting_appendix(
    section: SourceSection,
    title: str,
    facts: list[SourceFact],
) -> SourceSection:
    return SourceSection(
        section_id=f"{section.section_id}:appendix:{_slug(title)}",
        title=title,
        role="supporting",
        facts=tuple(facts),
    )


def _split_narrative_appendices(sections: list[SourceSection]) -> list[SourceSection]:
    """Move explicit appendices out of the curriculum while keeping them retrievable."""

    resolved: list[SourceSection] = []
    for section in sections:
        primary_facts: list[SourceFact] = []
        appendix_title = ""
        appendix_facts: list[SourceFact] = []

        for fact in section.facts:
            marker = _APPENDIX_MARKER_RE.search(fact.value)
            if marker is not None:
                if appendix_facts:
                    resolved.append(
                        _supporting_appendix(section, appendix_title, appendix_facts)
                    )
                appendix_title = f"Приложение {marker.group('label').upper()}"
                appendix_facts = [fact]
            elif appendix_title:
                appendix_facts.append(fact)
            else:
                primary_facts.append(fact)
        if primary_facts:
            resolved.append(SourceSection(
                section_id=section.section_id,
                title=section.title,
                role=section.role,
                facts=tuple(primary_facts),
            ))
        if appendix_facts:
            resolved.append(_supporting_appendix(section, appendix_title, appendix_facts))
    return resolved


def build_evidence_source(corpus: DirectSourceCorpus) -> EvidenceSourceBundle:
    """Convert verified direct-source chunks without reopening an ambient file."""

    passport = build_document_passport(corpus)
    role_by_section = {
        (section.document_id, section.name.casefold().strip()): section.role
        for section in passport.sections
    }
    document_by_id = {document.doc_id: document for document in corpus.documents}
    sections: list[SourceSection] = []
    tables = merged_direct_source_worksheet_tables(corpus)
    table_keys: set[tuple[str, str]] = set()
    for doc_id, normalized_heading, heading, headers, rows in tables:
        table_keys.add((doc_id, normalized_heading))
        role = role_by_section.get((doc_id, normalized_heading), SectionRole.UNKNOWN)
        title = heading.removeprefix("[Worksheet] ").strip()
        document = document_by_id[doc_id]
        sheet_facts: list[SourceFact] = []
        matrix = bool(headers and headers[0].casefold().strip() in {
            "поле", "характеристика", "параметр", "свойство", "field", "attribute", "parameter", "property",
        })
        for row_index, (cells, _raw) in enumerate(rows, start=2):
            if matrix:
                attribute = cells[0].strip()
                for column_index, entity in enumerate(headers[1:], start=2):
                    value = cells[column_index - 1].strip() if column_index - 1 < len(cells) else ""
                    if not attribute or not entity.strip() or not value:
                        continue
                    sheet_facts.append(SourceFact(
                        fact_id=_stable_id("source-fact", doc_id, title, attribute, entity, value),
                        subject=entity.strip(),
                        attribute=attribute,
                        value=value,
                        source_locator=_locator(
                            doc_id=doc_id,
                            source_revision=document.source_revision,
                            section=title,
                            row=row_index,
                            column=column_index,
                        ),
                    ))
            else:
                subject = cells[0].strip() if cells else ""
                if not subject:
                    continue
                for column_index, header in enumerate(headers[1:], start=2):
                    value = cells[column_index - 1].strip() if column_index - 1 < len(cells) else ""
                    if not header.strip() or not value:
                        continue
                    sheet_facts.append(SourceFact(
                        fact_id=_stable_id("source-fact", doc_id, title, subject, header, value),
                        subject=subject,
                        attribute=header.strip(),
                        value=value,
                        source_locator=_locator(
                            doc_id=doc_id,
                            source_revision=document.source_revision,
                            section=title,
                            row=row_index,
                            column=column_index,
                        ),
                    ))
        if sheet_facts:
            sections.append(SourceSection(
                section_id=f"{doc_id}:sheet:{_slug(title)}",
                title=title,
                role=_section_role(role),  # type: ignore[arg-type]
                facts=tuple(sheet_facts),
            ))

    for document in corpus.documents:
        ordered_chunks = [
            chunk
            for chunk in sorted(document.chunks, key=lambda item: item.chunk_index)
            if (
                document.doc_id,
                next(
                    (
                        heading.removeprefix("[Worksheet] ").strip().casefold()
                        for heading in reversed(chunk.headings)
                    ),
                    "",
                ),
            )
            not in table_keys
        ]
        if ordered_chunks and all(not chunk.headings for chunk in ordered_chunks):
            reconstructed = _merge_overlapping_chunks(ordered_chunks)
            plain_sections = _plain_numbered_sections(reconstructed, document.title)
            if plain_sections:
                for section_index, (section_name, text) in enumerate(plain_sections, start=1):
                    role = _narrative_section_role(
                        document_id=document.doc_id,
                        section_name=section_name,
                        role_by_section=role_by_section,
                    )
                    if section_name == document.title and len(plain_sections) > 1:
                        role = SectionRole.SUPPORTING
                    section = _narrative_section(
                        document=document,
                        section_name=section_name,
                        text=text,
                        role=role,
                        section_index=section_index,
                    )
                    if section is not None:
                        sections.append(section)
                continue

        navigation_prefix_end = _initial_navigation_prefix_end(ordered_chunks)
        if navigation_prefix_end:
            first_body = ordered_chunks[navigation_prefix_end]
            ordered_chunks = [
                replace(first_body, text=_trim_to_first_numbered_markdown_heading(first_body.text)),
                *ordered_chunks[navigation_prefix_end + 1 :],
            ]

        grouped: dict[str, list[Any]] = defaultdict(list)
        has_structured_headings = any(chunk.headings for chunk in ordered_chunks)
        previous_section_name = ""
        for chunk in ordered_chunks:
            section_name = _chunk_section_name(chunk, document.title).removeprefix(
                "[Worksheet] "
            ).strip()
            normalized = section_name.casefold().strip()
            if (document.doc_id, normalized) in table_keys:
                continue
            if is_navigation_heading(section_name):
                previous_section_name = ""
                continue
            if _is_wrapped_heading_extension(previous_section_name, section_name):
                grouped[section_name] = [*grouped.pop(previous_section_name), chunk]
            elif (
                _NUMBERED_SECTION_PREFIX_RE.match(previous_section_name)
                and _is_uppercase_heading_fragment(section_name)
            ):
                if previous_section_name.casefold().endswith(section_name.casefold()):
                    grouped[previous_section_name].append(chunk)
                    section_name = previous_section_name
                else:
                    section_name = f"{previous_section_name} {section_name}"
                    grouped[section_name] = [*grouped.pop(previous_section_name), chunk]
            else:
                grouped[section_name].append(chunk)
            previous_section_name = section_name
        for section_name, chunks in grouped.items():
            role = _narrative_section_role(
                document_id=document.doc_id,
                section_name=section_name,
                role_by_section=role_by_section,
            )
            if has_structured_headings and len(grouped) > 1 and section_name == document.title:
                role = SectionRole.SUPPORTING
            narrative_facts: list[SourceFact] = []
            # Reassemble overlapping storage chunks before semantic splitting;
            # storage/token boundaries must not detach a rule from its exception.
            section_text = _merge_overlapping_chunks(chunks)
            for part_index, value in enumerate(_split_narrative_chunk(section_text), start=1):
                metadata = _narrative_fact_metadata(value)
                narrative_facts.append(SourceFact(
                    fact_id=_stable_id("source-fact", document.doc_id, section_name,
                                       str(part_index), value),
                    subject=section_name,
                    attribute=_narrative_attribute(value),
                    value=value,
                    source_locator=_locator(
                        doc_id=document.doc_id, source_revision=document.source_revision,
                        chunk_ids=",".join(chunk.chunk_id for chunk in chunks),
                        section=section_name, part=part_index,
                    ),
                    confidence=float(metadata["confidence"]),
                    uncertainty=str(metadata["uncertainty"]),
                ))
            if narrative_facts:
                sections.append(SourceSection(
                    section_id=f"{document.doc_id}:section:{_slug(section_name)}",
                    title=section_name,
                    role=_section_role(role),  # type: ignore[arg-type]
                    facts=tuple(narrative_facts),
                ))

    revisions = sorted(document.source_revision for document in corpus.documents)
    digest = hashlib.sha256("\x1f".join(revisions).encode("utf-8")).hexdigest()
    titles = list(dict.fromkeys(document.title for document in corpus.documents))
    kind: Literal["spreadsheet", "narrative"] = "spreadsheet" if tables else "narrative"
    if kind == "narrative":
        sections = _split_narrative_appendices(sections)
    return EvidenceSourceBundle(
        document=SourceDocument(
            source_id=f"direct:{digest}",
            title=" + ".join(titles),
            kind=kind,
            sections=tuple(sections),
            source_sha256=digest,
            teachable_units=passport.teachable_units,
        )
    )


async def _checkpoint(callback: CancellationCallback | None) -> None:
    if callback is None:
        return
    value = callback()
    if inspect.isawaitable(value):
        await value


async def _progress(
    callback: ProgressCallback | None,
    stage: str,
    completed: int,
    total: int,
    provider: str | None = None,
    attempt: int | None = None,
) -> None:
    if callback is None:
        return
    value = callback(stage, completed, total, provider, attempt)
    if inspect.isawaitable(value):
        await value


def _json_object(value: str) -> dict[str, Any]:
    content = value.strip()
    if content.startswith("```"):
        content = content.removeprefix("```json").removeprefix("```")
        content = content.removesuffix("```").strip()
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("evidence_realizer_response_not_object")
    return payload


def _deduplicate_questions(questions: list[QuestionDraft]) -> list[QuestionDraft]:
    accepted: list[QuestionDraft] = []
    seen: set[str] = set()
    for question in questions:
        key = " ".join(question.prompt.casefold().replace("ё", "е").split())
        if key in seen:
            continue
        seen.add(key)
        accepted.append(question)
    return accepted


def _escape_markdown_text(value: str) -> str:
    """Neutralize source markup while preserving source-visible text."""

    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
    for marker in ("`", "*", "_", "#", "|", "!", "~", "[", "]", "(", ")"):
        escaped = escaped.replace(marker, f"\\{marker}")
    escaped = re.sub(r"(?m)^(\s*)([-+>])", r"\1\\\2", escaped)
    escaped = re.sub(r"(?m)^(\s*)(\d+)\.", r"\1\2\\.", escaped)
    return escaped


def _grounded_fallback(
    *,
    base_lesson: LessonDraft,
    plan_fact_ids: tuple[str, ...],
    facts_by_id: dict[str, SourceFact],
    seeds: list[QuestionDraft],
) -> tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]]:
    """Return a readable source-only lesson when every model attempt is unusable."""

    blocks: list[GroundedBlock] = []
    rendered: list[str] = []
    for fact_id in plan_fact_ids:
        fact = facts_by_id[fact_id]
        heading = neutralize_unprofessional_source_language(
            " ".join(fact.attribute.strip().rstrip(".:").split())
        ) or "Подтверждённые сведения"
        text = neutralize_unprofessional_source_language(fact.value.strip())
        blocks.append(
            GroundedBlock(
                lesson_id=base_lesson.lesson_id,
                heading=heading,
                text=text,
                fact_ids=(fact_id,),
            )
        )
        rendered.extend((f"### {_escape_markdown_text(heading)}", "", _escape_markdown_text(text), ""))
    word_count = len(re.findall(r"\w+", " ".join(rendered), flags=re.UNICODE))
    return (
        LessonDraft(
            lesson_id=base_lesson.lesson_id,
            module_title=base_lesson.module_title,
            title=neutralize_unprofessional_source_language(base_lesson.title),
            objective=neutralize_unprofessional_source_language(base_lesson.objective),
            content="\n".join(rendered).strip(),
            fact_ids=base_lesson.fact_ids,
            supporting_fact_ids=base_lesson.supporting_fact_ids,
            duration_minutes=max(2, math.ceil(word_count / 130)),
        ),
        list(seeds),
        blocks,
    )


async def generate_evidence_course(
    corpus: DirectSourceCorpus,
    *,
    intent: CourseIntent,
    generation_client: GenerationClient,
    embedding_client: EmbeddingClient,
    progress_callback: ProgressCallback | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> EvidenceGenerationOutput:
    """Generate a complete validated draft or raise before database persistence."""

    started = perf_counter()
    await _checkpoint(cancellation_callback)
    bundle = build_evidence_source(corpus)
    evidence_result = EvidenceCourseEngine().generate_from_document(bundle.document, intent=intent)
    if not evidence_result.evidence_plan:
        raise ValueError("evidence_plan_empty")
    preflight_reasons = evaluate_plan_preflight(evidence_result)
    if preflight_reasons:
        raise ValueError("evidence_plan_invalid:" + ",".join(preflight_reasons))
    evidence_seconds = perf_counter() - started
    await _progress(progress_callback, "evidence_plan", 1, 1)

    facts = list(evidence_result.admitted_facts)
    facts_by_id = {fact.fact_id: fact for fact in facts}
    lesson_by_id = {lesson.lesson_id: lesson for lesson in evidence_result.course.lessons}
    seeds_by_lesson: dict[str, list[QuestionDraft]] = defaultdict(list)
    for question in evidence_result.assessment.questions:
        seeds_by_lesson[question.lesson_id].append(question)

    embedding_started = perf_counter()
    embedding_model = ""
    embedding_dimension = 0
    embedding_degraded = False
    embedding_error = ""
    retrieval: list[RetrievalMeasurement] = []
    embedding_total = len(facts) + len(evidence_result.evidence_plan)

    async def document_progress(
        completed: int,
        _total: int,
        provider: str,
        attempt: int = 1,
    ) -> None:
        await _progress(
            progress_callback,
            "embeddings",
            completed,
            embedding_total,
            provider,
            attempt,
        )

    async def query_progress(
        completed: int,
        _total: int,
        provider: str,
        attempt: int = 1,
    ) -> None:
        await _progress(
            progress_callback,
            "embeddings",
            len(facts) + completed,
            embedding_total,
            provider,
            attempt,
        )

    try:
        await _checkpoint(cancellation_callback)
        document_batch = await embedding_client.embed_documents_with_provenance(
            [fact.value for fact in facts],
            on_progress=document_progress,
        )
        document_vectors = tuple(_normalize(tuple(vector)) for vector in document_batch.vectors)
        if len(document_vectors) != len(facts):
            raise ValueError("document_embedding_count_mismatch")
        queries: list[str] = []
        for plan in evidence_result.evidence_plan:
            await _checkpoint(cancellation_callback)
            # The resilient client owns the Qwen instruction prefix and applies
            # it only to query embeddings. Passing plain text avoids double prefixing.
            queries.append(" ".join((
                plan.title,
                plan.objective,
                *sorted({facts_by_id[fact_id].attribute for fact_id in plan.fact_ids}),
            )))
        query_batch = await embedding_client.embed_queries_with_provenance(
            queries,
            on_progress=query_progress,
        )
        if len(query_batch.vectors) != len(queries):
            raise ValueError("query_embedding_count_mismatch")
        if query_batch.space != document_batch.space:
            # Provider failover is allowed, but vectors from unrelated model
            # families must never be compared. Retrieval is a quality metric,
            # so degrade it without blocking grounded course realization.
            embedding_degraded = True
            embedding_error = "IncompatibleEmbeddingSpace"
        else:
            query_vectors = tuple(
                _normalize(tuple(vector)) for vector in query_batch.vectors
            )
            retrieval = ProviderBackedEvidenceEngine._measure_retrieval(
                facts=facts,
                document_vectors=document_vectors,
                query_vectors=query_vectors,
                plans=evidence_result.evidence_plan,
            )
        embedding_model = str(document_batch.model)
        embedding_dimension = len(document_vectors[0]) if document_vectors else 0
    except AllProvidersFailedError as exc:
        embedding_degraded = True
        embedding_error = type(exc).__name__
    embedding_seconds = perf_counter() - embedding_started
    if embedding_degraded:
        await _progress(progress_callback, "embeddings", embedding_total, embedding_total)

    realization_started = perf_counter()
    realized_lessons: list[LessonDraft] = []
    realized_questions: list[QuestionDraft] = []
    grounded_blocks: list[GroundedBlock] = []
    validation_errors: list[str] = []
    provider_fallback_count = 0
    deterministic_fallback_count = 0
    deterministic_fallback_lesson_ids: list[str] = []
    chat_attempt_count = 0
    chat_model = ""
    total = len(evidence_result.evidence_plan)
    for index, plan in enumerate(evidence_result.evidence_plan, start=1):
        await _checkpoint(cancellation_callback)
        base_lesson = lesson_by_id[plan.lesson_id]
        seeds = seeds_by_lesson.get(plan.lesson_id, [])
        request = ProviderBackedEvidenceEngine._realizer_request(
            plan,
            facts_by_id,
            seeds,
            intent,
        )

        def parser(
            raw: str,
            *,
            _base_lesson: LessonDraft = base_lesson,
            _plan_fact_ids: frozenset[str] = frozenset(plan.fact_ids),
            _seeds: tuple[QuestionDraft, ...] = tuple(seeds),
        ) -> tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]]:
            payload = _json_object(raw)
            return ProviderBackedEvidenceEngine._validate_and_render(
                payload,
                base_lesson=_base_lesson,
                plan_fact_ids=set(_plan_fact_ids),
                facts_by_id=facts_by_id,
                seeds=list(_seeds),
            )

        validated = None
        lesson_failure_reasons: list[ValidatedCallFailureReason] = []
        for attempt in range(2):
            try:
                validated = await generation_client.ainvoke_validated(
                    [
                        {"role": "system", "content": EVIDENCE_REALIZER_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                request,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    parser=parser,
                    response_format={"type": "json_object"},
                )
                chat_attempt_count += validated.attempt_count
                lesson_failure_reasons.extend(validated.failure_reasons)
                provider_fallback_count += max(0, validated.attempt_count - 1)
                break
            except AllProvidersFailedError as exc:
                reasons = list(exc.reasons) or [ValidatedCallFailureReason.PROVIDER_UNAVAILABLE]
                lesson_failure_reasons.extend(reasons)
                chat_attempt_count += len(reasons)
                provider_fallback_count += len(reasons)
                if attempt == 1:
                    validated = None
                    break
                request["validation_feedback"] = (
                    "The previous provider chain did not satisfy the strict evidence "
                    "contract. Return complete JSON, cover every supplied fact_id, and "
                    "introduce no facts or numbers outside the supplied evidence."
                )
        validation_errors.extend(reason.value for reason in lesson_failure_reasons)
        if validated is None:
            deterministic_fallback_count += 1
            deterministic_fallback_lesson_ids.append(plan.lesson_id)
            lesson, questions, blocks = _grounded_fallback(
                base_lesson=base_lesson,
                plan_fact_ids=plan.fact_ids,
                facts_by_id=facts_by_id,
                seeds=seeds,
            )
            chat_model = "deterministic-grounded-fallback"
        else:
            lesson, questions, blocks = validated.value
            chat_model = str(validated.model_id)
        realized_lessons.append(lesson)
        realized_questions.extend(questions)
        grounded_blocks.extend(blocks)
        await _progress(progress_callback, "realization", index, total)

    assessment_started = perf_counter()

    async def assessment_progress(done: int, count: int) -> None:
        await _progress(progress_callback, "assessment", done, count)

    reviewed = await generate_block_assessment(
        realized_lessons, facts_by_id, generation_client,
        checkpoint=lambda: _checkpoint(cancellation_callback),
        on_progress=assessment_progress,
    )
    realized_questions = list(reviewed.questions)
    chat_attempt_count += reviewed.attempt_count
    realized_course = CourseDraft(
        title=bundle.document.title,
        description=evidence_result.course.description,
        lessons=tuple(realized_lessons),
    )
    realized_assessment = AssessmentDraft(questions=tuple(realized_questions))
    publishability = evaluate_publishability(
        course=realized_course,
        assessment=realized_assessment,
        blocks=tuple(grounded_blocks),
        planned_fact_ids={fact.fact_id for fact in evidence_result.admitted_facts},
        provider_fallback_count=provider_fallback_count,
    )
    if not publishability.publishable:
        raise ValueError("evidence_publishability_failed:" + ",".join(publishability.reasons))
    if not realized_questions:
        # Keep usable lessons, but never label an empty assessment publishable.
        # The pipeline persists this as a review-required saved draft.
        publishability = replace(publishability, publishable=False,
                                 reasons=("assessment_no_valid_questions",))
    elif reviewed.audit.get("coverage", {}).get("requires_review"):
        publishability = replace(publishability, publishable=False,
                                 reasons=("assessment_coverage_incomplete",))
    await _checkpoint(cancellation_callback)
    await _progress(progress_callback, "quality", 1, 1)
    result = ProviderBackedResult(
        evidence_result=evidence_result,
        realized_course=realized_course,
        realized_assessment=realized_assessment,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        embedding_degraded=embedding_degraded,
        embedding_error=embedding_error,
        chat_model=chat_model,
        retrieval=tuple(retrieval),
        grounded_blocks=tuple(grounded_blocks),
        publishability=publishability,
        provider_fallback_count=provider_fallback_count,
        deterministic_fallback_count=deterministic_fallback_count,
        deterministic_fallback_lesson_ids=tuple(deterministic_fallback_lesson_ids),
        validation_errors=tuple(validation_errors),
        chat_attempt_count=chat_attempt_count,
        prompt_tokens=0,
        completion_tokens=0,
        assessment_review=reviewed.audit,
        timings=(
            StageTiming(stage="evidence_plan", seconds=evidence_seconds),
            StageTiming(stage="embeddings", seconds=embedding_seconds),
            StageTiming(stage="realization", seconds=assessment_started - realization_started),
            StageTiming(stage="assessment", seconds=perf_counter() - assessment_started),
        ),
    )
    return EvidenceGenerationOutput(result=result, corpus=corpus)


def _fact_reference(fact: SourceFact, corpus: DirectSourceCorpus) -> dict[str, Any]:
    values = _locator_values(fact.source_locator)
    doc_id = values.get("doc_id", "")
    document = next((item for item in corpus.documents if item.doc_id == doc_id), None)
    doc_name = document.filename if document is not None else doc_id
    section = values.get("section", "")
    headings = [section] if section else []
    return {
        "document": doc_name,
        "doc_id": doc_id,
        "doc_name": doc_name,
        "headings": headings,
        "context_sections": [
            {"document": doc_name, "headings": headings, "is_anchor": True}
        ],
        "source_locator": fact.source_locator,
        "fact_id": fact.fact_id,
    }


def to_generation_artifacts(output: EvidenceGenerationOutput) -> GenerationArtifacts:
    """Map the validated V2 result onto the existing single persistence contract."""

    result = output.result
    facts_by_id = {
        fact.fact_id: fact
        for fact in (
            *result.evidence_result.admitted_facts,
            *result.evidence_result.supporting_facts,
        )
    }
    questions_by_lesson: dict[str, list[QuestionDraft]] = defaultdict(list)
    for question in result.realized_assessment.questions:
        questions_by_lesson[question.lesson_id].append(question)
    grouped: dict[str, list[LessonDraft]] = defaultdict(list)
    for lesson in result.realized_course.lessons:
        grouped[lesson.module_title].append(lesson)
    fallback_lesson_ids = set(result.deterministic_fallback_lesson_ids)

    structure_modules: list[StructureModule] = []
    content_modules: list[ModuleContent] = []
    assessments: list[LessonAssessment] = []
    for module_title, lessons in grouped.items():
        structure_lessons: list[StructureLesson] = []
        content_lessons: list[LessonContent] = []
        for lesson in lessons:
            fact_ids = tuple(dict.fromkeys((*lesson.fact_ids, *lesson.supporting_fact_ids)))
            lesson_facts = [facts_by_id[fact_id] for fact_id in fact_ids]
            references = [_fact_reference(fact, output.corpus) for fact in lesson_facts]
            doc_ids = list(dict.fromkeys(ref["doc_id"] for ref in references if ref["doc_id"]))
            headings = list(dict.fromkeys(
                heading for ref in references for heading in ref.get("headings", []) if heading
            ))
            structure_lessons.append(StructureLesson(
                title=lesson.title,
                objectives=[LearningObjective(text=lesson.objective)],
                description=lesson.objective,
                source_doc_ids=doc_ids,
                relevant_headings=headings,
            ))
            content_lessons.append(LessonContent(
                title=lesson.title,
                objectives=[lesson.objective],
                content=lesson.content,
                source_chunks=[fact.value for fact in lesson_facts],
                source_references=references,
                quality_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
                source_validation_status=(
                    "needs_review" if lesson.lesson_id in fallback_lesson_ids else "verified"
                ),
            ))
            lesson_questions = questions_by_lesson.get(lesson.lesson_id, [])
            assessments.append(LessonAssessment(
                lesson_title=lesson.title,
                mcq=[
                    MCQQuestion(
                        question=question.prompt,
                        options=[
                            MCQOption(text=option, is_correct=option == question.correct_answer)
                            for option in question.options
                        ],
                        explanation=question.explanation,
                        source_quote=question.source_quote or facts_by_id[question.fact_id].value,
                        quality_score=3.0,
                    )
                    for question in lesson_questions
                ],
                quality_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
                omission_reason=("no_safe_source_grounded_questions" if not lesson_questions else ""),
            ))
        structure_modules.append(StructureModule(
            title=module_title,
            description="",
            lessons=structure_lessons,
        ))
        content_modules.append(ModuleContent(title=module_title, lessons=content_lessons))

    degraded = result.embedding_degraded or result.deterministic_fallback_count > 0
    degraded_notice = (
        "Часть материала сохранена только по подтверждённым сведениям источника "
        "из-за недоступности или некорректного ответа модели. Черновик требует "
        "проверки методистом перед публикацией."
    )
    course_description = result.realized_course.description
    if degraded and degraded_notice not in course_description:
        course_description = "\n\n".join(filter(None, (course_description, degraded_notice)))

    diagnostics = {
        "engine": "evidence_v2",
        "quality_policy_version": EVIDENCE_QUALITY_POLICY_VERSION,
        "semantic_fingerprint": result.evidence_result.semantic_fingerprint,
        "publishable": result.publishability.publishable,
        "fact_coverage_ratio": result.publishability.fact_coverage_ratio,
        "admitted_fact_count": result.evidence_result.document_plan.admitted_fact_count,
        "supporting_fact_count": result.evidence_result.document_plan.supporting_fact_count,
        "lesson_count": len(result.realized_course.lessons),
        "question_count": len(result.realized_assessment.questions),
        "assessment_review": result.assessment_review,
        "supporting_lesson_share": result.evidence_result.evaluation.supporting_lesson_share,
        "plan_capacity_ratio": result.evidence_result.evaluation.capacity_ratio,
        "generated_duration_minutes": sum(
            lesson.duration_minutes for lesson in result.realized_course.lessons
        ),
        "pre_realization_invalid_title_count": (
            result.evidence_result.evaluation.invalid_title_count
        ),
        "quota_padding_count": result.evidence_result.evaluation.quota_padding_count,
        "embedding_model": result.embedding_model,
        "embedding_dimension": result.embedding_dimension,
        "embedding_degraded": result.embedding_degraded,
        "chat_model": result.chat_model,
        "quality_status": (
            "degraded_needs_review" if degraded else
            "assessment_needs_review" if not result.realized_assessment.questions
            or result.assessment_review.get("terminal_status") == "review_required"
            or result.assessment_review.get("coverage", {}).get("requires_review") else "validated_draft"
        ),
        "provider_fallback_count": result.provider_fallback_count,
        "deterministic_fallback_count": result.deterministic_fallback_count,
        "validation_errors": list(dict.fromkeys(result.validation_errors))[:50],
        "chat_attempt_count": result.chat_attempt_count,
        "timings": {timing.stage: round(timing.seconds, 3) for timing in result.timings},
    }
    return GenerationArtifacts(
        structure=CourseStructure(
            title=result.realized_course.title,
            description=course_description,
            modules=structure_modules,
        ),
        content=CourseContent(
            title=result.realized_course.title,
            description=course_description,
            modules=content_modules,
            source_warnings=[degraded_notice] if degraded else [],
        ),
        assessment=CourseAssessment(assessments=assessments),
        diagnostics=diagnostics,
    )
