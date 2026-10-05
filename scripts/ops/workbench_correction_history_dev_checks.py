"""All-column learner history proof around actual correction application."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from workbench_correction_application_dev_checks import verify_application
from workbench_document_dev_gate import GateBlocked, safe_schema, set_context

HISTORY_CHECKS = frozenset({
    "learner_history_fixture", "learner_history_apply",
    "learner_history_replay", "learner_history_refusal",
})


def history_fingerprint(rows):
    expected = {"enrollments", "quiz_attempts", "certificates", "content_releases", "current_release_id"}
    if not isinstance(rows, dict) or set(rows) != expected:
        raise GateBlocked("history_shape_invalid")
    for key in expected - {"current_release_id"}:
        if not isinstance(rows[key], list) or len(rows[key]) != 1 or not isinstance(rows[key][0], dict):
            raise GateBlocked("history_nonempty_required")
    enrollment, attempt, certificate, release = (rows[key][0] for key in
        ("enrollments", "quiz_attempts", "certificates", "content_releases"))
    if not (
        enrollment.get("status") == "completed" and enrollment.get("completed_at")
        and attempt.get("completed_at") and attempt.get("passed") is True
        and attempt.get("answers") and attempt.get("evidence_snapshot")
        and attempt.get("evidence_sha256") and attempt.get("enrollment_id")
        and attempt.get("score_percent") == 100 and attempt.get("total_points") == 1
        and attempt.get("earned_points") == 1
        and certificate.get("enrollment_id") and certificate.get("metadata")
        and certificate.get("pdf_sha256") and certificate.get("revoked_at") is None
        and release.get("snapshot") and release.get("snapshot_sha256")
        and rows["current_release_id"] == release.get("id")
        and enrollment.get("content_release_id") == release.get("id")
        and attempt.get("content_release_id") == release.get("id")
    ):
        raise GateBlocked("history_evidence_incomplete")
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


async def verify_history(owner_engine, runtime_engine, schema, checks):
    from app.models.enrollment import Enrollment
    from app.models.users import User
    from app.modules.certificates.models import Certificate
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from app.modules.quizzes.models import QuizAttempt

    qualified = safe_schema(schema)
    sealed = None
    course_id = None

    async def snapshot(sql):
        rows = {}
        for table in ("enrollments", "quiz_attempts", "certificates", "content_releases"):
            where = " WHERE t.course_id=:course" if table == "content_releases" else ""
            rows[table] = (await sql(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id),'[]'::jsonb) FROM {qualified}.{table} t{where}",
                {"course": course_id} if where else None,
            )).scalar_one()
        pointer = (await sql(
            f"SELECT current_release_id FROM {qualified}.courses WHERE id=:course",
            {"course": course_id},
        )).scalar_one()
        rows["current_release_id"] = str(pointer) if pointer else None
        return history_fingerprint(rows)

    async def probe(stage, case, sql, actor):
        nonlocal sealed, course_id
        if stage == "seed":
            if sealed is not None:
                return
            course_id = case.course
            student, enrollment_id = uuid4(), uuid4()
            completed = datetime.now(UTC)
            evidence = {"question": "Material?", "answer": "steel", "points": 1}
            evidence_hash = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
            async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
                await set_context(db, schema, actor.tenant_id, actor.actor_id)
                release = (await db.scalars(select(ContentRelease).where(ContentRelease.course_id == course_id))).one()
                course = await db.get(Course, course_id)
                course.current_release_id = release.id
                db.add(User(id=student, tenant_id=actor.tenant_id, first_name="Synthetic", last_name="Learner", role="student", status="active", is_active=True))
                await db.flush()
                db.add(Enrollment(id=enrollment_id, tenant_id=actor.tenant_id, course_id=course_id, user_id=student, content_release_id=release.id, status="completed", source="manual", completed_at=completed))
                await db.flush()
                db.add(QuizAttempt(id=uuid4(), tenant_id=actor.tenant_id, quiz_id=case.quiz, user_id=student, enrollment_id=enrollment_id, content_release_id=release.id, passed=True, score_percent=100, total_points=1, earned_points=1, answers=[evidence], evidence_snapshot=evidence, evidence_sha256=evidence_hash, completed_at=completed, time_spent_seconds=30))
                db.add(Certificate(id=uuid4(), tenant_id=actor.tenant_id, user_id=student, course_id=course_id, enrollment_id=enrollment_id, certificate_number=f"QA-{uuid4().hex}", metadata_={"user_name": "Synthetic Learner", "course_title": "Synthetic"}, pdf_sha256="e" * 64, pdf_path="synthetic/not-a-file.pdf"))
                await db.commit()
            sealed = await snapshot(sql)
            checks.append("learner_history_fixture")
        else:
            if sealed is None or case.course != course_id or await snapshot(sql) != sealed:
                raise GateBlocked("learner_history_changed")
            checks.append(f"learner_history_{stage}")

    await verify_application(owner_engine, runtime_engine, schema, checks, history_probe=probe)
