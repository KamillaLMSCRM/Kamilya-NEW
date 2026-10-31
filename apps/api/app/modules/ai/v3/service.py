"""Production service entry point for V3 Course & Assessment Co-Generation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import CurriculumGroup, DocumentRuleModel, RuleEntity, V3Course, V3Lesson
from app.modules.ai.v3.validator import normalize_text_for_search, validate_v3_course

logger = logging.getLogger(__name__)


def _extract_corpus_text(corpus: DirectSourceCorpus) -> tuple[str, str]:
    """Concatenates chunk text across all documents in the corpus and computes SHA256.

    IMPORTANT: Metadata headers (document titles, filenames) are strictly excluded from full_text
    so that citation grounding validates exclusively against authentic chunk contents.
    """
    text_parts: list[str] = []
    for doc in corpus.documents:
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
    source_revision: str
    char_start: int
    char_end: int
    matched_text: str


def normalize_with_char_map(text: str) -> tuple[str, list[int]]:
    """Normalizes text by removing markdown table pipes, newlines, extra whitespace,
    and converting to lowercase, while returning a map of original character indices.

    Guarantees:
        len(norm_text) == len(char_map)
        norm_text[i] originated from text[char_map[i]].
    """
    cleaned_chars: list[str] = []
    char_map: list[int] = []
    in_whitespace = True

    for idx, char in enumerate(text):
        if char in " \t\r\n|":
            if not in_whitespace:
                cleaned_chars.append(" ")
                char_map.append(idx)
                in_whitespace = True
        else:
            cleaned_chars.append(char.lower())
            char_map.append(idx)
            in_whitespace = False

    if cleaned_chars and cleaned_chars[-1] == " ":
        cleaned_chars.pop()
        char_map.pop()

    return "".join(cleaned_chars), char_map


def find_quote_occurrences_in_corpus(
    quote: str,
    corpus: DirectSourceCorpus,
) -> list[QuoteOccurrence]:
    """Finds all exact occurrences of quote inside document chunks with verified original coordinates.

    Guarantees that chunk.text[char_start:char_end] strictly matches the quote without truncating words.
    """
    clean_quote = quote.strip()
    if not clean_quote:
        return []
    norm_q = normalize_text_for_search(clean_quote)
    if not norm_q:
        return []

    occurrences: list[QuoteOccurrence] = []
    match_len = len(norm_q)

    for doc in corpus.documents:
        for chunk in doc.chunks:
            c_text = chunk.text
            norm_c, char_map = normalize_with_char_map(c_text)
            start_pos = 0
            while True:
                idx = norm_c.find(norm_q, start_pos)
                if idx == -1:
                    break
                orig_start = char_map[idx]
                orig_end = char_map[idx + match_len - 1] + 1
                matched_slice = c_text[orig_start:orig_end]
                # Reverse verification check: normalized slice must match norm_q
                if normalize_text_for_search(matched_slice) == norm_q:
                    occurrences.append(
                        QuoteOccurrence(
                            doc_id=doc.doc_id,
                            chunk_id=chunk.chunk_id,
                            source_revision=doc.source_revision or chunk.source_revision,
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
            return True, first.doc_id, first.chunk_id, first.char_start, first.char_end
    first = occurrences[0]
    return True, first.doc_id, first.chunk_id, first.char_start, first.char_end


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
        return False, (
            f"Неподтвержденная цитата в правиле {rule.rule_id} ('{rule.title}'): фрагмент карты правил отсутствует в содержимом документов корпуса"
        ), []

    rule_doc_id = (rule.doc_id or "").strip()
    if rule_doc_id:
        doc_matches = [occ for occ in all_occurrences if occ.doc_id == rule_doc_id]
        if not doc_matches:
            other_docs = sorted(list({occ.doc_id for occ in all_occurrences}))
            return False, (
                f"Несоответствие источника: цитата правила {rule.rule_id} ('{rule.title}') найдена в документах {other_docs}, но правило привязано к документу '{rule_doc_id}'"
            ), all_occurrences
        target_matches = doc_matches
    else:
        # Rule has no explicit doc_id
        distinct_docs = sorted(list({occ.doc_id for occ in all_occurrences}))
        if len(distinct_docs) > 1:
            return False, (
                f"Неоднозначная принадлежность цитаты для правила {rule.rule_id} ('{rule.title}'): фраза обнаружена сразу в нескольких документах ({distinct_docs}). Требуется явное указание doc_id правила."
            ), all_occurrences
        target_matches = all_occurrences

    primary = target_matches[0]
    multi_note = f" (всего совпадений в документе: {len(target_matches)})" if len(target_matches) > 1 else ""
    fragment_str = (
        f"[Верифицированная цитата | Документ {primary.doc_id}{multi_note} | "
        f"Чанк {primary.chunk_id} ({primary.char_start}:{primary.char_end})]: {primary.matched_text}"
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
            r = RuleEntity(
                rule_id=assigned_id,
                section=r.section,
                title=r.title,
                statement=r.statement,
                conditions=r.conditions,
                exceptions=r.exceptions,
                actors=r.actors,
                timing=r.timing,
                consequences=r.consequences,
                source_quote=r.source_quote,
                doc_id=r.doc_id,
                source_revision=r.source_revision,
            )
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

    # Score validation helper
    def _validate_score_val(name: str, val: Any) -> tuple[bool, float, str]:
        if isinstance(val, bool) or not isinstance(val, int | float):
            return False, 0.0, f"Поле '{name}' должно быть числом (int или float), получено: {type(val).__name__} ({val!r})"
        val_f = float(val)
        if 1.0 <= val_f <= 5.0:
            norm = (val_f - 1.0) / 4.0
        elif 0.0 <= val_f <= 1.0:
            norm = val_f
        elif 0.0 <= val_f <= 100.0:
            norm = val_f / 100.0
        else:
            return False, 0.0, f"Оценка '{name}' вне допустимого диапазона (1-5 или 0.0-1.0): {val}"
        return True, norm, ""

    # Check scores: canonical prompt scores (factual_score, alignment_score, didactic_score)
    # and alternate/legacy scores (confidence, factual_accuracy_score, evidence_grounding_score)
    score_names = [
        "factual_score", "alignment_score", "didactic_score",
        "confidence", "factual_accuracy_score", "evidence_grounding_score",
    ]
    scores_found: dict[str, float] = {}
    for s_name in score_names:
        if s_name in review_res and review_res[s_name] is not None:
            ok, norm_val, err_msg = _validate_score_val(s_name, review_res[s_name])
            if not ok:
                return False, f"Ошибка в оценке критика для урока {lesson_id}: {err_msg}"
            scores_found[s_name] = norm_val

    if not scores_found:
        return False, (
            f"Ответ критика для урока {lesson_id} не содержит обязательных числовых оценок качества "
            f"(ожидались: factual_score/alignment_score/didactic_score из контракта промпта или confidence)"
        )

    # Consistency checks based on verdict
    if verdict == "PASS":
        if len(defects) > 0:
            return False, f"Противоречивый ответ: вердикт PASS содержит дефекты: {defects}"

        # All present scores must be >= 0.70 (corresponds to >= 3.8/5 on 1-5 scale)
        for s_name, norm_val in scores_found.items():
            if norm_val < 0.70:
                raw_val = review_res[s_name]
                return False, (
                    f"Противоречивый ответ: вердикт PASS при низкой оценке {s_name}={raw_val} "
                    f"(нормализовано: {norm_val:.2f}, требуется не менее 0.70)"
                )

        # Check negative sentiment markers in summary
        lower_summary = clean_summary.lower()
        negative_markers = (
            "не соответств",
            "грубые ошибки",
            "грубая ошибка",
            "противоречит исходник",
            "правила не соответств",
            "искажен",
        )
        for marker in negative_markers:
            if marker in lower_summary:
                return False, f"Противоречивый ответ: вердикт PASS, но в summary зафиксировано замечание ('{marker}')"

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


def _build_curriculum_groups(rule_model: DocumentRuleModel) -> list[CurriculumGroup]:
    """Builds resilient curriculum groups with unique stable IDs and multi-level transitive dependency closures.

    Guarantees:
    1. Zero rule leak: all rules from rule_model are allocated without omission (both count and set equality).
    2. Identical section names or auto-split chunk names never overwrite each other (stores in a list with unique IDs).
    3. Multi-level transitive dependency closure: Rule 3 -> Rule 2 -> Rule 1 brings all prerequisites into context.
    4. Boundary-safe rule matching: 'r1' never matches inside 'r10'.
    5. Natural clause/point reference resolution with ambiguous reference detection.
    """
    sanitized_rules, raw_to_rules = _sanitize_rules(rule_model.rules)

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

    for g in groups:
        primary_ids = {r.rule_id for r in g.primary_rules}
        visited_ids = set(primary_ids)
        queue = list(g.primary_rules)
        prereqs: list[RuleEntity] = []
        group_unresolved: list[str] = []

        while queue:
            curr_rule = queue.pop(0)
            direct_deps, direct_unresolved = _find_direct_rule_dependencies(
                curr_rule,
                all_rules=sanitized_rules,
                clause_index=clause_index,
                raw_to_rules=raw_to_rules,
                current_section=g.section,
            )
            for u in direct_unresolved:
                if u not in group_unresolved:
                    group_unresolved.append(u)

            for dep in direct_deps:
                if dep.rule_id not in visited_ids:
                    visited_ids.add(dep.rule_id)
                    prereqs.append(dep)
                    queue.append(dep)

        groups_with_dependencies.append(
            CurriculumGroup(
                group_id=g.group_id,
                display_title=g.display_title,
                section=g.section,
                primary_rules=g.primary_rules,
                context_prerequisite_rules=tuple(prereqs),
                unresolved_dependencies=tuple(group_unresolved),
            )
        )

    return groups_with_dependencies


async def generate_v3_course_from_corpus(
    corpus: DirectSourceCorpus,
    *,
    intent: CourseIntent,
    generation_client: Any,
    progress_callback: Callable[[str, int, int, str | None, int | None], Awaitable[None]] | None = None,
    cancellation_callback: Callable[[], Awaitable[None]] | None = None,
) -> GenerationArtifacts:
    """End-to-end generator integrating V3 Co-Generation with production direct-source corpus."""
    full_text, doc_sha = _extract_corpus_text(corpus)
    first_title = corpus.documents[0].title if corpus.documents else "Курс по регламенту"

    async def llm_invoker(messages: list[dict[str, str]], response_format: dict[str, Any] | None = None) -> dict[str, Any]:
        if cancellation_callback:
            await cancellation_callback()

        # ResilientLLMClient support
        if hasattr(generation_client, "ainvoke"):
            res = await generation_client.ainvoke(messages, response_format=response_format)
            raw_text = res.content if hasattr(res, "content") else str(res)
        elif callable(generation_client):
            raw_text = await generation_client(messages, response_format)
        else:
            raise TypeError(f"Unsupported generation_client type: {type(generation_client)}")

        if isinstance(raw_text, dict):
            return raw_text
        parsed: dict[str, Any] = json.loads(raw_text)
        return parsed

    pipeline = V3GenerationPipeline(llm_invoker)

    # Stage 1: Extract structured rule model
    if progress_callback:
        await progress_callback("realization", 1, 5, getattr(generation_client, "name", "llm"), 1)

    logger.info("V3 Engine: Step 1 - Extracting rule model for sha=%s", doc_sha[:12])
    first_doc = corpus.documents[0] if corpus.documents else None
    first_doc_id = first_doc.doc_id if first_doc else ""
    first_revision = first_doc.source_revision if first_doc else ""

    rule_model: DocumentRuleModel = await pipeline.extract_rule_model(
        document_title=first_title,
        document_text=full_text,
        document_sha256=doc_sha,
        doc_id=first_doc_id,
        source_revision=first_revision,
    )
    logger.info("V3 Engine: Step 1 complete. Extracted %d rules.", len(rule_model.rules))

    if cancellation_callback:
        await cancellation_callback()

    # Stage 2: Resilient curriculum grouping with unique group IDs and dependency closures
    curriculum_groups = _build_curriculum_groups(rule_model)
    total_lessons = len(curriculum_groups)

    generated_lessons: list[V3Lesson] = []
    semantic_reviews: dict[str, Any] = {}
    lessons_summary = ""

    # Stage 3: Co-generate each lesson paired with assessment cases
    semantic_violations: list[str] = []

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
        lesson = await pipeline.generate_lesson_with_scenarios(
            module_title=first_title,
            lesson_theme=group.display_title,
            rules=list(group.primary_rules),
            existing_lessons_summary=lessons_summary,
            prerequisite_rules=list(group.context_prerequisite_rules),
            audience=intent.audience,
            purpose=intent.purpose,
            emphasis=intent.emphasis,
        )
        generated_lessons.append(lesson)
        lessons_summary += f"\n- {lesson.title}: {lesson.content[:150]}..."

        # Stage 4: Run Two-Factor semantic review with verified source fragments
        try:
            review_rules = list(group.primary_rules) + list(group.context_prerequisite_rules)
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

            review_res = await pipeline.review_lesson(lesson, review_rules, source_fragments=source_frags)
            semantic_reviews[lesson.lesson_id] = review_res

            # Strict schema validation: check full response schema
            is_valid, schema_err = _validate_critic_response(review_res, lesson.lesson_id, lesson.title)
            if not is_valid:
                semantic_violations.append(schema_err)
            else:
                verdict = str(review_res.get("verdict", "")).strip().upper()
                defects = review_res.get("defects") or []
                if not isinstance(defects, list):
                    defects = [str(defects)]

                if verdict == "PASS":
                    pass  # Full validated PASS with confidence, rationale, and zero defects
                elif verdict == "FAIL":
                    if defects:
                        for defect in defects:
                            semantic_violations.append(
                                f"Семантический критик отклонил урок {lesson.lesson_id} ({lesson.title}): {defect}"
                            )
                    else:
                        semantic_violations.append(
                            f"Семантический критик отклонил урок {lesson.lesson_id} ({lesson.title}) с вердиктом FAIL (детали дефекта не предоставлены)"
                        )
                elif verdict == "NEEDS_REVISION":
                    if defects:
                        for defect in defects:
                            semantic_violations.append(
                                f"Семантический критик запросил доработку урока {lesson.lesson_id} ({lesson.title}): {defect}"
                            )
                    else:
                        semantic_violations.append(
                            f"Семантический критик запросил доработку урока {lesson.lesson_id} ({lesson.title}) с вердиктом NEEDS_REVISION"
                        )
        except Exception as review_err:
            logger.warning("V3 Engine: Two-factor semantic review skipped due to error: %s", review_err)
            semantic_reviews[lesson.lesson_id] = {"verdict": "ERROR", "error": str(review_err)}
            semantic_violations.append(
                f"Ошибка выполнения семантической проверки урока {lesson.lesson_id}: {review_err}"
            )

    unvalidated_course = V3Course(
        course_id=f"course-v3-{doc_sha[:12]}",
        title=first_title,
        document_sha256=doc_sha,
        lessons=tuple(generated_lessons),
        quality_verdict="needs_review",
    )

    report = validate_v3_course(unvalidated_course, full_text)
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

    artifacts = v3_course_to_generation_artifacts(
        course,
        source_document_ids=list(corpus.document_ids),
    )
    return artifacts
