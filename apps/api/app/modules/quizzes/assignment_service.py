"""Quiz Assignment service"""
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select


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


async def assign_quiz_by_positions(
    db: AsyncSession,
    quiz_id: UUID,
    position_ids: list[UUID],
    assigned_by: UUID,
    tenant_id: UUID,
    due_date: datetime | None = None,
) -> dict:
    """Expand positions → users in one shot, then assign.

    Returns a summary so the UI can tell the methodologist "expanded from
    N positions, M users, K already had this quiz". This is the bulk
    variant of `assign_quiz` for "назначить всем кассирам" workflows.

    Positions not found in this tenant are reported (so the UI can warn),
    not silently dropped — silent drops are how data integrity bugs sneak in.
    """
    # 1. Resolve positions → user_ids, scoped to tenant. We also keep the
    # mapping user_id → position_id for the response so the UI can show
    # "назначено как <position>" without a follow-up query.
    if not position_ids:
        return {
            "positions_requested": 0,
            "users_targeted": 0,
            "users_assigned": 0,
            "users_skipped": 0,
            "positions_not_found": [],
        }

    pos_result = await db.execute(
        text(
            """SELECT id, name FROM positions
               WHERE tenant_id = :tid AND id = ANY(:pids)"""
        ),
        {"tid": tenant_id, "pids": list(position_ids)},
    )
    found_positions = {r[0]: r[1] for r in pos_result.all()}
    positions_not_found = [p for p in position_ids if p not in found_positions]

    if not found_positions:
        return {
            "positions_requested": len(position_ids),
            "users_targeted": 0,
            "users_assigned": 0,
            "users_skipped": 0,
            "positions_not_found": positions_not_found,
        }

    # 2. Users on those positions in this tenant. Exclude inactive users
    # so we don't blast assignments to deactivated accounts.
    user_result = await db.execute(
        text(
            """SELECT id, position_id FROM users
               WHERE tenant_id = :tid
                 AND position_id = ANY(:pids)
                 AND is_active = true"""
        ),
        {"tid": tenant_id, "pids": list(found_positions.keys())},
    )
    user_rows = user_result.all()
    user_ids = [r[0] for r in user_rows]

    # 3. Delegate to the regular assign_quiz for the actual insert —
    # it already handles dedup correctly. No code duplication.
    bulk_result = await assign_quiz(
        db,
        quiz_id=quiz_id,
        user_ids=user_ids,
        assigned_by=assigned_by,
        tenant_id=tenant_id,
        due_date=due_date,
    )

    return {
        "positions_requested": len(position_ids),
        "users_targeted": len(user_ids),
        "users_assigned": bulk_result["created"],
        "users_skipped": bulk_result["skipped"],
        "positions_not_found": positions_not_found,
    }


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
    """List all assignments in a tenant, with user + position context.

    `position_id`/`position_name` are taken from `users.position_id` AT
    QUERY TIME (not when the assignment was created) — so if a user
    changes positions, future queries show the new one. This matches the
    mental model "where does this person work now?".
    """
    result = await db.execute(
        text(
            """SELECT qa.id, qa.quiz_id, q.title as quiz_title,
                      qa.user_id,
                      COALESCE(NULLIF(u.first_name || ' ' || u.last_name, ' '), u.email, 'Unknown') as user_name,
                      u.email as user_email,
                      u.position_id,
                      p.name as position_name,
                      qa.assigned_by, qa.status, qa.score_percent,
                      qa.due_date, qa.completed_at, qa.created_at
               FROM quiz_assignments qa
               LEFT JOIN quizzes q ON q.id = qa.quiz_id
               LEFT JOIN users u ON u.id = qa.user_id
               LEFT JOIN positions p ON p.id = u.position_id
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
            "user_email": r[5],
            "position_id": str(r[6]) if r[6] else None,
            "position_name": r[7],
            "assigned_by": str(r[8]),
            "status": r[9],
            "score_percent": r[10],
            "due_date": r[11].isoformat() if r[11] else None,
            "completed_at": r[12].isoformat() if r[12] else None,
            "created_at": r[13].isoformat() if r[13] else None,
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
