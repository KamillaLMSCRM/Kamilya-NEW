"""Read/write service for the unified position qualification card."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from app.models.courses import Course
from app.models.document import Document
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.competencies.models import Competency, CompetencyCourse, PositionCompetency
from app.modules.positions.batch_service import recompute_position_holders
from app.modules.positions.models import DepartmentCourse, Position, PositionCourse, PositionQuiz
from app.modules.positions.qualification_models import PositionQualificationVersion
from app.modules.positions.qualification_schemas import (
    CourseRule,
    EffectiveCourse,
    PositionQualificationCard,
    QualificationCompetenciesPut,
    QualificationCompetency,
    QualificationEmployees,
    QualificationHistoryItem,
    QualificationInstruction,
    QualificationOnboardingQuiz,
    QualificationProfile,
    QualificationProfilePatch,
    QualificationTraining,
    QualificationTrainingPut,
)


async def _locked_position(db: AsyncSession, position_id: UUID, tenant_id: UUID) -> Position:
    result = await db.execute(
        select(Position)
        .options(lazyload(Position.department_obj))
        .where(Position.id == position_id, Position.tenant_id == tenant_id)
        .with_for_update()
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return position


async def _position(db: AsyncSession, position_id: UUID, tenant_id: UUID) -> Position:
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    position = result.scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return position


async def _course_map(db: AsyncSession, tenant_id: UUID, course_ids: set[UUID]) -> dict[UUID, Course]:
    if not course_ids:
        return {}
    result = await db.execute(
        select(Course).where(Course.tenant_id == tenant_id, Course.id.in_(course_ids))
    )
    return {course.id: course for course in result.scalars().all()}


def _course_rule(course: Course, required: bool, source: str) -> CourseRule:
    return CourseRule(
        course_id=course.id,
        title=course.title,
        status=course.status,
        required=required,
        source=source,
    )


async def _collect_state(db: AsyncSession, position: Position) -> dict[str, Any]:
    tenant_id = position.tenant_id

    instruction = None
    if position.instruction_document_id:
        instruction = await db.scalar(
            select(Document).where(
                Document.id == position.instruction_document_id,
                Document.tenant_id == tenant_id,
            )
        )

    position_links = (
        await db.execute(
            select(PositionCompetency).where(
                PositionCompetency.position_id == position.id,
                PositionCompetency.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    competency_ids = {link.competency_id for link in position_links}
    competencies = (
        await db.execute(
            select(Competency).where(
                Competency.tenant_id == tenant_id,
                Competency.id.in_(competency_ids) if competency_ids else Competency.id == UUID(int=0),
            )
        )
    ).scalars().all()
    competency_by_id = {item.id: item for item in competencies}

    competency_course_rows = (
        await db.execute(
            select(CompetencyCourse).where(
                CompetencyCourse.tenant_id == tenant_id,
                CompetencyCourse.competency_id.in_(competency_ids)
                if competency_ids
                else CompetencyCourse.competency_id == UUID(int=0),
            )
        )
    ).scalars().all()
    competency_course_ids = {row.course_id for row in competency_course_rows}

    position_course_rows = (
        await db.execute(
            select(PositionCourse).where(
                PositionCourse.position_id == position.id,
                PositionCourse.tenant_id == tenant_id,
            )
        )
    ).scalars().all()

    department_course_rows: list[DepartmentCourse] = []
    if position.department_id:
        department_course_rows = (
            await db.execute(
                select(DepartmentCourse).where(
                    DepartmentCourse.department_id == position.department_id,
                    DepartmentCourse.tenant_id == tenant_id,
                )
            )
        ).scalars().all()

    all_course_ids = (
        {row.course_id for row in position_course_rows}
        | {row.course_id for row in department_course_rows}
        | competency_course_ids
    )
    courses = await _course_map(db, tenant_id, all_course_ids)

    position_rules = [
        _course_rule(courses[row.course_id], row.required, "position")
        for row in position_course_rows
        if row.course_id in courses
    ]
    department_rules = [
        _course_rule(courses[row.course_id], row.required, "department")
        for row in department_course_rows
        if row.course_id in courses
    ]
    competency_rules = [
        _course_rule(courses[row.course_id], True, "competency")
        for row in competency_course_rows
        if row.course_id in courses
    ]

    effective: dict[UUID, EffectiveCourse] = {}
    for rule in [*position_rules, *department_rules, *competency_rules]:
        item = effective.get(rule.course_id)
        if item is None:
            effective[rule.course_id] = EffectiveCourse(
                course_id=rule.course_id,
                title=rule.title,
                status=rule.status,
                required=rule.required,
                sources=[rule.source],
            )
        else:
            item.required = item.required or rule.required
            if rule.source not in item.sources:
                item.sources.append(rule.source)

    quiz = await db.scalar(
        select(PositionQuiz).where(
            PositionQuiz.position_id == position.id,
            PositionQuiz.tenant_id == tenant_id,
        )
    )
    active_count = await db.scalar(
        select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.position_id == position.id,
            User.is_active.is_(True),
        )
    )
    latest_version = await db.scalar(
        select(func.max(PositionQualificationVersion.version_no)).where(
            PositionQualificationVersion.tenant_id == tenant_id,
            PositionQualificationVersion.position_id == position.id,
        )
    )
    history_count = await db.scalar(
        select(func.count(PositionQualificationVersion.id)).where(
            PositionQualificationVersion.tenant_id == tenant_id,
            PositionQualificationVersion.position_id == position.id,
        )
    )

    return {
        "position": position,
        "instruction": instruction,
        "position_links": position_links,
        "competency_by_id": competency_by_id,
        "competency_course_rows": competency_course_rows,
        "courses": courses,
        "position_rules": position_rules,
        "department_rules": department_rules,
        "competency_rules": competency_rules,
        "effective_courses": list(effective.values()),
        "quiz": quiz,
        "active_count": int(active_count or 0),
        "latest_version": int(latest_version) if latest_version is not None else None,
        "history_count": int(history_count or 0),
    }


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    position: Position = state["position"]
    return {
        "profile": {
            "name": position.name,
            "department": position.department,
            "level": position.level,
            "responsibilities": position.responsibilities,
            "requirements": position.requirements,
        },
        "instruction_document_id": str(position.instruction_document_id)
        if position.instruction_document_id
        else None,
        "competencies": [
            {"competency_id": str(link.competency_id), "required_level": link.required_level}
            for link in state["position_links"]
        ],
        "training": {
            "position_courses": [
                {
                    "course_id": str(rule.course_id),
                    "required": rule.required,
                }
                for rule in state["position_rules"]
            ],
        },
        "onboarding_quiz": (
            {
                "id": str(state["quiz"].id),
                "title": state["quiz"].title,
                "pass_score": state["quiz"].pass_score,
                "time_limit": state["quiz"].time_limit,
                "questions": state["quiz"].questions or [],
                "is_active": state["quiz"].is_active,
            }
            if state["quiz"]
            else None
        ),
    }


def _card_from_state(state: dict[str, Any]) -> PositionQualificationCard:
    position: Position = state["position"]
    instruction = state["instruction"]
    quiz = state["quiz"]
    competencies = [
        QualificationCompetency(
            id=link.competency_id,
            name=state["competency_by_id"].get(link.competency_id).name,
            description=state["competency_by_id"].get(link.competency_id).description,
            required_level=link.required_level,
            course_ids=sorted(
                [
                    row.course_id
                    for row in state.get("competency_course_rows", [])
                    if row.competency_id == link.competency_id
                ],
                key=str,
            ),
        )
        for link in state["position_links"]
        if link.competency_id in state["competency_by_id"]
    ]
    if not competencies:
        # The course rows are not needed for writes; load them from the
        # already-materialized competency rules when the card is assembled.
        competencies = []

    return PositionQualificationCard(
        profile=QualificationProfile(
            id=position.id,
            tenant_id=position.tenant_id,
            name=position.name,
            department=position.department,
            level=position.level,
            responsibilities=position.responsibilities,
            requirements=position.requirements,
            employee_count=position.employee_count,
            current_employee_count=state["active_count"],
            created_at=position.created_at,
        ),
        instruction=(
            QualificationInstruction(
                document_id=instruction.id,
                filename=instruction.filename,
                index_status=instruction.index_status,
                index_error_code=instruction.index_error_code,
                updated_at=instruction.updated_at,
                version=instruction.version,
            )
            if instruction
            else None
        ),
        competencies=competencies,
        training=QualificationTraining(
            position_courses=state["position_rules"],
            department_courses=state["department_rules"],
            competency_courses=state["competency_rules"],
            effective_courses=state["effective_courses"],
        ),
        onboarding_quiz=(
            QualificationOnboardingQuiz(
                id=quiz.id,
                title=quiz.title,
                pass_score=quiz.pass_score,
                time_limit=quiz.time_limit,
                is_active=quiz.is_active,
                question_count=len(quiz.questions or []),
                questions=quiz.questions or [],
                updated_at=quiz.updated_at,
            )
            if quiz
            else None
        ),
        employees=QualificationEmployees(active_count=state["active_count"]),
        latest_version=state["latest_version"],
        history_count=state["history_count"],
    )


async def get_card(db: AsyncSession, position_id: UUID, tenant_id: UUID) -> PositionQualificationCard:
    return _card_from_state(await _collect_state(db, await _position(db, position_id, tenant_id)))


async def _ensure_baseline(db: AsyncSession, position: Position, actor_id: UUID) -> None:
    existing = await db.scalar(
        select(func.count(PositionQualificationVersion.id)).where(
            PositionQualificationVersion.tenant_id == position.tenant_id,
            PositionQualificationVersion.position_id == position.id,
        )
    )
    if existing:
        return
    state = await _collect_state(db, position)
    db.add(
        PositionQualificationVersion(
            tenant_id=position.tenant_id,
            position_id=position.id,
            version_no=1,
            snapshot=_state_snapshot(state),
            change_kind="baseline",
            created_by=actor_id,
        )
    )
    await db.flush()


async def prepare_external_change(
    db: AsyncSession,
    position_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
) -> Position:
    """Lock a position and capture its current state before another editor mutates it."""
    position = await _locked_position(db, position_id, tenant_id)
    await _ensure_baseline(db, position, actor_id)
    return position


async def _record_version(
    db: AsyncSession,
    position: Position,
    actor_id: UUID,
    change_kind: str,
    change_reason: str | None,
) -> None:
    state = await _collect_state(db, position)
    latest = await db.scalar(
        select(func.max(PositionQualificationVersion.version_no)).where(
            PositionQualificationVersion.tenant_id == position.tenant_id,
            PositionQualificationVersion.position_id == position.id,
        )
    )
    db.add(
        PositionQualificationVersion(
            tenant_id=position.tenant_id,
            position_id=position.id,
            version_no=(int(latest) if latest is not None else 0) + 1,
            snapshot=_state_snapshot(state),
            change_kind=change_kind,
            change_reason=change_reason,
            created_by=actor_id,
        )
    )
    await db.flush()


async def record_external_change(
    db: AsyncSession,
    position: Position,
    actor_id: UUID,
    change_kind: str,
    change_reason: str | None = None,
) -> None:
    """Record a mutation performed by the existing JD or onboarding editor."""
    await _record_version(db, position, actor_id, change_kind, change_reason)
    await log_action(
        db,
        tenant_id=position.tenant_id,
        action=f"position_qualification_{change_kind}",
        resource_type="position_qualification",
        resource_id=position.id,
        user_id=actor_id,
        details={"change_reason": change_reason} if change_reason else None,
    )


async def _mutated_card(
    db: AsyncSession,
    position: Position,
    actor_id: UUID,
    change_kind: str,
    change_reason: str | None,
) -> PositionQualificationCard:
    await _record_version(db, position, actor_id, change_kind, change_reason)
    await log_action(
        db,
        tenant_id=position.tenant_id,
        action=f"position_qualification_{change_kind}",
        resource_type="position_qualification",
        resource_id=position.id,
        user_id=actor_id,
        details={"change_reason": change_reason} if change_reason else None,
    )
    return await get_card(db, position.id, position.tenant_id)


async def update_profile(
    db: AsyncSession,
    position_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    payload: QualificationProfilePatch,
) -> PositionQualificationCard:
    position = await _locked_position(db, position_id, tenant_id)
    changed_fields = {
        field: getattr(payload, field).strip()
        for field in ("name", "department", "level", "responsibilities", "requirements")
        if getattr(payload, field) is not None
        and getattr(position, field) != getattr(payload, field).strip()
    }
    if not changed_fields:
        return await get_card(db, position_id, tenant_id)
    await _ensure_baseline(db, position, actor_id)
    for field, value in changed_fields.items():
        setattr(position, field, value)
    await db.flush()
    return await _mutated_card(db, position, actor_id, "profile_update", payload.change_reason)


async def update_competencies(
    db: AsyncSession,
    position_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    payload: QualificationCompetenciesPut,
) -> PositionQualificationCard:
    position = await _locked_position(db, position_id, tenant_id)
    items = payload.items
    competency_ids = [item.competency_id for item in items]
    if len(set(competency_ids)) != len(competency_ids):
        raise HTTPException(status_code=422, detail={"code": "duplicate_competency"})
    valid = set(
        (
            await db.execute(
                select(Competency.id).where(
                    Competency.tenant_id == tenant_id,
                    Competency.id.in_(competency_ids) if competency_ids else Competency.id == UUID(int=0),
                )
            )
        ).scalars().all()
    )
    if valid != set(competency_ids):
        raise HTTPException(status_code=422, detail={"code": "competency_outside_tenant"})
    existing_rows = (
        await db.execute(
            select(PositionCompetency).where(
                PositionCompetency.position_id == position.id,
                PositionCompetency.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    existing = {row.competency_id: row.required_level for row in existing_rows}
    requested = {item.competency_id: item.required_level for item in items}
    if existing == requested:
        return await get_card(db, position_id, tenant_id)
    await _ensure_baseline(db, position, actor_id)
    await db.execute(
        delete(PositionCompetency).where(
            PositionCompetency.position_id == position.id,
            PositionCompetency.tenant_id == tenant_id,
        )
    )
    for item in items:
        db.add(
            PositionCompetency(
                tenant_id=tenant_id,
                position_id=position.id,
                competency_id=item.competency_id,
                required_level=item.required_level,
            )
        )
    await db.flush()
    return await _mutated_card(db, position, actor_id, "competencies_update", payload.change_reason)


async def update_training(
    db: AsyncSession,
    position_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    payload: QualificationTrainingPut,
) -> PositionQualificationCard:
    position = await _locked_position(db, position_id, tenant_id)
    course_ids = [item.course_id for item in payload.items]
    if len(set(course_ids)) != len(course_ids):
        raise HTTPException(status_code=422, detail={"code": "duplicate_course"})
    courses = await _course_map(db, tenant_id, set(course_ids))
    if len(courses) != len(set(course_ids)):
        raise HTTPException(status_code=422, detail={"code": "course_outside_tenant"})
    existing_rows = (
        await db.execute(
            select(PositionCourse).where(
                PositionCourse.position_id == position.id,
                PositionCourse.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    existing = {row.course_id: row.required for row in existing_rows}
    requested = {item.course_id: item.required for item in payload.items}
    if existing == requested:
        return await get_card(db, position_id, tenant_id)
    await _ensure_baseline(db, position, actor_id)
    await db.execute(
        delete(PositionCourse).where(
            PositionCourse.position_id == position.id,
            PositionCourse.tenant_id == tenant_id,
        )
    )
    for item in payload.items:
        db.add(
            PositionCourse(
                tenant_id=tenant_id,
                position_id=position.id,
                course_id=item.course_id,
                required=item.required,
            )
        )
    await db.flush()
    await recompute_position_holders(db, position.id, tenant_id)
    return await _mutated_card(db, position, actor_id, "training_update", payload.change_reason)


async def history(db: AsyncSession, position_id: UUID, tenant_id: UUID) -> list[QualificationHistoryItem]:
    await _position(db, position_id, tenant_id)
    result = await db.execute(
        select(PositionQualificationVersion)
        .where(
            PositionQualificationVersion.position_id == position_id,
            PositionQualificationVersion.tenant_id == tenant_id,
        )
        .order_by(PositionQualificationVersion.version_no.desc())
    )
    return [QualificationHistoryItem.model_validate(item, from_attributes=True) for item in result.scalars().all()]


async def restore(
    db: AsyncSession,
    position_id: UUID,
    version_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    change_reason: str | None,
) -> PositionQualificationCard:
    position = await _locked_position(db, position_id, tenant_id)
    version = await db.scalar(
        select(PositionQualificationVersion).where(
            PositionQualificationVersion.id == version_id,
            PositionQualificationVersion.position_id == position_id,
            PositionQualificationVersion.tenant_id == tenant_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Qualification version not found")
    snapshot = version.snapshot or {}
    profile = snapshot.get("profile") or {}
    instruction_id = snapshot.get("instruction_document_id")
    if instruction_id:
        instruction = await db.scalar(
            select(Document).where(
                Document.id == UUID(str(instruction_id)),
                Document.tenant_id == tenant_id,
                Document.lifecycle_status == "active",
            )
        )
        if instruction is None:
            raise HTTPException(status_code=409, detail={"code": "snapshot_reference_missing", "entity": "document"})
    competency_items = snapshot.get("competencies") or []
    competency_ids = {UUID(str(item["competency_id"])) for item in competency_items}
    valid_competencies = set(
        (
            await db.execute(
                select(Competency.id).where(
                    Competency.tenant_id == tenant_id,
                    Competency.id.in_(competency_ids) if competency_ids else Competency.id == UUID(int=0),
                )
            )
        ).scalars().all()
    )
    if valid_competencies != competency_ids:
        raise HTTPException(status_code=409, detail={"code": "snapshot_reference_missing", "entity": "competency"})
    training = snapshot.get("training") or {}
    training_items = training.get("position_courses") or []
    course_ids = {UUID(str(item["course_id"])) for item in training_items}
    if len(await _course_map(db, tenant_id, course_ids)) != len(course_ids):
        raise HTTPException(status_code=409, detail={"code": "snapshot_reference_missing", "entity": "course"})
    quiz_snapshot = snapshot.get("onboarding_quiz")

    await _ensure_baseline(db, position, actor_id)
    for field in ("name", "department", "level", "responsibilities", "requirements"):
        if field in profile:
            setattr(position, field, profile[field] or "")
    position.instruction_document_id = UUID(str(instruction_id)) if instruction_id else None

    await db.execute(
        delete(PositionCompetency).where(
            PositionCompetency.position_id == position_id,
            PositionCompetency.tenant_id == tenant_id,
        )
    )
    for item in competency_items:
        db.add(
            PositionCompetency(
                tenant_id=tenant_id,
                position_id=position_id,
                competency_id=UUID(str(item["competency_id"])),
                required_level=int(item.get("required_level", 1)),
            )
        )
    await db.execute(
        delete(PositionCourse).where(
            PositionCourse.position_id == position_id,
            PositionCourse.tenant_id == tenant_id,
        )
    )
    for item in training_items:
        db.add(
            PositionCourse(
                tenant_id=tenant_id,
                position_id=position_id,
                course_id=UUID(str(item["course_id"])),
                required=bool(item.get("required", True)),
            )
        )
    current_quiz = await db.scalar(
        select(PositionQuiz).where(
            PositionQuiz.position_id == position_id,
            PositionQuiz.tenant_id == tenant_id,
        )
    )
    if quiz_snapshot is None:
        if current_quiz is not None:
            await db.delete(current_quiz)
    else:
        if current_quiz is None:
            quiz_kwargs: dict[str, Any] = {
                "position_id": position_id,
                "tenant_id": tenant_id,
                "created_by": actor_id,
            }
            if quiz_snapshot.get("id"):
                quiz_kwargs["id"] = UUID(str(quiz_snapshot["id"]))
            current_quiz = PositionQuiz(**quiz_kwargs)
            db.add(current_quiz)
        current_quiz.title = str(quiz_snapshot.get("title") or "Onboarding")
        current_quiz.pass_score = int(quiz_snapshot.get("pass_score", 80))
        current_quiz.time_limit = quiz_snapshot.get("time_limit")
        current_quiz.questions = quiz_snapshot.get("questions") or []
        current_quiz.is_active = bool(quiz_snapshot.get("is_active", True))

    await db.flush()
    await recompute_position_holders(db, position_id, tenant_id)
    return await _mutated_card(db, position, actor_id, "restore", change_reason)
