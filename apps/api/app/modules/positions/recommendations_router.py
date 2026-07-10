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

from app.core.auth import get_current_user, require_tenant_user
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

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(require_tenant_user())],
)


# ── Helpers ──────────────────────────────────────────────────


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

    from app.core.trial_limits import assert_can_create_courses
    await assert_can_create_courses(db, user.tenant_id, requested=len(payload.items))

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
        # Attach to position so new employees auto-enroll.
        # tenant_id is required by the NOT NULL constraint; smoke 2026-06-30.
        db.add(PositionCourse(
            position_id=position_id,
            course_id=course_id,
            tenant_id=user.tenant_id,
        ))
        created_refs.append(CreatedCourseRef(id=str(course_id), title=item.title.strip()))

    await db.commit()

    return CreateCoursesResponse(
        created=created_refs,
        attached_to_position=len(created_refs),
    )


# ── Bulk JD analysis (multi-file upload) ──────────────────────


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
# NOTE: `recommended_courses` was previously registered here as well as in
# jd_router.py — same path (`GET /positions/{id}/recommended-courses`),
# same handler. After the 2026-07-10 split refactor this became a
# `Duplicate Operation ID` warning at FastAPI startup. The real handler
# lives in jd_router.py; this stub intentionally stays empty so future
# readers know why the function isn't here.


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
