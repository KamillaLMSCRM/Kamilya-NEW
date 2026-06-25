"""Positions — API router with course attachment + JD analysis"""
import uuid
import os
import json
import logging
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.models.enrollment import Enrollment
from app.modules.positions.models import Position, PositionCourse

logger = logging.getLogger(__name__)
from app.modules.positions.schemas import (
    PositionCreate,
    PositionUpdate,
    PositionResponse,
    BulkJDItem,
    BulkJDResponse,
    BulkPositionRequest,
    BulkPositionResponse,
    BulkPositionCreated,
    BulkPositionFailed,
    RecommendedContentItem,
    RecommendedContentResponse,
    GenerateJDRequest,
    GenerateJDResponse,
    JDPreviewRequest,
    JDPreviewItem,
    JDPreviewResponse,
    RecommendedCourseItem,
    RecommendedCoursesResponse,
    JDVersionItem,
    JDVersionListResponse,
    JDVersionCreate,
    JDRestoreResponse,
    JDAuditItem,
    JDAuditResponse,
    CourseSuggestion,
    CourseSuggestionsResponse,
    CreateCourseItem,
    CreateCoursesRequest,
    CreatedCourseRef,
    CreateCoursesResponse,
    QuizQuestionDraft,
    SuggestOnboardingQuizResponse,
    SavePositionQuizRequest,
    PositionQuizResponse,
)
from app.modules.positions.models import PositionJDVersion, PositionQuiz
from app.modules.courses.models import Course

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
        "issues": _audit_jd_text(
            text,
            data.get("name", ""),
            data.get("responsibilities", ""),
            data.get("requirements", ""),
        ),
    }


# ── JD audit (LLM quality check) ──────────────────────────────


async def _audit_jd_text(
    text: str,
    name: str = "",
    responsibilities: str = "",
    requirements: str = "",
) -> list[JDAuditItem]:
    """Run an LLM quality audit on a JD and return a list of findings.

    Categories:
    - completeness: missing required sections (KPIs, safety, compliance)
    - specificity: vague wording, no measurable outcomes
    - clarity: jargon, ambiguous pronouns, out-of-date terms
    - compliance: missing ОТ/ИБ/etc. if relevant for the role
    - structure: order/format issues
    - other: anything else

    Severity:
    - "warning": should fix before publishing
    - "suggestion": nice-to-have improvement
    - "ok": positive observation (also surfaced, capped to top-2)

    Returns [] on AI failure — audit is best-effort, never blocks the
    main analyze-jd response.
    """
    if not text.strip():
        return []

    from app.modules.ai.llm_client import create_llm

    audit_prompt = f"""Ты — HR-эксперт по качеству должностных инструкций в Казахстане.
Проведи АУДИТ этой ДИ и найди 3-7 проблем или рекомендаций по улучшению.

КОНТЕКСТ:
- Название: {name or "(не указано)"}

ТЕКСТ ДИ:
{text[:6000]}

Ответь ТОЛЬКО валидным JSON без markdown-обёрток:
{{
  "issues": [
    {{
      "severity": "warning" | "suggestion" | "ok",
      "category": "completeness" | "specificity" | "clarity" | "compliance" | "structure" | "other",
      "field": "responsibilities" | "requirements" | "name" | "",
      "message": "Краткое описание проблемы на русском (1 предложение)",
      "suggestion": "Конкретное предложение как исправить (или пустая строка)"
    }}
  ]
}}

Сфокусируйся на проблемах, которые РЕАЛЬНО важны для казахстанской компании:
- Полнота: есть ли обязанности, требования, KPI, взаимодействие?
- Конкретность: обязанности измеримы? (не "выполняет задачи", а "обрабатывает 50 заявок/день")
- Compliance: для производства — ОТ/ТБ, для IT — ИБ, для финансов — ПОД/ФТ
- Ясность: нет ли устаревших формулировок, двусмысленностей

Если ДИ хорошая — всё равно верни 1-2 positive findings (severity="ok")."""

    try:
        llm = create_llm(temperature=0.2, max_tokens=1500)
        response = await llm.ainvoke([{"role": "user", "content": audit_prompt}])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        data = json.loads(raw)
        items_raw = data.get("issues", [])
        if not isinstance(items_raw, list):
            return []
        # Validate and cap
        valid: list[JDAuditItem] = []
        for it in items_raw[:10]:  # hard cap at 10
            if not isinstance(it, dict):
                continue
            try:
                valid.append(JDAuditItem(
                    severity=str(it.get("severity", "suggestion")),
                    category=str(it.get("category", "other")),
                    field=str(it.get("field", "")),
                    message=str(it.get("message", "")),
                    suggestion=str(it.get("suggestion", "")),
                ))
            except Exception:
                continue
        return valid
    except Exception as e:
        logger.warning(f"JD audit failed: {e}")
        return []


@router.post("/{position_id}/jd-audit", response_model=JDAuditResponse)
async def jd_audit(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-audit a saved position's JD (no file upload needed).

    Uses the position's current responsibilities + requirements + name
    as input. Returns a fresh list of issues. Useful for the methodologist
    who wants to check existing positions without re-uploading files.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    # Build pseudo-text from saved fields (no file)
    text = f"{pos.responsibilities}\n\n{pos.requirements}".strip()
    if not text:
        return JDAuditResponse(items=[])

    issues = await _audit_jd_text(text, pos.name, pos.responsibilities, pos.requirements)
    return JDAuditResponse(items=issues)


@router.post("/{position_id}/restore-jd/{version_id}", response_model=JDRestoreResponse)
async def restore_jd_version(
    position_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore a position's JD from a historical version.

    This creates a NEW auto-snapshot of the current values (so the
    restore is itself reversible) and overwrites with the version's content.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    ver = await db.get(PositionJDVersion, version_id)
    if not ver or ver.position_id != position_id:
        raise HTTPException(status_code=404, detail="Version not found")

    # Snapshot current BEFORE restoring
    db.add(PositionJDVersion(
        position_id=pos.id,
        tenant_id=pos.tenant_id,
        responsibilities=pos.responsibilities,
        requirements=pos.requirements,
        source="auto",
        note=f"auto-snapshot before restore from version {version_id}",
        created_by=user.id,
    ))

    pos.responsibilities = ver.responsibilities
    pos.requirements = ver.requirements
    await db.commit()
    await db.refresh(pos)

    course_ids = await _get_course_ids(db, pos.id)
    return JDRestoreResponse(
        position=PositionResponse(
            id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
            department=pos.department, level=pos.level,
            responsibilities=pos.responsibilities, requirements=pos.requirements,
            course_ids=course_ids, employee_count=pos.employee_count,
            created_at=pos.created_at,
        ),
        restored_from_version_id=version_id,
    )


# ── AI course suggestions (Phase 2) ────────────────────────────


@router.post("/{position_id}/suggest-courses", response_model=CourseSuggestionsResponse)
async def suggest_courses(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI proposes 3-5 course topics for this position based on its JD.

    The suggestions are titles + descriptions + chapter estimates —
    enough for the methodologist to pick which to create as draft
    courses. Actual course content (modules, lessons) is generated
    separately via /ai/generate/ (the methodologist picks the source
    documents there).

    Best-effort: if the LLM fails, returns [] with no error.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    jd_text = f"""Должность: {pos.name}
Отдел: {pos.department or '(не указан)'}
Уровень: {pos.level or '(не указан)'}

ОБЯЗАННОСТИ:
{pos.responsibilities or '(не указаны)'}

ТРЕБОВАНИЯ:
{pos.requirements or '(не указаны)'}"""

    if not (pos.responsibilities.strip() or pos.requirements.strip()):
        return CourseSuggestionsResponse(items=[])

    from app.modules.ai.llm_client import create_llm

    prompt = f"""На основе должностной инструкции предложи 3-5 тем обучающих курсов для онбординга сотрудника на эту должность.

{jd_text}

Каждый курс должен закрывать конкретный навык или знание, нужное для этой работы. Избегай общих тем типа "Введение в компанию" — фокус на профессиональных hard-skills.

Ответь ТОЛЬКО валидным JSON без markdown-обёрток:
{{
  "items": [
    {{
      "title": "Название курса (короткое, понятное)",
      "description": "Чему научится сотрудник, 1-2 предложения",
      "estimated_chapters": 4,
      "reason": "Почему этот курс важен для этой должности (1 предложение)"
    }}
  ]
}}

Пиши на русском. Курсы должны быть конкретными и actionable, не общими."""

    try:
        llm = create_llm(temperature=0.5, max_tokens=1500)
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        data = json.loads(raw)
        items_raw = data.get("items", [])
        if not isinstance(items_raw, list):
            return CourseSuggestionsResponse(items=[])
        valid: list[CourseSuggestion] = []
        for it in items_raw[:5]:  # cap at 5
            if not isinstance(it, dict):
                continue
            title = str(it.get("title", "")).strip()
            if not title:
                continue
            try:
                valid.append(CourseSuggestion(
                    title=title[:200],
                    description=str(it.get("description", "")).strip()[:2000],
                    estimated_chapters=max(1, min(20, int(it.get("estimated_chapters", 3)))),
                    reason=str(it.get("reason", "")).strip()[:500],
                ))
            except Exception:
                continue
        return CourseSuggestionsResponse(items=valid)
    except Exception as e:
        logger.warning(f"suggest-courses failed: {e}")
        return CourseSuggestionsResponse(items=[])


@router.post("/{position_id}/create-courses", response_model=CreateCoursesResponse, status_code=201)
async def create_courses_from_suggestions(
    position_id: UUID,
    payload: CreateCoursesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create draft courses from selected AI suggestions and attach
    them to this position.

    Each new course:
    - status = 'draft' (methodologist fills in content later)
    - tenant_id = user's tenant
    - linked to position via position_courses (auto-enrolls future hires)

    Returns the list of created courses with their ids. The methodologist
    can then go to /ai/generate/ to fill in the actual content, or edit
    the course directly.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    if not payload.items:
        raise HTTPException(status_code=400, detail="items is empty")

    created_refs: list[CreatedCourseRef] = []
    for item in payload.items:
        course_id = uuid.uuid4()
        db.add(Course(
            id=course_id,
            tenant_id=user.tenant_id,
            title=item.title.strip(),
            description=item.description.strip(),
            status="draft",
            ai_generated=False,
            created_by=user.id,
        ))
        # Attach to position so new employees auto-enroll
        db.add(PositionCourse(position_id=position_id, course_id=course_id))
        created_refs.append(CreatedCourseRef(id=str(course_id), title=item.title.strip()))

    await db.commit()

    return CreateCoursesResponse(
        created=created_refs,
        attached_to_position=len(created_refs),
    )


# ── Bulk JD analysis (multi-file upload) ──────────────────────


@router.post("/bulk-analyze-jd", response_model=BulkJDResponse)
async def bulk_analyze_jd(
    files: List[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    """Analyze multiple JD files in one request.

    Returns a list of BulkJDItem — one per file. Per-file failures are
    captured in `error` (e.g. unsupported format, AI parse error) so the
    methodologist sees a full preview, not just a 500 on file #5 of 12.

    Limits:
    - Max 50 files per request (UI also enforces)
    - Each file max 5 MB (per existing single-JD rule)
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 50:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files ({len(files)}). Max 50 per request.",
        )

    from app.modules.ai.llm_client import create_llm

    items: list[BulkJDItem] = []

    for f in files:
        item = BulkJDItem(filename=f.filename or "<unnamed>")
        try:
            content = await f.read()
            if len(content) > 5 * 1024 * 1024:
                item.error = "File too large (max 5MB)"
                items.append(item)
                continue

            text_ = _extract_text(content, f.filename or "")
            if not text_.strip():
                item.error = "Could not extract text from file"
                items.append(item)
                continue

            text_ = text_[:8000]

            prompt = f"""Проанализируй текст должностной инструкции и извлеки структурированные данные.

ТЕКСТ:
{text_}

Ответь ТОЛЬКО валидным JSON без markdown-обёрток:
{{
  "name": "Название должности (на русском)",
  "department": "Отдел/департамент",
  "level": "junior/middle/senior/lead/head",
  "responsibilities": "Краткий список ключевых обязанностей (3-7 пунктов через перенос строки)",
  "requirements": "Краткий список требований (3-7 пунктов через перенос строки)"
}}

Если информация не найдена — поставь пустую строку."""

            llm = create_llm(temperature=0.3, max_tokens=1024)
            response = await llm.ainvoke([{"role": "user", "content": prompt}])
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            data = json.loads(raw)

            item.name = (data.get("name") or "").strip()
            item.department = (data.get("department") or "").strip()
            item.level = (data.get("level") or "").strip()
            item.responsibilities = (data.get("responsibilities") or "").strip()
            item.requirements = (data.get("requirements") or "").strip()
            # Run AI audit on this item (best-effort, never blocks)
            try:
                item.issues = await _audit_jd_text(
                    text_,
                    item.name,
                    item.responsibilities,
                    item.requirements,
                )
            except Exception as audit_err:
                logger.warning(f"bulk-analyze-jd: audit failed for {item.filename}: {audit_err}")
        except json.JSONDecodeError:
            item.error = "AI returned invalid response"
            logger.warning(f"bulk-analyze-jd: invalid JSON for {item.filename}")
        except Exception as e:
            item.error = f"Failed: {type(e).__name__}"
            logger.error(f"bulk-analyze-jd: error for {item.filename}: {e}")
        finally:
            items.append(item)

    return BulkJDResponse(items=items)


# ── Bulk create positions ─────────────────────────────────────


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


# ── Recommended content (vector search) ────────────────────────


@router.get("/{position_id}/recommended-content", response_model=RecommendedContentResponse)
async def recommended_content(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 5,
):
    """Return top-N documents most semantically similar to a position's JD.

    Uses the responsibilities + requirements as the query, embeds via
    Qwen (or hash fallback), and runs cosine similarity against
    document_embeddings filtered to the current tenant.

    Returns document metadata (not courses directly) because the
    document_embeddings table is the source of truth for content;
    courses are built on top of documents. The methodologist can then
    decide which doc/course to attach.
    """
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=400, detail="limit must be 1..20")

    # Load position (and verify tenant)
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    query_text = f"{pos.responsibilities}\n{pos.requirements}".strip()
    if not query_text:
        return RecommendedContentResponse(items=[])

    # Embed
    from app.modules.ai.ingestion import EmbeddingsProvider
    provider = EmbeddingsProvider()
    embeddings = await provider.embed([query_text])
    emb = embeddings[0]
    emb_str = str(emb)

    # Vector search: top `limit * 5` chunks, then dedupe by doc_id, then trim.
    # We over-fetch because many chunks can come from the same doc.
    raw_limit = limit * 5
    sql = text(f"""
        SELECT doc_id, doc_name, headings,
               1 - (embedding <=> CAST(:emb AS vector)) as distance
        FROM document_embeddings
        WHERE tenant_id = :tenant_id
        ORDER BY distance
        LIMIT :n
    """)

    result = await db.execute(
        sql,
        {"emb": emb_str, "tenant_id": str(user.tenant_id), "n": raw_limit},
    )
    rows = result.fetchall()

    # Dedupe by doc_id, keep highest-similarity chunk per doc
    seen: dict[UUID, RecommendedContentItem] = {}
    for row in rows:
        doc_id, doc_name, headings, distance = row[0], row[1], row[2], float(row[3])
        if doc_id in seen:
            continue
        seen[doc_id] = RecommendedContentItem(
            doc_id=doc_id,
            doc_name=doc_name or "",
            similarity=round(distance, 4),
            headings=headings or "",
        )
        if len(seen) >= limit:
            break

    return RecommendedContentResponse(items=list(seen.values()))


# ── Generate JD from name (no file) ────────────────────────────


@router.post("/generate-jd-from-name", response_model=GenerateJDResponse)
async def generate_jd_from_name(
    req: GenerateJDRequest,
    user: User = Depends(get_current_user),
):
    """AI generates responsibilities + requirements from a job title.

    Use case: the methodologist is creating a new position but doesn't
    have a JD document yet. They enter the title (and optionally
    department + level), and we generate a reasonable draft they can edit.

    Same LLM prompt as analyze-jd, just no text extraction step.
    """
    from app.modules.ai.llm_client import create_llm

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    prompt = f"""Сгенерируй типичные обязанности и требования для должности.

НАЗВАНИЕ: {name}
{f"ОТДЕЛ: {req.department}" if req.department else ""}
{f"УРОВЕНЬ: {req.level}" if req.level else ""}

Ответь ТОЛЬКО валидным JSON без markdown-обёрток:
{{
  "name": "Название должности (на русском, уточнённое)",
  "department": "Отдел/департамент (предложение, если не указан)",
  "level": "junior/middle/senior/lead/head",
  "responsibilities": "Список 3-7 ключевых обязанностей через перенос строки",
  "requirements": "Список 3-7 требований через перенос строки"
}}

Пиши реалистично, как для реальной должности в казахстанской компании."""

    try:
        llm = create_llm(temperature=0.4, max_tokens=1024)
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="AI returned invalid response. Please try again.")
    except Exception as e:
        logger.error(f"generate-jd-from-name failed: {e}")
        raise HTTPException(status_code=503, detail="AI service unavailable. Please try again later.")

    return GenerateJDResponse(
        name=(data.get("name") or name).strip(),
        department=(data.get("department") or req.department or "").strip(),
        level=(data.get("level") or req.level or "").strip(),
        responsibilities=(data.get("responsibilities") or "").strip(),
        requirements=(data.get("requirements") or "").strip(),
    )


# ── JD preview / diff against current position ────────────────


@router.post("/{position_id}/jd-preview", response_model=JDPreviewResponse)
async def jd_preview(
    position_id: UUID,
    req: JDPreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Compute a field-by-field diff between the position's current values
    and what the AI would propose given the input (text or pre-filled fields).

    The user reviews and clicks 'Apply' to overwrite, or edits manually.
    No mutation of the position.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    # If text is provided, run analyze-jd-style extraction
    proposed_name = req.name
    proposed_department = req.department
    proposed_level = req.level
    proposed_resp = ""
    proposed_req = ""

    if req.text.strip():
        from app.modules.ai.llm_client import create_llm
        text = req.text.strip()[:8000]
        prompt = f"""Проанализируй текст должностной инструкции и сравни с текущими значениями.

ТЕКСТ:
{text}

ТЕКУЩИЕ ЗНАЧЕНИЯ:
- name: {pos.name}
- department: {pos.department or '(пусто)'}
- level: {pos.level or '(пусто)'}
- responsibilities: {pos.responsibilities or '(пусто)'}
- requirements: {pos.requirements or '(пусто)'}

Верни ТОЛЬКО валидный JSON с предложенными значениями (используй текущие, если в тексте нет новых):
{{
  "name": "{pos.name}",
  "department": "{pos.department}",
  "level": "{pos.level}",
  "responsibilities": "(уточнённый текст)",
  "requirements": "(уточнённый текст)"
}}"""
        try:
            llm = create_llm(temperature=0.3, max_tokens=1024)
            response = await llm.ainvoke([{"role": "user", "content": prompt}])
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            data = json.loads(raw)
            proposed_name = (data.get("name") or pos.name).strip()
            proposed_department = (data.get("department") or pos.department or "").strip()
            proposed_level = (data.get("level") or pos.level or "").strip()
            proposed_resp = (data.get("responsibilities") or "").strip()
            proposed_req = (data.get("requirements") or "").strip()
        except Exception as e:
            logger.error(f"jd-preview LLM failed: {e}")
            # Fall through with pre-filled values only
    else:
        # No text, just use the pre-filled values from req as "proposed"
        proposed_resp = req.name  # not used; just keep current

    def _diff(field: str, current: str, proposed: str) -> JDPreviewItem:
        return JDPreviewItem(
            field=field,
            current=current or "",
            proposed=proposed or "",
            changed=(current or "").strip() != (proposed or "").strip(),
        )

    items = [
        _diff("name", pos.name, proposed_name),
        _diff("department", pos.department, proposed_department),
        _diff("level", pos.level, proposed_level),
        _diff("responsibilities", pos.responsibilities, proposed_resp),
        _diff("requirements", pos.requirements, proposed_req),
    ]
    return JDPreviewResponse(items=items)


# ── Recommended courses (text-match against course titles) ─────


@router.get("/{position_id}/recommended-courses", response_model=RecommendedCoursesResponse)
async def recommended_courses(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 5,
):
    """Return top-N courses whose content (via document embeddings)
    is most semantically similar to the position's JD.

    Unlike /recommended-content (which returns docs directly), this
    endpoint aggregates by course: if any document in the course
    library is similar to the position, the course is recommended.

    Aggregation strategy: for each top doc_id, look at all courses
    in the tenant; for each course, compute the avg similarity of
    its' chunks to the position. Return top-N unique courses.

    This is a simple heuristic — proper aggregation would require a
    `course_documents` table (TODO: separate PR).
    """
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=400, detail="limit must be 1..20")

    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    query_text = f"{pos.responsibilities}\n{pos.requirements}".strip()
    if not query_text:
        return RecommendedCoursesResponse(items=[])

    from app.modules.ai.ingestion import EmbeddingsProvider
    provider = EmbeddingsProvider()
    embeddings = await provider.embed([query_text])
    emb_str = str(embeddings[0])

    # Get top 25 chunks
    sql = text(f"""
        SELECT doc_id, doc_name, headings,
               1 - (embedding <=> CAST(:emb AS vector)) as distance
        FROM document_embeddings
        WHERE tenant_id = :tenant_id
        ORDER BY distance
        LIMIT 25
    """)
    result = await db.execute(sql, {"emb": emb_str, "tenant_id": str(user.tenant_id)})
    chunks = result.fetchall()

    # Group chunks by doc_name (heuristic for course identity, since
    # there's no formal document-to-course mapping). Best doc_name in
    # the tenant becomes a course recommendation.
    by_doc: dict[str, tuple[float, str]] = {}
    for doc_id, doc_name, headings, distance in chunks:
        key = (doc_name or "").strip()
        if not key:
            continue
        if key not in by_doc or by_doc[key][0] < float(distance):
            by_doc[key] = (float(distance), str(doc_id))

    # Also list tenant's courses and try to fuzzy-match doc_name -> course.title
    courses_result = await db.execute(
        text("SELECT id, title FROM courses WHERE tenant_id = :tid"),
        {"tid": str(user.tenant_id)},
    )
    courses = courses_result.fetchall()
    course_by_title = {(c[1] or "").strip().lower(): (c[0], c[1]) for c in courses}

    items: list[RecommendedCourseItem] = []
    # First pass: exact title match
    for doc_name, (sim, doc_id) in sorted(by_doc.items(), key=lambda x: -x[1][0])[:limit * 2]:
        key = doc_name.lower()
        # Try exact match first
        if key in course_by_title:
            cid, title = course_by_title[key]
            items.append(RecommendedCourseItem(
                course_id=cid, title=title, similarity=round(sim, 4), matched_doc_name=doc_name,
            ))
            continue
        # Try substring match (doc_name contains course title or vice versa)
        for ctitle, (cid, title) in course_by_title.items():
            if ctitle and (ctitle in key or key in ctitle):
                items.append(RecommendedCourseItem(
                    course_id=cid, title=title, similarity=round(sim, 4), matched_doc_name=doc_name,
                ))
                break
        if len(items) >= limit:
            break

    return RecommendedCoursesResponse(items=items[:limit])


# ── JD version history ─────────────────────────────────────────


@router.get("/{position_id}/jd-versions", response_model=JDVersionListResponse)
async def list_jd_versions(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all historical JD snapshots for a position, newest first."""
    # Verify position + tenant
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    result = await db.execute(
        select(PositionJDVersion)
        .where(PositionJDVersion.position_id == position_id)
        .order_by(PositionJDVersion.created_at.desc())
    )
    rows = result.scalars().all()
    return JDVersionListResponse(items=[
        JDVersionItem(
            id=r.id,
            responsibilities=r.responsibilities,
            requirements=r.requirements,
            source=r.source,
            note=r.note,
            created_at=r.created_at,
            created_by=r.created_by,
        )
        for r in rows
    ])


@router.post("/{position_id}/jd-versions", response_model=JDVersionItem, status_code=201)
async def create_jd_version(
    position_id: UUID,
    req: JDVersionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually snapshot the position's CURRENT responsibilities +
    requirements as a version. Useful for marking known-good states
    before a planned refactor."""
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    version = PositionJDVersion(
        position_id=pos.id,
        tenant_id=pos.tenant_id,
        responsibilities=pos.responsibilities,
        requirements=pos.requirements,
        source="manual",
        note=req.note,
        created_by=user.id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)

    return JDVersionItem(
        id=version.id,
        responsibilities=version.responsibilities,
        requirements=version.requirements,
        source=version.source,
        note=version.note,
        created_at=version.created_at,
        created_by=version.created_by,
    )


@router.post("/{position_id}/jd-versions/{version_id}/restore", response_model=JDRestoreResponse)
async def restore_jd_version(
    position_id: UUID,
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore a position's JD from a historical version.

    This creates a NEW auto-snapshot of the current values (so the
    restore is itself reversible) and overwrites with the version's content.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    ver = await db.get(PositionJDVersion, version_id)
    if not ver or ver.position_id != position_id:
        raise HTTPException(status_code=404, detail="Version not found")

    # Snapshot current BEFORE restoring
    db.add(PositionJDVersion(
        position_id=pos.id,
        tenant_id=pos.tenant_id,
        responsibilities=pos.responsibilities,
        requirements=pos.requirements,
        source="auto",
        note=f"auto-snapshot before restore from version {version_id}",
        created_by=user.id,
    ))

    pos.responsibilities = ver.responsibilities
    pos.requirements = ver.requirements
    await db.commit()
    await db.refresh(pos)

    course_ids = await _get_course_ids(db, pos.id)
    return JDRestoreResponse(
        position=PositionResponse(
            id=pos.id, tenant_id=pos.tenant_id, name=pos.name,
            department=pos.department, level=pos.level,
            responsibilities=pos.responsibilities, requirements=pos.requirements,
            course_ids=course_ids, employee_count=pos.employee_count,
            created_at=pos.created_at,
        ),
        restored_from_version_id=version_id,
    )



# ── Onboarding quiz (Phase 3) ──────────────────────────────────


@router.post("/{position_id}/suggest-onboarding-quiz", response_model=SuggestOnboardingQuizResponse)
async def suggest_onboarding_quiz(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI generates a draft onboarding quiz from the position's JD.

    Returns 7 MCQ questions testing whether a new hire understood
    their responsibilities and requirements. The methodologist then
    edits the questions in the modal before calling
    POST /{id}/onboarding-quiz to save.

    Best-effort: LLM failure -> returns a quiz with 0 questions (so the
    UI does not block on AI being down). Methodologist can build the
    quiz manually in that case.
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    if not (pos.responsibilities.strip() or pos.requirements.strip()):
        return SuggestOnboardingQuizResponse(
            title=f"Онбординг: {pos.name}",
            questions=[],
        )

    from app.modules.ai.llm_client import create_llm

    jd_text = f"""Должность: {pos.name}
Отдел: {pos.department or '(не указан)'}
Уровень: {pos.level or '(не указан)'}

ОБЯЗАННОСТИ:
{pos.responsibilities or '(не указаны)'}

ТРЕБОВАНИЯ:
{pos.requirements or '(не указаны)'}"""

    prompt = f"""Сгенерируй онбординг-тест для нового сотрудника на этой должности.

{jd_text}

Цель теста — проверить, что новый сотрудник ПОНЯЛ свои обязанности и требования, а не просто прочитал. Избегай trivia-вопросов про законы/статьи. Фокус на прикладных ситуациях: «что ты сделаешь, если...?», «какой результат ожидается от...?», «какое поведение НЕдопустимо в работе X?».

Сгенерируй 7 вопросов. Каждый — MCQ с 4 вариантами и ровно 1 правильным. К каждому вопросу добавь короткое объяснение правильного ответа.

Ответь ТОЛЬКО валидным JSON без markdown-обёрток:
{{
  "title": "Онбординг: {pos.name}",
  "questions": [
    {{
      "text": "Ситуационный вопрос (что / как / зачем)",
      "type": "MCQ",
      "explanation": "Почему этот ответ правильный (1-2 предложения)",
      "choices": [
        {{"text": "вариант 1", "is_correct": false}},
        {{"text": "вариант 2", "is_correct": true}},
        {{"text": "вариант 3", "is_correct": false}},
        {{"text": "вариант 4", "is_correct": false}}
      ]
    }}
  ]
}}

Пиши на русском. Вопросы и варианты — конкретные по этой должности, не общие."""

    try:
        llm = create_llm(temperature=0.6, max_tokens=3500)
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        data = json.loads(raw)
    except Exception as e:
        logger.warning(f"suggest-onboarding-quiz failed: {e}")
        return SuggestOnboardingQuizResponse(
            title=f"Онбординг: {pos.name}",
            questions=[],
        )

    # Parse + validate questions
    valid: list[QuizQuestionDraft] = []
    for q in (data.get("questions") or [])[:30]:  # hard cap
        if not isinstance(q, dict):
            continue
        text = str(q.get("text", "")).strip()
        if len(text) < 3:
            continue
        raw_choices = q.get("choices") or []
        if not isinstance(raw_choices, list):
            continue
        choices = []
        for c in raw_choices[:8]:
            if not isinstance(c, dict):
                continue
            ctext = str(c.get("text", "")).strip()
            if not ctext:
                continue
            choices.append(QuizChoiceDraft(
                text=ctext[:1000],
                is_correct=bool(c.get("is_correct", False)),
            ))
        if len(choices) < 2:
            continue
        # Ensure exactly one correct
        if not any(c.is_correct for c in choices):
            choices[0].is_correct = True
        elif sum(1 for c in choices if c.is_correct) > 1:
            seen = False
            for c in choices:
                if c.is_correct and seen:
                    c.is_correct = False
                elif c.is_correct:
                    seen = True
        valid.append(QuizQuestionDraft(
            text=text[:2000],
            type=str(q.get("type", "MCQ"))[:32] or "MCQ",
            explanation=str(q.get("explanation", "")).strip()[:2000],
            choices=choices,
        ))

    return SuggestOnboardingQuizResponse(
        title=str(data.get("title") or f"Онбординг: {pos.name}").strip()[:255],
        questions=valid,
    )


@router.get("/{position_id}/onboarding-quiz", response_model=PositionQuizResponse | None)
async def get_onboarding_quiz(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the saved onboarding quiz for a position, or None if not yet set."""
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    result = await db.execute(
        select(PositionQuiz).where(PositionQuiz.position_id == position_id)
    )
    qz = result.scalar_one_or_none()
    if not qz:
        return None

    # Deserialize questions JSON -> QuizQuestionDraft list (with normalization)
    raw_qs = qz.questions or []
    questions = []
    for q in raw_qs:
        if not isinstance(q, dict):
            continue
        choices_raw = q.get("choices") or []
        choices = [
            QuizChoiceDraft(
                text=str(c.get("text", "")).strip()[:1000],
                is_correct=bool(c.get("is_correct", False)),
            )
            for c in choices_raw
            if isinstance(c, dict) and str(c.get("text", "")).strip()
        ]
        if len(choices) < 2:
            continue
        questions.append(QuizQuestionDraft(
            text=str(q.get("text", "")).strip()[:2000],
            type=str(q.get("type", "MCQ"))[:32] or "MCQ",
            explanation=str(q.get("explanation", "")).strip()[:2000],
            choices=choices,
        ).normalize())

    return PositionQuizResponse(
        id=qz.id,
        position_id=qz.position_id,
        title=qz.title,
        pass_score=qz.pass_score,
        time_limit=qz.time_limit,
        questions=questions,
        is_active=qz.is_active,
        created_at=qz.created_at,
        updated_at=qz.updated_at,
    )


@router.post("/{position_id}/onboarding-quiz", response_model=PositionQuizResponse)
async def save_onboarding_quiz(
    position_id: UUID,
    payload: SavePositionQuizRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create or replace the onboarding quiz for a position.

    Upsert semantics: if a quiz already exists for this position,
    update it (questions replaced entirely). Otherwise insert a new row.

    Methodologist responsibility: review the AI-generated draft,
    edit/add/remove questions, then save. We validate that:
    - every question has >=2 choices
    - every question has exactly one is_correct: true choice
    - at least one question total
    """
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    # Normalize + validate
    clean_questions: list[dict] = []
    for q in payload.questions:
        normalized = q.normalize()
        if len(normalized.choices) < 2:
            raise HTTPException(
                status_code=422,
                detail=f"Вопрос «{normalized.text[:60]}» должен иметь минимум 2 варианта ответа",
            )
        correct_count = sum(1 for c in normalized.choices if c.is_correct)
        if correct_count != 1:
            raise HTTPException(
                status_code=422,
                detail=f"Вопрос «{normalized.text[:60]}» должен иметь ровно 1 правильный ответ",
            )
        clean_questions.append({
            "text": normalized.text,
            "type": normalized.type,
            "explanation": normalized.explanation,
            "choices": [
                {"text": c.text, "is_correct": c.is_correct}
                for c in normalized.choices
            ],
        })

    # Upsert
    result = await db.execute(
        select(PositionQuiz).where(PositionQuiz.position_id == position_id)
    )
    qz = result.scalar_one_or_none()

    if qz:
        qz.title = payload.title.strip()
        qz.pass_score = payload.pass_score
        qz.time_limit = payload.time_limit
        qz.questions = clean_questions
        qz.is_active = payload.is_active
    else:
        qz = PositionQuiz(
            position_id=position_id,
            tenant_id=user.tenant_id,
            title=payload.title.strip(),
            pass_score=payload.pass_score,
            time_limit=payload.time_limit,
            questions=clean_questions,
            is_active=payload.is_active,
            created_by=user.id,
        )
        db.add(qz)

    await db.commit()
    await db.refresh(qz)

    return PositionQuizResponse(
        id=qz.id,
        position_id=qz.position_id,
        title=qz.title,
        pass_score=qz.pass_score,
        time_limit=qz.time_limit,
        questions=[
            QuizQuestionDraft(
                text=q["text"],
                type=q["type"],
                explanation=q.get("explanation", ""),
                choices=[QuizChoiceDraft(text=c["text"], is_correct=c["is_correct"]) for c in q["choices"]],
            )
            for q in clean_questions
        ],
        is_active=qz.is_active,
        created_at=qz.created_at,
        updated_at=qz.updated_at,
    )


@router.delete("/{position_id}/onboarding-quiz", status_code=204)
async def delete_onboarding_quiz(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove the onboarding quiz for a position."""
    pos = await db.get(Position, position_id)
    if not pos or pos.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    result = await db.execute(
        select(PositionQuiz).where(PositionQuiz.position_id == position_id)
    )
    qz = result.scalar_one_or_none()
    if not qz:
        raise HTTPException(status_code=404, detail="Onboarding quiz not found")

    await db.delete(qz)
    await db.commit()
    return None
