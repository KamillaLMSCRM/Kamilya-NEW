"""Tenant-bound standalone assessment endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.knowledge_checks.models import KnowledgeCheck, KnowledgeCheckAssignment, KnowledgeCheckAttempt
from app.modules.knowledge_checks.schemas import Answer, Answers, Assign, Content, Create, Replace, Revision
from app.modules.knowledge_checks.service import digest, grade, normalize_answers, public_snapshot

router = APIRouter(prefix="/knowledge-checks", tags=["knowledge-checks"])
Author = Annotated[User, Depends(require_role("superadmin", "methodologist"))]
async def standalone_student(user: Annotated[User, Depends(require_role("student"))]) -> User:
    # A personal course link authenticates only its exact enrollment. It must
    # not acquire access to unrelated employee assessments through a new route.
    if getattr(user, "assignment_access_enrollment_id", None) is not None:
        raise HTTPException(403, "Sign in with your employee account to open knowledge checks")
    return user


Student = Annotated[User, Depends(standalone_student)]
DB = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def tenant(user: Any) -> Any:
    if not user.tenant_id:
        raise HTTPException(403, "Tenant context required")
    return user.tenant_id


def conflict(message: str) -> NoReturn:
    raise HTTPException(409, message)


def check_response(check: Any) -> dict[str, Any]:
    return {"id": check.id, "revision": check.revision, "status": check.status,
            **check.content, "created_at": check.created_at, "updated_at": check.updated_at}


def attempt_response(attempt: Any, *, include_snapshot: bool = False) -> dict[str, Any]:
    value = {key: getattr(attempt, key) for key in (
        "id", "assignment_id", "number", "status", "started_at", "deadline_at", "completed_at",
        "score_percent", "passed", "earned_points", "total_points", "answers")}
    if include_snapshot:
        value["snapshot"] = public_snapshot(attempt.snapshot)
    return value


def summary(assignment: Any, attempts: list[Any]) -> dict[str, Any]:
    latest = attempts[-1] if attempts else None
    status = "assigned" if latest is None else ("in_progress" if latest.completed_at is None else
             "passed" if latest.passed else "failed")
    return {"id": assignment.id, "check_id": assignment.check_id, "title": assignment.snapshot["title"],
            "revision": assignment.revision, "due_at": assignment.due_at, "status": status,
            "attempt_limit": assignment.snapshot["attempt_limit"], "attempts_count": len(attempts),
            "score_percent": latest.score_percent if latest else None, "passed": latest.passed if latest else None}


async def get_check(db: AsyncSession, user: Any, check_id: UUID, *, lock: bool = False) -> Any:
    query = select(KnowledgeCheck).where(KnowledgeCheck.id == check_id, KnowledgeCheck.tenant_id == tenant(user))
    if lock:
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        raise HTTPException(404, "Not found")
    return item


async def get_assignment(db: AsyncSession, user: Any, assignment_id: UUID, *, lock: bool = False) -> Any:
    query = select(KnowledgeCheckAssignment).where(KnowledgeCheckAssignment.id == assignment_id,
             KnowledgeCheckAssignment.tenant_id == tenant(user), KnowledgeCheckAssignment.user_id == user.id)
    if lock:
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        raise HTTPException(404, "Not found")
    return item


async def get_attempt(db: AsyncSession, user: Any, attempt_id: UUID, *, lock: bool = False) -> Any:
    query = (select(KnowledgeCheckAttempt).join(KnowledgeCheckAssignment,
             (KnowledgeCheckAssignment.id == KnowledgeCheckAttempt.assignment_id) &
             (KnowledgeCheckAssignment.tenant_id == KnowledgeCheckAttempt.tenant_id)).where(
             KnowledgeCheckAttempt.id == attempt_id, KnowledgeCheckAttempt.tenant_id == tenant(user),
             KnowledgeCheckAssignment.user_id == user.id))
    if lock:
        query = query.with_for_update(of=KnowledgeCheckAttempt)
    item = await db.scalar(query)
    if item is None:
        raise HTTPException(404, "Not found")
    return item


async def assignment_attempts(db: AsyncSession, assignment: KnowledgeCheckAssignment) -> list[KnowledgeCheckAttempt]:
    result = await db.scalars(select(KnowledgeCheckAttempt).where(
        KnowledgeCheckAttempt.tenant_id == assignment.tenant_id,
        KnowledgeCheckAttempt.assignment_id == assignment.id).order_by(KnowledgeCheckAttempt.number))
    return list(result.all())


def page(items: list[Any], limit: int) -> dict[str, Any]:
    return {"items": items[:limit], "has_more": len(items) > limit}


@router.get("/")
async def list_checks(user: Author, db: DB, limit: Limit = 50, offset: Offset = 0) -> dict[str, Any]:
    rows = (await db.scalars(select(KnowledgeCheck).where(KnowledgeCheck.tenant_id == tenant(user))
            .order_by(KnowledgeCheck.created_at.desc(), KnowledgeCheck.id).offset(offset).limit(limit + 1))).all()
    return page([{"id": row.id, "revision": row.revision, "status": row.status,
                  **{key: value for key, value in row.content.items() if key != "questions"},
                  "question_count": len(row.content["questions"]),
                  "created_at": row.created_at, "updated_at": row.updated_at} for row in rows], limit)


@router.post("/")
async def create_check(body: Create, user: Author, db: DB) -> dict[str, Any]:
    content = body.model_dump(mode="json", exclude={"id"})
    now = datetime.now(UTC)
    await db.execute(insert(KnowledgeCheck).values(id=body.id, tenant_id=tenant(user), content=content, create_sha256=digest(content),
        revision=1, status="draft", created_by=user.id, created_at=now, updated_at=now).on_conflict_do_nothing())
    check = await db.scalar(select(KnowledgeCheck).where(KnowledgeCheck.id == body.id,
                            KnowledgeCheck.tenant_id == tenant(user)).with_for_update())
    if check is None or check.created_by != user.id or check.create_sha256 != digest(content):
        conflict("Check id already used")
    return check_response(check)


@router.get("/my")
async def my_assignments(user: Student, db: DB, limit: Limit = 50, offset: Offset = 0) -> dict[str, Any]:
    rows = (await db.scalars(select(KnowledgeCheckAssignment).where(
        KnowledgeCheckAssignment.tenant_id == tenant(user), KnowledgeCheckAssignment.user_id == user.id)
        .order_by(KnowledgeCheckAssignment.created_at.desc(), KnowledgeCheckAssignment.id)
        .offset(offset).limit(limit + 1))).all()
    return page([summary(row, await assignment_attempts(db, row)) for row in rows], limit)


@router.get("/assignments/{assignment_id}")
async def assignment_detail(assignment_id: UUID, user: Student, db: DB) -> dict[str, Any]:
    assignment = await get_assignment(db, user, assignment_id)
    attempts = await assignment_attempts(db, assignment)
    return {**summary(assignment, attempts), "attempts": [attempt_response(a) for a in attempts]}


@router.post("/assignments/{assignment_id}/start")
async def start(assignment_id: UUID, user: Student, db: DB) -> dict[str, Any]:
    assignment = await get_assignment(db, user, assignment_id, lock=True)
    attempts = await assignment_attempts(db, assignment)
    if attempts and attempts[-1].completed_at is None:
        return attempt_response(attempts[-1], include_snapshot=True)
    now = datetime.now(UTC)
    if assignment.due_at is not None and now >= assignment.due_at:
        conflict("Assignment is overdue")
    if attempts and (attempts[-1].passed or len(attempts) >= assignment.snapshot["attempt_limit"]):
        conflict("No attempts available")
    duration = assignment.snapshot["time_limit_minutes"]
    deadline = now + timedelta(minutes=duration) if duration is not None else None
    if assignment.due_at is not None and (deadline is None or assignment.due_at < deadline):
        deadline = assignment.due_at
    attempt = KnowledgeCheckAttempt(id=uuid4(), tenant_id=tenant(user), assignment_id=assignment.id,
        number=len(attempts) + 1, snapshot=assignment.snapshot, snapshot_sha256=assignment.snapshot_sha256,
        started_at=now, deadline_at=deadline, answers=[], status="started")
    db.add(attempt)
    await db.flush()
    return attempt_response(attempt, include_snapshot=True)


@router.get("/attempts/{attempt_id}")
async def attempt_detail(attempt_id: UUID, user: Student, db: DB) -> dict[str, Any]:
    return attempt_response(await get_attempt(db, user, attempt_id), include_snapshot=True)


@router.put("/attempts/{attempt_id}/answers")
async def save_answers(attempt_id: UUID, body: Answers, user: Student, db: DB) -> dict[str, Any]:
    attempt = await get_attempt(db, user, attempt_id, lock=True)
    if attempt.completed_at is not None or (attempt.deadline_at and datetime.now(UTC) >= attempt.deadline_at):
        conflict("Attempt is closed or expired")
    attempt.answers = normalize_answers(attempt.snapshot, body.answers)
    await db.flush()
    return attempt_response(attempt, include_snapshot=True)


@router.post("/attempts/{attempt_id}/submit")
async def submit(attempt_id: UUID, body: Answers, user: Student, db: DB) -> dict[str, Any]:
    attempt = await get_attempt(db, user, attempt_id, lock=True)
    if attempt.completed_at is not None:
        if attempt.status != "expired" and digest(normalize_answers(attempt.snapshot, body.answers)) != attempt.submission_sha256:
            conflict("Different submission already recorded")
        return attempt_response(attempt, include_snapshot=True)
    now = datetime.now(UTC)
    expired = bool(attempt.deadline_at and now >= attempt.deadline_at)
    answers = normalize_answers(attempt.snapshot, [Answer.model_validate(a) for a in attempt.answers]) if expired else normalize_answers(attempt.snapshot, body.answers, complete=True)
    for key, value in grade(attempt.snapshot, answers).items():
        setattr(attempt, key, value)
    attempt.answers = answers
    attempt.submission_sha256 = digest(answers)
    attempt.completed_at = now
    attempt.status = "expired" if expired else "submitted"
    await db.flush()
    return attempt_response(attempt, include_snapshot=True)


@router.get("/{check_id}")
async def check_detail(check_id: UUID, user: Author, db: DB) -> dict[str, Any]:
    return check_response(await get_check(db, user, check_id))


@router.put("/{check_id}")
async def replace_check(check_id: UUID, body: Replace, user: Author, db: DB) -> dict[str, Any]:
    check = await get_check(db, user, check_id, lock=True)
    if check.revision != body.expected_revision:
        conflict("Stale revision")
    check.content = body.model_dump(mode="json", exclude={"expected_revision"})
    check.revision += 1
    check.status = "draft"
    check.updated_at = datetime.now(UTC)
    await db.flush()
    return check_response(check)


@router.post("/{check_id}/publish")
async def publish(check_id: UUID, body: Revision, user: Author, db: DB) -> dict[str, Any]:
    check = await get_check(db, user, check_id, lock=True)
    if check.revision != body.expected_revision:
        conflict("Stale revision")
    Content.model_validate(check.content)
    check.status = "published"
    await db.flush()
    return check_response(check)


@router.post("/{check_id}/assign")
async def assign(check_id: UUID, body: Assign, user: Author, db: DB) -> dict[str, Any]:
    check = await get_check(db, user, check_id, lock=True)
    if check.revision != body.expected_revision or check.status != "published":
        conflict("Published revision required")
    employees = (await db.scalars(select(User.id).where(User.tenant_id == tenant(user), User.id.in_(body.user_ids),
                  User.is_active.is_(True), User.status == "active", User.role == "student").with_for_update())).all()
    if set(employees) != set(body.user_ids):
        raise HTTPException(404, "Audience not found")
    snapshot = check.content
    existing = (await db.scalars(select(KnowledgeCheckAssignment).where(
        KnowledgeCheckAssignment.tenant_id == tenant(user), KnowledgeCheckAssignment.check_id == check.id,
        KnowledgeCheckAssignment.revision == check.revision,
        KnowledgeCheckAssignment.user_id.in_(body.user_ids)))).all()
    if any(item.due_at != body.due_at for item in existing):
        conflict("Assignment already exists with a different due date")
    for uid in body.user_ids:
        await db.execute(insert(KnowledgeCheckAssignment).values(id=uuid4(), tenant_id=tenant(user),
            check_id=check.id, user_id=uid, assigned_by=user.id, revision=check.revision, snapshot=snapshot,
            snapshot_sha256=digest(snapshot), due_at=body.due_at, created_at=datetime.now(UTC))
            .on_conflict_do_nothing(index_elements=["check_id", "revision", "user_id"]))
    rows = (await db.scalars(select(KnowledgeCheckAssignment).where(KnowledgeCheckAssignment.tenant_id == tenant(user),
        KnowledgeCheckAssignment.check_id == check.id, KnowledgeCheckAssignment.revision == check.revision,
        KnowledgeCheckAssignment.user_id.in_(body.user_ids)))).all()
    return {"items": [summary(row, await assignment_attempts(db, row)) for row in rows], "has_more": False}


@router.get("/{check_id}/results")
async def results(check_id: UUID, user: Author, db: DB, limit: Limit = 50, offset: Offset = 0) -> dict[str, Any]:
    await get_check(db, user, check_id)
    rows = (await db.execute(select(KnowledgeCheckAssignment, User).join(User,
        (User.id == KnowledgeCheckAssignment.user_id) & (User.tenant_id == KnowledgeCheckAssignment.tenant_id))
        .where(KnowledgeCheckAssignment.tenant_id == tenant(user), KnowledgeCheckAssignment.check_id == check_id)
        .order_by(KnowledgeCheckAssignment.created_at.desc(), KnowledgeCheckAssignment.id)
        .offset(offset).limit(limit + 1))).all()
    values = []
    for assignment, employee in rows:
        attempts = await assignment_attempts(db, assignment)
        values.append({**summary(assignment, attempts), "user_id": employee.id,
                       "employee_label": f"{employee.last_name} {employee.first_name}".strip(),
                       "attempts": [attempt_response(a) for a in attempts]})
    return page(values, limit)
