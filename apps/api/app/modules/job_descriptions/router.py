"""Job Descriptions — API router"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.users import User
from app.modules.job_descriptions.models import JobDescription
from app.modules.job_descriptions.schemas import JobDescriptionCreate, JobDescriptionResponse

router = APIRouter(prefix="/job-descriptions", tags=["job-descriptions"])


@router.get("", response_model=list[JobDescriptionResponse])
async def list_job_descriptions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JobDescription)
        .where(JobDescription.tenant_id == user.tenant_id)
        .order_by(JobDescription.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=JobDescriptionResponse, status_code=201)
async def create_job_description(
    req: JobDescriptionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    jd = JobDescription(
        tenant_id=user.tenant_id,
        title=req.title,
        department=req.department,
        position=req.position,
        description=req.description,
        requirements=req.requirements,
        created_by=user.id,
    )
    db.add(jd)
    await db.flush()
    await db.refresh(jd)
    return jd
