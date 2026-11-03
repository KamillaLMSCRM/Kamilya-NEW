"""Adapter mapping V3 course and assessment contracts onto production GenerationArtifacts."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from app.modules.ai.architect_schema import CourseStructure, LearningObjective
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.canonical_citation import resolve_owned_citation
from app.modules.ai.v3.citation_review import bind_displayed_citation
from app.modules.ai.v3.models import RuleEntity, V3Course, V3Lesson
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.modules.methodologist_workbench.correction_proposal import MAX_SOURCE_CHARS


def _lesson_owned_source_references(
    lesson: V3Lesson, corpus: DirectSourceCorpus, rules: tuple[RuleEntity, ...], *, canonical_source: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """Resolve only unique, revision-bound rule quotes to their owned documents.

    Direct-source chunks are transient and are not durable chunk locators. This
    seam intentionally emits no chunk IDs, headings, or unverified offsets.
    """
    if not lesson.covered_rule_ids or len(set(lesson.covered_rule_ids)) != len(lesson.covered_rule_ids):
        return [], False
    if not canonical_source:
        for rule_id in lesson.covered_rule_ids:
            matched = [rule for rule in rules if rule.rule_id == rule_id]
            if len(matched) != 1:
                return [], False
            rule = matched[0]
            docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id]
            if (len(docs) != 1 or docs[0].source_revision != rule.source_revision
                    or not bind_displayed_citation(corpus, rule, rule.source_quote)):
                return [], False
        legacy_refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rule_id in lesson.covered_rule_ids:
            rule = next(rule for rule in rules if rule.rule_id == rule_id)
            if rule.doc_id not in seen:
                seen.add(rule.doc_id)
                legacy_refs.append({"doc_id": rule.doc_id})
        return legacy_refs, True
    raw_refs: list[tuple[str, str, str, str, int, int]] = []
    complete = True
    for rule_id in lesson.covered_rule_ids:
        matched = [rule for rule in rules if rule.rule_id == rule_id]
        if len(matched) != 1:
            complete = False
            continue
        rule = matched[0]
        docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id]
        resolved = resolve_owned_citation(corpus, rule, rule.source_quote)
        if len(docs) != 1 or resolved is None:
            complete = False
            continue
        source = docs[0].source_text or ""
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if not re.fullmatch(r"document:[0-9a-f]{64}", rule.source_revision):
            complete = False
            continue
        raw_refs.append((rule.doc_id, rule.source_revision, digest, source, resolved.start, resolved.end))
    merged: list[tuple[str, str, str, str, int, int]] = []
    for item in sorted(raw_refs, key=lambda value: (value[0], value[1], value[2], value[4], value[5])):
        if merged and item[:3] == merged[-1][:3] and item[4] <= merged[-1][5]:
            previous = merged[-1]
            merged[-1] = (*previous[:5], max(previous[5], item[5]))
        else:
            merged.append(item)
    if (len({item[0] for item in merged}) > 5 or len(merged) > 64
            or sum(item[5] - item[4] for item in merged) > MAX_SOURCE_CHARS):
        return [], False
    refs = [{
        "kind": "working_text_span_v1",
        "doc_id": doc_id,
        "source_revision": revision,
        "source_text_sha256": digest,
        "start": start,
        "end": end,
        "span_sha256": hashlib.sha256(source[start:end].encode("utf-8")).hexdigest(),
    } for doc_id, revision, digest, source, start, end in merged]
    return refs, complete


def v3_course_to_generation_artifacts(
    course: V3Course,
    *,
    source_document_ids: list[str] | None = None,
    source_corpus: DirectSourceCorpus | None = None,
    source_rules: tuple[RuleEntity, ...] | None = None,
    exact_narrative_facts: bool = False,
    canonical_source: bool = False,
) -> GenerationArtifacts:
    """Converts a high-fidelity V3Course into the production GenerationArtifacts contract.

    This ensures complete compatibility with the existing database persistence pipeline
    (_save_generation_to_db), saving Course, Module, Lesson, Quiz, Question, and QuizChoice.
    """
    doc_ids = list(source_document_ids or [])
    doc_refs = [{"doc_id": did} for did in doc_ids]

    grouped_lessons: dict[str, list[V3Lesson]] = defaultdict(list)
    for lesson in course.lessons:
        module_title = lesson.module_title or "Основной модуль"
        grouped_lessons[module_title].append(lesson)

    structure_modules: list[StructureModule] = []
    content_modules: list[ModuleContent] = []
    assessments: list[LessonAssessment] = []
    unresolved_provenance: list[str] = []

    for module_title, lessons in grouped_lessons.items():
        struct_lessons: list[StructureLesson] = []
        content_lessons: list[LessonContent] = []

        for lesson in lessons:
            if source_corpus is not None and source_rules is not None:
                lesson_refs, provenance_complete = _lesson_owned_source_references(
                    lesson, source_corpus, source_rules, canonical_source=canonical_source
                )
            else:
                lesson_refs, provenance_complete = doc_refs, True
            if ((source_corpus is None) != (source_rules is None)
                    or canonical_source and (source_corpus is None or source_rules is None)):
                lesson_refs, provenance_complete = [], False
            if exact_narrative_facts and not canonical_source:
                from app.modules.ai.v3.fact_provenance import exact_narrative_fact_references

                if source_corpus is None or source_rules is None or not provenance_complete:
                    lesson_refs, provenance_complete = [], False
                else:
                    primary = tuple(rule for rule in source_rules if rule.rule_id in lesson.covered_rule_ids)
                    facts = exact_narrative_fact_references(source_corpus, primary)
                    if facts is None:
                        from app.modules.ai.v3.working_text_reference import working_text_references

                        spans = working_text_references(source_corpus, primary)
                        if spans is None:
                            lesson_refs, provenance_complete = [], False
                        else:
                            lesson_refs = spans
                    else:
                        lesson_refs = facts
            if not provenance_complete:
                unresolved_provenance.append(lesson.lesson_id)
            lesson_doc_ids = (
                doc_ids if source_corpus is None and source_rules is None
                else list(dict.fromkeys(ref["doc_id"] for ref in lesson_refs))
            )
            # Structure
            struct_lessons.append(
                StructureLesson(
                    title=lesson.title,
                    description="",
                    objectives=[LearningObjective(text=f"Изучение правил: {', '.join(lesson.covered_rule_ids)}")],
                    source_doc_ids=lesson_doc_ids,
                )
            )

            # Content
            content_lessons.append(
                LessonContent(
                    title=lesson.title,
                    content=lesson.content,
                    source_references=lesson_refs,
                    source_validation_status="verified" if course.quality_verdict == "verified" and provenance_complete else "needs_review",
                )
            )

            # Assessment
            mcq_questions = project_lesson_questions(lesson)

            assessments.append(
                LessonAssessment(
                    lesson_title=lesson.title,
                    mcq=mcq_questions,
                    true_false=[],
                    matching=[],
                )
            )

        structure_modules.append(StructureModule(title=module_title, lessons=struct_lessons))
        content_modules.append(ModuleContent(title=module_title, lessons=content_lessons))

    structure = CourseStructure(
        title=course.title,
        description=f"Курс сгенерирован движком V3 на основе нормативного регламента (SHA256: {course.document_sha256[:16]}).",
        modules=structure_modules,
    )

    warnings: list[str] = []
    if course.validation_report and course.validation_report.get("violations"):
        warnings.extend(course.validation_report["violations"])
    if course.validation_report and course.validation_report.get("coverage_review_signals"):
        warnings.extend(course.validation_report["coverage_review_signals"])

    if unresolved_provenance:
        warnings.append("V3 lesson source provenance requires review")

    content = CourseContent(
        title=course.title,
        description=structure.description,
        modules=content_modules,
        source_warnings=warnings,
    )

    assessment = CourseAssessment(assessments=assessments)

    diagnostics: dict[str, Any] = {
        "generation_engine": "v3_cogen",
        "document_sha256": course.document_sha256,
        "lessons_count": len(course.lessons),
        "assessments_count": len(assessments),
        "quality_verdict": course.quality_verdict,
        "validation_report": course.validation_report,
        "violations": warnings,
        "requires_source_review": (course.quality_verdict != "verified" or bool(unresolved_provenance)),
    }
    if canonical_source or source_corpus is not None or source_rules is not None:
        diagnostics["unresolved_source_provenance_lesson_ids"] = unresolved_provenance

    return GenerationArtifacts(
        structure=structure,
        content=content,
        assessment=assessment,
        diagnostics=diagnostics,
    )
