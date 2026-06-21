"""AI Generation — service (stub for Week 5-6)"""
from uuid import uuid4
from typing import Dict

_jobs: Dict[str, dict] = {}


async def start_generation(data: dict) -> str:
    """Start AI course generation. Returns job_id."""
    job_id = str(uuid4())
    _jobs[job_id] = {
        "id": job_id,
        "status": "pending",
        "stage": "queued",
        "progress": 0,
        "course_id": None,
        "message": "Job queued",
    }
    return job_id


async def get_job_status(job_id: str) -> dict | None:
    return _jobs.get(job_id)


async def cancel_job(job_id: str) -> bool:
    if job_id in _jobs:
        _jobs[job_id]["status"] = "cancelled"
        _jobs[job_id]["message"] = "Cancelled by user"
        return True
    return False
