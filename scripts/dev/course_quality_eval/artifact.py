from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .domain import ArtifactIdentity, CourseArtifact, LessonArtifact, QuestionArtifact


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\u241f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:12]}"


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _lesson_source(lesson: dict[str, Any]) -> str:
    chunks = _strings(lesson.get("source_chunks"))
    if chunks:
        return "\n\n".join(chunks)
    source = lesson.get("source") or lesson.get("source_text") or ""
    return str(source).strip()


def _question_source(
    raw_question: dict[str, Any],
    *,
    facts: dict[str, str],
    lesson: LessonArtifact,
) -> str:
    if "evidence_fact_ids" in raw_question:
        raw_fact_ids = raw_question["evidence_fact_ids"]
        if not isinstance(raw_fact_ids, list):
            raise ValueError("Provider-backed question evidence_fact_ids must be an array")
        if any(not isinstance(fact_id, str) for fact_id in raw_fact_ids):
            raise ValueError(
                "Provider-backed question evidence_fact_ids must contain only strings"
            )
        fact_ids = tuple(dict.fromkeys(_strings(raw_fact_ids)))
        unknown_fact_ids = tuple(fact_id for fact_id in fact_ids if fact_id not in facts)
        if unknown_fact_ids:
            raise ValueError(
                "Provider-backed question contains unknown evidence_fact_ids: "
                + ", ".join(unknown_fact_ids)
            )
        if fact_ids:
            return "\n".join(facts[fact_id] for fact_id in fact_ids)

    fact_id = str(raw_question.get("fact_id", "")).strip()
    return facts.get(fact_id, lesson.source)


def _assessment_questions(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_lesson: dict[str, list[dict[str, Any]]] = {}
    assessments = payload.get("assessments", [])
    if not isinstance(assessments, list):
        return by_lesson
    for assessment in assessments:
        if not isinstance(assessment, dict):
            continue
        lesson_title = str(assessment.get("lesson_title", "")).strip()
        questions: list[dict[str, Any]] = []
        for key in ("mcq", "questions"):
            value = assessment.get(key, [])
            if isinstance(value, list):
                questions.extend(item for item in value if isinstance(item, dict))
        by_lesson.setdefault(lesson_title, []).extend(questions)
    return by_lesson


def _embedded_questions(lesson: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    direct = lesson.get("questions", [])
    if isinstance(direct, list):
        candidates.extend(item for item in direct if isinstance(item, dict))
    quiz = lesson.get("quiz")
    if isinstance(quiz, dict) and isinstance(quiz.get("questions"), list):
        candidates.extend(item for item in quiz["questions"] if isinstance(item, dict))
    return candidates


def _parse_question(
    raw: dict[str, Any],
    *,
    lesson: LessonArtifact,
    ordinal: int,
) -> QuestionArtifact:
    options_raw = raw.get("options", raw.get("choices", []))
    options: list[str] = []
    correct: list[int] = []
    if isinstance(options_raw, list):
        for index, option in enumerate(options_raw):
            if isinstance(option, dict):
                text = str(option.get("text", option.get("label", ""))).strip()
                is_correct = bool(option.get("is_correct", option.get("correct", False)))
            else:
                text = str(option).strip()
                is_correct = False
            if text:
                if is_correct:
                    correct.append(len(options))
                options.append(text)
    text = str(raw.get("question", raw.get("text", ""))).strip()
    source = str(raw.get("source_quote", raw.get("source", ""))).strip() or lesson.source
    return QuestionArtifact(
        id=_stable_id("question", lesson.id, ordinal, text),
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        text=text,
        options=tuple(options),
        correct_indexes=tuple(correct),
        explanation=str(raw.get("explanation", "")).strip(),
        source=source,
    )


def _load_provider_backed(
    *,
    payload: dict[str, Any],
    artifact_path: Path,
    artifact_sha256: str,
) -> CourseArtifact:
    evidence = payload.get("evidence_result")
    realized_course = payload.get("realized_course")
    realized_assessment = payload.get("realized_assessment")
    if not isinstance(evidence, dict) or not isinstance(realized_course, dict):
        raise ValueError("Malformed provider-backed course artifact")
    facts: dict[str, str] = {}
    for collection_name in ("admitted_facts", "supporting_facts"):
        collection = evidence.get(collection_name, [])
        if not isinstance(collection, list):
            continue
        for fact in collection:
            if not isinstance(fact, dict):
                continue
            fact_id = str(fact.get("fact_id", "")).strip()
            subject = str(fact.get("subject", "")).strip()
            attribute = str(fact.get("attribute", "")).strip()
            value = str(fact.get("value", "")).strip()
            if fact_id and value:
                context = [
                    f"Раздел: {subject}" if subject else "",
                    f"Атрибут: {attribute}" if attribute else "",
                    f"Факт: {value}",
                ]
                facts[fact_id] = "\n".join(part for part in context if part)
    lessons: list[LessonArtifact] = []
    lesson_by_id: dict[str, LessonArtifact] = {}
    raw_lessons = realized_course.get("lessons", [])
    if isinstance(raw_lessons, list):
        for index, raw_lesson in enumerate(raw_lessons):
            if not isinstance(raw_lesson, dict):
                continue
            raw_id = str(raw_lesson.get("lesson_id", "")).strip()
            title = str(raw_lesson.get("title", "Untitled lesson")).strip() or "Untitled lesson"
            fact_ids = [
                str(item)
                for key in ("fact_ids", "supporting_fact_ids")
                for item in (raw_lesson.get(key, []) if isinstance(raw_lesson.get(key), list) else [])
            ]
            lesson = LessonArtifact(
                id=raw_id or _stable_id("lesson", index, title),
                title=title,
                objectives=(str(raw_lesson.get("objective", "")).strip(),)
                if str(raw_lesson.get("objective", "")).strip()
                else (),
                content=str(raw_lesson.get("content", "")).strip(),
                source="\n".join(facts[fact_id] for fact_id in fact_ids if fact_id in facts),
            )
            lessons.append(lesson)
            lesson_by_id[lesson.id] = lesson
    questions: list[QuestionArtifact] = []
    raw_questions = (
        realized_assessment.get("questions", []) if isinstance(realized_assessment, dict) else []
    )
    if isinstance(raw_questions, list):
        for index, raw_question in enumerate(raw_questions):
            if not isinstance(raw_question, dict):
                continue
            question_lesson = lesson_by_id.get(str(raw_question.get("lesson_id", "")))
            if question_lesson is None:
                continue
            options = _strings(raw_question.get("options"))
            correct_answer = str(raw_question.get("correct_answer", "")).strip()
            correct_indexes = tuple(
                option_index for option_index, option in enumerate(options) if option == correct_answer
            )
            questions.append(
                QuestionArtifact(
                    id=str(raw_question.get("question_id", "")).strip()
                    or _stable_id("question", question_lesson.id, index),
                    lesson_id=question_lesson.id,
                    lesson_title=question_lesson.title,
                    text=str(raw_question.get("prompt", "")).strip(),
                    options=options,
                    correct_indexes=correct_indexes,
                    explanation=str(raw_question.get("explanation", "")).strip(),
                    source=_question_source(raw_question, facts=facts, lesson=question_lesson),
                )
            )
    if not lessons:
        raise ValueError("Provider-backed course artifact contains no lessons")
    plan = evidence.get("document_plan", {})
    source_sha = plan.get("source_sha256") if isinstance(plan, dict) else None
    return CourseArtifact(
        identity=ArtifactIdentity(
            path=str(artifact_path),
            sha256=artifact_sha256,
            source_sha256=str(source_sha) if source_sha else None,
            course_title=str(realized_course.get("title", "Untitled course")).strip()
            or "Untitled course",
        ),
        lessons=tuple(lessons),
        questions=tuple(questions),
        raw_path=artifact_path,
    )


def load_artifact(path: str | Path) -> CourseArtifact:
    artifact_path = Path(path).resolve()
    raw_bytes = artifact_path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Course artifact root must be a JSON object")
    artifact_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if "realized_course" in payload and "evidence_result" in payload:
        return _load_provider_backed(
            payload=payload,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
        )
    course = payload.get("course", payload)
    if not isinstance(course, dict):
        raise ValueError("Course artifact must contain a course object")
    title = str(course.get("title", "Untitled course")).strip() or "Untitled course"
    assessments = _assessment_questions(payload)
    lessons: list[LessonArtifact] = []
    questions: list[QuestionArtifact] = []
    modules = course.get("modules", [])
    if not isinstance(modules, list):
        raise ValueError("course.modules must be an array")
    for module_index, module in enumerate(modules):
        if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
            continue
        for lesson_index, raw_lesson in enumerate(module["lessons"]):
            if not isinstance(raw_lesson, dict):
                continue
            lesson_title = str(raw_lesson.get("title", "Untitled lesson")).strip() or "Untitled lesson"
            lesson = LessonArtifact(
                id=_stable_id("lesson", module_index, lesson_index, lesson_title),
                title=lesson_title,
                objectives=_strings(raw_lesson.get("objectives")),
                content=str(raw_lesson.get("content", "")).strip(),
                source=_lesson_source(raw_lesson),
            )
            lessons.append(lesson)
            raw_questions = [*_embedded_questions(raw_lesson), *assessments.get(lesson_title, [])]
            for question_index, raw_question in enumerate(raw_questions):
                questions.append(
                    _parse_question(raw_question, lesson=lesson, ordinal=question_index)
                )
    if not lessons:
        raise ValueError("Course artifact contains no lessons")
    source = payload.get("source", {})
    source_sha = source.get("sha256") if isinstance(source, dict) else None
    return CourseArtifact(
        identity=ArtifactIdentity(
            path=str(artifact_path),
            sha256=artifact_sha256,
            source_sha256=str(source_sha) if source_sha else None,
            course_title=title,
        ),
        lessons=tuple(lessons),
        questions=tuple(questions),
        raw_path=artifact_path,
    )
