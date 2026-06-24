"""Positions — API router with course attachment + JD analysis"""
import uuid
import os
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.models.enrollment import Enrollment
from app.modules.positions.models import Position, PositionCourse

logger = logging.getLogger(__name__)
from app.modules.positions.schemas import PositionCreate, PositionUpdate, PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])


# ── Helpers ──────────────────────────────────────────────────


async def _sync_courses(db: AsyncSession, position_id: UUID, course_ids: list[UUID] | None):
    """Replace all position_courses for a position."""
    if course_ids is None:
        return
    await db.execute(delete(PositionCourse).where(PositionCourse.position_id == position_id))
    for cid in course_ids:
        db.add(PositionCourse(position_id=position_id, course_id=cid))


async def _get_course_ids(db: AsyncSession, position_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(PositionCourse.course_id).where(PositionCourse.position_id == position_id)
    )
    return [row[0] for row in result.all()]


async def _bulk_enroll_users_in_courses(
    db: AsyncSession,
    user_ids: list[UUID],
    course_ids: list[UUID],
    tenant_id: UUID,
) -> int:
    """Enroll users in courses, skipping existing. Returns count of NEW enrollments.

    Single IN-query for dedup instead of N+1.
    """
    if not user_ids or not course_ids:
        return 0

    # Single query: find all existing enrollments for this batch
    existing_result = await db.execute(
        select(Enrollment.user_id, Enrollment.course_id).where(
            Enrollment.user_id.in_(user_ids),
            Enrollment.course_id.in_(course_ids),
            Enrollment.tenant_id == tenant_id,
        )
    )
    existing_pairs = {(r[0], r[1]) for r in existing_result.all()}

    new_count = 0
    for uid in user_ids:
        for cid in course_ids:
            if (uid, cid) in existing_pairs:
                continue
            db.add(Enrollment(
                id=uuid.uuid4(),
                course_id=cid,
                user_id=uid,
                tenant_id=tenant_id,
                status="enrolled",
            ))
            new_count += 1
    return new_count


async def _bulk_unenroll_users_from_courses(
    db: AsyncSession,
    user_ids: list[UUID],
    course_ids: list[UUID],
    tenant_id: UUID,
    only_active: bool = True,
) -> int:
    """Remove enrollments. Returns count of removed.

    By default, only removes 'enrolled' status (in-progress) — completed stays
    as a historical record. Set only_active=False to force-remove all.
    """
    if not user_ids or not course_ids:
        return 0
    from sqlalchemy import and_
    conds = [
        Enrollment.user_id.in_(user_ids),
        Enrollment.course_id.in_(course_ids),
        Enrollment.tenant_id == tenant_id,
    ]
    if only_active:
        conds.append(Enrollment.status == "enrolled")
    result = await db.execute(
        delete(Enrollment).where(and_(*conds))
    )
    return result.rowcount or 0


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
        responses.append(PositionResponse(
            id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
            department=pos.department, level=pos.level,
            responsibilities=pos.responsibilities, requirements=pos.requirements,
            course_ids=course_ids, employee_count=pos.employee_count,
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
    return PositionResponse(
        id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
        department=pos.department, level=pos.level,
        responsibilities=pos.responsibilities, requirements=pos.requirements,
        course_ids=course_ids, employee_count=pos.employee_count,
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
        await _sync_courses(db, pos.id, req.course_ids)
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
    """Update position. If course_ids change, re-enroll all current holders."""
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    for field, value in req.model_dump(exclude_unset=True, exclude={"course_ids"}).items():
        setattr(pos, field, value)

    re_enrolled = 0
    if req.course_ids is not None:
        new_course_ids = set(req.course_ids)
        old_course_ids = set(await _get_course_ids(db, pos.id))

        await _sync_courses(db, pos.id, req.course_ids)

        # Re-enroll all current holders in newly added courses
        added = new_course_ids - old_course_ids
        if added:
            holders_result = await db.execute(
                select(User.id).where(
                    User.position_id == position_id,
                    User.tenant_id == user.tenant_id,
                )
            )
            holder_ids = [r[0] for r in holders_result.all()]
            re_enrolled = await _bulk_enroll_users_in_courses(
                db, holder_ids, list(added), user.tenant_id
            )

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
    result = await db.execute(
        select(Position)
        .where(Position.id == position_id, Position.tenant_id == user.tenant_id)
    )
    pos = result.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    await db.delete(pos)


@router.post("/{position_id}/assign/{target_user_id}")
async def assign_user_to_position(
    position_id: UUID,
    target_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Assign a user to a position and auto-enroll them in all position courses.

    If user already had a different position, their OLD position's courses that
    are not in the NEW position are unenrolled (only in-progress ones).
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

    # Unenroll from old position's courses that aren't in the new position
    unenrolled = 0
    if old_position_id and old_position_id != position_id:
        old_course_ids = await _get_course_ids(db, old_position_id)
        new_course_ids = set(await _get_course_ids(db, position_id))
        to_remove = [cid for cid in old_course_ids if cid not in new_course_ids]
        if to_remove:
            unenrolled = await _bulk_unenroll_users_from_courses(
                db, [target_user_id], to_remove, user.tenant_id
            )
        # Update old position count
        await _update_employee_count(db, old_position_id, user.tenant_id)

    # Auto-enroll in new position's courses
    course_ids = await _get_course_ids(db, position_id)
    newly_enrolled = await _bulk_enroll_users_in_courses(
        db, [target_user_id], course_ids, user.tenant_id
    )

    await db.flush()

    return {
        "status": "ok",
        "position": pos.name,
        "courses_attached": len(course_ids),
        "newly_enrolled": newly_enrolled,
        "unenrolled_from_old": unenrolled,
    }


@router.post("/unassign/{target_user_id}")
async def unassign_user_from_position(
    target_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a user from their position. Active enrollments in position's courses
    are removed (completed enrollments stay as historical record)."""
    target = await db.get(User, target_user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")

    old_position_id = target.position_id
    target.position_id = None

    unenrolled = 0
    if old_position_id:
        old_course_ids = await _get_course_ids(db, old_position_id)
        if old_course_ids:
            unenrolled = await _bulk_unenroll_users_from_courses(
                db, [target_user_id], old_course_ids, user.tenant_id
            )
        await _update_employee_count(db, old_position_id, user.tenant_id)

    await db.flush()
    return {"status": "ok", "unenrolled": unenrolled}


# ── JD analysis ─────────────────────────────────────────────


def _extract_text(content: bytes, filename: str) -> str:
    """Extract text from uploaded file (PDF, DOCX, TXT)."""
    ext = os.path.splitext(filename or "")[1].lower()

    if ext == ".txt":
        return content.decode("utf-8", errors="replace")

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return ""

    if ext in (".docx", ".doc"):
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.warning(f"DOCX extraction failed: {e}")
            return ""

    return content.decode("utf-8", errors="replace")


@router.post("/analyze-jd")
async def analyze_jd(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze a job description document and extract position fields."""
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    text = _extract_text(content, file.filename or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    # Truncate to avoid token overflow
    text = text[:8000]

    prompt = f"""Проанализируй текст должностной инструкции и извлеки структурированные данные.

ТЕКСТ:
{text}

Ответь ТОЛЬКО валидным JSON без markdown-обёрток:
{{
  "name": "Название должности (на русском)",
  "department": "Отдел/департамент",
  "level": "junior/middle/senior/lead/head",
  "responsibilities": "Краткий список ключевых обязанностей (3-7 пунктов через перенос строки)",
  "requirements": "Краткий список требований (3-7 пунктов через перенос строки)"
}}

Если информация не найдена — поставь пустую строку."""

    try:
        from app.modules.ai.llm_client import create_llm
        llm = create_llm(temperature=0.3, max_tokens=1024)
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        raw = response.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}")
        raise HTTPException(status_code=422, detail="AI returned invalid response. Please try again.")
    except Exception as e:
        logger.error(f"JD analysis failed: {e}")
        raise HTTPException(status_code=503, detail="AI service unavailable. Please try again later.")

    return {
        "name": data.get("name", ""),
        "department": data.get("department", ""),
        "level": data.get("level", ""),
        "responsibilities": data.get("responsibilities", ""),
        "requirements": data.get("requirements", ""),
    }
