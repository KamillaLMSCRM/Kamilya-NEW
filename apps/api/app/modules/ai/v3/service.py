"""Production service entry point for V3 Course & Assessment Co-Generation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
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
    """Concatenates chunk text across all documents in the corpus and computes SHA256."""
    text_parts: list[str] = []
    for doc in corpus.documents:
        text_parts.append(f"# ДОКУМЕНТ: {doc.title} ({doc.filename})\n")
        for chunk in doc.chunks:
            c = chunk.text.strip()
            if c:
                text_parts.append(c)

    full_text = "\n\n".join(text_parts)
    sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    return full_text, sha256


COMPOUND_CLAUSE_SECTION_RE = re.compile(
    r"(?:пункт[а-я]*|п\.|подпункт[а-я]*|пп\.)\s*([0-9]+(?:\.[0-9]+)*)\s+"
    r"(?:раздел[а-я]*|разд\.|глав[а-я]*|стать[а-я]*|ст\.|таблиц[а-я]*)\s*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)
REVERSED_COMPOUND_RE = re.compile(
    r"(?:раздел[а-я]*|разд\.|глав[а-я]*|стать[а-я]*|ст\.|таблиц[а-я]*)\s*([0-9]+(?:\.[0-9]+)*)\s*,?\s*"
    r"(?:пункт[а-я]*|п\.|подпункт[а-я]*|пп\.)\s*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)
CLAUSE_REF_RE = re.compile(
    r"(?:пункт[а-я]*|п\.|подпункт[а-я]*|пп\.|стать[а-я]*|ст\.|раздел[а-я]*|таблиц[а-я]*)\s*([0-9]+(?:\.[0-9]+)*)",
    re.IGNORECASE,
)


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

    for match in COMPOUND_CLAUSE_SECTION_RE.finditer(text):
        clause_clean = match.group(1).strip().rstrip(".")
        section_num = match.group(2).strip().rstrip(".")
        span = match.span()
        # Blank out this compound span so standalone matcher won't parse 2 and 4 separately
        remaining_text = remaining_text[:span[0]] + " " * (span[1] - span[0]) + remaining_text[span[1]:]

        candidates = [c for c in clause_index.get(clause_clean, []) if c.rule_id != rule.rule_id]
        matching = [
            c for c in candidates
            if section_num in _extract_clause_numbers(c.section) or re.search(r"\bраздел[а-я]*\s*" + re.escape(section_num) + r"\b", c.section, re.IGNORECASE)
        ]
        if len(matching) == 1:
            if matching[0] not in direct_deps:
                direct_deps.append(matching[0])
        elif len(matching) > 1:
            match_ids = [c.rule_id for c in matching]
            unresolved.append(
                f"Неоднозначная составная ссылка на пункт '{clause_clean}' раздела '{section_num}' в правиле '{rule.rule_id}' (найдено несколько совпадений: {', '.join(match_ids)})"
            )
            for c in matching:
                if c not in direct_deps:
                    direct_deps.append(c)
        else:
            unresolved.append(
                f"Неразрешенная составная ссылка на пункт '{clause_clean}' раздела '{section_num}' в правиле '{rule.rule_id}'"
            )

    for match in REVERSED_COMPOUND_RE.finditer(remaining_text):
        section_num = match.group(1).strip().rstrip(".")
        clause_clean = match.group(2).strip().rstrip(".")
        span = match.span()
        remaining_text = remaining_text[:span[0]] + " " * (span[1] - span[0]) + remaining_text[span[1]:]

        candidates = [c for c in clause_index.get(clause_clean, []) if c.rule_id != rule.rule_id]
        matching = [
            c for c in candidates
            if section_num in _extract_clause_numbers(c.section) or re.search(r"\bраздел[а-я]*\s*" + re.escape(section_num) + r"\b", c.section, re.IGNORECASE)
        ]
        if len(matching) == 1:
            if matching[0] not in direct_deps:
                direct_deps.append(matching[0])
        elif len(matching) > 1:
            match_ids = [c.rule_id for c in matching]
            unresolved.append(
                f"Неоднозначная составная ссылка на пункт '{clause_clean}' раздела '{section_num}' в правиле '{rule.rule_id}' (найдено несколько совпадений: {', '.join(match_ids)})"
            )
            for c in matching:
                if c not in direct_deps:
                    direct_deps.append(c)
        else:
            unresolved.append(
                f"Неразрешенная составная ссылка на пункт '{clause_clean}' раздела '{section_num}' в правиле '{rule.rule_id}'"
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
    rule_model: DocumentRuleModel = await pipeline.extract_rule_model(
        document_title=first_title,
        document_text=full_text,
        document_sha256=doc_sha,
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
            norm_source = normalize_text_for_search(full_text)
            source_frags: list[str] = []
            for r in review_rules:
                raw_q = (r.source_quote or "").strip()
                if raw_q:
                    norm_q = normalize_text_for_search(raw_q)
                    if norm_q and norm_q in norm_source:
                        source_frags.append(f"[Верифицированная цитата оригинала | {r.rule_id}]: {raw_q}")
                    else:
                        semantic_violations.append(
                            f"Неподтвержденная цитата в правиле {r.rule_id} ({r.title}): фрагмент карты правил отсутствует в исходном тексте документа"
                        )
                        source_frags.append(f"[НЕВЕРИФИЦИРОВАНО, отсутствует в тексте оригинала | {r.rule_id}]: {raw_q}")

            review_res = await pipeline.review_lesson(lesson, review_rules, source_fragments=source_frags)
            semantic_reviews[lesson.lesson_id] = review_res

            # Strict schema validation: any verdict other than valid confirmed PASS is recorded as violation
            if not isinstance(review_res, dict):
                semantic_violations.append(
                    f"Критик вернул невалидный формат ответа для урока {lesson.lesson_id} ({lesson.title}): {type(review_res).__name__}"
                )
            else:
                verdict = str(review_res.get("verdict", "")).strip().upper()
                defects = review_res.get("defects") or []
                if not isinstance(defects, list):
                    defects = [str(defects)]

                if verdict == "PASS":
                    if defects:
                        for defect in defects:
                            semantic_violations.append(
                                f"Замечание критика к уроку {lesson.lesson_id} ({lesson.title}): {defect}"
                            )
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
                elif verdict == "UNKNOWN" or not verdict:
                    comment = review_res.get("comment") or review_res.get("reason") or "ответ не содержит подтверждения соответствия"
                    semantic_violations.append(
                        f"Семантический критик вернул неопределенный вердикт (UNKNOWN) для урока {lesson.lesson_id} ({lesson.title}): {comment}"
                    )
                else:
                    semantic_violations.append(
                        f"Семантический критик вернул неизвестный статус '{verdict}' для урока {lesson.lesson_id} ({lesson.title})"
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
