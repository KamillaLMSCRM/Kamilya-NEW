"""Edit lesson practice through the existing native-course authoring boundary."""

from hashlib import sha256
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.courses import Course
from app.models.users import User
from app.modules.courses.localization_router import _author_course
from app.modules.courses.release_service import touch_course
from app.modules.lessons.decision_practice import BLOCK_TYPE, DecisionPractice, PracticeModel
from app.modules.lessons.models import ContentBlock, Lesson, Module

router = APIRouter(prefix="/courses/{course_id}/lessons/{lesson_id}/decision-practice", tags=["lesson practice"])
Db = Annotated[AsyncSession, Depends(get_db)]
Author = Annotated[User, Depends(require_role("superadmin", "methodologist"))]


class PracticeEdit(PracticeModel):
    revision: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    practice: DecisionPractice | None


async def _draft_block(
    db: Db, course_id: UUID, lesson_id: UUID, author: Author, *, lock: bool = False,
) -> tuple[Course, ContentBlock | None]:
    course = await _author_course(db, course_id, author, locked=lock)
    lesson = await db.scalar(
        select(Lesson.id).join(Module, Module.id == Lesson.module_id).where(
            Lesson.id == lesson_id, Lesson.tenant_id == author.tenant_id,
            Module.course_id == course_id, Module.tenant_id == author.tenant_id,
        ),
    )
    if lesson != lesson_id:
        raise HTTPException(404, detail="lesson_not_found")
    block = (await db.execute(select(ContentBlock).where(
        ContentBlock.lesson_id == lesson_id, ContentBlock.block_type == BLOCK_TYPE,
    ))).scalar_one_or_none()
    return course, block


def _revision(raw: str | None) -> str | None:
    return sha256(raw.encode()).hexdigest() if raw is not None else None


@router.get("/editor", response_model=PracticeEdit)
async def read_editor(course_id: UUID, lesson_id: UUID, db: Db, author: Author) -> PracticeEdit:
    _, block = await _draft_block(db, course_id, lesson_id, author)
    raw = cast(str | None, block.content) if block else None
    return PracticeEdit(revision=_revision(raw), practice=DecisionPractice.model_validate_json(raw) if raw else None)


@router.put("/editor", response_model=PracticeEdit)
async def save_editor(course_id: UUID, lesson_id: UUID, payload: PracticeEdit, db: Db, author: Author) -> PracticeEdit:
    course, existing = await _draft_block(db, course_id, lesson_id, author, lock=True)
    prior = cast(str | None, existing.content) if existing else None
    if payload.revision != _revision(prior):
        raise HTTPException(409, detail="decision_practice_revision_changed")
    raw = payload.practice.model_dump_json() if payload.practice else None
    if prior != raw:
        if existing and raw is None:
            await db.delete(existing)
        elif existing:
            cast(Any, existing).content = raw
        else:
            db.add(ContentBlock(lesson_id=lesson_id, block_type=BLOCK_TYPE, content=raw))
        await touch_course(db, course.id, author.tenant_id)
        await db.flush()
    return PracticeEdit(revision=_revision(raw), practice=payload.practice)
