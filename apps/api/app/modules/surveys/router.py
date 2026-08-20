from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.modules.surveys.models import Survey, SurveyResponse
from app.modules.surveys.schemas import (
    LearnerSurvey,
    SurveyAnswerSubmit,
    SurveyCreate,
    SurveyDetail,
    SurveyQuestion,
    SurveySummary,
)

router = APIRouter(prefix="/surveys", tags=["surveys"], dependencies=[Depends(require_tenant_user())])
MANAGER_ROLES = ("methodologist",)


def _summary(item: Survey) -> SurveySummary:
    return SurveySummary(
        id=item.id,
        course_id=item.course_id,
        title=item.title,
        status=item.status,
        question_count=len(item.questions or []),
        created_at=item.created_at,
    )


def _detail(item: Survey) -> SurveyDetail:
    return SurveyDetail(
        **_summary(item).model_dump(), questions=[SurveyQuestion.model_validate(q) for q in (item.questions or [])]
    )


@router.get("", response_model=list[SurveySummary])
async def list_surveys(db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))):
    result = await db.execute(
        select(Survey).where(Survey.tenant_id == user.tenant_id).order_by(Survey.created_at.desc())
    )
    return [_summary(item) for item in result.scalars().all()]


@router.post("", response_model=SurveyDetail, status_code=201)
async def create_survey(
    payload: SurveyCreate, db: AsyncSession = Depends(get_db), user=Depends(require_role(*MANAGER_ROLES))
):
    course = (
        await db.execute(select(Course).where(Course.id == payload.course_id, Course.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=422, detail={"code": "course_outside_tenant"})
    ids = [question.id for question in payload.questions]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Question ids must be unique")
    item = Survey(
        tenant_id=user.tenant_id,
        course_id=payload.course_id,
        created_by=user.id,
        title=payload.title.strip(),
        status=payload.status,
        questions=[question.model_dump() for question in payload.questions],
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    await db.commit()
    return _detail(item)


@router.get("/my", response_model=list[LearnerSurvey])
async def list_my_surveys(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    enrollment_exists = select(Enrollment.id).where(
        Enrollment.course_id == Survey.course_id,
        Enrollment.user_id == user.id,
        Enrollment.tenant_id == user.tenant_id,
        Enrollment.status == "completed",
    )
    if assignment_enrollment_id is not None:
        enrollment_exists = enrollment_exists.where(Enrollment.id == assignment_enrollment_id)
    query = (
        select(Survey, Course)
        .join(Course, Course.id == Survey.course_id)
        .where(
            Survey.tenant_id == user.tenant_id,
            Survey.status == "published",
            exists(enrollment_exists),
        )
    )
    result = await db.execute(query)
    rows = result.all()
    response_rows = []
    for survey, course in rows:
        completed_enrollment_query = (
            select(Enrollment.id)
            .where(
                Enrollment.course_id == survey.course_id,
                Enrollment.user_id == user.id,
                Enrollment.tenant_id == user.tenant_id,
                Enrollment.status == "completed",
            )
            .order_by(Enrollment.completed_at.desc(), Enrollment.enrolled_at.desc())
            .limit(1)
        )
        if assignment_enrollment_id is not None:
            completed_enrollment_query = completed_enrollment_query.where(Enrollment.id == assignment_enrollment_id)
        completed_enrollment_id = (await db.execute(completed_enrollment_query)).scalar_one_or_none()
        response_enrollment_scope = SurveyResponse.enrollment_id == completed_enrollment_id
        if assignment_enrollment_id is None:
            response_enrollment_scope = or_(response_enrollment_scope, SurveyResponse.enrollment_id.is_(None))
        submitted = (
            await db.execute(
                select(SurveyResponse.id).where(
                    SurveyResponse.survey_id == survey.id,
                    SurveyResponse.user_id == user.id,
                    SurveyResponse.tenant_id == user.tenant_id,
                    response_enrollment_scope,
                )
            )
        ).scalar_one_or_none() is not None
        response_rows.append(
            LearnerSurvey(
                id=survey.id,
                course_id=course.id,
                course_title=course.title,
                title=survey.title,
                questions=[SurveyQuestion.model_validate(q) for q in (survey.questions or [])],
                submitted=submitted,
            )
        )
    return response_rows


@router.post("/{survey_id}/responses", status_code=201)
async def submit_response(
    survey_id: UUID, payload: SurveyAnswerSubmit, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)
):
    survey = (
        await db.execute(
            select(Survey).where(
                Survey.id == survey_id, Survey.tenant_id == user.tenant_id, Survey.status == "published"
            )
        )
    ).scalar_one_or_none()
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    enrollment_query = (
        select(Enrollment.id)
        .where(
            Enrollment.course_id == survey.course_id,
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == user.tenant_id,
            Enrollment.status == "completed",
        )
        .order_by(Enrollment.completed_at.desc(), Enrollment.enrolled_at.desc())
        .limit(1)
    )
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    if assignment_enrollment_id is not None:
        enrollment_query = enrollment_query.where(Enrollment.id == assignment_enrollment_id)
    completed = (await db.execute(enrollment_query)).scalar_one_or_none()
    if not completed:
        raise HTTPException(status_code=403, detail="Complete the course before submitting feedback")
    response_enrollment_scope = SurveyResponse.enrollment_id == completed
    if assignment_enrollment_id is None:
        response_enrollment_scope = or_(response_enrollment_scope, SurveyResponse.enrollment_id.is_(None))
    existing = (
        await db.execute(
            select(SurveyResponse.id).where(
                SurveyResponse.survey_id == survey.id,
                SurveyResponse.user_id == user.id,
                SurveyResponse.tenant_id == user.tenant_id,
                response_enrollment_scope,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Feedback has already been submitted")
    allowed = {question["id"] for question in survey.questions or []}
    if any(key not in allowed for key in payload.answers):
        raise HTTPException(status_code=422, detail="Unknown survey question")
    db.add(
        SurveyResponse(
            tenant_id=user.tenant_id,
            survey_id=survey.id,
            user_id=user.id,
            enrollment_id=completed,
            answers=payload.answers,
            submitted_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return {"submitted": True}
