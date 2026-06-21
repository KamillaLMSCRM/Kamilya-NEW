"""AI Generation — API router with WebSocket progress."""
from __future__ import annotations

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from uuid import UUID, uuid4
from datetime import datetime, timezone

from app.core.auth import get_current_user
from app.modules.ai.schemas import AIGenerateRequest, AIJobResponse
from app.modules.ai.pipeline import get_job_state, start_generation_job, update_job
from app.modules.ai.tasks import generate_course_task

router = APIRouter(prefix="/ai", tags=["ai-generation"])


@router.post("/generate-course", response_model=AIJobResponse, status_code=202)
async def generate_course(
    req: AIGenerateRequest,
    user=Depends(get_current_user),
):
    """Start AI course generation (returns job_id for polling/WebSocket)."""
    job_id = start_generation_job(
        documents=req.documents,
        target_audience=req.target_audience,
        num_modules=req.num_modules,
        language=req.language,
        course_id=str(req.course_id) if req.course_id else None,
    )

    # Start Celery task (async background processing)
    generate_course_task.delay(
        job_id=job_id,
        documents=req.documents,
        target_audience=req.target_audience,
        num_modules=req.num_modules,
        language=req.language,
        course_id=str(req.course_id) if req.course_id else None,
    )

    return AIJobResponse(
        id=job_id,
        status="pending",
        course_id=req.course_id,
        created_at=datetime.now(timezone.utc),
        progress=0,
        stage="queued",
        message="Job queued",
    )


@router.get("/jobs/{job_id}", response_model=AIJobResponse)
async def get_job(
    job_id: str,
    user=Depends(get_current_user),
):
    """Get job status (for polling)."""
    state = get_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    return AIJobResponse(
        id=state.job_id,
        status=state.status,
        course_id=UUID(state.course_id) if state.course_id else None,
        created_at=datetime.fromtimestamp(state.started_at, tz=timezone.utc),
        progress=state.progress,
        stage=state.stage,
        message=state.message,
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_generation(
    job_id: str,
    user=Depends(get_current_user),
):
    """Cancel a running generation job."""
    state = get_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    if state.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="Job already finished")

    update_job(job_id, status="cancelled", message="Cancelled by user")
    return {"status": "cancelled"}


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job progress updates."""
    await websocket.accept()

    try:
        while True:
            state = get_job_state(job_id)
            if not state:
                await websocket.send_json({"error": "Job not found"})
                break

            await websocket.send_json({
                "job_id": state.job_id,
                "status": state.status,
                "stage": state.stage,
                "progress": state.progress,
                "message": state.message,
            })

            if state.status in ("completed", "failed", "cancelled"):
                break

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
