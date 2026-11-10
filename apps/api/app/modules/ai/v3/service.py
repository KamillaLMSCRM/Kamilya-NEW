"""Production service entry point for V3 Course & Assessment Co-Generation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.extraction_checkpoint import ExtractionJournal, ExtractionOutcomeUnknownError
from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity, V3Course, V3Lesson
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision, reference_context_for_rules
from app.modules.ai.v3.source_units import find_rendered_quote_spans, rendered_candidate_preserves_table_boundaries
from app.modules.ai.v3.validator import (
    normalize_literal_quote,
    normalize_literal_quote_with_char_map,
    validate_v3_course,
)
from app.modules.ai.v3.validator import (
    normalize_text_for_search as normalize_text_for_search,
)

logger = logging.getLogger(__name__)


def _extract_corpus_text(corpus: DirectSourceCorpus) -> tuple[str, str]:
    """Use the retained converted source and compute its SHA256.

    IMPORTANT: Metadata headers (document titles, filenames) are strictly excluded from full_text
    so that citation grounding validates exclusively against authentic chunk contents.
    """
    text_parts: list[str] = []
    for doc in corpus.documents:
        if doc.source_text is not None:
            if doc.source_text:
                text_parts.append(doc.source_text)
            continue
        # Legacy captured corpora have no original text; preserve all chunks
        # verbatim rather than guessing whether a repeated passage is overlap.
        for chunk in doc.chunks:
            c = chunk.text.strip()
            if c:
                text_parts.append(c)

    full_text = "\n\n".join(text_parts)
    sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    return full_text, sha256


@dataclass(frozen=True)
class QuoteOccurrence:
    doc_id: str
    chunk_id: str
    doc_revision: str
    chunk_revision: str
    source_revision: str
    char_start: int
    char_end: int
    matched_text: str
    scope: str = "chunk"


def find_quote_occurrences_in_corpus(
    quote: str,
    corpus: DirectSourceCorpus,
) -> list[QuoteOccurrence]:
    """Find exact occurrences in the canonical source, or legacy chunks when unavailable.

    Guarantees that chunk.text[char_start:char_end] strictly matches the quote without truncating words.
    """
    clean_quote = quote.strip()
    if not clean_quote:
        return []
    norm_q = normalize_literal_quote(clean_quote)
    if not norm_q:
        return []

    occurrences: list[QuoteOccurrence] = []
    match_len = len(norm_q)

    for doc in corpus.documents:
        doc_rev = (doc.source_revision or "").strip()
        if doc.source_text is not None:
            # When a full working source exists it is authoritative. Chunks
            # can be stale even when the original document revision matches.
            # Conflicting or absent chunk revisions remain a review hold.
            if not doc_rev or not doc.chunks or any(
                chunk.doc_id != doc.doc_id or (chunk.source_revision or "").strip() != doc_rev
                for chunk in doc.chunks
            ):
                continue
            norm_doc, doc_map = normalize_literal_quote_with_char_map(doc.source_text)
            start_pos = 0
            while (idx := norm_doc.find(norm_q, start_pos)) >= 0:
                orig_start = doc_map[idx]
                orig_end = doc_map[idx + match_len - 1] + 1
                matched_slice = doc.source_text[orig_start:orig_end]
                if normalize_literal_quote(matched_slice) == normalize_literal_quote(clean_quote):
                    occurrences.append(QuoteOccurrence(
                        doc_id=doc.doc_id, chunk_id="", doc_revision=doc_rev,
                        chunk_revision="", source_revision=doc_rev,
                        char_start=orig_start, char_end=orig_end, matched_text=matched_slice, scope="document",
                    ))
                start_pos = idx + 1
            continue

        for chunk in doc.chunks:
            c_text = chunk.text
            norm_c, char_map = normalize_literal_quote_with_char_map(c_text)
            chunk_rev = (chunk.source_revision or "").strip()
            doc_rev = (doc.source_revision or "").strip()
            effective_rev = chunk_rev or doc_rev
            start_pos = 0
            while True:
                idx = norm_c.find(norm_q, start_pos)
                if idx == -1:
                    break
                orig_start = char_map[idx]
                orig_end = char_map[idx + match_len - 1] + 1
                matched_slice = c_text[orig_start:orig_end]
                # Reverse verification check: normalized slice must match norm_q
                # Do not silently join different table cells into one claimed
                # quotation when the submitted quote contains no delimiters.
                if normalize_literal_quote(matched_slice) == normalize_literal_quote(clean_quote):
                    occurrences.append(
                        QuoteOccurrence(
                            doc_id=doc.doc_id,
                            chunk_id=chunk.chunk_id,
                            doc_revision=doc_rev,
                            chunk_revision=chunk_rev,
                            source_revision=effective_rev,
                            char_start=orig_start,
                            char_end=orig_end,
                            matched_text=matched_slice,
                        )
                    )
                start_pos = idx + 1


    return occurrences


def _find_quote_in_corpus(
    quote: str,
    corpus: DirectSourceCorpus,
    preferred_doc_id: str | None = None,
) -> tuple[bool, str | None, str | None, int | None, int | None]:
    """Backwards-compatible wrapper returning the primary matching occurrence coordinates."""
    occurrences = find_quote_occurrences_in_corpus(quote, corpus)
    if not occurrences:
        return False, None, None, None, None
    if preferred_doc_id:
        doc_matches = [occ for occ in occurrences if occ.doc_id == preferred_doc_id]
        if doc_matches:
            first = doc_matches[0]
            return True, first.doc_id, first.chunk_id or None, first.char_start, first.char_end
    first = occurrences[0]
    return True, first.doc_id, first.chunk_id or None, first.char_start, first.char_end


def _occurrence_matches_revision(occ: QuoteOccurrence, rule_rev: str) -> tuple[bool, str]:
    """Jointly verifies revision consistency between Rule, Document, and specific Chunk.

    Guarantees:
    - Every revision (Rule, Document, Chunk) must be explicitly known and non-empty.
    - Missing or unknown revisions are NEVER assumed or substituted; they require manual review.
    - If chunk has a revision different from document, conflict is detected.
    - If chunk has a revision different from rule, conflict is detected.
    - If document has a revision different from rule, conflict is detected.
    """
    chunk_rev = (occ.chunk_revision or "").strip()
    doc_rev = (occ.doc_revision or "").strip()
    rule_rev = (rule_rev or "").strip()

    if occ.scope == "document":
        if not doc_rev or not rule_rev:
            return False, "Неизвестная ревизия документа или правила требует проверки"
        if doc_rev != rule_rev:
            return False, f"Несоответствие ревизии документа '{occ.doc_id}' и правила"
        return True, ""

    # 1. Unknown / missing revisions must fail verification and stay for review
    if not chunk_rev:
        return False, (
            f"Неопределенная ревизия фрагмента: чанк '{occ.chunk_id}' документа '{occ.doc_id}' "
            "не имеет указанной source_revision (неизвестная ревизия требует проверки)"
        )
    if not doc_rev:
        return False, (
            f"Неопределенная ревизия документа: документ '{occ.doc_id}' "
            "не имеет указанной source_revision (неизвестная ревизия требует проверки)"
        )
    if not rule_rev:
        return False, (
            "Неопределенная ревизия правила: правило не указывает обязательную source_revision "
            "(неизвестная ревизия требует проверки)"
        )

    # 2. Internal consistency between document and chunk
    if chunk_rev != doc_rev:
        return False, (
            f"Несогласованность ревизий источника: документ '{occ.doc_id}' имеет ревизию '{doc_rev}', "
            f"но чанк '{occ.chunk_id}' содержит ревизию '{chunk_rev}'"
        )

    # 3. Rule revision matching
    if chunk_rev == doc_rev and doc_rev != rule_rev:
        return False, (
            f"Несоответствие ревизии документа: документ '{occ.doc_id}' (чанк '{occ.chunk_id}') имеет ревизию '{doc_rev}', "
            f"а правило привязано к ревизии '{rule_rev}'"
        )
    if chunk_rev != rule_rev:
        return False, (
            f"Несоответствие ревизии чанка: чанк '{occ.chunk_id}' имеет ревизию '{chunk_rev}', "
            f"а правило привязано к ревизии '{rule_rev}'"
        )
    if doc_rev != rule_rev:
        return False, (
            f"Несоответствие ревизии документа: документ '{occ.doc_id}' имеет ревизию '{doc_rev}', "
            f"а правило привязано к ревизии '{rule_rev}'"
        )

    return True, ""


def _verify_rule_quote_grounding(
    rule: RuleEntity,
    corpus: DirectSourceCorpus,
) -> tuple[bool, str, list[QuoteOccurrence]]:
    """Verifies citation grounding of a rule against the corpus, enforcing ownership and ambiguity resolution.

    Returns:
        (is_verified, formatted_fragment_or_error, occurrences)
    """
    raw_q = (rule.source_quote or "").strip()
    if not raw_q:
        return False, (
            f"Пробел верификации: у правила {rule.rule_id} ('{rule.title}') полностью отсутствует подтверждающая цитата из первоисточника"
        ), []

    all_occurrences = find_quote_occurrences_in_corpus(raw_q, corpus)
    if not all_occurrences:
        # Candidate retrieval is diagnostic only: stripping display markup can
        # be ambiguous and document offsets differ from chunk coordinates.
        for doc in corpus.documents:
            if (rule.doc_id and rule.doc_id != doc.doc_id) or not rule.source_revision:
                continue
            if doc.source_revision != rule.source_revision or doc.source_text is None:
                continue
            spans = find_rendered_quote_spans(doc.source_text, raw_q)
            if spans:
                return False, (
                    f"Неподтвержденная цитата в правиле {rule.rule_id}: найдено возможное соответствие "
                    f"с учетом форматирования в документе {doc.doc_id} ({len(spans)} совпадений); "
                    "необходимо сопоставить с точным исходным фрагментом"
                ), []
        return False, (
            f"Неподтвержденная цитата в правиле {rule.rule_id} ('{rule.title}'): фрагмент карты правил отсутствует в содержимом документов корпуса"
        ), []

    rule_doc_id = (rule.doc_id or "").strip()
    rule_rev = (rule.source_revision or "").strip()

    if rule_doc_id:
        doc_matches = [occ for occ in all_occurrences if occ.doc_id == rule_doc_id]
        if not doc_matches:
            other_docs = sorted(list({occ.doc_id for occ in all_occurrences}))
            return False, (
                f"Несоответствие источника: цитата правила {rule.rule_id} ('{rule.title}') найдена в документах {other_docs}, но правило привязано к документу '{rule_doc_id}'"
            ), all_occurrences

        # Joint Rule, Document, and Chunk revision check
        rev_matches: list[QuoteOccurrence] = []
        rev_errors: list[str] = []
        for occ in doc_matches:
            ok, err = _occurrence_matches_revision(occ, rule_rev)
            if ok:
                rev_matches.append(occ)
            else:
                rev_errors.append(err)

        if not rev_matches:
            err_msg = rev_errors[0] if rev_errors else (
                f"Несоответствие ревизии для правила {rule.rule_id} ('{rule.title}'): правило требует '{rule_rev}'"
            )
            return False, err_msg, doc_matches
        target_matches = rev_matches
    else:
        # Rule has no explicit doc_id
        distinct_docs = sorted(list({occ.doc_id for occ in all_occurrences}))
        if len(distinct_docs) > 1:
            return False, (
                f"Неоднозначная принадлежность цитаты для правила {rule.rule_id} ('{rule.title}'): фраза обнаружена сразу в нескольких документах ({distinct_docs}). Требуется явное указание doc_id правила."
            ), all_occurrences

        rev_matches = []
        rev_errors = []
        for occ in all_occurrences:
            ok, err = _occurrence_matches_revision(occ, rule_rev)
            if ok:
                rev_matches.append(occ)
            else:
                rev_errors.append(err)

        if not rev_matches:
            err_msg = rev_errors[0] if rev_errors else (
                f"Несоответствие ревизии для правила {rule.rule_id} ('{rule.title}'): правило требует '{rule_rev}'"
            )
            return False, err_msg, all_occurrences
        target_matches = rev_matches

    # A rule extracted from a source unit must not be certified with text
    # taken only from a neighboring unit, even in the same document/revision.
    if rule.source_start is not None or rule.source_end is not None:
        if (type(rule.source_start) is not int or type(rule.source_end) is not int
                or rule.source_start < 0 or rule.source_end <= rule.source_start):
            return False, f"Некорректная граница источника правила {rule.rule_id}", target_matches
        in_unit = [occ for occ in target_matches if occ.scope == "document"
                   and rule.source_start <= occ.char_start < occ.char_end <= rule.source_end
                   and any(doc.doc_id == occ.doc_id and doc.source_revision == occ.doc_revision
                           and doc.source_text is not None and rule.source_end <= len(doc.source_text)
                           for doc in corpus.documents)]
        if not in_unit:
            return False, f"Цитата правила {rule.rule_id} находится вне его исходного фрагмента", target_matches
        target_matches = in_unit

    primary = target_matches[0]
    multi_note = f" (всего совпадений в документе: {len(target_matches)})" if len(target_matches) > 1 else ""
    location = (
        "координаты полного текста"
        if primary.scope == "document"
        else f"Чанк {primary.chunk_id} (rev: {primary.chunk_revision or primary.doc_revision or 'n/a'})"
    )
    fragment_str = (
        f"[Верифицированная цитата | Документ {primary.doc_id} (rev: {primary.doc_revision or 'n/a'}) | "
        f"{location}{multi_note} | ({primary.char_start}:{primary.char_end})]: {primary.matched_text}"
    )
    return True, fragment_str, target_matches


COMPOUND_REF_RE = re.compile(
    r"(?:пункт[а-я]*|п\.|подпункт[а-я]*|пп\.)\s*([0-9]+(?:\.[0-9]+)*)\s+"
    r"(подраздел[а-я]*|подразд\.|раздел[а-я]*|разд\.|таблиц[а-я]*|табл\.|глав[а-я]*|гл\.|стать[а-я]*|ст\.|приложени[а-я]*|прил\.)\s*"
    r"([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)
REVERSED_COMPOUND_REF_RE = re.compile(
    r"(подраздел[а-я]*|подразд\.|раздел[а-я]*|разд\.|таблиц[а-я]*|табл\.|глав[а-я]*|гл\.|стать[а-я]*|ст\.|приложени[а-я]*|прил\.)\s*"
    r"([0-9]+(?:\.[0-9]+)*)\s*,?\s*"
    r"(?:пункт[а-я]*|п\.|подпункт[а-я]*|пп\.)\s*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)
CLAUSE_REF_RE = re.compile(
    r"(?:пункт[а-я]*|п\.|подпункт[а-я]*|пп\.|стать[а-я]*|ст\.|раздел[а-я]*|таблиц[а-я]*)\s*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)


def _normalize_container_type(raw_type: str) -> str:
    """Normalizes container type, strictly prioritizing 'подраздел' over 'раздел'."""
    raw = raw_type.lower().strip().rstrip(".")
    if raw.startswith("подразд"):
        return "subsection"
    if raw.startswith("разд"):
        return "section"
    if raw.startswith("табл"):
        return "table"
    if raw.startswith("глав") or raw == "гл":
        return "chapter"
    if raw.startswith("стат") or raw == "ст":
        return "article"
    if raw.startswith("прилож") or raw == "прил":
        return "appendix"
    return "unknown"


def _candidate_matches_container(
    candidate: RuleEntity,
    container_type: str,
    container_num: str,
) -> bool:
    """Verifies that candidate strictly matches both the container type and exact number.

    Prevents 'таблица 4' matching 'раздел 4', and 'раздел 4' matching 'подраздел 4.1'.
    """
    sec_title = f"{candidate.section} {candidate.title}".lower()
    num_pattern = r"(?<![\w.-])" + re.escape(container_num) + r"(?![\w.-])"

    if container_type == "table":
        pattern = r"(?:таблиц[а-я]*|табл\.?)\s*" + num_pattern
        return bool(re.search(pattern, sec_title, re.IGNORECASE))

    if container_type == "section":
        # Must declare 'раздел' (and NOT 'подраздел') with the exact number
        pattern = r"(?<!под)(?:раздел[а-я]*|разд\.?)\s*" + num_pattern
        return bool(re.search(pattern, candidate.section, re.IGNORECASE))

    if container_type == "subsection":
        pattern = r"(?:подраздел[а-я]*|подразд\.?)\s*" + num_pattern
        return bool(re.search(pattern, candidate.section, re.IGNORECASE))

    if container_type == "chapter":
        pattern = r"(?:глав[а-я]*|гл\.?)\s*" + num_pattern
        return bool(re.search(pattern, sec_title, re.IGNORECASE))

    if container_type == "article":
        pattern = r"(?:стать[а-я]*|ст\.?)\s*" + num_pattern
        return bool(re.search(pattern, sec_title, re.IGNORECASE))

    if container_type == "appendix":
        pattern = r"(?:приложени[а-я]*|прил\.?)\s*" + num_pattern
        return bool(re.search(pattern, sec_title, re.IGNORECASE))

    return False


def _extract_clause_numbers(text: str) -> list[str]:
    """Extracts formal clause/section numbers from text (e.g. 'пункт 2', 'п. 2.1', '2. Ограничения')."""
    matches = CLAUSE_REF_RE.findall(text)
    start_match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)*)[\.\)\s]", text)
    if start_match:
        matches.append(start_match.group(1))
    res: list[str] = []
    for m in matches:
        clean = m.strip().rstrip(".")
        if clean and clean not in res:
            res.append(clean)
    return res


def _sanitize_rules(
    rules: tuple[RuleEntity, ...] | list[RuleEntity]
) -> tuple[list[RuleEntity], dict[str, list[RuleEntity]]]:
    """Ensures every rule has a non-empty, strictly unique rule_id without collisions.

    Tracks raw IDs so references to duplicated initial IDs are recognized as ambiguous.
    """
    taken_ids: set[str] = set()
    for r in rules:
        clean = (r.rule_id or "").strip()
        if clean:
            taken_ids.add(clean)

    allocated_ids: set[str] = set()
    sanitized: list[RuleEntity] = []
    raw_to_rules: dict[str, list[RuleEntity]] = {}

    for idx, r in enumerate(rules, 1):
        raw_id = (r.rule_id or "").strip()
        base_id = raw_id if raw_id else f"rule-{idx:03d}"
        assigned_id = base_id

        # If base_id is already allocated (or empty), pick a guaranteed collision-free suffix
        if not raw_id or assigned_id in allocated_ids:
            counter = 1
            candidate = f"{base_id}-{counter:03d}"
            while candidate in taken_ids or candidate in allocated_ids:
                counter += 1
                candidate = f"{base_id}-{counter:03d}"
            assigned_id = candidate

        allocated_ids.add(assigned_id)
        taken_ids.add(assigned_id)

        if assigned_id != r.rule_id:
            r = replace(r, rule_id=assigned_id)
        sanitized.append(r)
        if raw_id:
            raw_to_rules.setdefault(raw_id, []).append(r)

    return sanitized, raw_to_rules


def _find_direct_rule_dependencies(
    rule: RuleEntity,
    all_rules: list[RuleEntity],
    clause_index: dict[str, list[RuleEntity]],
    raw_to_rules: dict[str, list[RuleEntity]],
    current_section: str,
    confirmed_clauses: dict[str, RuleEntity] | None = None,
) -> tuple[list[RuleEntity], list[str]]:
    """Discovers direct dependencies for a rule using boundary-safe regex, compound hierarchy, and ambiguous reference tracking."""
    text = f"{rule.statement} {' '.join(rule.conditions)} {' '.join(rule.exceptions)} {rule.timing} {rule.consequences}"
    direct_deps: list[RuleEntity] = []
    unresolved: list[str] = []

    # 1. Exact Rule ID match with boundary safety (?<![\w-])id(?![\w-])
    for target in all_rules:
        if target.rule_id == rule.rule_id:
            continue
        pattern = r"(?<![\w-])" + re.escape(target.rule_id) + r"(?![\w-])"
        if re.search(pattern, text, re.IGNORECASE):
            if target not in direct_deps:
                direct_deps.append(target)

    # 2. Check for references to original raw IDs (including duplicated ones)
    for raw_id, target_rules in raw_to_rules.items():
        if not raw_id:
            continue
        pattern = r"(?<![\w-])" + re.escape(raw_id) + r"(?![\w-])"
        if re.search(pattern, text, re.IGNORECASE):
            other_targets = [t for t in target_rules if t.rule_id != rule.rule_id]
            if len(other_targets) > 1:
                match_ids = [t.rule_id for t in other_targets]
                unresolved.append(
                    f"Неоднозначная ссылка на дублирующийся идентификатор '{raw_id}' в правиле '{rule.rule_id}' (найдено несколько правил с таким исходным ID: {', '.join(match_ids)})"
                )
                for t in other_targets:
                    if t not in direct_deps:
                        direct_deps.append(t)
            elif len(other_targets) == 1:
                if other_targets[0] not in direct_deps:
                    direct_deps.append(other_targets[0])

    # 3. Significant Title match with word boundaries
    for target in all_rules:
        if target.rule_id == rule.rule_id or target in direct_deps:
            continue
        clean_title = target.title.strip()
        if len(clean_title) >= 8 and not clean_title.lower().startswith(("правило", "раздел", "пункт")):
            pattern = r"\b" + re.escape(clean_title) + r"\b"
            if re.search(pattern, text, re.IGNORECASE):
                direct_deps.append(target)

    # 4. Compound hierarchical references (e.g. 'пункт 2 раздела 4', 'раздел 4, пункт 2')
    remaining_text = text

    for match in COMPOUND_REF_RE.finditer(text):
        clause_clean = match.group(1).strip().rstrip(".")
        raw_container_type = match.group(2)
        container_num = match.group(3).strip().rstrip(".")
        container_type = _normalize_container_type(raw_container_type)
        span = match.span()
        # Blank out this compound span so standalone matcher won't parse clause and container separately
        remaining_text = remaining_text[:span[0]] + " " * (span[1] - span[0]) + remaining_text[span[1]:]

        candidates = [c for c in clause_index.get(clause_clean, []) if c.rule_id != rule.rule_id]
        matching = [
            c for c in candidates
            if _candidate_matches_container(c, container_type, container_num)
        ]
        if len(matching) == 1:
            if matching[0] not in direct_deps:
                direct_deps.append(matching[0])
        elif len(matching) > 1:
            match_ids = [c.rule_id for c in matching]
            unresolved.append(
                f"Неоднозначная составная ссылка на пункт '{clause_clean}' {raw_container_type} '{container_num}' в правиле '{rule.rule_id}' (найдено несколько совпадений: {', '.join(match_ids)})"
            )
            for c in matching:
                if c not in direct_deps:
                    direct_deps.append(c)
        else:
            unresolved.append(
                f"Неразрешенная составная ссылка на пункт '{clause_clean}' {raw_container_type} '{container_num}' в правиле '{rule.rule_id}' (точное совпадение по типу и номеру не найдено)"
            )

    for match in REVERSED_COMPOUND_REF_RE.finditer(remaining_text):
        raw_container_type = match.group(1)
        container_num = match.group(2).strip().rstrip(".")
        clause_clean = match.group(3).strip().rstrip(".")
        container_type = _normalize_container_type(raw_container_type)
        span = match.span()
        remaining_text = remaining_text[:span[0]] + " " * (span[1] - span[0]) + remaining_text[span[1]:]

        candidates = [c for c in clause_index.get(clause_clean, []) if c.rule_id != rule.rule_id]
        matching = [
            c for c in candidates
            if _candidate_matches_container(c, container_type, container_num)
        ]
        if len(matching) == 1:
            if matching[0] not in direct_deps:
                direct_deps.append(matching[0])
        elif len(matching) > 1:
            match_ids = [c.rule_id for c in matching]
            unresolved.append(
                f"Неоднозначная составная ссылка на {raw_container_type} '{container_num}', пункт '{clause_clean}' в правиле '{rule.rule_id}' (найдено несколько совпадений: {', '.join(match_ids)})"
            )
            for c in matching:
                if c not in direct_deps:
                    direct_deps.append(c)
        else:
            unresolved.append(
                f"Неразрешенная составная ссылка на {raw_container_type} '{container_num}', пункт '{clause_clean}' в правиле '{rule.rule_id}' (точное совпадение по типу и номеру не найдено)"
            )

    # 5. Standalone clause/point references (e.g. 'пункт 2', 'п. 2')
    referenced_clauses = CLAUSE_REF_RE.findall(remaining_text)
    for clause_str in referenced_clauses:
        clause_clean = clause_str.strip().rstrip(".")
        confirmed = (confirmed_clauses or {}).get(clause_clean)
        if confirmed is not None:
            if confirmed.rule_id != rule.rule_id and confirmed not in direct_deps:
                direct_deps.append(confirmed)
            continue
        candidates = [c for c in clause_index.get(clause_clean, []) if c.rule_id != rule.rule_id]
        if not candidates:
            unresolved.append(f"Неразрешенная ссылка на пункт '{clause_clean}' в правиле '{rule.rule_id}'")
            continue

        if len(candidates) == 1:
            single_match = candidates[0]
            if single_match not in direct_deps:
                direct_deps.append(single_match)
        else:
            # Multiple candidates across sections: do not assume current section, preserve uncertainty
            match_ids = [c.rule_id for c in candidates]
            unresolved.append(
                f"Неоднозначная ссылка на пункт '{clause_clean}' в правиле '{rule.rule_id}' (найдено несколько совпадений: {', '.join(match_ids)})"
            )
            for c in candidates:
                if c not in direct_deps:
                    direct_deps.append(c)

    return direct_deps, unresolved


def _confirmed_reference_rule_links(
    corpus: DirectSourceCorpus, rules: list[RuleEntity], decisions: tuple[SourceReferenceDecision, ...],
    *, source_only: bool = False, allow_contained_target: bool = False,
) -> dict[str, dict[str, RuleEntity]]:
    """Bind a confirmed source occurrence to one exact source-backed target rule.

    A source unit may contain many rules; unit overlap alone is not identity.
    Ambiguous quotes, multiple occurrences, or competing decisions remain unresolved.
    """
    reference_context_for_rules(corpus.tenant_id, corpus.documents, decisions, ())
    candidates: dict[tuple[str, str], list[RuleEntity]] = {}
    for decision in decisions:
        clauses = CLAUSE_REF_RE.findall(decision.reference_exact)
        if len(clauses) != 1:
            continue
        clause = clauses[0].strip().rstrip(".")
        referring: list[RuleEntity] = []
        targets: list[RuleEntity] = []
        for rule in rules:
            if rule.doc_id != decision.document_id or rule.source_revision != decision.source_revision:
                continue
            grounded, _, occurrences = _verify_rule_quote_grounding(rule, corpus)
            owned = [occ for occ in occurrences if occ.doc_id == decision.document_id
                     and occ.source_revision == decision.source_revision and occ.scope == "document"]
            if not grounded or len(owned) != 1:
                continue
            occ = owned[0]
            if occ.char_start <= decision.reference_start < decision.reference_end <= occ.char_end:
                fields = [rule.statement, *rule.conditions, *rule.exceptions, rule.timing, rule.consequences]
                per_field = [[value.strip().rstrip(".") for value in CLAUSE_REF_RE.findall(field)] for field in fields]
                quoted = [value.strip().rstrip(".") for value in CLAUSE_REF_RE.findall(rule.source_quote)]
                projections = {rule.source_quote.strip().rstrip(". ").casefold(),
                               decision.reference_exact.strip().rstrip(". ").casefold()}
                exact_projection = any(field.strip().rstrip(". ").casefold() in projections
                                       for field in fields if field.strip())
                if quoted.count(clause) == 1 and (source_only or (
                        sum(values.count(clause) for values in per_field) == 1 and exact_projection)):
                    referring.append(rule)
            # The authenticated target can be a complete literal subspan of
            # one uniquely grounded quote containing additional source context.
            # Uniqueness below still rejects competing target owners.
            if ((occ.char_start == decision.target_start and occ.char_end == decision.target_end)
                    or (allow_contained_target and occ.char_start <= decision.target_start < decision.target_end <= occ.char_end)):
                targets.append(rule)
        if len(referring) == 1 and len(targets) == 1 and referring[0].rule_id != targets[0].rule_id:
            candidates.setdefault((referring[0].rule_id, clause), []).append(targets[0])
    result: dict[str, dict[str, RuleEntity]] = {}
    for (rule_id, clause), linked in candidates.items():
        if len(linked) == 1:
            result.setdefault(rule_id, {})[clause] = linked[0]
    return result


def _confirmed_source_reference_clauses(
    corpus: DirectSourceCorpus, rules: list[RuleEntity], decisions: tuple[SourceReferenceDecision, ...],
) -> dict[str, set[str]]:
    """Identify references in verified source quotes even if target binding is ambiguous."""
    reference_context_for_rules(corpus.tenant_id, corpus.documents, decisions, ())
    result: dict[str, set[str]] = {}
    for decision in decisions:
        clauses = CLAUSE_REF_RE.findall(decision.reference_exact)
        if len(clauses) != 1:
            continue
        clause = clauses[0].strip().rstrip(".")
        for rule in rules:
            if rule.doc_id != decision.document_id or rule.source_revision != decision.source_revision:
                continue
            grounded, _, occurrences = _verify_rule_quote_grounding(rule, corpus)
            owned = [occ for occ in occurrences if occ.doc_id == decision.document_id
                     and occ.source_revision == decision.source_revision and occ.scope == "document"]
            quoted = [value.strip().rstrip(".") for value in CLAUSE_REF_RE.findall(rule.source_quote)]
            if (grounded and len(owned) == 1 and quoted.count(clause) == 1
                    and owned[0].char_start <= decision.reference_start < decision.reference_end <= owned[0].char_end):
                result.setdefault(rule.rule_id, set()).add(clause)
    return result


def _validate_critic_response(
    review_res: Any,
    lesson_id: str,
    lesson_title: str,
) -> tuple[bool, str]:
    """Strictly validates QA critic response against contract, schema types, and internal consistency.

    Contract aligns with QA_REVIEW_SYSTEM_PROMPT:
      - verdict: 'PASS' | 'NEEDS_REVISION' | 'FAIL'
      - factual_score: numeric 1-5 (or normalized 0-1)
      - alignment_score: numeric 1-5 (or normalized 0-1)
      - didactic_score: numeric 1-5 (or normalized 0-1)
      - summary: non-empty string (>= 10 chars, not dict/object)
      - defects: list of defect objects/strings
    """
    if not isinstance(review_res, dict):
        return False, f"Критик вернул невалидный тип ответа для урока {lesson_id} ({lesson_title}): {type(review_res).__name__}"

    raw_verdict = str(review_res.get("verdict", "")).strip().upper()
    verdict = raw_verdict
    if not raw_verdict or raw_verdict == "UNKNOWN":
        return False, f"Семантический критик вернул неопределенный вердикт (UNKNOWN) для урока {lesson_id} ({lesson_title})"

    if raw_verdict not in ("PASS", "FAIL", "NEEDS_REVISION"):
        return False, f"Критик вернул неподдерживаемый вердикт '{raw_verdict}' для урока {lesson_id} ({lesson_title})"

    if raw_verdict == "NEEDS_REVISION" and ("defects" not in review_res or not review_res["defects"]):
        return False, f"Семантический критик запросил доработку урока {lesson_id} ({lesson_title}) с вердиктом NEEDS_REVISION"

    if raw_verdict == "FAIL" and ("defects" not in review_res or not review_res["defects"]):
        return False, f"Семантический критик отклонил урок {lesson_id} ({lesson_title}) с вердиктом FAIL (без списка дефектов)"

    if "defects" not in review_res:
        return False, f"В ответе критика для урока {lesson_id} отсутствует обязательное поле 'defects'"

    defects = review_res["defects"]
    if not isinstance(defects, list):
        return False, f"Поле 'defects' в ответе критика должно быть списком для урока {lesson_id}, получено: {type(defects).__name__}"

    # Validate summary / rationale
    raw_summary = review_res.get("summary")
    if raw_summary is None:
        raw_summary = review_res.get("rationale") or review_res.get("comment")
    # On FAIL or NEEDS_REVISION, if summary is not explicitly provided, synthesize from defects
    if (raw_summary is None or (isinstance(raw_summary, str) and not raw_summary.strip())) and raw_verdict in ("FAIL", "NEEDS_REVISION") and defects:
        raw_summary = "; ".join(str(d.get("issue") if isinstance(d, dict) else d) for d in defects)

    if raw_summary is None or not isinstance(raw_summary, str):
        return False, f"Поле 'summary' в ответе критика должно быть строкой для урока {lesson_id}, получено: {type(raw_summary).__name__}"

    clean_summary = raw_summary.strip()
    if len(clean_summary) < 10:
        return False, f"Мотивировочная часть 'summary' слишком коротка или пуста для урока {lesson_id} (минимум 10 символов)"

    # Score validation helpers with unambiguous individual scales:
    def _validate_scale_1_to_5(name: str, val: Any) -> tuple[bool, float, str]:
        if isinstance(val, bool) or not isinstance(val, int | float):
            return False, 0.0, f"Поле '{name}' должно быть числом (int или float), получено: {type(val).__name__} ({val!r})"
        val_f = float(val)
        if not (1.0 <= val_f <= 5.0):
            return False, 0.0, f"Оценка '{name}' вне допустимой шкалы 1-5 (получено: {val})"
        norm = (val_f - 1.0) / 4.0
        return True, norm, ""

    def _validate_scale_confidence(name: str, val: Any) -> tuple[bool, float, str]:
        if isinstance(val, bool) or not isinstance(val, int | float):
            return False, 0.0, f"Поле '{name}' должно быть числом (int или float), получено: {type(val).__name__} ({val!r})"
        val_f = float(val)
        if not (0.0 <= val_f <= 1.0):
            return False, 0.0, f"Оценка '{name}' вне допустимой шкалы 0.0-1.0 (получено: {val})"
        return True, val_f, ""

    # Strict fail-closed schema: ALL 3 canonical criteria from prompts.py are mandatory!
    canonical_fields = ["factual_score", "alignment_score", "didactic_score"]
    scores_found: dict[str, float] = {}

    for f in canonical_fields:
        if f not in review_res or review_res[f] is None:
            return False, (
                f"Ответ критика для урока {lesson_id} не соответствует строгому контракту: "
                f"отсутствует обязательное поле '{f}' (шкала 1-5)"
            )
        ok, norm_val, err = _validate_scale_1_to_5(f, review_res[f])
        if not ok:
            return False, f"Ошибка в оценке критика для урока {lesson_id}: {err}"
        scores_found[f] = norm_val

    # Optional auxiliary field: confidence (if provided, must be in 0.0-1.0)
    if "confidence" in review_res and review_res["confidence"] is not None:
        ok, norm_val, err = _validate_scale_confidence("confidence", review_res["confidence"])
        if not ok:
            return False, f"Ошибка в оценке критика для урока {lesson_id}: {err}"
        scores_found["confidence"] = norm_val

    # Consistency checks based on verdict
    if verdict == "PASS":
        if len(defects) > 0:
            return False, f"Противоречивый ответ: вердикт PASS содержит дефекты: {defects}"

        # All present scores must be >= 0.70 (corresponds to >= 3.8/5 on 1-5 scale, or >= 0.70 confidence)
        for s_name, norm_val in scores_found.items():
            if norm_val < 0.70:
                raw_val = review_res[s_name]
                return False, (
                    f"Противоречивый ответ: вердикт PASS при низкой оценке {s_name}={raw_val} "
                    f"(нормализовано: {norm_val:.2f}, требуется не менее 0.70)"
                )

        # Check for explicit affirmative contradiction phrases without negation
        lower_summary = clean_summary.lower()
        affirmative_failure_phrases = (
            "урок не соответствует",
            "правила не соответствуют",
            "противоречит регламенту",
            "противоречит исходнику",
            "содержит грубые ошибки",
            "содержит грубую ошибку",
            "выявлены искажения",
            "обнаружены искажения",
        )
        for phrase in affirmative_failure_phrases:
            if phrase in lower_summary:
                return False, f"Противоречивый ответ: вердикт PASS, но в summary зафиксировано замечание ('{phrase}')"

    elif verdict in ("FAIL", "NEEDS_REVISION"):
        if len(defects) == 0:
            return False, f"Неполный ответ критика: вердикт {verdict} не содержит ни одного дефекта в поле 'defects'"
        for d_idx, d in enumerate(defects, 1):
            if isinstance(d, dict):
                issue = d.get("issue") or d.get("recommendation") or d.get("description")
                if not issue or not isinstance(issue, str) or not issue.strip():
                    return False, f"Дефект #{d_idx} в ответе критика для урока {lesson_id} не содержит описания (поле 'issue')"
            elif isinstance(d, str):
                if not d.strip():
                    return False, f"Дефект #{d_idx} в ответе критика для урока {lesson_id} является пустой строкой"
            else:
                return False, f"Дефект #{d_idx} в ответе критика для урока {lesson_id} имеет невалидный тип: {type(d).__name__}"

    return True, ""


def _rule_source_span(rule: RuleEntity) -> tuple[str, str, int, int] | None:
    start, end = rule.source_start, rule.source_end
    if (not rule.doc_id or not rule.source_revision or type(start) is not int or type(end) is not int
            or start < 0 or end <= start):
        return None
    return (rule.doc_id, rule.source_revision, start, end)


def _source_atomic_blocks(rules: list[RuleEntity]) -> list[list[RuleEntity]]:
    """Keep table families and rules from the same exact source unit together."""
    parent = list(range(len(rules)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    identities: dict[tuple[Any, ...], int] = {}
    for index, rule in enumerate(rules):
        keys: list[tuple[Any, ...]] = []
        if rule.source_family:
            keys.append(("family", rule.doc_id, rule.source_revision, rule.source_family))
        span = _rule_source_span(rule)
        if span is not None:
            keys.append(("span", *span))
        for key in keys:
            if key in identities:
                left, right = find(index), find(identities[key])
                if left != right:
                    parent[left] = right
            else:
                identities[key] = index
    blocks: dict[int, list[RuleEntity]] = {}
    for index, rule in enumerate(rules):
        blocks.setdefault(find(index), []).append(rule)
    return list(blocks.values())


# These are planning targets for one table family, not document limits.
# They trigger only when distinct source topics can be retained separately.
_SHARED_FAMILY_RULE_TARGET = 12
_SHARED_FAMILY_SPAN_TARGET = 12000


def _large_shared_topic_family(rules: list[RuleEntity]) -> bool:
    topics = {rule.source_topic for rule in rules if rule.source_topic}
    if len(topics) < 2 or not any(not rule.source_topic for rule in rules):
        return False
    spans = [_rule_source_span(rule) for rule in rules]
    if any(span is None for span in spans):
        return False
    typed = [span for span in spans if span is not None]
    if len({(span[0], span[1]) for span in typed}) != 1:
        return False
    return (len(rules) > _SHARED_FAMILY_RULE_TARGET or
            max(span[3] for span in typed) - min(span[2] for span in typed) > _SHARED_FAMILY_SPAN_TARGET)


def _build_curriculum_groups(
    rule_model: DocumentRuleModel, *, corpus: DirectSourceCorpus | None = None,
    reference_decisions: tuple[SourceReferenceDecision, ...] = (),
    source_view: Any = None,
) -> list[CurriculumGroup]:
    """Builds resilient curriculum groups with unique stable IDs and multi-level transitive dependency closures.

    Guarantees:
    1. Zero rule leak: all rules from rule_model are allocated without omission (both count and set equality).
    2. Identical section names or auto-split chunk names never overwrite each other (stores in a list with unique IDs).
    3. Multi-level transitive dependency closure: Rule 3 -> Rule 2 -> Rule 1 brings all prerequisites into context.
    4. Boundary-safe rule matching: 'r1' never matches inside 'r10'.
    5. Natural clause/point reference resolution with ambiguous reference detection.
    """
    allow_contained_target = False
    if source_view is not None:
        from app.modules.ai.v3.reference_source_view import POLICY as VIEW_POLICY
        from app.modules.ai.v3.reference_source_view import SourceReferenceView
        if (type(source_view) is not SourceReferenceView or source_view.policy != VIEW_POLICY
                or source_view.rule_model is not rule_model or source_view.unresolved_decision_ids):
            raise ValueError("v3_reference_planning_view_unverified")
        allow_contained_target = True
    sanitized_rules, raw_to_rules = _sanitize_rules(rule_model.rules)
    confirmed_links = (_confirmed_reference_rule_links(corpus, sanitized_rules, reference_decisions,
                                                    allow_contained_target=allow_contained_target)
                       if corpus is not None and reference_decisions else {})
    # A verified source occurrence may require its target as context even when
    # individual model paraphrases cannot be bound to that occurrence. Keep
    # those paraphrases unresolved: the edge is not a verdict about them.
    source_edges = (_confirmed_reference_rule_links(corpus, sanitized_rules, reference_decisions, source_only=True,
                                                 allow_contained_target=allow_contained_target)
                    if corpus is not None and reference_decisions else {})
    source_clauses = (_confirmed_source_reference_clauses(corpus, sanitized_rules, reference_decisions)
                      if corpus is not None and reference_decisions else {})
    unmatched_references: list[str] = []
    if corpus is not None and reference_decisions:
        from app.modules.ai.v3.reference_coverage import unmatched_confirmed_references

        unmatched_references = unmatched_confirmed_references(corpus, sanitized_rules, reference_decisions)
        if not sanitized_rules and unmatched_references:
            raise ValueError("v3_confirmed_reference_without_extracted_rule")

    # Invariant: unique IDs
    all_rule_ids = [r.rule_id for r in sanitized_rules]
    assert len(all_rule_ids) == len(set(all_rule_ids)), "Sanitization failed: duplicate rule IDs remain!"

    section_map: dict[str, list[RuleEntity]] = {}
    for r in sanitized_rules:
        sec = r.section.strip() if r.section.strip() else "Основные правила"
        section_map.setdefault(sec, []).append(r)

    groups: list[CurriculumGroup] = []
    group_counter = 1

    for sec, r_list in section_map.items():
        if len(r_list) <= 6:
            groups.append(
                CurriculumGroup(
                    group_id=f"cg-{group_counter:03d}",
                    display_title=sec,
                    section=sec,
                    primary_rules=tuple(r_list),
                )
            )
            group_counter += 1
        elif any(rule.source_family or _rule_source_span(rule) is not None for rule in r_list):
            # Keep source-table rows in the same group rather than splitting
            # related thresholds and conditions at an arbitrary rule count.
            blocks = _source_atomic_blocks(r_list)
            # Source-labelled table rows may be separate teaching topics. Only
            # subdivide an oversized family when every row has a known label;
            # the complete family is added back as context below.
            refined: list[list[RuleEntity]] = []
            for block in blocks:
                topics = {r.source_topic for r in block}
                span_topics: dict[tuple[str, str, int, int], set[str]] = {}
                for item in block:
                    span = _rule_source_span(item)
                    if span is not None:
                        span_topics.setdefault(span, set()).add(item.source_topic)
                spans_cross_topics = any(len(values) > 1 for values in span_topics.values())
                split_labeled = len(block) > 6 and "" not in topics and len(topics) > 1
                split_large_shared = _large_shared_topic_family(block)
                if (split_labeled or split_large_shared) and not spans_cross_topics:
                    shared = [r for r in block if not r.source_topic]
                    for topic in dict.fromkeys(r.source_topic for r in block if r.source_topic):
                        topic_rules = [r for r in block if r.source_topic == topic]
                        refined.append(shared + topic_rules if shared else topic_rules)
                        shared = []
                else:
                    refined.append(block)
            blocks = refined
            chunks: list[list[RuleEntity]] = []
            current: list[RuleEntity] = []
            packing_limit = 6 if any(rule.source_family for rule in r_list) else 5
            for block in blocks:
                if current and len(current) + len(block) > packing_limit:
                    chunks.append(current)
                    current = []
                current.extend(block)
            if current:
                chunks.append(current)
            for chunk_idx, chunk in enumerate(chunks):
                part_title = f"{sec} (Часть {chunk_idx + 1})" if len(chunks) > 1 else sec
                groups.append(CurriculumGroup(group_id=f"cg-{group_counter:03d}", display_title=part_title,
                                              section=sec, primary_rules=tuple(chunk)))
                group_counter += 1
        else:
            for chunk_idx in range(0, len(r_list), 5):
                chunk = r_list[chunk_idx : chunk_idx + 5]
                part_title = f"{sec} (Часть {chunk_idx // 5 + 1})" if chunk_idx > 0 else sec
                groups.append(
                    CurriculumGroup(
                        group_id=f"cg-{group_counter:03d}",
                        display_title=part_title,
                        section=sec,
                        primary_rules=tuple(chunk),
                    )
                )
                group_counter += 1

    if not groups and sanitized_rules:
        groups.append(
            CurriculumGroup(
                group_id="cg-001",
                display_title="Основные стандарты",
                section="Все правила",
                primary_rules=tuple(sanitized_rules),
            )
        )

    # Verify zero rule leak: count check and set check
    total_allocated_count = sum(len(g.primary_rules) for g in groups)
    if total_allocated_count != len(sanitized_rules):
        allocated_rule_ids = {r.rule_id for g in groups for r in g.primary_rules}
        missing = set(all_rule_ids) - allocated_rule_ids
        if missing:
            missing_entities = tuple(r for r in sanitized_rules if r.rule_id in missing)
            groups.append(
                CurriculumGroup(
                    group_id=f"cg-{group_counter:03d}",
                    display_title="Дополнительные нормативные требования",
                    section="Прочее",
                    primary_rules=missing_entities,
                )
            )

    # Hard invariant: zero lost rules
    final_count = sum(len(g.primary_rules) for g in groups)
    final_allocated = {r.rule_id for g in groups for r in g.primary_rules}
    assert final_count == len(sanitized_rules), f"Rule count leak! Expected {len(sanitized_rules)}, got {final_count}"
    assert final_allocated == set(all_rule_ids), f"Rule set leak! Missing: {set(all_rule_ids) - final_allocated}"

    # Build clause index for clause/point resolution
    clause_index: dict[str, list[RuleEntity]] = {}
    for r in sanitized_rules:
        clauses = _extract_clause_numbers(f"{r.title} {r.rule_id}")
        for c in clauses:
            clause_index.setdefault(c, []).append(r)

    # Build multi-level transitive dependency closure across groups
    groups_with_dependencies: list[CurriculumGroup] = []

    for group_index, g in enumerate(groups):
        primary_ids = {r.rule_id for r in g.primary_rules}
        visited_ids = set(primary_ids)
        queue = list(g.primary_rules)
        prereqs: list[RuleEntity] = []
        group_unresolved: list[str] = [
            f"Подтвержденная ссылка источника {identity[:12]} не связана с единственным извлеченным правилом"
            for identity in unmatched_references
        ]

        while queue:
            curr_rule = queue.pop(0)
            direct_deps, direct_unresolved = _find_direct_rule_dependencies(
                curr_rule,
                all_rules=sanitized_rules,
                clause_index=clause_index,
                raw_to_rules=raw_to_rules,
                current_section=g.section,
                confirmed_clauses=confirmed_links.get(curr_rule.rule_id),
            )
            direct_deps.extend(source_edges.get(curr_rule.rule_id, {}).values())
            missing_source_edges = source_clauses.get(curr_rule.rule_id, set()) - set(source_edges.get(curr_rule.rule_id, {}))
            for clause in sorted(missing_source_edges):
                direct_unresolved.append(
                    f"Неразрешенная ссылка на пункт '{clause}' в исходном фрагменте правила "
                    f"'{curr_rule.rule_id}': целевое правило отсутствует или неоднозначно"
                )
            # A unique numbered candidate does not establish which of several
            # generated mentions corresponds to the confirmed source span.
            unbound = source_clauses.get(curr_rule.rule_id, set()) - set(confirmed_links.get(curr_rule.rule_id, {}))
            fields = [("statement", curr_rule.statement),
                      *((f"conditions[{i}]", value) for i, value in enumerate(curr_rule.conditions)),
                      *((f"exceptions[{i}]", value) for i, value in enumerate(curr_rule.exceptions)),
                      ("timing", curr_rule.timing), ("consequences", curr_rule.consequences)]
            for field_name, value in fields:
                for match in CLAUSE_REF_RE.finditer(value):
                    clause = match.group(1).strip().rstrip(".")
                    if clause in unbound:
                        direct_unresolved.append(
                            f"Неразрешенная ссылка на пункт '{clause}' в правиле '{curr_rule.rule_id}', "
                            f"поле {field_name}, позиция {match.start()}: нет привязки к исходному фрагменту"
                        )
            for u in direct_unresolved:
                if u not in group_unresolved:
                    group_unresolved.append(u)

            for dep in direct_deps:
                if dep.rule_id not in visited_ids:
                    visited_ids.add(dep.rule_id)
                    prereqs.append(dep)
                    queue.append(dep)

        neighbors: list[RuleEntity] = []
        families = {(r.doc_id, r.source_revision, r.source_family) for r in g.primary_rules if r.source_family}
        family_rules = {identity: [r for r in sanitized_rules
                                   if (r.doc_id, r.source_revision, r.source_family) == identity]
                        for identity in families}
        large_families = {identity for identity, members in family_rules.items() if _large_shared_topic_family(members)}
        if large_families:
            group_unresolved.append("Большая таблица разделена по исходным темам; проверить межтематические зависимости")
        for related in sanitized_rules:
            identity = (related.doc_id, related.source_revision, related.source_family)
            if related.source_family and identity in families and related.rule_id not in visited_ids:
                # Shared unlabelled notes remain in every topic's context. Other
                # topics enter through explicit dependency closure or adjacency.
                if identity in large_families and related.source_topic:
                    continue
                neighbors.append(related)
                visited_ids.add(related.rule_id)
        for neighbor_index in (group_index - 1, group_index + 1):
            if 0 <= neighbor_index < len(groups) and groups[neighbor_index].section == g.section:
                for neighbor_rule in groups[neighbor_index].primary_rules:
                    if neighbor_rule.rule_id not in visited_ids:
                        neighbors.append(neighbor_rule)
                        visited_ids.add(neighbor_rule.rule_id)
        groups_with_dependencies.append(
            CurriculumGroup(
                group_id=g.group_id,
                display_title=g.display_title,
                section=g.section,
                primary_rules=g.primary_rules,
                context_prerequisite_rules=tuple(prereqs),
                unresolved_dependencies=tuple(group_unresolved),
                context_neighbor_rules=tuple(neighbors),
            )
        )

    return groups_with_dependencies


def _cases_outside_primary_rule_scope(lesson: V3Lesson, rules: list[RuleEntity]) -> list[tuple[str, str]]:
    """Identify case links that do not establish a primary-rule target."""
    primary = {rule.rule_id for rule in rules}
    if lesson.cases:
        return [(case.case_id if isinstance(case.case_id, str) else "",
                 case.rule_id if isinstance(case.rule_id, str) else "")
                for case in lesson.cases if not isinstance(case.rule_id, str) or case.rule_id not in primary]
    return [(question.question_id if isinstance(question.question_id, str) else "",
             question.rule_id if isinstance(question.rule_id, str) else "")
            for question in lesson.questions if not isinstance(question.rule_id, str) or question.rule_id not in primary]


def _unassessed_primary_rule_ids(lesson: V3Lesson, rules: list[RuleEntity]) -> list[str]:
    """Find rules without a direct nonempty assessment link, not semantic coverage."""
    linked = {case.rule_id for case in lesson.cases if case.rule_id and case.variants}
    linked.update(question.rule_id for question in lesson.questions if question.rule_id)
    return [rule.rule_id for rule in rules if rule.rule_id not in linked]


def _semantic_review_parts(lesson: V3Lesson) -> list[V3Lesson]:
    """Keep the complete lesson while reviewing each independently exported case."""
    if lesson.cases:
        return [replace(lesson, cases=(case,), questions=()) for case in lesson.cases]
    if lesson.questions:
        return [replace(lesson, questions=(question,)) for question in lesson.questions]
    return [lesson]


def _lesson_objective_section(text: str) -> bool:
    """Select only explicitly labelled learning-objective sections for the tailored prompt."""
    first = text.lstrip().split("\n", 1)[0].strip()
    return bool(re.match(r"^#{1,6}\s*(?:цел(?:ь|и)(?:\s+(?:урока|обучения))?|учебные\s+цели|результаты\s+обучения)\s*:?[#\s]*$",
                         first, re.IGNORECASE))


def _lesson_claim_sections(text: str) -> list[str]:
    """Partition on real Markdown headings without losing text or splitting fences."""
    boundaries: list[int] = []
    offset = 0
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
        elif fence is None and re.match(r"^ {0,3}#{1,2}[ \t]+\S", line):
            boundaries.append(offset)
        offset += len(line)
    if len(boundaries) < 2:
        return [text]
    chunks: list[str] = []
    start = 0
    for boundary in boundaries[1:]:
        segment = text[start:boundary]
        # A document title belongs with the following section, not a model call.
        if segment.strip() and all(re.match(r"^ {0,3}#{1,2}[ \t]+\S", line)
                                   for line in segment.splitlines() if line.strip()):
            continue
        chunks.append(segment)
        start = boundary
    chunks.append(text[start:])
    return chunks


def _lesson_claim_table_parts(section: str) -> list[tuple[str, str]]:
    """Split a long Markdown table by complete rows, retaining exact header context."""
    lines = section.splitlines(keepends=True)
    offsets: list[int] = []
    pos = 0
    fences: str | None = None
    delimiters: list[int] = []
    for index, line in enumerate(lines):
        offsets.append(pos)
        pos += len(line)
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)[0]
            fences = marker if fences is None else (None if fences == marker else fences)
            continue
        if fences is None and index and re.fullmatch(r"\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*", line):
            if lines[index - 1].lstrip().startswith("|"):
                delimiters.append(index)
    if len(delimiters) != 1:
        return [(section, "")]
    delimiter = delimiters[0]
    rows: list[int] = []
    index = delimiter + 1
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        rows.append(index)
        index += 1
    if len(rows) <= 3:
        return [(section, "")]
    header = lines[delimiter - 1] + lines[delimiter]
    heading = next((line.strip() for line in lines[:delimiter - 1]
                    if re.match(r"^ {0,3}#{1,3}[ \t]+\S", line)), "")
    context = (heading + "\n" if heading else "") + header
    start = 0
    parts: list[tuple[str, str]] = []
    for row_index in rows[3::3]:
        end = offsets[row_index]
        parts.append((section[start:end], "" if start == 0 else context))
        start = end
    parts.append((section[start:], context))
    return parts


def _lesson_claim_subparts(section: str) -> list[tuple[str, str]]:
    """Keep complete nested Markdown subsections together in small logical groups."""
    headings: list[int] = []
    parent_heading = ""
    fence: str | None = None
    offset = 0
    for line in section.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)[0]
            fence = marker if fence is None else (None if fence == marker else fence)
        elif fence is None:
            if not parent_heading and re.match(r"^ {0,3}#{1,2}[ \t]+\S", line):
                parent_heading = line.strip()
            if re.match(r"^ {0,3}#{3}[ \t]+\S", line):
                headings.append(offset)
        offset += len(line)
    if len(headings) <= 3:
        return [(section, "")]
    result: list[tuple[str, str]] = []
    start = 0
    for boundary in headings[3::3]:
        result.append((section[start:boundary], "" if start == 0 else parent_heading))
        start = boundary
    result.append((section[start:], parent_heading))
    return result


def _validate_answer_entailment(value: Any) -> tuple[bool, str]:
    allowed = {"SUPPORTED", "CONTRADICTED", "UNCERTAIN"}
    if (not isinstance(value, dict) or not isinstance(value.get("verdict"), str)
            or value["verdict"] not in allowed):
        return False, "невалидный вердикт проверки ответа"
    claims = value.get("claims")
    if not isinstance(claims, list) or not claims or not isinstance(value.get("summary"), str) or not value["summary"].strip():
        return False, "проверка ответа не содержит утверждений или обоснования"
    statuses: list[str] = []
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get("claim"), str) or not claim["claim"].strip()
                or not isinstance(claim.get("status"), str) or claim["status"] not in allowed
                or not isinstance(claim.get("reason"), str)
                or not claim["reason"].strip()):
            return False, "невалидное утверждение в проверке ответа"
        statuses.append(claim["status"])
    verdict = value["verdict"]
    if ((verdict == "SUPPORTED" and any(status != "SUPPORTED" for status in statuses))
            or (verdict == "CONTRADICTED" and "CONTRADICTED" not in statuses)
            or (verdict == "UNCERTAIN" and ("UNCERTAIN" not in statuses or "CONTRADICTED" in statuses))):
        return False, "вердикт проверки ответа противоречит статусам утверждений"
    return True, ""


def _validate_answer_completeness(value: Any, *, explanation_consistency: bool = True) -> tuple[bool, str]:
    if not isinstance(value, dict) or not isinstance(value.get("answers"), list) or len(value["answers"]) != 1:
        return False, "нет независимой проверки полноты ответа"
    answer = value["answers"][0]
    if not isinstance(answer, dict) or type(answer.get("index")) is not int or answer["index"] != 0:
        return False, "неверный индекс проверки полноты"
    omissions = answer.get("omissions")
    if not isinstance(omissions, list) or any(not isinstance(item, str) or not item.strip() for item in omissions):
        return False, "некорректный результат проверки полноты"
    if omissions:
        return False, "пропущены обязательные элементы: " + "; ".join(omissions)
    if not explanation_consistency:
        return True, ""
    explanation = value.get("explanation_review")
    if not isinstance(explanation, dict):
        return False, "проверка объяснения отсутствует"
    valid, error = _validate_answer_entailment(explanation)
    if not valid:
        return False, "проверка объяснения: " + error
    if explanation.get("verdict") != "SUPPORTED":
        return False, "объяснение не подтверждено: " + str(explanation.get("verdict"))
    return True, ""


def _validate_question_entailment(value: Any, expected: list[bool]) -> tuple[bool, str]:
    if not isinstance(value, dict) or not isinstance(value.get("options"), list):
        return False, "нет проверки всех вариантов ответа"
    by_index: dict[int, dict[str, Any]] = {}
    for item in value["options"]:
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            return False, "невалидный индекс варианта ответа"
        index = item["index"]
        if index in by_index or not 0 <= index < len(expected):
            return False, "повторный или посторонний вариант ответа"
        by_index[index] = item
    if set(by_index) != set(range(len(expected))):
        return False, "проверены не все варианты ответа"
    for index, is_correct in enumerate(expected):
        valid, error = _validate_answer_entailment(by_index[index])
        if not valid:
            return False, f"вариант {index}: {error}"
        omissions = by_index[index].get("omitted_required_elements")
        if not isinstance(omissions, list) or any(not isinstance(item, str) or not item.strip() for item in omissions):
            return False, f"вариант {index}: нет корректной проверки полноты ответа"
        if is_correct and omissions:
            return False, f"вариант {index}: пропущены обязательные элементы ответа"
        required = "SUPPORTED" if is_correct else "CONTRADICTED"
        if by_index[index]["verdict"] != required:
            return False, f"вариант {index}: ожидался {required}, получен {by_index[index]['verdict']}"
    return True, ""


def _flagged_incorrect_options(value: Any, expected: list[bool]) -> list[dict[str, Any]]:
    """Only repair identifiable wrong options when the correct one is supported."""
    if (len(expected) != 4 or sum(expected) != 1 or not isinstance(value, dict)
            or not isinstance(value.get("options"), list) or len(value["options"]) != len(expected)):
        return []
    by_index: dict[int, dict[str, Any]] = {}
    for item in value["options"]:
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            return []
        index = item["index"]
        if not 0 <= index < len(expected) or index in by_index or not _validate_answer_entailment(item)[0]:
            return []
        omissions = item.get("omitted_required_elements")
        if not isinstance(omissions, list) or any(not isinstance(x, str) or not x.strip() for x in omissions):
            return []
        by_index[index] = item
    if set(by_index) != set(range(len(expected))):
        return []
    correct = by_index[expected.index(True)]
    if correct["verdict"] != "SUPPORTED" or correct["omitted_required_elements"]:
        return []
    return [by_index[i] for i, is_correct in enumerate(expected)
            if not is_correct and by_index[i]["verdict"] in {"SUPPORTED", "UNCERTAIN"}]


def _direct_explanation_requires_hold(explanation: str) -> bool:
    """Reject unstable option-position references; semantic review remains mandatory."""
    from app.modules.ai.v3.validator import has_order_dependent_feedback

    return (not explanation.strip() or has_order_dependent_feedback(explanation)
            or bool(re.search(r"\b(?:последн\w*|предпоследн\w*)\s+(?:ответ\w*|вариант\w*)\b"
                              r"|\b(?:last|penultimate)\s+(?:answer|option)\b", explanation, re.IGNORECASE)))


def _question_explanation(lesson: V3Lesson, question_id: str) -> str:
    """Return the uniquely bound displayed explanation, or fail closed."""
    matches = ([v.explanation for c in lesson.cases for v in c.variants if v.variant_id == question_id]
               if lesson.cases else [q.explanation for q in lesson.questions if q.question_id == question_id])
    return matches[0] if len(matches) == 1 and isinstance(matches[0], str) else ""


def _question_option_inputs(lesson: V3Lesson) -> list[tuple[str, str, str, list[tuple[str, bool]], str]]:
    if lesson.cases:
        result = []
        for case_index, case in enumerate(lesson.cases, 1):
            for variant_index, variant in enumerate(case.variants, 1):
                assembled = variant.assemble_question(seed=100 + case_index * 10 + variant_index)
                result.append((variant.variant_id, assembled.scenario_premise, variant.prompt,
                               [(option.text, option.is_correct) for option in assembled.options], case.rule_id))
        return result
    return [(question.question_id, question.scenario_premise, question.prompt,
             [(option.text, option.is_correct) for option in question.options], question.rule_id)
            for question in lesson.questions]


def _review_source_unit_fragments(rules: list[RuleEntity], corpus: DirectSourceCorpus) -> list[str]:
    """Retrieve exact same-revision source units; never certify model quotes."""
    fragments: list[str] = []
    seen: set[tuple[str, str, int, int]] = set()
    for rule in rules:
        if not rule.doc_id or not rule.source_revision:
            continue
        matching = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id
                    and doc.source_revision == rule.source_revision and doc.source_text is not None]
        if len(matching) != 1 or type(rule.source_start) is not int or type(rule.source_end) is not int:
            continue
        doc = matching[0]
        assert doc.source_text is not None
        if not (0 <= rule.source_start < rule.source_end <= len(doc.source_text)):
            continue
        identity = (doc.doc_id, doc.source_revision, rule.source_start, rule.source_end)
        if identity not in seen:
            seen.add(identity)
            working_sha = hashlib.sha256(doc.source_text.encode("utf-8")).hexdigest()
            fragments.append(f"[Исходный блок документа {doc.doc_id}, ревизия {doc.source_revision}, "
                             f"SHA256 рабочего текста {working_sha}, {rule.source_start}:{rule.source_end}]: "
                             + doc.source_text[rule.source_start:rule.source_end])
    return fragments


def _unbound_case_citation_ids(
    lesson: V3Lesson, rules: list[RuleEntity], corpus: DirectSourceCorpus,
) -> list[str]:
    """Hold quotes lacking a literal occurrence inside their unique owned rule span."""
    held: list[str] = []
    for case in lesson.cases:
        matches = [rule for rule in rules if rule.rule_id == case.rule_id]
        for variant in case.variants:
            grounded = False
            if len(matches) == 1:
                rule = matches[0]
                documents = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id
                             and doc.source_revision == rule.source_revision and doc.source_text is not None]
                if len(documents) == 1 and type(rule.source_start) is int and type(rule.source_end) is int:
                    source = documents[0].source_text or ""
                    if 0 <= rule.source_start < rule.source_end <= len(source):
                        quote = normalize_literal_quote(variant.source_quote.replace("<br>", " ").strip())
                        source_span = normalize_literal_quote(source[rule.source_start:rule.source_end])
                        first = source_span.find(quote) if quote else -1
                        grounded = first >= 0 and source_span.find(quote, first + 1) < 0
            if not grounded:
                held.append(variant.variant_id)
    return held


def _nonliteral_case_citation_ids(
    lesson: V3Lesson, rules: list[RuleEntity], corpus: DirectSourceCorpus,
) -> list[str]:
    """Early stop when unique owned text proves absence or a wrong source span."""
    held: list[str] = []
    for case in lesson.cases:
        matching = [rule for rule in rules if rule.rule_id == case.rule_id]
        if len(matching) != 1:
            continue
        rule = matching[0]
        docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id
                and doc.source_revision == rule.source_revision and doc.source_text is not None]
        if len(docs) != 1:
            continue
        source = normalize_literal_quote(docs[0].source_text or "")
        for variant in case.variants:
            quote = normalize_literal_quote(variant.source_quote.replace("<br>", " ").strip())
            if not quote:
                continue
            raw_source = docs[0].source_text or ""
            valid_span = (type(rule.source_start) is int and type(rule.source_end) is int
                          and 0 <= rule.source_start < rule.source_end <= len(raw_source))
            outside_owned_span = (valid_span and quote not in
                                  normalize_literal_quote(raw_source[rule.source_start:rule.source_end]))
            if quote not in source or outside_owned_span:
                held.append(variant.variant_id)
    return held


def _bind_rendered_quote_candidates(
    lesson: V3Lesson, rules: list[RuleEntity], corpus: DirectSourceCorpus,
) -> tuple[V3Lesson, list[str]]:
    """Bind only unique rendered candidates to exact revision-owned source spans.

    This preserves literal provenance; it does not certify that the source span
    supports the answer. A review signal is always emitted for changed quotes.
    """
    warnings: list[str] = []
    updated_cases = []
    for case in lesson.cases:
        matching_rules = [r for r in rules if r.rule_id == case.rule_id]
        updated_variants = []
        for variant in case.variants:
            replacement = variant
            if len(matching_rules) == 1 and variant.source_quote.strip():
                rule = matching_rules[0]
                docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id
                        and doc.source_revision == rule.source_revision and doc.source_text is not None]
                if len(docs) == 1 and rule.source_start is not None and rule.source_end is not None:
                    source = docs[0].source_text or ""
                    if 0 <= rule.source_start < rule.source_end <= len(source):
                        quote = variant.source_quote.strip()
                        if normalize_literal_quote(quote) not in normalize_literal_quote(source):
                            spans = find_rendered_quote_spans(source, quote)
                            if len(spans) == 1:
                                start, end = spans[0]
                                if (rule.source_start <= start < end <= rule.source_end
                                        and rendered_candidate_preserves_table_boundaries(source[start:end], quote)):
                                    replacement = replace(variant, source_quote=source[start:end])
                                    quote_sha = hashlib.sha256(quote.encode("utf-8")).hexdigest()
                                    warnings.append(
                                        f"Урок {lesson.lesson_id}, вопрос {variant.variant_id}: цитата привязана "
                                        f"к исходному фрагменту {rule.doc_id} {rule.source_revision} "
                                        f"({start}:{end}), исходная формулировка SHA256={quote_sha}; "
                                        "требуется смысловая проверка"
                                    )
            updated_variants.append(replacement)
        updated_cases.append(replace(case, variants=tuple(updated_variants)))
    if not warnings:
        return lesson, []
    cases = tuple(updated_cases)
    questions = tuple(case.variants[0].assemble_question(seed=42) for case in cases if case.variants)
    return replace(lesson, cases=cases, questions=questions), warnings


class OptionShortcutRepairUnresolvedError(ValueError):
    """A known complete repair failed; retain this lesson's original defects."""

    def __init__(self, violations: tuple[str, ...]):
        self.violations = violations
        super().__init__("v3_option_repair_requires_review")


async def _repair_option_shortcuts(
    lesson: V3Lesson, source: str, source_sha: str, source_fragments: list[str],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    reference_context: tuple[str, ...] = (),
    source_documents: tuple[str, ...] | None = None,
    *, typed_output: bool = False, convergent_repair: bool = False,
) -> tuple[V3Lesson, bool]:
    """Repair structural option defects without aborting the rest of the course.

    A passed structural recheck is not semantic approval. Other defects are
    retained for the normal fail-closed validation path, without a repair call.
    """
    from app.modules.ai.v3.option_repair import repair_length_shortcuts, repair_options

    current = V3Course(course_id="repair-check", title=lesson.title, document_sha256=source_sha, lessons=(lesson,))
    report = validate_v3_course(current, source_document_text=source, source_documents=source_documents)
    eligible = ("Anti-cheating violation:", "Invariant 4", "Invariant 5")
    if (not report.violations or not lesson.cases or not source_fragments
            or any(not issue.startswith(eligible) for issue in report.violations)):
        return lesson, False
    def complete_lesson_passes(partial: V3Lesson) -> bool:
        partial_course = replace(current, lessons=(partial,))
        return validate_v3_course(partial_course, source_document_text=source,
                                  source_documents=source_documents).structural_verdict == "PASS"

    if (all(issue.startswith("Invariant 4") for issue in report.violations)
            and any("correct answer is longest" in issue or "correct answer is shortest" in issue
                    for issue in report.violations)):
        candidate = await repair_length_shortcuts(lesson, list(report.violations), source_fragments, invoke,
                                                  reference_context, **({"typed_output": True} if typed_output else {}),
                                                  **({"measured_feedback": True} if convergent_repair else {}))
    else:
        candidate = await repair_options(lesson, list(report.violations), source_fragments, invoke, reference_context,
                                         accept_partial=complete_lesson_passes,
                                         **({"typed_output": True} if typed_output else {}))
    updated = replace(current, lessons=(candidate,))
    candidate_report = validate_v3_course(updated, source_document_text=source, source_documents=source_documents)
    if candidate_report.structural_verdict != "PASS":
        if not convergent_repair:
            raise ValueError("v3_option_repair_failed_validation")
        # A complete model response can improve mean length while leaving a
        # longest/shortest-answer clue. One new request is justified only by
        # measurable progress and a narrower, still-failing length obligation.
        # Neither replay nor a transport-unknown result authorizes another call.
        def length_distance(value: Any) -> float:
            ratio = value.metrics.length_bias_ratio_mean
            return float(max(0.80 - ratio, 0.0, ratio - 1.25))

        progressed = (
            len(candidate_report.violations) < len(report.violations)
            or candidate_report.metrics.longest_correct_count < report.metrics.longest_correct_count
            or candidate_report.metrics.shortest_correct_count < report.metrics.shortest_correct_count
            or length_distance(candidate_report) < length_distance(report)
        )
        length_only = candidate_report.violations and all(
            issue.startswith("Invariant 4") for issue in candidate_report.violations
        )
        if progressed and length_only:
            candidate = await repair_length_shortcuts(
                candidate, list(candidate_report.violations), source_fragments, invoke, reference_context,
                **({"typed_output": True} if typed_output else {}),
                measured_feedback=True,
            )
            candidate_report = validate_v3_course(
                replace(current, lessons=(candidate,)), source_document_text=source, source_documents=source_documents,
            )
        if candidate_report.structural_verdict != "PASS":
            # Preserve the original for the normal full-course validator and
            # independent semantic review. Failed candidates stay in the owned
            # journal; they are never promoted, padded or declared approved.
            logger.warning("v3.option_repair.held structural_candidate_not_accepted")
            raise OptionShortcutRepairUnresolvedError(tuple(report.violations))
    return candidate, True


class SemanticRepairRejectedError(ValueError):
    """A completed repair candidate violated a local preservation invariant."""


async def _repair_reviewed_case(
    lesson: V3Lesson, part: V3Lesson, review: Any, source: str, source_sha: str,
    source_fragments: list[str],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    reference_context: tuple[str, ...] = (),
    source_documents: tuple[str, ...] | None = None,
    *, repair_prompt: bool = False, typed_output: bool = False,
) -> tuple[V3Lesson, bool]:
    """Repair a uniquely identified question case without touching other cases.

    This applies a candidate only; callers must repeat semantic and answer
    checks. Unscoped or mixed defects are preserved for human review.
    """
    from app.modules.ai.v3.case_repair_gate import case_compatibility_identity_matches
    from app.modules.ai.v3.option_repair import repair_options

    if (not isinstance(review, dict) or len(part.cases) != 1 or not source_fragments
            or part.lesson_id != lesson.lesson_id):
        return lesson, False
    case = part.cases[0]
    if (not isinstance(case.case_id, str) or not case.case_id or not case.variants
            or any(not isinstance(v.variant_id, str) or not v.variant_id for v in case.variants)
            or len({v.variant_id for v in case.variants}) != len(case.variants)):
        return lesson, False
    matches = [item for item in lesson.cases if item.case_id == case.case_id]
    if (len(matches) != 1 or matches[0] != case
            or not case_compatibility_identity_matches(lesson, case.case_id)):
        return lesson, False
    defects = review.get("defects")
    if not isinstance(defects, list) or not defects:
        return lesson, False
    ids = {case.case_id, *(variant.variant_id for variant in case.variants)}
    if any(not isinstance(item, dict) or item.get("scope") != "question"
           or not isinstance(item.get("question_id"), str) or item["question_id"] not in ids
           or not isinstance(item.get("issue"), str)
           or not item["issue"].strip() for item in defects):
        return lesson, False
    issues = [item["issue"] for item in defects]
    defect_ids = {item["question_id"] for item in defects}
    target_ids = ({v.variant_id for v in case.variants} if case.case_id in defect_ids else defect_ids)
    selected = tuple(v for v in case.variants if v.variant_id in target_ids)
    isolated = replace(lesson, cases=(replace(case, variants=selected),), questions=())

    async def exact_answer_invoke(
        messages: list[dict[str, str]], response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        messages = [dict(message) for message in messages]
        messages[0]["content"] += "\nСохрани правильный ответ дословно, без изменений текста."
        return await invoke(messages, response_format)

    if typed_output:
        candidate = await repair_options(
            isolated, issues, source_fragments, exact_answer_invoke, reference_context,
            repair_prompt=repair_prompt, typed_output=True)
    else:
        candidate = await repair_options(
            isolated, issues, source_fragments, exact_answer_invoke, reference_context, repair_prompt=repair_prompt)
    repaired_variants = candidate.cases[0].variants
    if any(before.correct_option.text != after.correct_option.text for before, after in zip(
        selected, repaired_variants, strict=True
    )):
        raise SemanticRepairRejectedError("v3_semantic_repair_changed_correct_answer")
    repaired = {before.variant_id: replace(after, correct_option=before.correct_option)
                for before, after in zip(selected, repaired_variants, strict=True)}
    updated_case = replace(case, variants=tuple(repaired.get(v.variant_id, v) for v in case.variants))
    cases = tuple(updated_case if item.case_id == case.case_id else item for item in lesson.cases)
    questions = tuple(
        updated_case.variants[0].assemble_question(seed=42)
        if item.case_id == case.case_id and case.variants[0].variant_id in target_ids else old
        for item, old in zip(lesson.cases, lesson.questions, strict=True)
    ) if lesson.questions else ()
    updated = replace(lesson, cases=cases, questions=questions)
    before_course = V3Course(course_id="repair-check", title=lesson.title, document_sha256=source_sha, lessons=(lesson,))
    after_course = replace(before_course, lessons=(updated,))
    before = validate_v3_course(before_course, source_document_text=source, source_documents=source_documents)
    after = validate_v3_course(after_course, source_document_text=source, source_documents=source_documents)
    if set(after.violations) - set(before.violations):
        raise SemanticRepairRejectedError("v3_semantic_repair_added_structural_violations")
    return updated, True


async def _review_final_diversity(*, policy: str | None, lessons: list[V3Lesson],
                                  groups: list[tuple[str, tuple[RuleEntity, ...]]], corpus: DirectSourceCorpus,
                                  journal: Any, source_context: Any, direct_client: Any, source_sha256: str,
                                  route_fingerprint: str, invoke: Any, max_tokens: int,
                                  cancellation_callback: Any, signals: list[str], violations: list[str],
                                  repair_contexts: list[Any] | None = None,
                                  review_records: dict[str, Any] | None = None,
                                  allow_repair: bool = False, revision_policy: str | None = None,
                                  typed_invoke: Any = None) -> None:
    from app.modules.ai.v3.qa_luna_pending_policy import OWNED_POLICIES
    from app.modules.ai.v3.revision_policy import is_scoped_policy

    owned = policy in OWNED_POLICIES
    if not owned and (not is_scoped_policy(revision_policy) or policy is not None):
        return
    from app.modules.ai.v3.diversity_review import review_final_lesson
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    if owned:
        valid = (type(journal) is PendingStageJournal and direct_client is not None
                 and callable(journal.verify_source) and journal.tenant_id == corpus.tenant_id)
    else:
        from app.modules.ai.v3.revision_policy import POLICY
        source_context = getattr(journal, "expected_revision_source", None)
        journal_valid = (type(journal) is WorkerCycleJournal or (revision_policy == POLICY
            and type(journal) is PendingStageJournal and callable(journal.verify_source)))
        valid = (journal_valid and direct_client is None
                 and journal.tenant_id == corpus.tenant_id
                 and journal.expected_revision_policy == revision_policy
                 and type(source_context) is OwnedSourceContext
                 and source_context.journal is journal and source_context.corpus is corpus)
    if not valid:
        raise ExtractionOutcomeUnknownError("v3_diversity_owned_context_unverified")
    for lesson_index, (final_lesson, (group_id, primary_rules)) in enumerate(zip(lessons, groups, strict=True)):
        if cancellation_callback:
            await cancellation_callback()
        context_rules: tuple[RuleEntity, ...] = ()
        if repair_contexts is not None:
            context_rules, unresolved = repair_contexts[lesson_index]
            if unresolved:
                signals.append(f"Урок {final_lesson.lesson_id}: зависимые условия требуют проверки методиста")
                violations.append(f"Урок {final_lesson.lesson_id}: проверка разнообразия отложена до проверки связанных источников")
                continue
        observed = await review_final_lesson(
            lesson=final_lesson, corpus=corpus, rules=primary_rules,
            expected_tenant_id=journal.tenant_id, expected_document_ids=source_context.selection,
            journal=journal, group_id=f"diversity:{group_id}", source_sha256=source_sha256,
            route_fingerprint=route_fingerprint, invoke=invoke, direct_client=direct_client,
            direct_max_output_tokens=max_tokens, context_rules=context_rules,
            **({"typed_invoke": typed_invoke} if typed_invoke is not None else {}),
        )
        if review_records is not None and isinstance(review_records.get(final_lesson.lesson_id), dict):
            prior_review = review_records[final_lesson.lesson_id]
            omissions = observed.get("omissions", [])
            safe_omissions = [{"rule_id": item["rule_id"],
                "quote_sha256": hashlib.sha256(item["exact_quote"].encode("utf-8")).hexdigest()}
                for item in omissions if isinstance(item, dict) and isinstance(item.get("rule_id"), str)
                and isinstance(item.get("exact_quote"), str)] if isinstance(omissions, list) else []
            review_records[final_lesson.lesson_id] = {**prior_review, "diversity_observation": {
                "status": observed.get("status"), "fingerprint": observed.get("fingerprint"),
                "overlaps": observed.get("overlaps", []), "omissions": safe_omissions,
                "inventory_completeness": observed.get("inventory_completeness", "unknown")}}
        if (owned and allow_repair and repair_contexts is not None and review_records is not None
                and observed.get("status") == "review_required"
                and isinstance(observed.get("overlaps"), list) and len(observed["overlaps"]) == 1
                and isinstance(observed.get("omissions"), list) and len(observed["omissions"]) == 1):
            from app.modules.ai.v3.diversity_repair_promotion import staged_diversity_repair
            from app.modules.ai.v3.diversity_repair_selection import select_owned_candidate

            overlap = observed["overlaps"][0]
            if (isinstance(overlap, list) and len(overlap) == 2 and type(overlap[1]) is int):
                selected = await select_owned_candidate(
                    lesson=final_lesson, corpus=corpus, rules=primary_rules,
                    expected_tenant_id=journal.tenant_id, expected_document_ids=source_context.selection,
                    journal=journal, group_id=f"diversity:{group_id}", source_sha256=source_sha256,
                    route_fingerprint=route_fingerprint, selected_index=overlap[1], context_rules=context_rules,
                    **({"typed_output": True} if typed_invoke is not None else {}))
                if selected is not None:
                    context_rules, unresolved = repair_contexts[lesson_index]
                    repair_feedback: dict[str, Any] = {}
                    repaired, accepted = await staged_diversity_repair(
                        lesson=final_lesson, corpus=corpus, rules=primary_rules, selected=selected,
                        journal=journal, expected_document_ids=source_context.selection,
                        review_group_id=f"diversity:{group_id}", source_sha256=source_sha256,
                        route_fingerprint=route_fingerprint, direct_client=direct_client,
                        max_output_tokens=max_tokens, context_rules=context_rules,
                        unresolved_dependencies=unresolved, feedback=repair_feedback,
                        **({"typed_output": True} if typed_invoke is not None else {}))
                    prior = review_records.get(final_lesson.lesson_id)
                    if isinstance(prior, dict):
                        review_records[final_lesson.lesson_id] = {**prior, "diversity_repair": repair_feedback}
                    if accepted:
                        lessons[lesson_index] = repaired
                        prior = review_records.get(final_lesson.lesson_id)
                        if isinstance(prior, dict):
                            review_records[final_lesson.lesson_id] = {
                                **prior, "verdict": "NEEDS_REVISION", "prior_review_stale": True,
                                "reason": "final_question_changed_requires_manual_review"}
                        signals.append(f"Урок {final_lesson.lesson_id}: вопрос изменён; прежняя проверка сохранена как история, требуется проверка методиста")
        signals.append(f"Урок {final_lesson.lesson_id}: полнота исходных целей и покрытие тестом требуют проверки методиста")
        if observed.get("status") != "review_required" or observed.get("overlaps") or observed.get("omissions"):
            violations.append(f"Урок {final_lesson.lesson_id}: разнообразие вопросов или полнота покрытия требуют проверки")


async def _practical_output_budget(review_policy: str | None, direct_client: Any) -> int:
    from app.modules.ai.managed_luna_client import LUNA6_MODEL, ManagedLunaClient
    from app.modules.ai.v3.revision_policy import PRACTICAL_MAX_OUTPUT_TOKENS, is_autonomous_editorial_policy
    if is_autonomous_editorial_policy(review_policy) and type(direct_client) is ManagedLunaClient and direct_client.model == LUNA6_MODEL:
        from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings
        return (await resolve_runtime_settings()).integer("generation.editorial_luna_max_tokens")
    return PRACTICAL_MAX_OUTPUT_TOKENS


async def generate_v3_course_from_corpus(
    corpus: DirectSourceCorpus,
    *,
    intent: CourseIntent,
    generation_client: Any,
    progress_callback: Callable[[str, int, int, str | None, int | None], Awaitable[None]] | None = None,
    cancellation_callback: Callable[[], Awaitable[None]] | None = None,
    extraction_journal: ExtractionJournal | None = None,
    route_fingerprint: str = "",
    reference_decisions: tuple[SourceReferenceDecision, ...] = (),
    allow_unreviewed_on_unknown: bool = False,
    direct_client: Any = None,
    direct_max_output_tokens: int = 8192,
    authenticated_qa_policy: str | None = None,
    owned_source_context: Any = None,
    revision_policy: str | None = None,
    review_policy: str | None = None,
) -> GenerationArtifacts:
    """Generate V3 artifacts; the optional authenticated policy is reserved for future use."""
    from app.modules.ai.v3.revision_policy import (
        AUXILIARY_REVIEW_POLICY,
        BUCKET_REVIEW_POLICY,
        LEGACY_REVIEW_POLICY,
        PRACTICAL_MAX_OUTPUT_TOKENS,
        PREVIOUS_REVIEW_POLICY,
        REVIEW_POLICY,
        is_practical_policy,
        is_scoped_policy,
    )
    from app.modules.ai.v3.revision_policy import POLICY as REVISION_POLICY

    if revision_policy is not None and not is_scoped_policy(revision_policy):
        raise ValueError("v3_revision_policy_invalid")
    scoped_revision = is_scoped_policy(revision_policy)
    batched_decisions = review_policy in {LEGACY_REVIEW_POLICY, PREVIOUS_REVIEW_POLICY, BUCKET_REVIEW_POLICY, AUXILIARY_REVIEW_POLICY, REVIEW_POLICY}
    typed_auxiliary = review_policy in {AUXILIARY_REVIEW_POLICY, REVIEW_POLICY}
    strict_batch_contract = review_policy in {PREVIOUS_REVIEW_POLICY, BUCKET_REVIEW_POLICY, AUXILIARY_REVIEW_POLICY, REVIEW_POLICY}
    practical = is_practical_policy(review_policy)
    if review_policy is not None and (not (batched_decisions or practical) or revision_policy != REVISION_POLICY):
        raise ValueError("v3_review_policy_invalid")
    if allow_unreviewed_on_unknown and extraction_journal is None:
        raise ValueError("v3_unknown_review_requires_journal")
    if direct_client is not None and extraction_journal is None:
        raise ValueError("direct_owned_journal_required")
    if direct_client is not None and direct_max_output_tokens not in ({8192, PRACTICAL_MAX_OUTPUT_TOKENS} if practical else {8192}):
        raise ValueError("direct_owned_output_policy_invalid")
    from app.modules.ai.v3.qa_luna_pending_policy import OWNED_POLICIES

    if authenticated_qa_policy in OWNED_POLICIES:
        from app.modules.ai.v3.owned_source_context import OwnedSourceContext
        from app.modules.ai.v3.pending_stage_journal import PendingStageJournal

        if (type(extraction_journal) is not PendingStageJournal or direct_client is None
                or not callable(extraction_journal.verify_source)
                or extraction_journal.tenant_id != corpus.tenant_id
                or type(owned_source_context) is not OwnedSourceContext
                or owned_source_context.journal is not extraction_journal
                or owned_source_context.corpus is not corpus
                or str(owned_source_context.tenant_id) != extraction_journal.tenant_id
                or owned_source_context.user_id != extraction_journal.user_id
                or owned_source_context.job_id != extraction_journal.job_id
                or tuple(corpus.document_ids) != owned_source_context.selection):
            raise ExtractionOutcomeUnknownError("v3_diversity_owned_context_unverified")
    full_text, doc_sha = _extract_corpus_text(corpus)
    source_documents = tuple(doc.source_text if doc.source_text is not None else
                             "\n\n".join(chunk.text.strip() for chunk in doc.chunks if chunk.text.strip())
                             for doc in corpus.documents)
    # These objects are accepted only from a trusted server-side caller. They
    # are never inferred from model output or document conversion metadata.
    reference_context_for_rules(corpus.tenant_id, corpus.documents, reference_decisions, ())
    first_title = corpus.documents[0].title if corpus.documents else "Курс по регламенту"

    async def invoke_payload(messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> Any:
        if cancellation_callback:
            await cancellation_callback()

        # ResilientLLMClient support
        if hasattr(generation_client, "ainvoke"):
            res = await generation_client.ainvoke(messages, response_format=response_format)
            if getattr(res, "finish_reason", None) in {"length", "content_filter"} or getattr(res, "content_is_reasoning", False):
                raise ValueError("v3_provider_incomplete_response")
            raw_text = res.content if hasattr(res, "content") else str(res)
        elif callable(generation_client):
            raw_text = await generation_client(messages, response_format)
        else:
            raise TypeError(f"Unsupported generation_client type: {type(generation_client)}")

        if practical:
            from app.modules.ai.v3.practical_author_transport import PracticalAuthorArtifact, normalize_practical_author
            from app.modules.ai.v3.practical_contract import is_practical_course_format
            if is_practical_course_format(response_format):
                if type(raw_text) is PracticalAuthorArtifact:
                    return raw_text
                if type(raw_text) is str:
                    return normalize_practical_author(raw_text, response_format)
        if isinstance(raw_text, dict):
            return raw_text
        if strict_batch_contract or practical:
            from app.modules.ai.source_first_response import parse_source_first_response
            return parse_source_first_response(raw_text)
        parsed: dict[str, Any] = json.loads(raw_text)
        return parsed

    async def llm_invoker(messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> dict[str, Any]:
        value = await invoke_payload(messages, response_format)
        if not isinstance(value, dict):
            raise ValueError('v3_nonpractical_response_invalid')
        return value

    if practical:
        from app.modules.ai.v3.practical_service import generate_practical_course
        assert review_policy is not None
        return await generate_practical_course(corpus, intent=intent, invoke=invoke_payload,
            source_sha256=doc_sha, journal=extraction_journal, route_fingerprint=route_fingerprint,
            reference_decisions=reference_decisions, direct_client=direct_client,
            direct_max_output_tokens=await _practical_output_budget(review_policy, direct_client), cancellation_callback=cancellation_callback,
            progress_callback=progress_callback, review_policy=review_policy)

    neutral_fresh_quality = scoped_revision and authenticated_qa_policy is None
    quality_explanations = batched_decisions or neutral_fresh_quality or direct_client is not None
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    structured_author = scoped_revision and (type(direct_client) is ManagedLunaClient
        or revision_policy == REVISION_POLICY and direct_client is None)
    structured_extraction = revision_policy == REVISION_POLICY and (
        type(direct_client) is ManagedLunaClient or direct_client is None)
    pipeline = V3GenerationPipeline(llm_invoker, explanation_consistency=quality_explanations,
                                    scoped_revision=scoped_revision,
                                    **({"decision_contract": True} if batched_decisions else {}),
                                    **({"structured_author_output": True} if structured_author else {}),
                                    **({"structured_extraction_output": True} if structured_extraction else {}))

    # Stage 1: Extract structured rule model
    if progress_callback:
        await progress_callback("realization", 1, 5, getattr(generation_client, "name", "llm"), 1)

    logger.info("V3 Engine: Step 1 - Extracting rule model for sha=%s", doc_sha[:12])
    # ONLY assign default doc_id and revision if corpus has exactly 1 document!
    # In a multi-document corpus, rules must not blindly assume first_doc_id fallback.
    default_doc_id = corpus.documents[0].doc_id if len(corpus.documents) == 1 else ""
    default_revision = corpus.documents[0].source_revision if len(corpus.documents) == 1 else ""

    extraction_warnings: list[str] = []
    if extraction_journal is not None:
        from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model

        rule_model, extraction_warnings = await extract_partitioned_rule_model(
            corpus, extraction_journal, route_fingerprint, llm_invoker, cancellation_callback,
            direct_client=direct_client, direct_max_output_tokens=direct_max_output_tokens,
            **({"structured_output": True} if structured_extraction else {}),
            **({"decision_contract": True} if batched_decisions else {}),
        )
    else:
        rule_model = await pipeline.extract_rule_model(
            document_title=first_title,
            document_text=full_text,
            document_sha256=doc_sha,
            doc_id=default_doc_id,
            source_revision=default_revision,
        )
    logger.info("V3 Engine: Step 1 complete. Extracted %d rules.", len(rule_model.rules))

    if cancellation_callback:
        await cancellation_callback()

    # Stage 2: Resilient curriculum grouping with unique group IDs and dependency closures
    reference_view = None
    planning_rule_model = rule_model
    if scoped_revision and reference_decisions:
        from app.modules.ai.v3.reference_source_view import (
            SourceReferenceReviewRequiredError,
            build_source_reference_view,
        )
        reference_view = build_source_reference_view(corpus, rule_model, reference_decisions)
        if reference_view.unresolved_decision_ids:
            raise SourceReferenceReviewRequiredError(reference_view.unresolved_decision_ids)
        planning_rule_model = reference_view.rule_model
    curriculum_groups = _build_curriculum_groups(planning_rule_model, corpus=corpus, reference_decisions=reference_decisions,
                                                source_view=reference_view)
    total_lessons = len(curriculum_groups)

    generated_lessons: list[V3Lesson] = []
    generated_lesson_rules: list[list[RuleEntity]] = []
    generated_primary_groups: list[tuple[str, tuple[RuleEntity, ...]]] = []
    generated_repair_contexts: list[Any] = []
    semantic_reviews: dict[str, Any] = {}
    lessons_summary = ""

    # Stage 3: Co-generate each lesson paired with assessment cases
    semantic_violations: list[str] = []
    semantic_repairs: list[dict[str, Any]] = []
    coverage_review_signals: list[str] = list(extraction_warnings)
    if reference_decisions:
        coverage_review_signals.append("Учитываются уточнения ссылок источника; требуется проверка методиста")
    for doc in corpus.documents:
        if doc.source_text is None:
            coverage_review_signals.append(
                f"Документ {doc.doc_id}: полный конвертированный текст не сохранён; "
                "проверить порядок и перекрытия фрагментов источника"
            )

    for idx, group in enumerate(curriculum_groups, 1):
        if cancellation_callback:
            await cancellation_callback()

        if progress_callback:
            await progress_callback("realization", idx + 1, total_lessons + 1, getattr(generation_client, "name", "llm"), 1)

        # Track unresolved dependencies as didactic warnings
        if group.unresolved_dependencies:
            for unres in group.unresolved_dependencies:
                semantic_violations.append(
                    f"Группа {group.group_id} ({group.display_title}): {unres}"
                )

        logger.info(
            "V3 Engine: Step 2 - Generating lesson %d/%d (%s): %s (%d primary rules, %d context prereqs)",
            idx,
            total_lessons,
            group.group_id,
            group.display_title,
            len(group.primary_rules),
            len(group.context_prerequisite_rules),
        )
        review_cache_box: list[Any] = [None]
        def stage_pipeline(stage: str, group_id: str = group.group_id,
                           cache_box: list[Any] = review_cache_box) -> Any:
            if extraction_journal is None:
                return pipeline
            from app.modules.ai.v3.stage_checkpoint import stage_once

            async def invoke_stage(messages: list[dict[str, str]], response_format: dict[str, Any] | None) -> dict[str, Any]:
                async def invoke() -> dict[str, Any]:
                    return await llm_invoker(messages, response_format)

                return await stage_once(extraction_journal, stage=stage, group_id=group_id,
                                        source_sha256=doc_sha, route_fingerprint=route_fingerprint,
                                        messages=messages, response_format=response_format, invoke=invoke,
                                        direct_client=direct_client, direct_max_output_tokens=direct_max_output_tokens)

            selected = V3GenerationPipeline(invoke_stage, explanation_consistency=quality_explanations,
                scoped_revision=scoped_revision,
                **({"structured_auxiliary_output": True} if typed_auxiliary else {}),
                **({"decision_contract": True} if batched_decisions else {}),
                **({"structured_author_output": True} if structured_author else {}))
            return cache_box[0].wrap(selected) if stage == "review" and cache_box[0] is not None else selected

        group_reference_context = reference_context_for_rules(
            corpus.tenant_id, corpus.documents, reference_decisions, group.primary_rules)
        primary_sources = _review_source_unit_fragments(list(group.primary_rules), corpus)
        related_sources = _review_source_unit_fragments(
            list(group.context_prerequisite_rules) + list(group.context_neighbor_rules), corpus)
        related_sources = [fragment for fragment in related_sources if fragment not in primary_sources]
        if extraction_journal is not None:
            for source_rule in group.primary_rules:
                if not _review_source_unit_fragments([source_rule], corpus):
                    semantic_violations.append(
                        f"Правило {source_rule.rule_id}: отсутствует точный исходный блок для генерации урока"
                    )
        lesson = await stage_pipeline("lesson").generate_lesson_with_scenarios(
            module_title=first_title,
            lesson_theme=group.display_title,
            rules=list(group.primary_rules),
            existing_lessons_summary=lessons_summary,
            prerequisite_rules=list(group.context_prerequisite_rules),
            neighbor_rules=list(group.context_neighbor_rules),
            reference_context=group_reference_context,
            primary_source_fragments=tuple(primary_sources),
            related_source_fragments=tuple(related_sources),
            audience=intent.audience,
            purpose=intent.purpose,
            emphasis=intent.emphasis,
        )
        repair_rules = (list(group.primary_rules) + list(group.context_prerequisite_rules)
                        + list(group.context_neighbor_rules))
        if extraction_journal is not None:
            lesson, quote_signals = _bind_rendered_quote_candidates(lesson, repair_rules, corpus)
            coverage_review_signals.extend(quote_signals)
        citation_holds = _nonliteral_case_citation_ids(lesson, repair_rules, corpus)
        if extraction_journal is not None and not citation_holds:
            repair_sources = _review_source_unit_fragments(repair_rules, corpus)
            from app.modules.ai.v3.explanation_repair import repair_order_dependent_explanations

            repair_sources_by_rule: dict[str, list[str]] = {}
            for repair_case in lesson.cases:
                linked = [rule for rule in repair_rules if rule.rule_id == repair_case.rule_id]
                if len(linked) == 1 and _verify_rule_quote_grounding(linked[0], corpus)[0]:
                    repair_sources_by_rule[repair_case.rule_id] = _review_source_unit_fragments(linked, corpus)
            lesson, explanations_repaired = await repair_order_dependent_explanations(
                lesson, repair_sources_by_rule, stage_pipeline("repair").invoker, group_reference_context,
                **({"typed_output": True} if typed_auxiliary else {}),
            )
            if explanations_repaired:
                coverage_review_signals.append(
                    f"Урок {lesson.lesson_id}: объяснения исправлены без привязки к порядку; "
                    "требуется смысловая проверка"
                )
            try:
                lesson, repaired = await _repair_option_shortcuts(
                    lesson, full_text, doc_sha, repair_sources, stage_pipeline("repair").invoker, group_reference_context,
                    source_documents,
                    **({"typed_output": True} if typed_auxiliary else {}),
                    **({"convergent_repair": True} if review_policy == REVIEW_POLICY else {}),
                )
            except OptionShortcutRepairUnresolvedError as unresolved:
                repaired = False
                # A whole-course mean can dilute a failed lesson's signal.
                # Keep every original lesson defect as a separate final hold.
                semantic_violations.extend(f"Урок {lesson.lesson_id}: {issue}" for issue in unresolved.violations)
            if repaired:
                coverage_review_signals.append(
                    f"Урок {lesson.lesson_id}: варианты ответов отредактированы; требуется смысловая проверка"
                )
        citation_holds = _nonliteral_case_citation_ids(lesson, repair_rules, corpus)
        for variant_id in citation_holds:
            semantic_violations.append(
                f"Урок {lesson.lesson_id}, вопрос {variant_id}: цитата не подтверждена целиком "
                "в исходном блоке; требуется проверка источника"
            )
        generated_lessons.append(lesson)
        generated_lesson_rules.append(repair_rules)
        generated_primary_groups.append((group.group_id, group.primary_rules))
        generated_repair_contexts.append((tuple(group.context_prerequisite_rules) + tuple(group.context_neighbor_rules),
                                          tuple(group.unresolved_dependencies)))
        lessons_summary += f"\n- {lesson.title}: {lesson.content[:150]}..."

        # A rule assigned to a lesson is not evidence that a test assesses it.
        # This is a review signal, not a semantic judgment that coverage is absent:
        # a question linked to one rule may assess multiple closely related rules.
        for rule_id in _unassessed_primary_rule_ids(lesson, list(group.primary_rules)):
            coverage_review_signals.append(
                f"Урок {lesson.lesson_id}: нет прямой связи вопроса с правилом {rule_id}; "
                "необходима проверка покрытия с учётом связанных правил"
            )
        for case_id, rule_id in _cases_outside_primary_rule_scope(lesson, list(group.primary_rules)):
            coverage_review_signals.append(
                f"Урок {lesson.lesson_id}, кейс {case_id}: связь с правилом {rule_id or '(не указано)'} "
                "вне основных правил урока; проверить тему и возможный повтор"
            )

        # Stage 4: Run Two-Factor semantic review with verified source fragments
        part_reviews: list[dict[str, Any]] = []
        answer_checks: list[dict[str, Any]] = []
        lesson_claim_reviews: list[dict[str, Any]] = []
        citation_checks: list[dict[str, Any]] = []
        accepted_case_checks: dict[str, dict[str, Any]] = {}
        try:
            review_rules = (list(group.primary_rules) + list(group.context_prerequisite_rules)
                            + list(group.context_neighbor_rules))
            source_frags: list[str] = []
            for r in review_rules:
                is_grounded, frag_report, occs = _verify_rule_quote_grounding(r, corpus)
                if is_grounded:
                    source_frags.append(frag_report)
                else:
                    semantic_violations.append(frag_report)
                    raw_q = (r.source_quote or "").strip()
                    if not raw_q:
                        source_frags.append(
                            f"[ОТСУТСТВУЕТ ЦИТАТА: у правила {r.rule_id} нет подтверждающего фрагмента в карте правил]"
                        )
                    elif occs:
                        source_frags.append(
                            f"[ОШИБКА ПРИВЯЗКИ ЦИТАТЫ | {r.rule_id}]: {frag_report}"
                        )
                    else:
                        source_frags.append(
                            f"[НЕВЕРИФИЦИРОВАНО, отсутствует в тексте оригинала | {r.rule_id}]: {raw_q}"
                        )

            # Exact source units provide context without certifying model quotes.
            exact_source_units = _review_source_unit_fragments(review_rules, corpus)
            source_frags.extend(exact_source_units)
            # A held citation must not be sent to question/case review or
            # repair, but it must not suppress independent lesson-prose review
            # or valid sibling cases. Review a filtered projection and retain
            # the original lesson for export and final custody validation.
            review_lesson = lesson
            if citation_holds:
                held_question_ids = {f"{variant_id}-assembled" for variant_id in citation_holds}
                filtered_cases = tuple(
                    replace(case, variants=tuple(
                        variant for variant in case.variants if variant.variant_id not in citation_holds
                    ))
                    for case in lesson.cases
                )
                review_lesson = replace(
                    lesson,
                    cases=tuple(case for case in filtered_cases if case.variants),
                    questions=() if lesson.cases else tuple(
                        q for q in lesson.questions if q.question_id not in held_question_ids
                    ),
                )
            parts = ([] if citation_holds and lesson.cases and not review_lesson.cases
                     else _semantic_review_parts(review_lesson))
            if batched_decisions and extraction_journal is not None:
                from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
                from app.modules.ai.v3.batched_review import BatchedReview
                from app.modules.ai.v3.review_work_items import lesson_review_items
                work = lesson_review_items(lesson, parts, review_rules, corpus, source_frags,
                    exact_source_units, group_reference_context, explanation_consistency=quality_explanations,
                    held_question_ids=frozenset(citation_holds))
                review_cache_box[0] = await BatchedReview.prime(
                    work, stage_pipeline("review", group_id="batched-review:" + group.group_id).invoker,
                    typed_transport=strict_batch_contract and type(direct_client) is not DirectLunaResponsesClient,
                    strict_contract=strict_batch_contract, typed_buckets=review_policy in {BUCKET_REVIEW_POLICY, AUXILIARY_REVIEW_POLICY, REVIEW_POLICY},
                    typed_fallback=typed_auxiliary)
            all_parts_passed = True
            deferred_lesson_defects: list[tuple[int, Any]] = []
            lesson_scope_resolved = False
            prose_resolution_evidence: dict[str, Any] | None = None
            if len(parts) > 1:
                coverage_review_signals.append(
                    f"Урок {lesson.lesson_id}: межкейсовые смысловые повторы и полноту проверить отдельно"
                )
            for part_index, part in enumerate(parts, 1):
                review_res = await stage_pipeline("review").review_lesson(
                    part, review_rules, source_fragments=source_frags, partial_case=len(parts) > 1,
                    reference_context=group_reference_context,
                )
                # Retain the original review even if a later repair/recheck has
                # an unknown outcome and QA continues under a review hold.
                part_reviews.append(review_res)
                is_valid, schema_err = _validate_critic_response(review_res, lesson.lesson_id, lesson.title)
                case_has_held_variant = bool(part.cases and any(
                    variant.variant_id in citation_holds
                    for variant in next((case for case in lesson.cases if case.case_id == part.cases[0].case_id),
                                        part.cases[0]).variants
                ))
                lesson_only = (scoped_revision and is_valid and bool(review_res.get("defects")) and all(
                    isinstance(defect, dict) and defect.get("scope") == "lesson"
                    for defect in review_res["defects"]))
                if (extraction_journal is not None and part.cases and not case_has_held_variant and not lesson_only
                        and (not is_valid or str(review_res.get("verdict", "")).strip().upper() != "PASS")):
                    original_review = review_res
                    try:
                        repaired_lesson, was_repaired = await _repair_reviewed_case(
                            lesson, part, review_res, full_text, doc_sha, exact_source_units,
                            stage_pipeline("repair").invoker, group_reference_context, source_documents,
                            repair_prompt=scoped_revision,
                            **({"typed_output": True} if typed_auxiliary else {}),
                        )
                    except SemanticRepairRejectedError as repair_error:
                        rejection = str(repair_error)
                        semantic_repairs.append({"lesson_id": lesson.lesson_id, "case_id": part.cases[0].case_id,
                                                 "original_review": original_review, "recheck": None,
                                                 "rejected": rejection})
                        coverage_review_signals.append(
                            f"Урок {lesson.lesson_id}: правка отклонена; сохранены исходный вопрос и замечания"
                        )
                        repaired_lesson, was_repaired = lesson, False
                    if was_repaired:
                        case_id = part.cases[0].case_id
                        repair_record: dict[str, Any] = {"lesson_id": lesson.lesson_id, "case_id": case_id,
                                                         "original_review": original_review, "recheck": None}
                        semantic_repairs.append(repair_record)
                        from app.modules.ai.v3.case_repair_gate import review_staged_case

                        accepted, cached_checks = await review_staged_case(
                            repaired_lesson, case_id, review_rules, corpus, source_frags, exact_source_units,
                            group_reference_context, len(parts) > 1, stage_pipeline("review"), repair_record,
                        )
                        if accepted:
                            lesson = repaired_lesson
                            generated_lessons[-1] = lesson
                            accepted_case_checks.update(cached_checks)
                            review_res = repair_record["recheck"]
                            part_reviews[-1] = review_res
                            is_valid, schema_err = _validate_critic_response(review_res, lesson.lesson_id, lesson.title)
                            repair_record["accepted"] = True
                            coverage_review_signals.append(
                                f"Урок {lesson.lesson_id}, кейс {case_id}: варианты исправлены и перепроверены; "
                                "сохранено исходное замечание"
                            )
                        else:
                            all_parts_passed = False
                            semantic_violations.append(
                                f"Урок {lesson.lesson_id}, кейс {case_id}: правка отклонена: "
                                f"{repair_record.get('rejected', 'candidate_unverified')}"
                            )
                elif (extraction_journal is not None and part.cases and case_has_held_variant and not lesson_only
                      and (not is_valid or str(review_res.get("verdict", "")).strip().upper() != "PASS")):
                    semantic_repairs.append({"lesson_id": lesson.lesson_id, "case_id": part.cases[0].case_id,
                                             "original_review": review_res, "recheck": None,
                                             "rejected": "case_contains_held_variant"})
                    coverage_review_signals.append(
                        f"Урок {lesson.lesson_id}, кейс {part.cases[0].case_id}: автоматическая правка отложена; "
                        "кейс содержит неподтверждённую цитату"
                    )
                if not is_valid:
                    all_parts_passed = False
                    semantic_violations.append(f"Проверка части {part_index}: {schema_err}")
                    continue
                verdict = str(review_res.get("verdict", "")).strip().upper()
                if verdict != "PASS":
                    for defect in review_res.get("defects") or []:
                        if scoped_revision and isinstance(defect, dict) and defect.get("scope") == "lesson":
                            deferred_lesson_defects.append((part_index, defect))
                        else:
                            all_parts_passed = False
                            semantic_violations.append(
                                f"Семантический критик: урок {lesson.lesson_id}, часть {part_index}: {defect}"
                            )
            # The general critic can miss invented claims in lesson prose even
            # when the question itself is supported. Audit prose once per
            # lesson, not once per case. A failed case must not hide prose defects.
            if lesson.content.strip():
                if not exact_source_units:
                    all_parts_passed = False
                    semantic_violations.append(f"Урок {lesson.lesson_id}: нет исходных блоков для проверки текста")
                else:
                    prose_failures: list[dict[str, Any]] = []
                    sections = _lesson_claim_sections(lesson.content)
                    if len(sections) > 1:
                        coverage_review_signals.append(
                            f"Урок {lesson.lesson_id}: зависимости между частями текста требуют отдельной проверки"
                        )
                    for section_index, section in enumerate(sections, 1):
                        table_parts = _lesson_claim_table_parts(section)
                        if len(table_parts) > 1:
                            coverage_review_signals.append(
                                f"Урок {lesson.lesson_id}, часть {section_index}: "
                                "связи между строками таблицы требуют отдельной проверки"
                            )
                        for table_index, (table_text, table_context) in enumerate(table_parts, 1):
                            subparts = _lesson_claim_subparts(table_text)
                            if len(subparts) > 1:
                                coverage_review_signals.append(
                                    f"Урок {lesson.lesson_id}, часть {section_index}: "
                                    "связи между подразделами требуют отдельной проверки"
                                )
                            for subpart_index, (part_text, parent_heading) in enumerate(subparts, 1):
                                scenario = (f"Часть {section_index} из {len(sections)} одного урока; "
                                            "не делайте выводов о содержании отсутствующих частей.")
                                if len(table_parts) > 1:
                                    scenario += (f"\nГруппа строк таблицы {table_index} из {len(table_parts)}; "
                                                 "заголовок таблицы из урока для контекста:\n" + table_context)
                                if len(subparts) > 1:
                                    scenario += (f"\nГруппа подразделов {subpart_index} из {len(subparts)}; "
                                                 "родительский заголовок урока для контекста:\n" + parent_heading)
                                claim_review = await stage_pipeline("review").review_answer(
                                    scenario, "Фактические утверждения текста урока", part_text,
                                    exact_source_units, group_reference_context,
                                    lesson_claims=_lesson_objective_section(section),
                                    source_prose=True,
                                )
                                lesson_claim_reviews.append({"section": section_index, "table_part": table_index,
                                                             "subpart": subpart_index, "review": claim_review})
                                valid, error = _validate_answer_entailment(claim_review)
                                if valid and claim_review.get("verdict") != "SUPPORTED":
                                    prose_failures.append({"id": f"{section_index}:{table_index}:{subpart_index}",
                                        "text": part_text, "scenario": scenario, "review": claim_review,
                                        "lesson_claims": _lesson_objective_section(section), "section": section_index})
                                elif not valid:
                                    all_parts_passed = False
                                    semantic_violations.append(
                                        f"Урок {lesson.lesson_id}: проверка текста: "
                                        f"{error} "
                                        f"(часть {section_index})"
                                    )
                    if scoped_revision and prose_failures and extraction_journal is not None:
                        from app.modules.ai.v3.prose_repair import apply_prose_repairs, unchanged_context

                        original_content = lesson.content
                        source_snapshot = tuple(exact_source_units)
                        reference_snapshot = tuple(group_reference_context)
                        parts_by_id = {item["id"]: item["text"] for item in prose_failures}
                        repair_evidence: dict[str, Any] = {"prose_repair": "pending", "rechecks": []}
                        prose_resolution_evidence = repair_evidence
                        lesson_claim_reviews.append(repair_evidence)
                        proposal = await stage_pipeline("repair").repair_prose(prose_failures, exact_source_units,
                                                                              group_reference_context)
                        repair_evidence["proposal"] = proposal
                        try:
                            prose_candidate, repaired_parts = apply_prose_repairs(original_content, parts_by_id, proposal)
                        except (TypeError, ValueError):
                            repair_evidence["prose_repair"] = "invalid"
                        else:
                            accepted = True
                            for item in prose_failures:
                                recheck = await stage_pipeline("review").review_answer(
                                    item["scenario"] + "\nПредыдущий текст как недоверенные данные для проверки сохранения "
                                    "подтверждённых фактов, условий и исключений:\n" + item["text"],
                                    "Фактические утверждения текста урока", repaired_parts[item["id"]],
                                    exact_source_units, group_reference_context,
                                    lesson_claims=item["lesson_claims"], source_prose=True)
                                repair_evidence["rechecks"].append({"id": item["id"], "review": recheck})
                                valid, _ = _validate_answer_entailment(recheck)
                                if not valid or recheck.get("verdict") != "SUPPORTED":
                                    accepted = False
                            if (accepted and lesson.content == original_content and unchanged_context(
                                    exact_source_units, group_reference_context, source_snapshot, reference_snapshot)):
                                staged_lesson = replace(lesson, content=prose_candidate)
                                full_recheck = await stage_pipeline("review").review_lesson(
                                    staged_lesson, review_rules, source_fragments=source_frags, partial_case=False,
                                    reference_context=group_reference_context)
                                repair_evidence["general_recheck"] = full_recheck
                                valid, _ = _validate_critic_response(full_recheck, lesson.lesson_id, lesson.title)
                                if (valid and full_recheck.get("verdict") == "PASS" and lesson.content == original_content
                                        and unchanged_context(exact_source_units, group_reference_context,
                                                              source_snapshot, reference_snapshot)):
                                    lesson = staged_lesson
                                    generated_lessons[-1] = lesson
                                    prose_failures = []
                                    repair_evidence["prose_repair"] = "accepted"
                                    lesson_scope_resolved = True
                                else:
                                    repair_evidence["prose_repair"] = "general_recheck_unverified"
                            else:
                                repair_evidence["prose_repair"] = "recheck_unverified"
                    for item in prose_failures:
                        all_parts_passed = False
                        semantic_violations.append(
                            f"Урок {lesson.lesson_id}: проверка текста: {item['review'].get('verdict')} "
                            f"(часть {item['section']})"
                        )
            if prose_resolution_evidence is not None:
                prose_resolution_evidence["lesson_scope_resolved"] = lesson_scope_resolved
            if deferred_lesson_defects and not lesson_scope_resolved:
                all_parts_passed = False
                for part_index, defect in deferred_lesson_defects:
                    semantic_violations.append(
                        f"Семантический критик: урок {lesson.lesson_id}, часть {part_index}: {defect}"
                    )
            answers = _question_option_inputs(lesson)
            if answers and not exact_source_units:
                all_parts_passed = False
                semantic_violations.append(f"Урок {lesson.lesson_id}: нет точных исходных блоков для проверки ответов")
            else:
                for question_id, scenario, question, options, rule_id in answers:
                    if question_id in citation_holds:
                        continue
                    if (not question_id or not question or len(options) != 4
                            or sum(is_correct for _, is_correct in options) != 1
                            or any(not text.strip() for text, _ in options)):
                        all_parts_passed = False
                        semantic_violations.append(f"Урок {lesson.lesson_id}: неполный вопрос или правильный ответ")
                        continue
                    if quality_explanations and _direct_explanation_requires_hold(_question_explanation(lesson, question_id)):
                        all_parts_passed = False
                        semantic_violations.append(f"Урок {lesson.lesson_id}, вопрос {question_id}: отсутствует объяснение")
                        continue
                    linked_rules = [rule for rule in review_rules if rule.rule_id == rule_id]
                    if len(linked_rules) != 1 or not _review_source_unit_fragments(linked_rules, corpus):
                        all_parts_passed = False
                        semantic_violations.append(
                            f"Урок {lesson.lesson_id}, вопрос {question_id}: нет однозначного исходного блока связанного правила"
                        )
                        continue
                    from app.modules.ai.v3.case_repair_gate import answer_review_fingerprint
                    from app.modules.ai.v3.citation_expansion import citation_question_fingerprint

                    cached = accepted_case_checks.get(question_id)
                    if (cached and cached["fingerprint"] == citation_question_fingerprint(
                            lesson, f"{question_id}-assembled")
                            and cached["answer_review_fingerprint"] == answer_review_fingerprint(
                                scenario, question, options, rule_id, exact_source_units, group_reference_context)):
                        answer_checks.append(cached["check"])
                        continue
                    answer_review = await stage_pipeline("review").review_question_options(
                        scenario, question, [text for text, _ in options], exact_source_units, group_reference_context)
                    answer_checks.append({"question_id": question_id, "review": answer_review})
                    valid, error = _validate_question_entailment(answer_review, [correct for _, correct in options])
                    flagged = _flagged_incorrect_options(answer_review, [correct for _, correct in options]) \
                        if not valid else []
                    feedback_case_held = any(
                        variant.variant_id in citation_holds
                        for case in lesson.cases
                        if any(variant.variant_id == question_id
                               or f"{variant.variant_id}-assembled" == question_id for variant in case.variants)
                        for variant in case.variants
                    )
                    if (not valid and extraction_journal is not None and flagged
                            and lesson.cases and feedback_case_held):
                        answer_checks[-1]["distractor_repair"] = {
                            "original_review": answer_review,
                            "rejected": "case_contains_held_variant",
                        }
                    if not valid:
                        flagged = _flagged_incorrect_options(answer_review, [correct for _, correct in options])
                        if extraction_journal is not None and flagged and lesson.cases and not feedback_case_held:
                            from app.modules.ai.v3.option_repair import (
                                DistractorFeedbackRejectedError,
                                repair_distractor_feedback,
                            )

                            attempt: dict[str, Any] = {"original_review": answer_review, "recheck": None}
                            answer_checks[-1]["distractor_repair"] = attempt
                            try:
                                candidate = await repair_distractor_feedback(
                                    lesson, question_id, flagged, exact_source_units,
                                    stage_pipeline("repair").invoker, group_reference_context,
                                    **({"typed_output": True} if typed_auxiliary else {}),
                                )
                            except DistractorFeedbackRejectedError as rejected:
                                attempt["rejected"] = str(rejected)
                            else:
                                original_course = V3Course(course_id="feedback-check", title=lesson.title,
                                    document_sha256=doc_sha, lessons=(lesson,))
                                original_report = validate_v3_course(original_course, source_document_text=full_text,
                                                                     source_documents=source_documents)
                                candidate_report = validate_v3_course(replace(original_course, lessons=(candidate,)),
                                    source_document_text=full_text, source_documents=source_documents)
                                new_violations = set(candidate_report.violations) - set(original_report.violations)
                                matching_cases = [case for case in candidate.cases
                                    if any(variant.variant_id == question_id for variant in case.variants)]
                                matching_answers = [row for row in _question_option_inputs(candidate) if row[0] == question_id]
                                if (new_violations or len(matching_cases) != 1 or len(matching_answers) != 1
                                        or (quality_explanations and _direct_explanation_requires_hold(_question_explanation(candidate, question_id)))):
                                    attempt["rejected"] = "v3_distractor_feedback_structural_regression"
                                else:
                                    _qid, new_scenario, new_question, new_options, _rule_id = matching_answers[0]
                                    case_part = replace(candidate, cases=(matching_cases[0],), questions=())
                                    case_review = await stage_pipeline("review").review_lesson(
                                        case_part, review_rules, source_fragments=source_frags,
                                        partial_case=len(parts) > 1, reference_context=group_reference_context)
                                    critic_ok, _critic_error = _validate_critic_response(
                                        case_review, candidate.lesson_id, candidate.title)
                                    attempt["case_recheck"] = case_review
                                    if critic_ok and str(case_review.get("verdict", "")).strip().upper() == "PASS":
                                        revised = await stage_pipeline("review").review_question_options(
                                            new_scenario, new_question, [text for text, _ in new_options],
                                            exact_source_units, group_reference_context)
                                        attempt["recheck"] = revised
                                        revised_ok, _ = _validate_question_entailment(
                                            revised, [correct for _, correct in new_options])
                                        if revised_ok:
                                            compatible = await stage_pipeline("review").review_question_compatibility(
                                                new_scenario, new_question, [text for text, _ in new_options],
                                                exact_source_units, group_reference_context)
                                            from app.modules.ai.v3.compatibility_recheck import recheck_compatibility
                                            compatible_ok, _ = await recheck_compatibility(
                                                stage_pipeline("review"), new_scenario, new_question,
                                                [text for text, _ in new_options], [correct for _, correct in new_options],
                                                exact_source_units, group_reference_context, compatible, attempt)
                                            if compatible_ok:
                                                correct_text = next(text for text, flag in new_options if flag)
                                                complete = await stage_pipeline("review").review_answer_completeness(
                                                    new_scenario, new_question, correct_text, exact_source_units,
                                                    group_reference_context, explanation=_question_explanation(candidate, question_id),
                                                    options=[text for text, _ in new_options])
                                                attempt["completeness"] = complete
                                                if _validate_answer_completeness(complete, explanation_consistency=quality_explanations)[0]:
                                                    lesson = candidate
                                                    generated_lessons[-1] = lesson
                                                    attempt["accepted"] = True
                                                    coverage_review_signals.append(
                                                        f"Урок {lesson.lesson_id}, вопрос {question_id}: "
                                                        "неверный вариант исправлен по замечанию и перепроверен"
                                                    )
                                                    continue
                        all_parts_passed = False
                        semantic_violations.append(f"Урок {lesson.lesson_id}, вопрос {question_id}: {error}")
                        continue
                    compatibility = await stage_pipeline("review").review_question_compatibility(
                        scenario, question, [text for text, _ in options], exact_source_units, group_reference_context)
                    from app.modules.ai.v3.compatibility_recheck import recheck_compatibility
                    valid, error = await recheck_compatibility(
                        stage_pipeline("review"), scenario, question, [text for text, _ in options],
                        [correct for _, correct in options], exact_source_units, group_reference_context,
                        compatibility, answer_checks[-1])
                    if not valid:
                        all_parts_passed = False
                        semantic_violations.append(
                            f"Урок {lesson.lesson_id}, вопрос {question_id}: проверка совместимости: {error}"
                        )
                        continue
                    correct_answer = next(text for text, is_correct in options if is_correct)
                    completeness = await stage_pipeline("review").review_answer_completeness(
                        scenario, question, correct_answer, exact_source_units, group_reference_context,
                        explanation=_question_explanation(lesson, question_id), options=[text for text, _ in options])
                    answer_checks[-1]["completeness"] = completeness
                    valid, error = _validate_answer_completeness(completeness, explanation_consistency=quality_explanations)
                    if not valid:
                        all_parts_passed = False
                        semantic_violations.append(
                            f"Урок {lesson.lesson_id}, вопрос {question_id}: проверка полноты: {error}"
                        )
            # Run after all question repairs: an exact quote can still support
            # only part of the answer. Provenance and semantic support are
            # separate checks; no complete result establishes infallibility.
            from app.modules.ai.v3.citation_expansion import (
                citation_question_fingerprint,
                propose_rule_quote_expansion,
                stage_citation_candidate,
            )
            from app.modules.ai.v3.citation_review import (
                CitationReviewInvalidError,
                build_citation_review_items,
                review_displayed_citations,
            )

            # Critics and repairs may have replaced the lesson after the
            # initial filtered projection was created. Rebuild from the
            # current exported lesson so citation payloads/fingerprints never
            # describe stale question, answer, explanation, or quote data.
            citation_review_lesson = lesson
            if citation_holds:
                held_question_ids = {f"{variant_id}-assembled" for variant_id in citation_holds}
                current_cases = tuple(
                    replace(case, variants=tuple(
                        variant for variant in case.variants if variant.variant_id not in citation_holds
                    ))
                    for case in lesson.cases
                )
                citation_review_lesson = replace(
                    lesson,
                    cases=tuple(case for case in current_cases if case.variants),
                    questions=() if lesson.cases else tuple(
                        q for q in lesson.questions if q.question_id not in held_question_ids
                    ),
                )
            citation_items, citation_issues = build_citation_review_items(citation_review_lesson, review_rules, corpus)
            if citation_holds:
                all_parts_passed = False
            for issue in citation_issues:
                all_parts_passed = False
                semantic_violations.append(f"Урок {lesson.lesson_id}: источник цитаты не подтверждён: {issue}")
            for offset in range(0, len(citation_items), 8):
                batch = citation_items[offset:offset + 8]
                # Fingerprints bind the full exported lesson state, including
                # compatibility projections that are intentionally omitted from
                # the held-question citation-review projection.
                fingerprints = {item["id"]: citation_question_fingerprint(lesson, item["id"])
                                for item in batch}
                try:
                    reviewed = await review_displayed_citations(batch, stage_pipeline("review").invoker,
                        **({"typed_output": True} if typed_auxiliary else {}))
                except CitationReviewInvalidError as error:
                    all_parts_passed = False
                    semantic_violations.append(f"Урок {lesson.lesson_id}: проверка цитат не завершена: {error}")
                    continue
                for item in batch:
                    result = reviewed[item["id"]]
                    record: dict[str, Any] = {"question_id": item["id"], "source_identity": item["source_identity"],
                                              "review": result}
                    citation_checks.append(record)
                    if result["verdict"] == "PARTIAL":
                        if lesson.cases:
                            rule_ids = [case.rule_id for case in lesson.cases for variant in case.variants
                                        if f"{variant.variant_id}-assembled" == item["id"]]
                        else:
                            rule_ids = [q.rule_id for q in lesson.questions if q.question_id == item["id"]]
                        linked = [rule for rule in review_rules if len(rule_ids) == 1 and rule.rule_id == rule_ids[0]]
                        fingerprint = fingerprints[item["id"]]
                        if len(linked) == 1 and fingerprint:
                            quote_candidate = propose_rule_quote_expansion(corpus, linked[0], item["displayed_quote"])
                            staged = (stage_citation_candidate(lesson, linked[0], corpus, item, quote_candidate, fingerprint)
                                      if quote_candidate else None)
                            if quote_candidate and staged is not None:
                                staged_items, _ = build_citation_review_items(staged, review_rules, corpus)
                                matches = [candidate_item for candidate_item in staged_items
                                           if candidate_item["id"] == item["id"]]
                                if len(matches) == 1:
                                    record["candidate_source_identity"] = matches[0]["source_identity"]
                                    try:
                                        candidate_review = (await review_displayed_citations(
                                            matches, stage_pipeline("review").invoker,
                                            **({"typed_output": True} if typed_auxiliary else {})))[item["id"]]
                                    except CitationReviewInvalidError as error:
                                        record["candidate_error"] = str(error)
                                    else:
                                        record["candidate_review"] = candidate_review
                                        confirmed = stage_citation_candidate(
                                            lesson, linked[0], corpus, item, quote_candidate, fingerprint)
                                        if candidate_review["verdict"] == "COMPLETE" and confirmed is not None:
                                            lesson = confirmed
                                            generated_lessons[-1] = lesson
                                            record["candidate_accepted"] = True
                                            record["candidate_fingerprint"] = citation_question_fingerprint(
                                                lesson, item["id"]
                                            )
                                            coverage_review_signals.append(
                                                f"Урок {lesson.lesson_id}, вопрос {item['id']}: "
                                                "цитата расширена до исходного фрагмента и требует смысловой проверки"
                                            )
                                            continue
                    if result["verdict"] != "COMPLETE":
                        all_parts_passed = False
                        semantic_violations.append(
                            f"Урок {lesson.lesson_id}, вопрос {item['id']}: "
                            f"цитата подтверждает ответ не полностью: {result['verdict']}"
                        )
            semantic_reviews[lesson.lesson_id] = {
                "verdict": "PASS" if all_parts_passed else "NEEDS_REVISION", "parts": part_reviews,
                "lesson_claim_reviews": lesson_claim_reviews, "answer_checks": answer_checks,
                "citation_checks": citation_checks,
            }
        except Exception as review_err:
            unknown_review = isinstance(review_err, ExtractionOutcomeUnknownError)
            if unknown_review and authenticated_qa_policy in OWNED_POLICIES:
                raise
            if extraction_journal is not None and not (allow_unreviewed_on_unknown and unknown_review):
                raise
            logger.warning("V3 Engine: Two-factor semantic review skipped due to error: %s", review_err)
            semantic_reviews[lesson.lesson_id] = {"verdict": "ERROR", "error": str(review_err),
                                                   "parts": part_reviews, "lesson_claim_reviews": lesson_claim_reviews,
                                                   "answer_checks": answer_checks, "citation_checks": citation_checks}
            if unknown_review:
                semantic_violations.append(
                    f"Урок {lesson.lesson_id}: исход предыдущей проверки неизвестен; "
                    "повтор не выполнялся, необходима ручная проверка всего урока"
                )
            else:
                semantic_violations.append(
                    f"Ошибка выполнения семантической проверки урока {lesson.lesson_id}: {review_err}"
                )

    # Later semantic repairs may alter a lesson. Recheck the exported state;
    # retain earlier holds even when a later candidate appears grounded.
    for final_lesson, final_rules in zip(generated_lessons, generated_lesson_rules, strict=True):
        for variant_id in _unbound_case_citation_ids(final_lesson, final_rules, corpus):
            message = (f"Урок {final_lesson.lesson_id}, вопрос {variant_id}: цитата не подтверждена целиком "
                       "в исходном блоке; требуется проверка источника")
            if message not in semantic_violations:
                semantic_violations.append(message)

    async def invoke_diversity(messages: list[dict[str, str]]) -> dict[str, Any]:
        return await llm_invoker(messages, {"type": "json_object"})

    async def invoke_typed_diversity(messages: list[dict[str, str]], response_format: dict[str, Any]) -> dict[str, Any]:
        return await llm_invoker(messages, response_format)

    await _review_final_diversity(
        policy=authenticated_qa_policy, lessons=generated_lessons, groups=generated_primary_groups,
        corpus=corpus, journal=extraction_journal, source_context=owned_source_context,
        direct_client=direct_client, source_sha256=doc_sha, route_fingerprint=route_fingerprint,
        invoke=invoke_diversity, max_tokens=direct_max_output_tokens, cancellation_callback=cancellation_callback,
        signals=coverage_review_signals, violations=semantic_violations,
        repair_contexts=generated_repair_contexts, review_records=semantic_reviews,
        allow_repair=not reference_decisions, revision_policy=revision_policy,
        **({"typed_invoke": invoke_typed_diversity} if typed_auxiliary else {}),
    )

    if neutral_fresh_quality or authenticated_qa_policy in OWNED_POLICIES:
        from app.modules.ai.v3.exact_duplicate_review import has_cross_lesson_duplicate

        if has_cross_lesson_duplicate(generated_lessons):
            semantic_violations.append(
                "В разных уроках совпадают тексты вопросов; требуется проверка методиста"
            )

    unvalidated_course = V3Course(
        course_id=f"course-v3-{doc_sha[:12]}",
        title=first_title,
        document_sha256=doc_sha,
        lessons=tuple(generated_lessons),
        quality_verdict="needs_review",
    )

    report = validate_v3_course(unvalidated_course, full_text, source_documents=source_documents)
    # Automated structural validation never falsely certifies semantic truth; status remains needs_review
    quality_verdict = report.quality_status
    if report.structural_verdict != "PASS":
        logger.warning(
            "V3 Course Quality Gate identified %d structural violations: %s",
            len(report.violations),
            "; ".join(report.violations[:5]),
        )
    else:
        logger.info("V3 Course Quality Gate passed all structural invariants (verdict=%s)", report.structural_verdict)

    validation_payload = report.to_dict()
    validation_payload["semantic_reviews"] = semantic_reviews
    validation_payload["semantic_repairs"] = semantic_repairs
    validation_payload["coverage_review_signals"] = coverage_review_signals
    if reference_view is not None:
        validation_payload["source_reference_planning_view"] = {
            "policy": reference_view.policy, "fingerprint": reference_view.fingerprint,
            "changes": [asdict(change) for change in reference_view.changes],
            "unresolved_decision_ids": list(reference_view.unresolved_decision_ids),
            "semantic_approval": False,
        }

    # Propagate semantic review violations into the validation report
    all_violations = list(validation_payload.get("violations", []))
    if semantic_violations:
        all_violations.extend(semantic_violations)
        validation_payload["violations"] = all_violations
        validation_payload["verdict"] = "FAIL"

    course = V3Course(
        course_id=unvalidated_course.course_id,
        title=unvalidated_course.title,
        document_sha256=unvalidated_course.document_sha256,
        lessons=unvalidated_course.lessons,
        quality_verdict=quality_verdict,
        validation_report=validation_payload,
    )

    if progress_callback:
        await progress_callback("quality", total_lessons + 1, total_lessons + 1, None, None)

    adapter_options: dict[str, Any] = {}
    if neutral_fresh_quality or authenticated_qa_policy in OWNED_POLICIES:
        adapter_options = {"source_corpus": corpus, "source_rules": tuple(
            rule for _group_id, rules in generated_primary_groups for rule in rules), "exact_narrative_facts": True}
    artifacts = v3_course_to_generation_artifacts(course, source_document_ids=list(corpus.document_ids),
                                                  **adapter_options)
    return artifacts
