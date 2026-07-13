from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.modules.learning_paths.models import LearningPath, LearningPathCourse
from app.modules.learning_paths.schemas import (
    LearnerPathItem,
    LearningPathCourseItem,
    LearningPathCourseReplace,
    LearningPathCreate,
    LearningPathDetail,
    LearningPathSummary,
    LearningPathUpdate,
)

router = APIRouter(
    prefix="/learning-paths",
    tags=["learning-paths"],
    dependencies=[Depends(require_tenant_user())],
)

PATH_MANAGER_ROLES = ("methodologist", "teacher")


async def _get_path(db: AsyncSession, path_id: UUID, tenant_id: UUID) -> LearningPath:
    result = await db.execute(
        select(LearningPath)
        .options(selectinload(LearningPath.courses).selectinload(LearningPathCourse.course))
        .where(LearningPath.id == path_id, LearningPath.tenant_id == tenant_id)
    )
    path = result.scalar_one_or_none()
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")
    return path


def _summary(path: LearningPath) -> LearningPathSummary:
    return LearningPathSummary(
        id=path.id,
        title=path.title,
        description=path.description,
        status=path.status,
        course_count=len(path.courses),
        created_at=path.created_at,
    )


def _detail(path: LearningPath) -> LearningPathDetail:
    return LearningPathDetail(
        **_summary(path).model_dump(),
        courses=[
            LearningPathCourseItem(
                course_id=item.course_id,
                title=item.course.title,
                order_index=item.order_index,
                required=item.required,
            )
            for item in path.courses
            if item.course is not None
        ],
    )


@router.get("", response_model=list[LearningPathSummary])
async def list_paths(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    result = await db.execute(
        select(LearningPath)
        .options(selectinload(LearningPath.courses))
        .where(LearningPath.tenant_id == user.tenant_id)
        .order_by(LearningPath.created_at.desc())
    )
    return [_summary(path) for path in result.scalars().unique().all()]


@router.post("", response_model=LearningPathSummary, status_code=201)
async def create_path(
    payload: LearningPathCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    path = LearningPath(
        tenant_id=user.tenant_id,
        title=payload.title.strip(),
        description=payload.description,
        status=payload.status,
        created_by=user.id,
    )
    db.add(path)
    await db.flush()
    await db.refresh(path)
    await db.commit()
    return LearningPathSummary(
        id=path.id,
        title=path.title,
        description=path.description,
        status=path.status,
        course_count=0,
        created_at=path.created_at,
    )


@router.get("/my", response_model=list[LearnerPathItem])
async def list_my_paths(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(LearningPath)
        .options(selectinload(LearningPath.courses).selectinload(LearningPathCourse.course))
        .where(LearningPath.tenant_id == user.tenant_id, LearningPath.status == "published")
        .order_by(LearningPath.created_at.desc())
    )
    paths = result.scalars().unique().all()
    course_ids = {item.course_id for path in paths for item in path.courses}
    completed: set[UUID] = set()
    if course_ids:
        enrollments = await db.execute(
            select(Enrollment.course_id).where(
                Enrollment.tenant_id == user.tenant_id,
                Enrollment.user_id == user.id,
                Enrollment.course_id.in_(course_ids),
                Enrollment.status == "completed",
            )
        )
        completed = set(enrollments.scalars().all())
    return [
        LearnerPathItem(
            id=path.id,
            title=path.title,
            description=path.description,
            total_courses=len(path.courses),
            completed_courses=sum(item.course_id in completed for item in path.courses),
            progress_percent=round(
                sum(item.course_id in completed for item in path.courses) / len(path.courses) * 100
            ) if path.courses else 0,
        )
        for path in paths
    ]


@router.get("/{path_id}", response_model=LearningPathDetail)
async def get_path(
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    return _detail(await _get_path(db, path_id, user.tenant_id))


@router.patch("/{path_id}", response_model=LearningPathDetail)
async def update_path(
    path_id: UUID,
    payload: LearningPathUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    path = await _get_path(db, path_id, user.tenant_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(path, key, value.strip() if isinstance(value, str) and key != "status" else value)
    await db.commit()
    return _detail(await _get_path(db, path_id, user.tenant_id))


@router.put("/{path_id}/courses", response_model=LearningPathDetail)
async def replace_path_courses(
    path_id: UUID,
    payload: LearningPathCourseReplace,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*PATH_MANAGER_ROLES)),
):
    path = await _get_path(db, path_id, user.tenant_id)
    course_ids = payload.course_ids
    if len(set(course_ids)) != len(course_ids):
        raise HTTPException(status_code=422, detail="A course cannot appear twice in a learning path")
    if course_ids:
        result = await db.execute(
            select(Course.id).where(Course.tenant_id == user.tenant_id, Course.id.in_(course_ids))
        )
        available = set(result.scalars().all())
        missing = [str(course_id) for course_id in course_ids if course_id not in available]
        if missing:
            raise HTTPException(status_code=422, detail={"code": "courses_outside_tenant", "course_ids": missing})
    for item in list(path.courses):
        await db.delete(item)
    await db.flush()
    for index, course_id in enumerate(course_ids):
        db.add(LearningPathCourse(path_id=path.id, course_id=course_id, order_index=index, required=True))
    await db.commit()
    return _detail(await _get_path(db, path_id, user.tenant_id))
