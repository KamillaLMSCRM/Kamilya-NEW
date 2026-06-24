"""Quiz Assignment service"""
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def assign_quiz(
    db: AsyncSession,
    quiz_id: UUID,
    user_ids: list[UUID],
    assigned_by: UUID,
    tenant_id: UUID,
    due_date: datetime | None = None,
) -> dict:
    created = 0
    skipped = 0
    for uid in user_ids:
        existing = await db.execute(
            text("SELECT id FROM quiz_assignments WHERE quiz_id = :qid AND user_id = :uid AND tenant_id = :tid"),
            {"qid": str(quiz_id), "uid": str(uid), "tid": str(tenant_id)},
        )
        if existing.first():
            skipped += 1
            continue
        await db.execute(
            text(
                """INSERT INTO quiz_assignments (quiz_id, user_id, assigned_by, tenant_id, due_date, status)
                   VALUES (:qid, :uid, :by, :tid, :due, 'assigned')"""
            ),
            {"qid": str(quiz_id), "uid": str(uid), "by": str(assigned_by), "tid": str(tenant_id), "due": due_date},
        )
        created += 1
    await db.flush()
    return {"created": created, "skipped": skipped}


async def get_my_assignments(db: AsyncSession, user_id: UUID, tenant_id: UUID) -> list[dict]:
    result = await db.execute(
        text(
            """SELECT qa.id, qa.quiz_id, q.title as quiz_title, qa.status, qa.score_percent,
                      qa.due_date, qa.completed_at, qa.created_at
               FROM quiz_assignments qa
               LEFT JOIN quizzes q ON q.id = qa.quiz_id
               WHERE qa.user_id = :uid AND qa.tenant_id = :tid
               ORDER BY qa.created_at DESC"""
        ),
        {"uid": str(user_id), "tid": str(tenant_id)},
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "quiz_id": str(r[1]),
            "quiz_title": r[2],
            "status": r[3],
            "score_percent": r[4],
            "due_date": r[5].isoformat() if r[5] else None,
            "completed_at": r[6].isoformat() if r[6] else None,
            "created_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]


async def get_all_assignments(db: AsyncSession, tenant_id: UUID) -> list[dict]:
    result = await db.execute(
        text(
            """SELECT qa.id, qa.quiz_id, q.title as quiz_title, qa.user_id,
                      COALESCE(NULLIF(u.first_name || ' ' || u.last_name, ' '), u.email, 'Unknown') as user_name,
                      qa.status, qa.score_percent, qa.due_date, qa.completed_at, qa.created_at
               FROM quiz_assignments qa
               LEFT JOIN quizzes q ON q.id = qa.quiz_id
               LEFT JOIN users u ON u.id = qa.user_id
               WHERE qa.tenant_id = :tid
               ORDER BY qa.created_at DESC"""
        ),
        {"tid": str(tenant_id)},
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]),
            "quiz_id": str(r[1]),
            "quiz_title": r[2],
            "user_id": str(r[3]),
            "user_name": r[4],
            "status": r[5],
            "score_percent": r[6],
            "due_date": r[7].isoformat() if r[7] else None,
            "completed_at": r[8].isoformat() if r[8] else None,
            "created_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]


async def delete_assignment(db: AsyncSession, assignment_id: UUID, tenant_id: UUID) -> bool:
    result = await db.execute(
        text("DELETE FROM quiz_assignments WHERE id = :id AND tenant_id = :tid"),
        {"id": str(assignment_id), "tid": str(tenant_id)},
    )
    await db.flush()
    return result.rowcount > 0


async def update_assignment_status(
    db: AsyncSession, quiz_id: UUID, user_id: UUID, tenant_id: UUID,
    score_percent: int, passed: bool
) -> None:
    status = "completed" if passed else "completed"
    await db.execute(
        text(
            """UPDATE quiz_assignments
               SET status = :status, score_percent = :score, completed_at = now()
               WHERE quiz_id = :qid AND user_id = :uid AND tenant_id = :tid"""
        ),
        {"status": status, "score": score_percent, "qid": str(quiz_id), "uid": str(user_id), "tid": str(tenant_id)},
    )
    await db.flush()
