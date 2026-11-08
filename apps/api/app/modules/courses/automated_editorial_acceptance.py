"""Server-owned current-content receipt; never a publication or role approval."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.ai.v3.revision_policy import is_autonomous_editorial_policy
from app.modules.courses.draft_review import read_draft_review

KEY = 'v3_automated_editorial_acceptance'
POLICY = 'v3-automated-editorial-acceptance-v1'


def clean_manifest(analysis: Any) -> dict[str, Any] | None:
    if not isinstance(analysis, dict) or 'unresolved_source_uncertainty' in analysis:
        return None
    evidence = analysis.get('evidence_v3')
    if (not isinstance(evidence, dict) or not is_autonomous_editorial_policy(evidence.get('v3_review_policy'))
            or evidence.get('automated_review_passed') is not True
            or evidence.get('requires_source_review') is not False
            or evidence.get('quality_verdict') != 'verified'):
        return None
    manifest = read_draft_review(analysis)
    return manifest if manifest is not None and manifest.get('content_review_required') is False else None


def receipt(*, manifest: dict[str, Any], course_id: Any, content_hash: str) -> dict[str, Any]:
    return {'policy': POLICY, 'course_id': str(course_id), 'content_hash': content_hash,
        'source_fingerprint': manifest['source_fingerprint'], 'draft_fingerprint': manifest['draft_fingerprint']}


async def bind_automated_acceptance(db: Any, *, course: Any, job: Any) -> None:
    """Called only by the owned generation transaction after all rows are ready."""
    manifest = clean_manifest(course.source_analysis)
    if manifest is None:
        return
    if (str(job.course_id) != str(course.id) or job.tenant_id != course.tenant_id
            or job.status != 'completed' or job.stage != 'completed' or not isinstance(job.result, dict)):
        raise ValueError('automated_editorial_save_scope_invalid')
    from app.modules.courses.source_uncertainty import compute_course_content_snapshot_hash

    await db.flush()
    content_hash = await compute_course_content_snapshot_hash(db, course)
    job.result = {**job.result, KEY: receipt(manifest=manifest, course_id=course.id, content_hash=content_hash)}


async def automatic_acceptance_is_current(db: Any, *, course: Any, content_hash: str) -> bool:
    """Caller holds Course and owned source locks. Changed/missing proof fails closed."""
    manifest = clean_manifest(course.source_analysis)
    if manifest is None:
        return False
    from app.models.ai_job import AIJob

    # Fresh completed jobs are immutable evidence here; never trust a client-held
    # manifest as authority. Do not invert the caller's Course→Document lock order.
    jobs = list((await db.scalars(select(AIJob).where(AIJob.tenant_id == course.tenant_id,
        AIJob.course_id == course.id, AIJob.status == 'completed', AIJob.stage == 'completed')
        .execution_options(populate_existing=True).limit(2))).all())
    if len(jobs) != 1:
        return False
    job = jobs[0]
    return (job.tenant_id == course.tenant_id and str(job.course_id) == str(course.id)
        and job.status == 'completed' and job.stage == 'completed'
        and isinstance(job.result, dict) and job.result.get(KEY) == receipt(
        manifest=manifest, course_id=course.id, content_hash=content_hash))
