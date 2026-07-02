"""Lessons module — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.auth import get_current_user, require_tenant_user
from app.core.db import get_db
from app.modules.lessons.schemas import (
    ModuleCreate, ModuleUpdate, ModuleResponse,
    LessonCreate, LessonUpdate, LessonResponse,
    CourseStructureResponse, ModuleWithLessonsResponse,
    ContentBlockCreate, ContentBlockResponse,
)
from app.modules.lessons.service import (
    list_modules, create_module, update_module, delete_module,
    list_lessons, create_lesson as create_lesson_service, update_lesson, delete_lesson,
    reorder_items, get_course_structure,
    list_content_blocks, create_content_block, update_content_block,
    delete_content_block, reorder_content_blocks,
)
from app.modules.lessons.models import Module
from app.models.courses import Course

router = APIRouter(
    dependencies=[Depends(require_tenant_user())],
)


@router.get("/courses/{course_id}/modules", response_model=List[ModuleResponse])
async def list_course_modules(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    modules = await list_modules(db, course_id, user.tenant_id)
    return modules


@router.post("/courses/{course_id}/modules", response_model=ModuleResponse, status_code=201)
async def create_course_module(
    course_id: UUID,
    data: ModuleCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    module = await create_module(db, course_id, user.tenant_id, data)
    return module


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
async def update_course_module(
    module_id: UUID,
    data: ModuleUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    module = await update_module(db, module_id, user.tenant_id, data)
    return module


@router.delete("/modules/{module_id}", status_code=204)
async def delete_course_module(
    module_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await delete_module(db, module_id, user.tenant_id)


@router.post("/courses/{course_id}/reorder", status_code=200)
async def reorder_modules(
    course_id: UUID,
    ids_order: List[UUID],
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await reorder_items(db, "module", ids_order, user.tenant_id)
    return {"status": "ok"}


@router.get("/modules/{module_id}/lessons", response_model=List[LessonResponse])
async def list_module_lessons(
    module_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(Module).where(Module.id == module_id, Module.tenant_id == user.tenant_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    lessons = await list_lessons(db, module_id, user.tenant_id)
    return lessons


@router.post("/modules/{module_id}/lessons", response_model=LessonResponse, status_code=201)
async def create_lesson(
    module_id: UUID,
    data: LessonCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(select(Module).where(Module.id == module_id, Module.tenant_id == user.tenant_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    lesson = await create_lesson_service(db, module_id, user.tenant_id, data)
    return lesson


@router.get("/lessons/{lesson_id}", response_model=LessonResponse)
async def get_lesson_endpoint(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    from sqlalchemy import select
    from app.modules.lessons.models import Lesson
    result = await db.execute(
        select(Lesson).where(Lesson.id == lesson_id, Lesson.tenant_id == user.tenant_id)
    )
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


@router.patch("/lessons/{lesson_id}", response_model=LessonResponse)
async def update_lesson_endpoint(
    lesson_id: UUID,
    data: LessonUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    lesson = await update_lesson(db, lesson_id, user.tenant_id, data)
    return lesson


@router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson_endpoint(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await delete_lesson(db, lesson_id, user.tenant_id)


@router.post("/lessons/{module_id}/reorder", status_code=200)
async def reorder_lessons(
    module_id: UUID,
    ids_order: List[UUID],
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await reorder_items(db, "lesson", ids_order, user.tenant_id)
    return {"status": "ok"}


@router.get("/courses/{course_id}/structure", response_model=CourseStructureResponse)
async def get_course_structure_endpoint(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = await get_course_structure(db, course_id, user.tenant_id)
    return course


# ── Content Blocks ──────────────────────────────────────────


@router.get("/lessons/{lesson_id}/content-blocks", response_model=List[ContentBlockResponse])
async def list_lesson_content_blocks(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await list_content_blocks(db, lesson_id, user.tenant_id)


@router.post("/lessons/{lesson_id}/content-blocks", response_model=ContentBlockResponse, status_code=201)
async def create_lesson_content_block(
    lesson_id: UUID,
    data: ContentBlockCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        block = await create_content_block(
            db, lesson_id, user.tenant_id,
            block_type=data.block_type,
            content=data.content,
            order_index=data.order_index,
            metadata_=data.metadata,
        )
        return block
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/content-blocks/{block_id}", response_model=ContentBlockResponse)
async def update_lesson_content_block(
    block_id: UUID,
    data: ContentBlockCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    block = await update_content_block(
        db, block_id, user.tenant_id,
        content=data.content,
        order_index=data.order_index,
        metadata_=data.metadata,
    )
    if not block:
        raise HTTPException(status_code=404, detail="Content block not found")
    return block


@router.delete("/content-blocks/{block_id}", status_code=204)
async def delete_lesson_content_block(
    block_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    deleted = await delete_content_block(db, block_id, user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Content block not found")


@router.post("/lessons/{lesson_id}/content-blocks/reorder", status_code=200)
async def reorder_lesson_content_blocks(
    lesson_id: UUID,
    ids_order: List[UUID],
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        await reorder_content_blocks(db, lesson_id, ids_order, user.tenant_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
