"""Lessons module — service layer"""
from uuid import UUID
from typing import List
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lessons.models import Module, Lesson, ContentBlock
from app.modules.lessons.schemas import ModuleCreate, ModuleUpdate, LessonCreate, LessonUpdate
from app.models.courses import Course


async def list_modules(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> List[Module]:
    result = await db.execute(
        select(Module).where(
            Module.course_id == course_id,
            Module.tenant_id == tenant_id,
        ).order_by(Module.order_index)
    )
    return result.scalars().all()


async def create_module(db: AsyncSession, course_id: UUID, tenant_id: UUID, data: ModuleCreate) -> Module:
    max_order = await db.execute(
        select(Module.order_index).where(Module.course_id == course_id).order_by(Module.order_index.desc()).limit(1)
    )
    next_order = (max_order.scalar() or 0) + 1
    module = Module(
        tenant_id=tenant_id,
        course_id=course_id,
        title=data.title,
        description=data.description,
        order_index=next_order,
    )
    db.add(module)
    await db.flush()
    return module


async def update_module(db: AsyncSession, module_id: UUID, tenant_id: UUID, data: ModuleUpdate) -> Module:
    result = await db.execute(select(Module).where(Module.id == module_id, Module.tenant_id == tenant_id))
    module = result.scalar_one_or_none()
    if not module:
        raise ValueError("Module not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(module, field, value)
    await db.flush()
    return module


async def delete_module(db: AsyncSession, module_id: UUID, tenant_id: UUID) -> None:
    result = await db.execute(select(Module).where(Module.id == module_id, Module.tenant_id == tenant_id))
    module = result.scalar_one_or_none()
    if not module:
        raise ValueError("Module not found")
    await db.delete(module)


async def list_lessons(db: AsyncSession, module_id: UUID, tenant_id: UUID) -> List[Lesson]:
    result = await db.execute(
        select(Lesson).where(
            Lesson.module_id == module_id,
            Lesson.tenant_id == tenant_id,
        ).order_by(Lesson.order_index)
    )
    return result.scalars().all()


async def create_lesson(db: AsyncSession, module_id: UUID, tenant_id: UUID, data: LessonCreate) -> Lesson:
    max_order = await db.execute(
        select(Lesson.order_index).where(Lesson.module_id == module_id).order_by(Lesson.order_index.desc()).limit(1)
    )
    next_order = (max_order.scalar() or 0) + 1
    lesson = Lesson(
        module_id=module_id,
        tenant_id=tenant_id,
        title=data.title,
        content_type=data.content_type,
        content=data.content,
        duration_seconds=data.duration_seconds,
        order_index=next_order,
    )
    db.add(lesson)
    await db.flush()
    return lesson


async def update_lesson(db: AsyncSession, lesson_id: UUID, tenant_id: UUID, data: LessonUpdate) -> Lesson:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise ValueError("Lesson not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(lesson, field, value)
    await db.flush()
    return lesson


async def delete_lesson(db: AsyncSession, lesson_id: UUID, tenant_id: UUID) -> None:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise ValueError("Lesson not found")
    await db.delete(lesson)


async def reorder_items(db: AsyncSession, item_type: str, ids_order: list[UUID]) -> None:
    """Reorder modules or lessons by array of IDs in order."""
    from app.modules.lessons.models import Module, Lesson
    model = Module if item_type == "module" else Lesson
    for index, item_id in enumerate(ids_order):
        await db.execute(
            update(model)
            .where(model.id == item_id)
            .values(order_index=index)
        )


async def get_course_structure(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> Course:
    """Get full course structure with modules and lessons."""
    result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id))
    course = result.scalar_one_or_none()
    if not course:
        raise ValueError("Course not found")
    return course
