"""Tenant-scoped assembly of immutable training-evidence packages."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.courses.models import Course
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.evidence_export import (
    AssignmentEvidence,
    AttemptEvidence,
    ConfirmationEvidence,
    CorrectionEvidence,
    CourseEvidence,
    DecisionEvidence,
    EmployeeEvidence,
    GroupEvidenceInput,
    IndividualEvidenceInput,
    ProcedureEvidence,
    TenantEvidence,
)
from app.modules.evidence_export.schemas import CommissionEvidence
from app.modules.positions.models import Position
from app.modules.quizzes.models import Quiz, QuizAttempt
from app.modules.training_evidence.export_schemas import (
    EvidenceState,
    LegalHoldEvidence,
    ServerGroupEvidenceInput,
    ServerGroupRecordEvidence,
    ServerIndividualEvidenceInput,
)
from app.modules.training_evidence.models import (
    TrainingEvidenceEvent,
    TrainingEvidenceLegalHold,
    TrainingEvidenceStepUpConfirmation,
)

_ATTEMPT_PROCEDURES = {"knowledge_check", "internal_attestation", "admission_decision"}


def _incomplete(event_id: UUID, missing: list[str], *, message: str | None = None) -> None:
    missing = sorted(set(missing))
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "evidence_incomplete",
            "event_id": str(event_id),
            "missing": missing,
            "message": message or "Полный доказательственный пакет не может быть сформирован.",
        },
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _event_order(event: TrainingEvidenceEvent) -> tuple[datetime, datetime, str]:
    minimum = datetime.min.replace(tzinfo=UTC)
    return event.occurred_at or minimum, event.created_at or minimum, str(event.id)


def _evidence_state_timestamp(
    chain: list[TrainingEvidenceEvent],
    confirmations: list[TrainingEvidenceStepUpConfirmation],
    holds: list[TrainingEvidenceLegalHold],
) -> datetime:
    """Return a stable timestamp for the exported evidence state.

    The package describes immutable database facts, so repeated downloads of
    the same state must produce identical bytes and hashes. A later correction,
    confirmation, revocation or legal-hold transition advances this timestamp
    and therefore creates a new deterministic package.
    """

    timestamps = [
        *(item.occurred_at or item.created_at for item in chain),
        *(item.confirmed_at for item in confirmations),
        *(item.occurred_at or item.created_at for item in holds),
    ]
    return max(item for item in timestamps if item is not None)


async def _load_event_chain(
    db: AsyncSession, tenant_id: UUID, event_id: UUID
) -> tuple[TrainingEvidenceEvent, list[TrainingEvidenceEvent]]:
    current = await db.scalar(
        select(TrainingEvidenceEvent).where(
            TrainingEvidenceEvent.id == event_id,
            TrainingEvidenceEvent.tenant_id == tenant_id,
        )
    )
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence event not found")

    ancestors: list[TrainingEvidenceEvent] = [current]
    seen = {current.id}
    while current.related_event_id is not None:
        if current.related_event_id in seen:
            _incomplete(event_id, ["valid_event_chain"], message="Evidence event chain contains a cycle.")
        parent = await db.scalar(
            select(TrainingEvidenceEvent).where(
                TrainingEvidenceEvent.id == current.related_event_id,
                TrainingEvidenceEvent.tenant_id == tenant_id,
            )
        )
        if parent is None:
            _incomplete(event_id, ["parent_event"], message="A related evidence event is unavailable.")
        ancestors.append(parent)
        seen.add(parent.id)
        current = parent
        if len(ancestors) > 200:
            _incomplete(event_id, ["valid_event_chain"], message="Evidence event chain is too long.")

    root = current
    if root.record_type != "original":
        _incomplete(event_id, ["original_event"], message="The evidence chain has no original event.")

    chain = list(reversed(ancestors))
    frontier = [root.id]
    while frontier:
        children = list(
            (
                await db.scalars(
                    select(TrainingEvidenceEvent).where(
                        TrainingEvidenceEvent.tenant_id == tenant_id,
                        TrainingEvidenceEvent.related_event_id.in_(frontier),
                    )
                )
            ).all()
        )
        frontier = []
        for child in children:
            if child.id not in seen:
                seen.add(child.id)
                chain.append(child)
                frontier.append(child.id)
        if len(chain) > 200:
            _incomplete(event_id, ["valid_event_chain"], message="Evidence event chain is too long.")

    chain.sort(key=_event_order)
    expected = (root.user_id, root.enrollment_id, root.content_release_id, root.procedure_type)
    for item in chain:
        if (item.user_id, item.enrollment_id, item.content_release_id, item.procedure_type) != expected:
            _incomplete(event_id, ["consistent_event_chain"], message="Evidence event chain contains inconsistent links.")
    return root, chain


async def _load_tenant_context(
    db: AsyncSession,
    tenant_id: UUID,
    root: TrainingEvidenceEvent,
    event_id: UUID,
) -> tuple[Tenant, User, Enrollment, ContentRelease, Course, Position | None, str | None]:
    missing: list[str] = []
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    user = await db.scalar(select(User).where(User.id == root.user_id, User.tenant_id == tenant_id))
    if tenant is None:
        missing.append("tenant")
    if user is None:
        missing.append("employee")
    if root.enrollment_id is None:
        missing.append("enrollment")
        _incomplete(event_id, missing)
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.id == root.enrollment_id,
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id == root.user_id,
        )
    )
    if enrollment is None:
        missing.append("enrollment")
        _incomplete(event_id, missing)
    if enrollment.content_release_id is None:
        _incomplete(event_id, ["enrollment_content_release"])

    if root.content_release_id is not None and enrollment.content_release_id not in (None, root.content_release_id):
        _incomplete(event_id, ["consistent_content_release"], message="Event and enrollment point to different releases.")
    release_id = root.content_release_id or enrollment.content_release_id
    if release_id is None:
        missing.append("content_release")
        _incomplete(event_id, missing)
    release = await db.scalar(
        select(ContentRelease).where(
            ContentRelease.id == release_id,
            ContentRelease.tenant_id == tenant_id,
        )
    )
    if release is None:
        missing.append("content_release")
        _incomplete(event_id, missing)
    if enrollment.course_id != release.course_id:
        _incomplete(event_id, ["consistent_course"], message="Enrollment and release point to different courses.")
    if canonical_json_sha256(release.snapshot) != release.snapshot_sha256:
        _incomplete(event_id, ["valid_content_release_hash"], message="Published release evidence hash is invalid.")

    course = await db.scalar(
        select(Course).where(Course.id == release.course_id, Course.tenant_id == tenant_id)
    )
    if course is None:
        missing.append("course")
        _incomplete(event_id, missing)

    position = None
    department_name = None
    if user.position_id is not None:
        position = await db.scalar(
            select(Position).where(Position.id == user.position_id, Position.tenant_id == tenant_id)
        )
        if position is not None:
            department_name = position.department
            if position.department_id is not None:
                department = await db.scalar(
                    select(Department).where(
                        Department.id == position.department_id,
                        Department.tenant_id == tenant_id,
                    )
                )
                if department is not None:
                    department_name = department.name
    return tenant, user, enrollment, release, course, position, department_name


async def _load_attempts(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    enrollment: Enrollment,
    release: ContentRelease,
    event_id: UUID,
    required: bool,
) -> list[AttemptEvidence]:
    rows = list(
        (
            await db.scalars(
                select(QuizAttempt)
                .where(
                    QuizAttempt.tenant_id == tenant_id,
                    QuizAttempt.user_id == user_id,
                    QuizAttempt.enrollment_id == enrollment.id,
                    QuizAttempt.content_release_id == release.id,
                )
                .order_by(QuizAttempt.started_at, QuizAttempt.id)
            )
        ).all()
    )
    if required and not rows:
        _incomplete(event_id, ["completed_quiz_attempt"])

    quiz_ids = {row.quiz_id for row in rows}
    quizzes = {
        quiz.id: quiz
        for quiz in (
            await db.scalars(
                select(Quiz).where(Quiz.id.in_(quiz_ids), Quiz.tenant_id == tenant_id)
            )
        ).all()
    } if quiz_ids else {}
    attempts: list[AttemptEvidence] = []
    invalid: list[str] = []
    for row in rows:
        snapshot = row.evidence_snapshot
        if not isinstance(snapshot, Mapping) or not row.evidence_sha256:
            invalid.append(f"attempt:{row.id}:evidence_snapshot")
            continue
        if canonical_json_sha256(dict(snapshot)) != row.evidence_sha256:
            invalid.append(f"attempt:{row.id}:evidence_hash")
            continue
        snapshot_attempt = _as_mapping(snapshot.get("attempt"))
        graded_answers = snapshot.get("graded_answers")
        if not isinstance(graded_answers, list):
            invalid.append(f"attempt:{row.id}:graded_answers")
            continue
        expected_links = {
            "id": str(row.id),
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "enrollment_id": str(enrollment.id),
            "content_release_id": str(release.id),
            "quiz_id": str(row.quiz_id),
        }
        if any(snapshot_attempt.get(key) != value for key, value in expected_links.items()):
            invalid.append(f"attempt:{row.id}:links")
            continue
        quiz = quizzes.get(row.quiz_id)
        if quiz is None:
            invalid.append(f"attempt:{row.id}:quiz")
            continue
        quiz_snapshot = _as_mapping(snapshot.get("quiz"))
        threshold = quiz_snapshot.get("pass_score", quiz.pass_score)
        attempts.append(
            AttemptEvidence(
                id=str(row.id),
                quiz_id=str(row.quiz_id),
                started_at=row.started_at,
                completed_at=row.completed_at,
                time_spent_seconds=row.time_spent_seconds,
                threshold_percent=threshold,
                score_percent=row.score_percent,
                total_points=row.total_points,
                earned_points=row.earned_points,
                passed=row.passed,
                answers=graded_answers,
            )
        )
    if invalid:
        _incomplete(event_id, invalid, message="One or more quiz attempts have incomplete or invalid evidence.")
    if required and not any(item.completed_at is not None for item in attempts):
        _incomplete(event_id, ["completed_quiz_attempt"])
    return attempts


def _procedure_and_decision(
    root: TrainingEvidenceEvent, course: Course, event_id: UUID
) -> tuple[ProcedureEvidence, CommissionEvidence | None, DecisionEvidence | None]:
    payload = _as_mapping(root.payload_snapshot)
    procedure_payload = _as_mapping(payload.get("procedure"))
    procedure = ProcedureEvidence(
        type=root.procedure_type,
        title=str(procedure_payload.get("title") or payload.get("procedure_title") or course.title),
        code=procedure_payload.get("code") or payload.get("procedure_code"),
        version=procedure_payload.get("version") or payload.get("procedure_version"),
        purpose=procedure_payload.get("purpose") or payload.get("purpose"),
    )
    commission = None
    decision = None
    if isinstance(payload.get("commission"), Mapping):
        try:
            commission = CommissionEvidence.model_validate(payload["commission"])
        except ValidationError:
            _incomplete(event_id, ["commission_snapshot"])
    if isinstance(payload.get("decision"), Mapping):
        try:
            decision = DecisionEvidence.model_validate(payload["decision"])
        except ValidationError:
            _incomplete(event_id, ["decision_snapshot"])
    return procedure, commission, decision


async def _build_server_parts(
    db: AsyncSession,
    tenant_id: UUID,
    event_id: UUID,
) -> tuple[IndividualEvidenceInput, TrainingEvidenceEvent, list[TrainingEvidenceEvent]]:
    root, chain = await _load_event_chain(db, tenant_id, event_id)
    tenant, user, enrollment, release, course, position, department_name = await _load_tenant_context(
        db, tenant_id, root, event_id
    )
    if root.recorded_by_user_id is None:
        _incomplete(event_id, ["recorded_by_user"])
    if root.procedure_type not in {"acknowledgement", "training", "knowledge_check", "internal_attestation", "admission_decision"}:
        _incomplete(event_id, ["procedure_type"])

    effective_event = next(
        (
            item
            for item in reversed(chain)
            if item.record_type in {"original", "correction"}
        ),
        root,
    )
    procedure, commission, decision = _procedure_and_decision(effective_event, course, event_id)
    if root.procedure_type == "admission_decision" and decision is None:
        _incomplete(event_id, ["decision"])
    attempts = await _load_attempts(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        enrollment=enrollment,
        release=release,
        event_id=event_id,
        required=root.procedure_type in _ATTEMPT_PROCEDURES,
    )

    event_ids = [item.id for item in chain]
    confirmations = list(
        (
            await db.scalars(
                select(TrainingEvidenceStepUpConfirmation)
                .where(
                    TrainingEvidenceStepUpConfirmation.tenant_id == tenant_id,
                    TrainingEvidenceStepUpConfirmation.event_id.in_(event_ids),
                    TrainingEvidenceStepUpConfirmation.user_id == user.id,
                )
                .order_by(TrainingEvidenceStepUpConfirmation.confirmed_at.desc())
            )
        ).all()
    )
    if not confirmations:
        _incomplete(event_id, ["step_up_confirmation"])
    latest_confirmation = confirmations[0]

    related_events = [item for item in chain if item.id != root.id]
    actor_ids = {
        item.recorded_by_user_id for item in related_events if item.recorded_by_user_id is not None
    }
    actor_ids.add(root.recorded_by_user_id)
    holds = list(
        (
            await db.scalars(
                select(TrainingEvidenceLegalHold)
                .where(
                    TrainingEvidenceLegalHold.tenant_id == tenant_id,
                    TrainingEvidenceLegalHold.event_id.in_(event_ids),
                )
                .order_by(TrainingEvidenceLegalHold.occurred_at, TrainingEvidenceLegalHold.created_at)
            )
        ).all()
    )
    actor_ids.update(item.acted_by_user_id for item in holds)
    actors = {
        actor.id: actor
        for actor in (
            await db.scalars(
                select(User).where(User.tenant_id == tenant_id, User.id.in_(actor_ids))
            )
        ).all()
    } if actor_ids else {}
    if root.recorded_by_user_id not in actors:
        _incomplete(event_id, ["recorded_by_user"])
    if any(item.acted_by_user_id not in actors for item in holds):
        _incomplete(event_id, ["legal_hold_actor"])

    corrections = [
        CorrectionEvidence(
            id=str(item.id),
            recorded_at=item.occurred_at,
            kind="annulment" if item.record_type == "revocation" else "correction",
            reason=item.reason or "",
            actor=(
                f"{actors[item.recorded_by_user_id].first_name} {actors[item.recorded_by_user_id].last_name}"
                if item.recorded_by_user_id in actors else None
            ),
            supersedes_sha256=root.payload_sha256,
            replacement_reference=str(item.id),
        )
        for item in related_events
        if item.record_type in {"correction", "revocation"}
    ]
    hold_evidence = [
        LegalHoldEvidence(
            id=str(item.id),
            action=item.action,
            reason=item.reason,
            acted_by=(
                f"{actors[item.acted_by_user_id].first_name} {actors[item.acted_by_user_id].last_name}"
                if item.acted_by_user_id in actors else None
            ),
            occurred_at=item.occurred_at,
            payload_sha256=item.payload_sha256,
        )
        for item in holds
    ]
    latest_hold_by_event: dict[UUID, TrainingEvidenceLegalHold] = {}
    for item in holds:
        latest_hold_by_event[item.event_id] = item
    latest_correction = next((item for item in reversed(related_events) if item.record_type == "correction"), None)
    latest_record = related_events[-1] if related_events else root
    state = EvidenceState(
        active_event_id=str(latest_record.id),
        active_record_type=latest_record.record_type,
        latest_correction_event_id=str(latest_correction.id) if latest_correction else None,
        revoked=any(item.record_type == "revocation" for item in related_events),
        legal_hold_active=any(item.action == "placed" for item in latest_hold_by_event.values()),
    )
    mapped_confirmation = ConfirmationEvidence(
        confirmed=True,
        method={
            "email_otp": "otp",
            "telegram": "other",
            "sso": "other",
            "password": "password",  # pragma: allowlist secret
        }.get(latest_confirmation.reauth_method, "other"),
        confirmed_at=latest_confirmation.confirmed_at,
        statement=latest_confirmation.action_text,
        actor=f"{user.first_name} {user.last_name}",
        evidence_reference=str(latest_confirmation.id),
    )
    individual = ServerIndividualEvidenceInput(
        tenant=TenantEvidence(id=str(tenant.id), name=tenant.name, slug=tenant.slug),
        employee=EmployeeEvidence(
            id=str(user.id),
            full_name=f"{user.first_name} {user.last_name}".strip(),
            email=user.email,
            personnel_number=user.personnel_number,
            department=department_name,
            position=position.name if position else None,
            phone=user.phone,
        ),
        procedure=procedure,
        course=CourseEvidence(
            id=str(course.id),
            title=course.title,
            delivery_type=course.delivery_type,
            release_id=str(release.id),
            release_version=release.version,
            release_sha256=release.snapshot_sha256,
        ),
        assignment=AssignmentEvidence(
            enrollment_id=str(enrollment.id),
            source=enrollment.source,
            assigned_at=enrollment.enrolled_at,
            group_or_rule=enrollment.source,
        ),
        attempts=attempts,
        confirmation=mapped_confirmation,
        corrections=corrections,
        commission=commission,
        decision=decision,
        generated_at=_evidence_state_timestamp(chain, confirmations, holds),
        state=state,
        legal_holds=hold_evidence,
    )
    return individual, root, chain


async def build_individual_evidence_input(
    db: AsyncSession, tenant_id: UUID, event_id: UUID
) -> IndividualEvidenceInput:
    """Build an export input exclusively from tenant-scoped database state."""

    result, _, _ = await _build_server_parts(db, tenant_id, event_id)
    return result


async def build_group_evidence_input(
    db: AsyncSession, tenant_id: UUID, event_ids: list[UUID]
) -> GroupEvidenceInput:
    if not event_ids:
        raise HTTPException(status_code=422, detail="At least one event ID is required")
    if len(event_ids) > 200:
        raise HTTPException(status_code=422, detail="A group export accepts at most 200 event IDs")
    if len(set(event_ids)) != len(event_ids):
        raise HTTPException(status_code=422, detail="Event IDs must be unique")

    individual_inputs = []
    for event_id in event_ids:
        individual, _, _ = await _build_server_parts(db, tenant_id, event_id)
        individual_inputs.append(individual)

    first = individual_inputs[0]
    incompatible = [
        str(event_id)
        for event_id, item in zip(event_ids, individual_inputs, strict=True)
        if (
            item.tenant.id != first.tenant.id
            or item.procedure.model_dump(mode="json", exclude_none=True)
            != first.procedure.model_dump(mode="json", exclude_none=True)
            or (item.course and first.course and item.course.release_id != first.course.release_id)
            or item.commission != first.commission
        )
    ]
    if incompatible:
        _incomplete(
            event_ids[0],
            ["compatible_group"],
            message=f"Events are not compatible for one group protocol: {', '.join(incompatible)}.",
        )

    records = [
        ServerGroupRecordEvidence(
            employee=item.employee,
            assignment=item.assignment,
            attempts=item.attempts,
            confirmation=item.confirmation,
            corrections=item.corrections,
            decision=item.decision,
            state=item.state,
            legal_holds=item.legal_holds,
        )
        for item in individual_inputs
    ]
    return ServerGroupEvidenceInput(
        tenant=first.tenant,
        procedure=first.procedure,
        course=first.course,
        records=records,
        commission=first.commission,
        decision=None,
        generated_at=max(
            item.generated_at
            for item in individual_inputs
            if item.generated_at is not None
        ),
    )
