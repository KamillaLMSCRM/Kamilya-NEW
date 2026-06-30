"""Positions — API router with course attachment + JD analysis"""
import logging
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.modules.positions.assignment_service import recompute_enrollments
from app.modules.positions.batch_service import (
    recompute_position_holders,
)
from app.modules.positions.models import Position, PositionCourse

logger = logging.getLogger(__name__)
from app.modules.positions.models import PositionJDVersion
from app.modules.positions.schemas import (
    BulkPositionCreated,
    BulkPositionFailed,
    BulkPositionRequest,
    BulkPositionResponse,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
)

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(require_tenant_user())],
)


# ── Helpers ──────────────────────────────────────────────────



async def _sync_courses(db: AsyncSession, position_id: UUID, course_ids: list[UUID] | None, tenant_id: UUID | None = None):
    """Replace all position_courses for a position.

    `tenant_id` is required by the NOT NULL constraint on
    position_courses.tenant_id; we resolve it from the caller because
    the model otherwise has no way to derive it (smoke 2026-06-30).
    """
    if course_ids is None:
        return
    await db.execute(delete(PositionCourse).where(PositionCourse.position_id == position_id))
    for cid in course_ids:
        db.add(PositionCourse(
            position_id=position_id,
            course_id=cid,
            tenant_id=tenant_id,
        ))


async def _get_course_ids(db: AsyncSession, position_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(PositionCourse.course_id).where(PositionCourse.position_id == position_id)
    )
    return [row[0] for row in result.all()]


async def _update_employee_count(db: AsyncSession, position_id: UUID, tenant_id: UUID) -> int:
    """Refresh position.employee_count. Returns new value."""
    count_result = await db.execute(
        select(func.count(User.id)).where(
            User.position_id == position_id,
            User.tenant_id == tenant_id,
        )
    )
    new_count = count_result.scalar() or 0
    pos = await db.get(Position, position_id)
    if pos:
        pos.employee_count = new_count
    return new_count


# ── CRUD ─────────────────────────────────────────────────────


async def _live_employee_count(db: AsyncSession, position_id: UUID, tenant_id: UUID) -> int:
    """Compute the real-time employee count for a position.

    Filters to `is_active = true` so deactivated users don't show up —
    matches the methodologist's mental model of "who currently works here".
    Counts only users belonging to the same tenant as a defense-in-depth
    measure (RLS already handles this but explicit is safer).
    """
    result = await db.execute(
        select(func.count(User.id)).where(
            User.position_id == position_id,
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712 (SQLAlchemy needs ==)
        )
    )
    return int(result.scalar() or 0)


@router.get("", response_model=list[PositionResponse])
async def list_positions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position)
        .where(Position.tenant_id == user.tenant_id)
        .order_by(Position.created_at.desc())
    )
    positions = result.scalars().all()
    responses = []
    for pos in positions:
        course_ids = await _get_course_ids(db, pos.id)
        live = await _live_employee_count(db, pos.id, user.tenant_id)
        responses.append(PositionResponse(
            id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
            department=pos.department, level=pos.level,
            responsibilities=pos.responsibilities, requirements=pos.requirements,
            course_ids=course_ids,
            employee_count=pos.employee_count,
            current_employee_count=live,
            employee_count_stale=pos.employee_count != live,
            created_at=pos.created_at,
        ))
    return responses


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    course_ids = await _get_course_ids(db, pos.id)
    live = await _live_employee_count(db, pos.id, user.tenant_id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids,
        employee_count=pos.employee_count,
        current_employee_count=live,
        employee_count_stale=pos.employee_count != live,
        created_at=pos.created_at,
    )


@router.post("/{position_id}/recalc-employees", response_model=PositionResponse)
async def recalc_employee_count(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually recompute and persist `employee_count` from the live
    `users` table.

    Use when:
    - staff-import added users via a path that bypassed
      `/positions/{id}/assign/{user}` (the only place that calls
      `_update_employee_count` automatically)
    - direct DB writes happened
    - tenant wants to clean up after a bulk edit

    Idempotent and safe to call anytime. Returns the updated PositionResponse
    with `employee_count == current_employee_count` and `employee_count_stale=False`.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    live = await _live_employee_count(db, pos.id, user.tenant_id)
    pos.employee_count = live
    await db.flush()
    await db.refresh(pos)

    course_ids = await _get_course_ids(db, pos.id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids,
        employee_count=pos.employee_count,
        current_employee_count=live,
        employee_count_stale=False,
        created_at=pos.created_at,
    )


@router.post("", response_model=PositionResponse, status_code=201)
async def create_position(
    req: PositionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pos = Position(
        tenant_id=user.tenant_id,
        name=req.name,
        department=req.department,
        level=req.level,
        responsibilities=req.responsibilities,
        requirements=req.requirements,
    )
    db.add(pos)
    await db.flush()

    if req.course_ids:
        await _sync_courses(db, pos.id, req.course_ids, tenant_id=user.tenant_id)
        await db.flush()

    course_ids = await _get_course_ids(db, pos.id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids, employee_count=pos.employee_count,
        created_at=pos.created_at,
    )


@router.put("/{position_id}", response_model=PositionResponse)
async def update_position(
    position_id: UUID,
    req: PositionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update position. If course_ids change, recompute all current
    holders' enrollments via the recompute kernel (B1b).

    This is symmetric in add/remove: adding a course creates
    enrollments, removing a course removes in-progress enrollments
    (completed are kept). P1-4 (asymmetric add-only) is resolved.
    """
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    for field, value in req.model_dump(exclude_unset=True, exclude={"course_ids"}).items():
        # Auto-snapshot JD BEFORE overwriting, so we always have the previous
        # values if responsibilities or requirements change.
        if field in ("responsibilities", "requirements") and getattr(pos, field) != value:
            db.add(PositionJDVersion(
                position_id=pos.id,
                tenant_id=pos.tenant_id,
                responsibilities=pos.responsibilities,
                requirements=pos.requirements,
                source="auto",
                created_by=user.id,
            ))
        setattr(pos, field, value)

    re_enrolled = 0
    if req.course_ids is not None:
        await _sync_courses(db, pos.id, req.course_ids)
        # Symmetric add+remove: run recompute on every holder. The
        # kernel handles both directions in one pass.
        batch = await recompute_position_holders(db, pos.id, user.tenant_id)
        re_enrolled = batch.added

    await db.flush()
    course_ids = await _get_course_ids(db, pos.id)
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids, employee_count=pos.employee_count,
        created_at=pos.created_at,
        re_enrolled=re_enrolled,
    )


@router.delete("/{position_id}", status_code=204)
async def delete_position(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a position.

    Before dropping, recompute every holder so that any enrollments
    coming from this position's PositionCourse rows are removed
    (in-progress only — completed are kept as historical record).
    Without this, holders would keep stale `source='position'`
    enrollments pointing at a deleted position, leaking rule data
    into the materialized view.
    """
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    # Recompute every holder first. recompute_enrollments reads the
    # user's position_id; once the row is gone we'd see the user's
    # old position as "no position" and not know to unenroll.
    holder_result = await db.execute(
        select(User.id).where(
            User.position_id == position_id,
            User.tenant_id == user.tenant_id,
        )
    )
    holder_ids = [r[0] for r in holder_result.all()]
    for user_id in holder_ids:
        await recompute_enrollments(db, user_id)
    # Set position_id NULL so the user no longer claims this position.
    await db.execute(
        User.__table__.update()
        .where(User.id.in_(holder_ids))
        .values(position_id=None)
    )
    await db.delete(pos)


class _PositionCourseItem(BaseModel):
    """Body for POST /v1/positions/{id}/courses (B1c).

    The same schema is accepted by POST /v1/departments/{id}/courses
    in the departments router.
    """

    course_id: UUID
    required: bool = True


@router.post(
    "/{position_id}/courses",
    response_model=PositionResponse,
    status_code=201,
)
async def attach_course_to_position(
    position_id: UUID,
    body: _PositionCourseItem,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist", "admin", "superadmin")),
):
    """Attach a single course to a Position (B1c).

    Idempotent: attaching a course that's already linked returns 200
    (not 409) with the current state of the position — that way the
    UI's "save" button can be re-clicked without surprises.

    Side effect: triggers a single-user recompute through the kernel
    for every holder of this position. The recompute is fan-outed via
    `recompute_position_holders` (see batch_service.py).
    """
    pos = await db.get(Position, position_id)
    if pos is None or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    # Idempotent insert. ON CONFLICT in the model handles the case
    # where (position_id, course_id) already exists.
    existing = await db.scalar(
        select(PositionCourse).where(
            PositionCourse.position_id == position_id,
            PositionCourse.course_id == body.course_id,
        )
    )
    if existing is None:
        db.add(
            PositionCourse(
                position_id=position_id,
                course_id=body.course_id,
                tenant_id=user.tenant_id,  # NOT NULL constraint; smoke 2026-06-30
                required=body.required,
            )
        )
        await db.flush()
    else:
        # Mutate `required` in-place if the user is changing the flag
        # on an existing binding.
        existing.required = body.required

    # Fan-out: re-derive every holder's enrollments from the rules.
    batch = await recompute_position_holders(db, position_id, user.tenant_id)
    await db.flush()

    course_ids = await _get_course_ids(db, position_id)
    return PositionResponse(
        id=pos.id,
        tenant_id=pos.tenant_id,
        name=pos.name,
        department=pos.department,
        level=pos.level,
        responsibilities=pos.responsibilities,
        requirements=pos.requirements,
        course_ids=course_ids,
        employee_count=pos.employee_count,
        created_at=pos.created_at,
        re_enrolled=batch.added,
    )


@router.delete(
    "/{position_id}/courses/{course_id}",
    response_model=PositionResponse,
)
async def detach_course_from_position(
    position_id: UUID,
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist", "admin", "superadmin")),
):
    """Detach a single course from a Position (B1c).

    Side effect: re-derive every holder's enrollments. Completions
    are kept; in-progress enrollments from this position are removed
    (B1a's symmetric add/remove semantics).
    """
    pos = await db.get(Position, position_id)
    if pos is None or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    binding = await db.scalar(
        select(PositionCourse).where(
            PositionCourse.position_id == position_id,
            PositionCourse.course_id == course_id,
        )
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")

    await db.delete(binding)
    await db.flush()

    # Fan-out recompute — same shape as attach.
    batch = await recompute_position_holders(db, position_id, user.tenant_id)
    await db.flush()

    course_ids = await _get_course_ids(db, position_id)
    return PositionResponse(
        id=pos.id,
        tenant_id=pos.tenant_id,
        name=pos.name,
        department=pos.department,
        level=pos.level,
        responsibilities=pos.responsibilities,
        requirements=pos.requirements,
        course_ids=course_ids,
        employee_count=pos.employee_count,
        created_at=pos.created_at,
        re_enrolled=batch.added,
    )


@router.post("/{position_id}/assign/{target_user_id}")
async def assign_user_to_position(
    position_id: UUID,
    target_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Assign a user to a position.

    Side effects: the recompute kernel derives the user's enrollments
    from the new position's PositionCourse rows (and the position's
    department's DepartmentCourse rows, B1b). Completed enrollments
    are kept; in-progress ones are dropped; manual ones are protected.

    Replaces the previous hand-rolled add/remove logic, which had a
    known asymmetry bug (only handled add, missed remove).
    """
    # Verify position exists
    pos_result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = pos_result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    # Verify target user exists
    target = await db.get(User, target_user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")

    old_position_id = target.position_id
    target.position_id = position_id
    await _update_employee_count(db, position_id, user.tenant_id)
    if old_position_id and old_position_id != position_id:
        await _update_employee_count(db, old_position_id, user.tenant_id)

    # Single recompute call: handles add (new position's courses)
    # AND remove (old position's courses not in new) AND manual
    # protection AND completed protection. Replaces the old two-step
    # add/remove with a single source of truth.
    outcome = await recompute_enrollments(db, target_user_id)
    await db.flush()

    return {
        "status": "ok",
        "position": pos.name,
        "added": outcome.added,
        "removed": outcome.removed,
        "skipped_manual": outcome.skipped_manual,
        "protected_completed": outcome.protected_completed,
    }


@router.post("/unassign/{target_user_id}")
async def unassign_user_from_position(
    target_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a user from their position. The recompute kernel
    removes rule-driven enrollments (in_progress only — completed
    are kept as historical record) and protects manual ones.
    """
    target = await db.get(User, target_user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")

    old_position_id = target.position_id
    target.position_id = None
    if old_position_id:
        await _update_employee_count(db, old_position_id, user.tenant_id)

    outcome = await recompute_enrollments(db, target_user_id)
    await db.flush()
    return {
        "status": "ok",
        "removed": outcome.removed,
        "protected_completed": outcome.protected_completed,
    }


# ── JD analysis ─────────────────────────────────────────────


def _extract_text(content: bytes, filename: str) -> str:
    """Extract text from uploaded file (PDF, DOCX, TXT)."""
    ext = os.path.splitext(filename or "")[1].lower()

    if ext == ".txt":
        return content.decode("utf-8", errors="replace")

    if ext == ".pdf":
        try:
            import io

            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return ""

    if ext in (".docx", ".doc"):
        try:
            import io

            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.warning(f"DOCX extraction failed: {e}")
            return ""

    return content.decode("utf-8", errors="replace")


@router.post("/analyze-jd")
@router.post("/bulk-create", response_model=BulkPositionResponse, status_code=201)
async def bulk_create_positions(
    payload: BulkPositionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create multiple positions in a single transaction.

    All-or-nothing per position: each is created in its own savepoint,
    so a failure on item #3 doesn't roll back items #1-#2 (or #4+).
    """
    if not payload.items:
        raise HTTPException(status_code=400, detail="items is empty")

    created: list[BulkPositionCreated] = []
    failed: list[BulkPositionFailed] = []

    for idx, item in enumerate(payload.items):
        try:
            if not item.name.strip():
                raise ValueError("name is empty")
            pos_id = uuid.uuid4()
            db.add(Position(
                id=pos_id,
                tenant_id=user.tenant_id,
                name=item.name.strip(),
                department=item.department.strip(),
                level=item.level.strip(),
                responsibilities=item.responsibilities.strip(),
                requirements=item.requirements.strip(),
                employee_count=0,
            ))
            if item.course_ids:
                await _sync_courses(db, pos_id, item.course_ids)
            await db.flush()
            created.append(BulkPositionCreated(index=idx, id=pos_id, name=item.name.strip()))
        except Exception as e:
            failed.append(BulkPositionFailed(
                index=idx,
                name=item.name,
                error=f"{type(e).__name__}: {e}",
            ))
            # Roll back this savepoint but keep going for the rest
            await db.rollback()

    await db.commit()
    return BulkPositionResponse(created=created, failed=failed)
