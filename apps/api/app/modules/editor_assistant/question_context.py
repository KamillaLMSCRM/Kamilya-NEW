"""Read-only trusted context resolution for one editor-assistant question.

This module is an application seam, not an HTTP endpoint. Authentication and
role authorization happen before it is called; the closed role input is still
validated defensively. Resolution never mutates durable state and never calls
an AI provider.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.modules.ai.source_analysis import dominant_language
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_FACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_READY_INDEX_STATUSES = frozenset({"ready", "partial"})
_MAX_LINKED_SOURCES = 8
_MAX_SOURCE_FACTS = 8
_MAX_SOURCE_TEXT = 1_200


class AuthorizedEditorRole(StrEnum):
    SUPERADMIN = "superadmin"
    METHODOLOGIST = "methodologist"


class QuestionContextFailureCode(StrEnum):
    CONTEXT_UNAVAILABLE = "question_context_unavailable"
    REQUIRES_NEW_DRAFT_REVISION = "requires_new_draft_revision"
    NOT_APPLICABLE = "not_applicable"
    MALFORMED_QUESTION = "malformed_question"
    SOURCE_EVIDENCE_UNAVAILABLE = "source_evidence_unavailable"


_FAILURE_MESSAGES: dict[QuestionContextFailureCode, str] = {
    QuestionContextFailureCode.CONTEXT_UNAVAILABLE: "Контекст вопроса недоступен.",
    QuestionContextFailureCode.REQUIRES_NEW_DRAFT_REVISION: (
        "Для опубликованного курса требуется новая черновая версия."
    ),
    QuestionContextFailureCode.NOT_APPLICABLE: (
        "Этот тип вопроса пока не поддерживается."
    ),
    QuestionContextFailureCode.MALFORMED_QUESTION: "Вопрос составлен некорректно.",
    QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE: (
        "Для вопроса недоступны подтверждающие материалы."
    ),
}


class QuestionContextError(ValueError):
    """Safe non-reflecting context-resolution failure."""

    def __init__(self, code: QuestionContextFailureCode) -> None:
        self.code = code
        super().__init__(_FAILURE_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class QuestionChoiceContext:
    choice_id: UUID
    text: str
    is_correct: bool
    order_index: int


@dataclass(frozen=True, slots=True)
class QuestionSourceReference:
    source_id: UUID
    document_title: str
    locator: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class QuestionSourceFact:
    fact_id: str
    source_id: UUID
    text: str
    locator: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ResolvedQuestionContext:
    tenant_id: UUID
    course_id: UUID
    module_id: UUID
    lesson_id: UUID
    quiz_id: UUID
    question_id: UUID
    question_type: str
    question_text: str
    choices: tuple[QuestionChoiceContext, ...]
    correct_choice_id: UUID
    explanation: str | None
    locale: str
    source_references: tuple[QuestionSourceReference, ...]
    source_facts: tuple[QuestionSourceFact, ...]
    snapshot_fingerprint: str


_SOURCE_FACTS_QUERY = text(
    """
    WITH ranked_facts AS (
        SELECT
            document_embeddings.id::text AS fact_id,
            document_embeddings.doc_id AS source_id,
            document_embeddings.text AS source_text,
            document_embeddings.headings AS headings,
            document_embeddings.chunk_index AS chunk_index,
            document_embeddings.embedding_content_sha256 AS content_sha256,
            ROW_NUMBER() OVER (
                PARTITION BY document_embeddings.doc_id
                ORDER BY document_embeddings.chunk_index ASC, document_embeddings.id ASC
            ) AS source_rank
        FROM document_embeddings
        JOIN documents AS active_document
          ON active_document.id::text = document_embeddings.doc_id
         AND active_document.tenant_id = document_embeddings.tenant_id
        WHERE document_embeddings.tenant_id = CAST(:tenant_id AS uuid)
          AND document_embeddings.doc_id = ANY(CAST(:document_ids AS text[]))
          AND document_embeddings.embedding_provenance_state = 'verified'
          AND document_embeddings.embedding_source_revision =
              'document:' || active_document.content_sha256
          AND document_embeddings.embedding_content_sha256 = active_document.content_sha256
          AND active_document.lifecycle_status = 'active'
          AND active_document.embedding_status = 'success'
          AND active_document.index_status IN ('ready', 'partial')
          AND active_document.content_sha256 IS NOT NULL
          AND (
              (
                  document_embeddings.embedding_index_revision_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM embedding_active_revisions AS active_index
                      WHERE active_index.tenant_id = document_embeddings.tenant_id
                        AND active_index.document_id = document_embeddings.doc_id
                  )
              )
              OR document_embeddings.embedding_index_revision_id = (
                  SELECT active_index.active_revision_id
                  FROM embedding_active_revisions AS active_index
                  WHERE active_index.tenant_id = document_embeddings.tenant_id
                    AND active_index.document_id = document_embeddings.doc_id
              )
          )
    )
    SELECT fact_id, source_id, source_text, headings, chunk_index, content_sha256
    FROM ranked_facts
    WHERE source_rank = 1
    ORDER BY source_id ASC, chunk_index ASC, fact_id ASC
    LIMIT 8
    """
)


def _error(code: QuestionContextFailureCode) -> QuestionContextError:
    return QuestionContextError(code)


def _bounded_text(value: object, *, maximum: int, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _error(QuestionContextFailureCode.MALFORMED_QUESTION)
    return value


def _source_text(value: object) -> str:
    if not isinstance(value, str):
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > _MAX_SOURCE_TEXT:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    return normalized


def _safe_document_title(value: object) -> str:
    if not isinstance(value, str):
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 240:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    return normalized


def _source_locator(headings: object, chunk_index: object) -> str:
    if isinstance(headings, list):
        normalized = [
            " ".join(item.split())
            for item in headings
            if isinstance(item, str) and item.strip()
        ]
        if normalized:
            locator = " / ".join(normalized[:3])
            if len(locator) <= 240:
                return locator
    if isinstance(chunk_index, int) and not isinstance(chunk_index, bool) and chunk_index >= 0:
        return f"chunk:{chunk_index + 1}"
    raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)


def _linked_document_ids(course: Course, lesson: Lesson) -> tuple[UUID, ...]:
    values: list[object] = []
    for source_values in (course.source_document_ids, lesson.source_document_ids):
        if not isinstance(source_values, list):
            raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
        values.extend(source_values)
    unique_input_values = {str(value) for value in values}
    if len(unique_input_values) > _MAX_LINKED_SOURCES:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    parsed: set[UUID] = set()
    for value in values:
        if not isinstance(value, str | UUID):
            continue
        try:
            parsed.add(value if isinstance(value, UUID) else UUID(value))
        except (TypeError, ValueError, AttributeError):
            continue
    if not parsed:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    return tuple(sorted(parsed, key=str))


def _locale(question_text: str, choices: tuple[QuestionChoiceContext, ...]) -> str:
    sample = " ".join((question_text, *(choice.text for choice in choices)))
    detected = dominant_language(sample)
    if detected in {"ru", "kk"}:
        return detected
    if detected == "latin":
        return "en"
    return "unknown"


def _fingerprint_payload(
    *,
    tenant_id: UUID,
    course_id: UUID,
    module_id: UUID,
    lesson_id: UUID,
    quiz_id: UUID,
    question_id: UUID,
    question_text: str,
    choices: tuple[QuestionChoiceContext, ...],
    explanation: str | None,
    locale: str,
    source_references: tuple[QuestionSourceReference, ...],
    source_facts: tuple[QuestionSourceFact, ...],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tenant_id": str(tenant_id),
        "course_id": str(course_id),
        "module_id": str(module_id),
        "lesson_id": str(lesson_id),
        "quiz_id": str(quiz_id),
        "question_id": str(question_id),
        "question_type": "MCQ",
        "question_text": question_text,
        "choices": [
            {
                "choice_id": str(choice.choice_id),
                "text": choice.text,
                "is_correct": choice.is_correct,
                "order_index": choice.order_index,
            }
            for choice in choices
        ],
        "explanation": explanation,
        "locale": locale,
        "source_references": [
            {
                "source_id": str(reference.source_id),
                "document_title": reference.document_title,
                "locator": reference.locator,
                "content_sha256": reference.content_sha256,
            }
            for reference in source_references
        ],
        "source_facts": [
            {
                "fact_id": fact.fact_id,
                "source_id": str(fact.source_id),
                "text": fact.text,
                "locator": fact.locator,
                "content_sha256": fact.content_sha256,
            }
            for fact in source_facts
        ],
    }


async def resolve_question_context(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    authorized_role: AuthorizedEditorRole | str,
    quiz_id: UUID,
    question_id: UUID,
) -> ResolvedQuestionContext:
    """Resolve one immutable, source-grounded draft question context."""

    try:
        role = AuthorizedEditorRole(authorized_role)
    except (TypeError, ValueError):
        raise _error(QuestionContextFailureCode.CONTEXT_UNAVAILABLE) from None
    if role not in {AuthorizedEditorRole.SUPERADMIN, AuthorizedEditorRole.METHODOLOGIST} or not all(
        isinstance(value, UUID) for value in (tenant_id, quiz_id, question_id)
    ):
        raise _error(QuestionContextFailureCode.CONTEXT_UNAVAILABLE)

    graph_result = await db.execute(
        select(Quiz, Question, Lesson, Module, Course)
        .join(Question, Question.quiz_id == Quiz.id)
        .join(Lesson, Lesson.id == Quiz.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Quiz.id == quiz_id,
            Question.id == question_id,
            Quiz.tenant_id == tenant_id,
            Lesson.tenant_id == tenant_id,
            Module.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
        )
    )
    graph = graph_result.first()
    if graph is None or len(graph) != 5:
        raise _error(QuestionContextFailureCode.CONTEXT_UNAVAILABLE)
    quiz, question, lesson, module, course = graph
    if not (
        quiz.id == quiz_id
        and question.id == question_id
        and question.quiz_id == quiz.id
        and quiz.lesson_id == lesson.id
        and lesson.module_id == module.id
        and module.course_id == course.id
        and quiz.tenant_id == tenant_id
        and lesson.tenant_id == tenant_id
        and module.tenant_id == tenant_id
        and course.tenant_id == tenant_id
    ):
        raise _error(QuestionContextFailureCode.CONTEXT_UNAVAILABLE)

    if course.status != "draft":
        raise _error(QuestionContextFailureCode.REQUIRES_NEW_DRAFT_REVISION)
    if not isinstance(question.type, str) or question.type.strip().upper() != "MCQ":
        raise _error(QuestionContextFailureCode.NOT_APPLICABLE)

    question_text = _bounded_text(question.text, maximum=4_000)
    explanation = _bounded_text(question.explanation, maximum=6_000, allow_none=True)
    assert isinstance(question_text, str)

    choice_rows = (
        (
            await db.execute(
                select(QuizChoice)
                .where(QuizChoice.question_id == question_id)
                .order_by(QuizChoice.order_index, QuizChoice.id)
            )
        )
        .scalars()
        .all()
    )
    if not 2 <= len(choice_rows) <= 20:
        raise _error(QuestionContextFailureCode.MALFORMED_QUESTION)
    choices: list[QuestionChoiceContext] = []
    seen_choice_ids: set[UUID] = set()
    seen_order_indices: set[int] = set()
    for row in choice_rows:
        if (
            row.question_id != question_id
            or not isinstance(row.id, UUID)
            or row.id in seen_choice_ids
            or not isinstance(row.order_index, int)
            or isinstance(row.order_index, bool)
            or row.order_index < 0
            or row.order_index in seen_order_indices
            or not isinstance(row.is_correct, bool)
        ):
            raise _error(QuestionContextFailureCode.MALFORMED_QUESTION)
        choice_text = _bounded_text(row.text, maximum=1_000)
        assert isinstance(choice_text, str)
        choices.append(
            QuestionChoiceContext(
                choice_id=row.id,
                text=choice_text,
                is_correct=row.is_correct,
                order_index=row.order_index,
            )
        )
        seen_choice_ids.add(row.id)
        seen_order_indices.add(row.order_index)
    choice_projection = tuple(choices)
    correct_choices = tuple(choice for choice in choice_projection if choice.is_correct)
    if len(correct_choices) != 1:
        raise _error(QuestionContextFailureCode.MALFORMED_QUESTION)

    linked_ids = _linked_document_ids(course, lesson)
    document_rows = (
        (
            await db.execute(
                select(Document)
                .where(
                    Document.id.in_(linked_ids),
                    Document.tenant_id == tenant_id,
                    Document.lifecycle_status == "active",
                    Document.embedding_status == "success",
                    Document.index_status.in_(_READY_INDEX_STATUSES),
                    Document.content_sha256.is_not(None),
                )
                .order_by(Document.id)
            )
        )
        .scalars()
        .all()
    )
    documents_by_id: dict[UUID, Document] = {}
    for document in document_rows:
        if (
            document.id not in linked_ids
            or document.tenant_id != tenant_id
            or document.lifecycle_status != "active"
            or document.embedding_status != "success"
            or document.index_status not in _READY_INDEX_STATUSES
            or not isinstance(document.content_sha256, str)
            or not _SHA256.fullmatch(document.content_sha256)
        ):
            continue
        documents_by_id[document.id] = document
    if not documents_by_id:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    confirmed_document_ids = tuple(sorted(documents_by_id, key=str))

    fact_result = await db.execute(
        _SOURCE_FACTS_QUERY,
        {
            "tenant_id": str(tenant_id),
            "document_ids": [str(document_id) for document_id in confirmed_document_ids],
        },
    )
    fact_rows = fact_result.mappings().all()
    if not fact_rows or len(fact_rows) > _MAX_SOURCE_FACTS:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    source_facts: list[QuestionSourceFact] = []
    seen_fact_ids: set[str] = set()
    seen_fact_sources: set[UUID] = set()
    for fact_row in fact_rows:
        try:
            source_id = UUID(str(fact_row["source_id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        fact_document = documents_by_id.get(source_id)
        fact_id = fact_row.get("fact_id")
        content_sha256 = fact_row.get("content_sha256")
        if (
            fact_document is None
            or not isinstance(fact_id, str)
            or not _OPAQUE_FACT_ID.fullmatch(fact_id)
            or fact_id in seen_fact_ids
            or source_id in seen_fact_sources
            or content_sha256 != fact_document.content_sha256
        ):
            continue
        try:
            locator = _source_locator(
                fact_row.get("headings"), fact_row.get("chunk_index")
            )
            bounded_source_text = _source_text(fact_row.get("source_text"))
        except QuestionContextError:
            continue
        source_facts.append(
            QuestionSourceFact(
                fact_id=fact_id,
                source_id=source_id,
                text=bounded_source_text,
                locator=locator,
                content_sha256=cast(str, fact_document.content_sha256),
            )
        )
        seen_fact_ids.add(fact_id)
        seen_fact_sources.add(source_id)
    if not source_facts:
        raise _error(QuestionContextFailureCode.SOURCE_EVIDENCE_UNAVAILABLE)
    facts = tuple(sorted(source_facts, key=lambda fact: (str(fact.source_id), fact.fact_id)))
    facts_by_source = {fact.source_id: fact for fact in facts}
    references = tuple(
        QuestionSourceReference(
            source_id=document_id,
            document_title=_safe_document_title(documents_by_id[document_id].title),
            locator=facts_by_source[document_id].locator,
            content_sha256=cast(str, documents_by_id[document_id].content_sha256),
        )
        for document_id in tuple(sorted(seen_fact_sources, key=str))
    )
    locale = _locale(question_text, choice_projection)
    payload = _fingerprint_payload(
        tenant_id=tenant_id,
        course_id=course.id,
        module_id=module.id,
        lesson_id=lesson.id,
        quiz_id=quiz.id,
        question_id=question.id,
        question_text=question_text,
        choices=choice_projection,
        explanation=explanation,
        locale=locale,
        source_references=references,
        source_facts=facts,
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ResolvedQuestionContext(
        tenant_id=tenant_id,
        course_id=course.id,
        module_id=module.id,
        lesson_id=lesson.id,
        quiz_id=quiz.id,
        question_id=question.id,
        question_type="MCQ",
        question_text=question_text,
        choices=choice_projection,
        correct_choice_id=correct_choices[0].choice_id,
        explanation=explanation,
        locale=locale,
        source_references=references,
        source_facts=facts,
        snapshot_fingerprint=fingerprint,
    )


__all__ = [
    "AuthorizedEditorRole",
    "QuestionChoiceContext",
    "QuestionContextError",
    "QuestionContextFailureCode",
    "QuestionSourceFact",
    "QuestionSourceReference",
    "ResolvedQuestionContext",
    "resolve_question_context",
]
