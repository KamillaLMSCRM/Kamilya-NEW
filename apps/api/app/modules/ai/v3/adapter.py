"""Adapter mapping V3 course and assessment contracts onto production GenerationArtifacts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.modules.ai.architect_schema import CourseStructure, LearningObjective
from app.modules.ai.architect_schema import Lesson as StructureLesson
from app.modules.ai.architect_schema import Module as StructureModule
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.evidence_engine.application import GenerationArtifacts
from app.modules.ai.v3.models import V3Course, V3Lesson
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


def v3_course_to_generation_artifacts(
    course: V3Course,
    *,
    source_document_ids: list[str] | None = None,
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

    for module_title, lessons in grouped_lessons.items():
        struct_lessons: list[StructureLesson] = []
        content_lessons: list[LessonContent] = []

        for lesson in lessons:
            # Structure
            struct_lessons.append(
                StructureLesson(
                    title=lesson.title,
                    description="",
                    objectives=[LearningObjective(text=f"Изучение правил: {', '.join(lesson.covered_rule_ids)}")],
                    source_doc_ids=doc_ids,
                )
            )

            # Content
            content_lessons.append(
                LessonContent(
                    title=lesson.title,
                    content=lesson.content,
                    source_references=doc_refs,
                    source_validation_status="verified",
                )
            )

            # Assessment
            mcq_questions: list[MCQQuestion] = []
            if lesson.cases:
                for case_idx, case in enumerate(lesson.cases, 1):
                    for v_idx, variant in enumerate(case.variants, 1):
                        assembled = variant.assemble_question(seed=100 + case_idx * 10 + v_idx)
                        mcq_questions.append(
                            MCQQuestion(
                                question=assembled.full_rendered_stem,
                                options=[
                                    MCQOption(text=opt.text, is_correct=opt.is_correct)
                                    for opt in assembled.options
                                ],
                                explanation=assembled.explanation,
                                source_quote=assembled.source_quote,
                                pool_group=case.case_id,
                            )
                        )
            elif lesson.questions:
                for q in lesson.questions:
                    mcq_questions.append(
                        MCQQuestion(
                            question=q.full_rendered_stem,
                            options=[
                                MCQOption(text=opt.text, is_correct=opt.is_correct)
                                for opt in q.options
                            ],
                            explanation=q.explanation,
                            source_quote=q.source_quote,
                        )
                    )

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

    content = CourseContent(
        title=course.title,
        description=structure.description,
        modules=content_modules,
    )

    assessment = CourseAssessment(assessments=assessments)

    diagnostics: dict[str, Any] = {
        "generation_engine": "v3_cogen",
        "document_sha256": course.document_sha256,
        "lessons_count": len(course.lessons),
        "assessments_count": len(assessments),
        "quality_verdict": course.quality_verdict,
    }

    return GenerationArtifacts(
        structure=structure,
        content=content,
        assessment=assessment,
        diagnostics=diagnostics,
    )
