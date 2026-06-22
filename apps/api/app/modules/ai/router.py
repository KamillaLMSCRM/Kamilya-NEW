"""AI Generation — API router with WebSocket progress."""
from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, decode_token
from app.core.db import get_db
from app.models.users import User
from app.modules.ai.schemas import AIGenerateRequest, AIJobResponse
from app.modules.ai.job_service import create_ai_job, get_ai_job, update_ai_job
from app.modules.ai.tasks import generate_course_task

router = APIRouter(prefix="/ai", tags=["ai-generation"])


@router.post("/generate-course", response_model=AIJobResponse, status_code=202)
async def generate_course(
    req: AIGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start AI course generation (returns job_id for polling/WebSocket)."""
    job = await create_ai_job(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        course_id=req.course_id,
        params={
            "documents": req.documents,
            "target_audience": req.target_audience,
            "num_modules": req.num_modules,
            "language": req.language,
        },
    )
    await db.commit()

    # Start Celery task (async background processing)
    try:
        generate_course_task.delay(
            job_id=job.id,
            documents=req.documents,
            target_audience=req.target_audience,
            num_modules=req.num_modules,
            language=req.language,
            course_id=str(req.course_id) if req.course_id else None,
            tenant_id=str(user.tenant_id),
            user_id=str(user.id),
        )
    except Exception:
        pass  # Celery/Redis not available — job still created

    return AIJobResponse(
        id=job.id,
        status="pending",
        course_id=req.course_id,
        created_at=job.created_at,
        progress=0,
        stage="queued",
        message="Job queued",
    )


@router.get("/jobs", response_model=list[AIJobResponse])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List AI jobs for current tenant."""
    from sqlalchemy import select
    from app.models.ai_job import AIJob

    stmt = (
        select(AIJob)
        .where(AIJob.tenant_id == user.tenant_id)
        .order_by(AIJob.created_at.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return [
        AIJobResponse(
            id=j.id,
            status=j.status,
            course_id=UUID(j.course_id) if j.course_id else None,
            created_at=j.created_at,
            progress=j.progress,
            stage=j.stage,
            message=j.message or "",
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=AIJobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get job status (for polling)."""
    job = await get_ai_job(db, job_id)
    if not job or job.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Job not found")

    return AIJobResponse(
        id=job.id,
        status=job.status,
        course_id=UUID(job.course_id) if job.course_id else None,
        created_at=job.created_at,
        progress=job.progress,
        stage=job.stage,
        message=job.message or "",
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_generation(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel a running generation job."""
    job = await get_ai_job(db, job_id)
    if not job or job.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="Job already finished")

    await update_ai_job(db, job_id, status="cancelled", message="Cancelled by user")
    await db.commit()
    return {"status": "cancelled"}


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str, token: str = Query(None)):
    """WebSocket endpoint for real-time job progress updates. Requires JWT via query param."""
    # Authenticate via token query param
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=4003, reason="Invalid token")
        return

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not user_id or not tenant_id:
        await websocket.close(code=4003, reason="Invalid token payload")
        return

    await websocket.accept()

    try:
        while True:
            from app.core.db import async_session_factory
            async with async_session_factory() as session:
                job = await get_ai_job(session, job_id)
                if not job:
                    await websocket.send_json({"error": "Job not found"})
                    break

                # Verify tenant access
                if str(job.tenant_id) != tenant_id:
                    await websocket.send_json({"error": "Access denied"})
                    break

                await websocket.send_json({
                    "job_id": job.id,
                    "status": job.status,
                    "stage": job.stage,
                    "progress": job.progress,
                    "message": job.message or "",
                })

                if job.status in ("completed", "failed", "cancelled"):
                    break

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
