"""Trusted integrations from persisted learning workflows into evidence."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.certificates.models import Certificate
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.quizzes.models import Quiz, QuizAttempt
from app.modules.training_evidence.form_settings import get_training_evidence_form_settings
from app.modules.training_evidence.models import TrainingEvidenceEvent
from app.modules.training_evidence.service import canonical_json_sha256 as evidence_payload_sha256
from app.modules.training_evidence.service import record_event


async def record_course_completion(
    db: AsyncSession,
    *,
    user: User,
    course: Course,
    enrollment: Enrollment,
    certificate: Certificate,
) -> TrainingEvidenceEvent:
    """Record a completion from server-side persisted state.

    The source key is stable for the enrollment, so a retry of the completion
    workflow is a read of the original evidence rather than a new record.
    Browser payloads and timestamps are deliberately not accepted here.
    """

    if course.tenant_id != user.tenant_id:
        raise ValueError("Course does not belong to the current tenant")
    if enrollment.tenant_id != user.tenant_id or enrollment.user_id != user.id or enrollment.course_id != course.id:
        raise ValueError("Course completion enrollment is inconsistent")
    if certificate.tenant_id != user.tenant_id or certificate.user_id != user.id or certificate.course_id != course.id:
        raise ValueError("Course completion certificate is inconsistent")

    release_id = enrollment.content_release_id or course.current_release_id
    if release_id is None:
        raise ValueError("Course completion requires an immutable ContentRelease")
    release = await db.scalar(
        select(ContentRelease).where(
            ContentRelease.id == release_id,
            ContentRelease.course_id == course.id,
            ContentRelease.tenant_id == user.tenant_id,
        )
    )
    if release is None:
        raise ValueError("Course completion release evidence is inconsistent")

    print_form_settings = await get_training_evidence_form_settings(db, cast(UUID, user.tenant_id))

    payload: dict[str, Any] = {
        "schema_version": 1,
        "source": "course_completion",
        "course_id": str(course.id),
        "enrollment_id": str(enrollment.id),
        "content_release_id": str(release.id) if release else None,
        "release_version": release.version,
        "content_release_sha256": release.snapshot_sha256,
        "certificate_id": str(certificate.id),
        "certificate_number": certificate.certificate_number,
        "status": "completed",
        "procedure": {
            "title": course.title,
            "version": str(release.version),
            "purpose": "course_completion",
        },
        "confirmation": {
            "statement": (
                f"Я подтверждаю, что завершил(а) курс „{course.title}“ "
                f"и ознакомился(лась) с материалами опубликованной версии {release.version}."
            ),
            "object_version": f"release:{release.version}",
        },
        "print_form": print_form_settings.to_print_form().model_dump(),
    }
    return await record_event(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        user_id=user.id,
        enrollment_id=enrollment.id,
        content_release_id=release.id if release else None,
        procedure_type="training",
        source_event_key=f"course-completion:{enrollment.id}",
        payload_snapshot=payload,
    )


async def record_quiz_submission(
    db: AsyncSession,
    *,
    user: User,
    attempt: QuizAttempt,
) -> TrainingEvidenceEvent:
    """Record one saved quiz attempt without creating an admission decision."""

    if attempt.user_id != user.id or attempt.tenant_id != user.tenant_id:
        raise ValueError("Quiz attempt does not belong to the current user")
    if attempt.enrollment_id is None or attempt.content_release_id is None:
        raise ValueError("Quiz attempt is missing enrollment or content release evidence")
    if not attempt.evidence_snapshot or not attempt.evidence_sha256:
        raise ValueError("Quiz attempt canonical evidence is missing")

    if canonical_json_sha256(attempt.evidence_snapshot) != attempt.evidence_sha256:
        raise ValueError("Quiz attempt canonical evidence hash is inconsistent")

    attempt_snapshot = attempt.evidence_snapshot.get("attempt")
    if not isinstance(attempt_snapshot, dict):
        raise ValueError("Quiz attempt canonical evidence is malformed")
    expected_snapshot_links = {
        "id": str(attempt.id),
        "tenant_id": str(user.tenant_id),
        "user_id": str(user.id),
        "enrollment_id": str(attempt.enrollment_id),
        "content_release_id": str(attempt.content_release_id),
    }
    if any(attempt_snapshot.get(key) != value for key, value in expected_snapshot_links.items()):
        raise ValueError("Quiz attempt canonical evidence links are inconsistent")

    release = await db.scalar(
        select(ContentRelease).where(
            ContentRelease.id == attempt.content_release_id,
            ContentRelease.tenant_id == user.tenant_id,
        )
    )
    if release is None:
        raise ValueError("Quiz attempt release evidence is inconsistent")
    if attempt_snapshot.get("content_release_sha256") != release.snapshot_sha256:
        raise ValueError("Quiz attempt release hash is inconsistent")

    quiz = await db.scalar(select(Quiz).where(Quiz.id == attempt.quiz_id, Quiz.tenant_id == user.tenant_id))
    if quiz is None:
        raise ValueError("Quiz attempt quiz is inconsistent")

    source_key = f"quiz-attempt:{attempt.id}"
    existing = await db.scalar(
        select(TrainingEvidenceEvent).where(
            TrainingEvidenceEvent.tenant_id == user.tenant_id,
            TrainingEvidenceEvent.source_event_key == source_key,
        )
    )
    if existing is not None:
        snapshot = existing.payload_snapshot
        binding = snapshot.get("attempt_evidence") if isinstance(snapshot, dict) else None
        if (
            existing.user_id != user.id
            or existing.enrollment_id != attempt.enrollment_id
            or existing.content_release_id != attempt.content_release_id
            or existing.procedure_type != "knowledge_check"
            or existing.record_type != "original"
            or not isinstance(binding, dict)
            or binding.get("attempt_id") != str(attempt.id)
            or binding.get("evidence_sha256") != attempt.evidence_sha256
            or snapshot.get("quiz_id") != str(attempt.quiz_id)
            or evidence_payload_sha256(snapshot) != existing.payload_sha256
        ):
            raise ValueError("Existing quiz attempt event is inconsistent")
        return existing

    form_settings = await get_training_evidence_form_settings(db, cast(UUID, user.tenant_id))

    payload = {
        "schema_version": 1,
        "source": "quiz_attempt",
        "attempt_evidence": {
            "attempt_id": str(attempt.id),
            "evidence_sha256": attempt.evidence_sha256,
        },
        "quiz_id": str(attempt.quiz_id),
        "course_id": attempt_snapshot.get("course_id"),
        "enrollment_id": str(attempt.enrollment_id),
        "content_release_id": str(attempt.content_release_id),
        "release_version": release.version,
        "content_release_sha256": release.snapshot_sha256,
        "score_percent": attempt.score_percent,
        "passed": bool(attempt.passed),
        "procedure": {
            "title": quiz.title,
            "version": str(release.version),
            "purpose": "knowledge_check",
        },
        "confirmation": {
            "statement": (
                f"Я подтверждаю, что прошел(ла) тест „{quiz.title}“ "
                f"по опубликованной версии {release.version}; зафиксированный результат "
                f"{attempt.score_percent}%, статус {'пройден' if attempt.passed else 'не пройден'}."
            ),
            "object_version": f"release:{release.version}",
        },
    }
    if form_settings.selected_fields is not None:
        payload["print_form"] = form_settings.to_print_form(for_quiz=True).model_dump()
    return await record_event(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        user_id=user.id,
        enrollment_id=attempt.enrollment_id,
        content_release_id=attempt.content_release_id,
        procedure_type="knowledge_check",
        source_event_key=source_key,
        payload_snapshot=payload,
    )
