"""Quiz Assignment — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.modules.quizzes.assignment_schemas import (
    QuizAssignmentCreate,
    QuizAssignmentByPositionsCreate,
    PositionAssignmentSummary,
)
from app.modules.quizzes.assignment_service import (
    assign_quiz,
    assign_quiz_by_positions,
    get_my_assignments,
    get_all_assignments,
    delete_assignment,
)

router = APIRouter(prefix="/quiz-assignments", tags=["quiz-assignments"])

QUIZ_ASSIGN_ROLES = ("superadmin", "methodologist")


@router.post("")
async def create_assignment(
    req: QuizAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*QUIZ_ASSIGN_ROLES)),
):
    result = await assign_quiz(
        db, req.quiz_id, req.user_ids, user.id, user.tenant_id, req.due_date
    )
    return result


@router.post("/by-positions", response_model=PositionAssignmentSummary)
async def create_assignment_by_positions(
    req: QuizAssignmentByPositionsCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*QUIZ_ASSIGN_ROLES)),
):
    """Bulk-assign by position. Backend expands position_ids → user_ids
    (all currently active users on those positions in this tenant).

    Why a separate endpoint and not just optional `position_ids` in the
    regular POST? Because the request/response shape is fundamentally
    different: positions are an alternative SELECTION MODE, not a
    parameter. Returning a PositionAssignmentSummary (with
    positions_not_found, users_skipped) gives the UI the right info to
    show "12 already had this quiz" or "position X not in this tenant".
    """
    result = await assign_quiz_by_positions(
        db,
        req.quiz_id,
        req.position_ids,
        user.id,
        user.tenant_id,
        req.due_date,
    )
    return result


@router.get("/my")
async def my_assignments(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_my_assignments(db, user.id, user.tenant_id)


@router.get("")
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*QUIZ_ASSIGN_ROLES)),
):
    return await get_all_assignments(db, user.tenant_id)


@router.delete("/{assignment_id}")
async def remove_assignment(
    assignment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(*QUIZ_ASSIGN_ROLES)),
):
    deleted = await delete_assignment(db, assignment_id, user.tenant_id)
    return {"deleted": deleted}
