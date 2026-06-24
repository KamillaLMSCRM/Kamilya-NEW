"""Quiz Assignment — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.modules.quizzes.assignment_schemas import QuizAssignmentCreate
from app.modules.quizzes.assignment_service import (
    assign_quiz,
    get_my_assignments,
    get_all_assignments,
    delete_assignment,
)

router = APIRouter(prefix="/quiz-assignments", tags=["quiz-assignments"])

QUIZ_ASSIGN_ROLES = ("admin", "superadmin", "org_admin", "teacher")


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
