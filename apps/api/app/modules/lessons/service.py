"""Lessons module — service layer"""

from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.courses import Course
from app.modules.courses.release_service import (
    touch_course as _touch_course,
)
from app.modules.courses.release_service import (
    touch_course_by_lesson as _touch_course_by_lesson,
)
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.lessons.schemas import LessonCreate, LessonUpdate, ModuleCreate, ModuleUpdate


async def _mark_lesson_quizzes_needs_review(db: AsyncSession, lesson_id: UUID, tenant_id: UUID) -> None:
    from app.modules.quizzes.models import Quiz

    await db.execute(
        update(Quiz)
        .where(Quiz.lesson_id == lesson_id, Quiz.tenant_id == tenant_id)
        .values(review_status="needs_review", reviewed_by=None, reviewed_at=None)
    )


async def list_modules(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> list[Module]:
    result = await db.execute(
        select(Module)
        .where(
            Module.course_id == course_id,
            Module.tenant_id == tenant_id,
        )
        .order_by(Module.order_index)
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
    await _touch_course(db, course_id, tenant_id)
    await db.flush()
    return module


async def update_module(db: AsyncSession, module_id: UUID, tenant_id: UUID, data: ModuleUpdate) -> Module:
    result = await db.execute(select(Module).where(Module.id == module_id, Module.tenant_id == tenant_id))
    module = result.scalar_one_or_none()
    if not module:
        raise ValueError("Module not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(module, field, value)
    await _touch_course(db, module.course_id, tenant_id)
    await db.flush()
    await db.refresh(module)
    return module


async def delete_module(db: AsyncSession, module_id: UUID, tenant_id: UUID) -> None:
    result = await db.execute(select(Module).where(Module.id == module_id, Module.tenant_id == tenant_id))
    module = result.scalar_one_or_none()
    if not module:
        raise ValueError("Module not found")
    course_id = module.course_id
    await db.delete(module)
    await _touch_course(db, course_id, tenant_id)


async def list_lessons(db: AsyncSession, module_id: UUID, tenant_id: UUID) -> list[Lesson]:
    result = await db.execute(
        select(Lesson)
        .where(
            Lesson.module_id == module_id,
            Lesson.tenant_id == tenant_id,
        )
        .order_by(Lesson.order_index)
    )
    return result.scalars().all()


async def create_lesson(db: AsyncSession, module_id: UUID, tenant_id: UUID, data: LessonCreate) -> Lesson:
    parent_module = await db.scalar(select(Module).where(Module.id == module_id, Module.tenant_id == tenant_id))
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
    if parent_module is not None:
        await _touch_course(db, parent_module.course_id, tenant_id)
    await db.flush()
    return lesson


async def update_lesson(db: AsyncSession, lesson_id: UUID, tenant_id: UUID, data: LessonUpdate) -> Lesson:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise ValueError("Lesson not found")
    parent_module = await db.scalar(select(Module).where(Module.id == lesson.module_id, Module.tenant_id == tenant_id))
    changes = data.model_dump(exclude_unset=True)
    source_affecting_change = any(
        field in changes and changes[field] != getattr(lesson, field) for field in ("title", "content")
    )
    for field, value in changes.items():
        setattr(lesson, field, value)
    if lesson.source_document_ids and source_affecting_change:
        lesson.source_validation_status = "needs_review"
    if source_affecting_change:
        await _mark_lesson_quizzes_needs_review(db, lesson.id, tenant_id)
    if parent_module is not None:
        await _touch_course(db, parent_module.course_id, tenant_id)
    await db.flush()
    await db.refresh(lesson)
    return lesson


async def delete_lesson(db: AsyncSession, lesson_id: UUID, tenant_id: UUID) -> None:
    result = await db.execute(select(Lesson).where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id))
    lesson = result.scalar_one_or_none()
    if not lesson:
        raise ValueError("Lesson not found")
    parent_module = await db.scalar(select(Module).where(Module.id == lesson.module_id, Module.tenant_id == tenant_id))
    await db.delete(lesson)
    if parent_module is not None:
        await _touch_course(db, parent_module.course_id, tenant_id)


async def reorder_items(db: AsyncSession, item_type: str, ids_order: list[UUID], tenant_id: UUID) -> None:
    """Reorder modules or lessons by array of IDs in order. Validates tenant ownership and strictly prevents cross-course reordering."""
    if not ids_order:
        return
    if item_type not in ("module", "lesson"):
        raise ValueError(f"Unknown item_type '{item_type}'")

    if item_type == "module":
        res = await db.execute(select(Module).where(Module.id.in_(ids_order), Module.tenant_id == tenant_id))
        modules = {m.id: m for m in res.scalars().all()}
        for item_id in ids_order:
            if item_id not in modules:
                raise ValueError("Module not found or access denied")
        course_ids = {m.course_id for m in modules.values()}
        if len(course_ids) > 1:
            raise ValueError("Запрещено переупорядочивать модули между разными курсами")
        for index, item_id in enumerate(ids_order):
            await db.execute(
                update(Module).where(Module.id == item_id, Module.tenant_id == tenant_id).values(order_index=index)
            )
        target_course_id = next(iter(course_ids))
        await _touch_course(db, target_course_id, tenant_id)

    elif item_type == "lesson":
        res = await db.execute(select(Lesson).where(Lesson.id.in_(ids_order), Lesson.tenant_id == tenant_id))
        lessons: dict[UUID, Lesson] = {cast(UUID, les.id): cast(Lesson, les) for les in res.scalars().all()}
        for item_id in ids_order:
            if item_id not in lessons:
                raise ValueError("Lesson not found or access denied")
        mod_ids = list({les.module_id for les in lessons.values()})
        mod_res = await db.execute(select(Module).where(Module.id.in_(mod_ids), Module.tenant_id == tenant_id))
        modules_map: dict[UUID, Module] = {cast(UUID, m.id): m for m in mod_res.scalars().all()}
        course_ids = {m.course_id for m in modules_map.values()}
        if len(course_ids) > 1:
            raise ValueError("Запрещено переупорядочивать уроки между разными курсами")
        for index, item_id in enumerate(ids_order):
            await db.execute(
                update(Lesson).where(Lesson.id == item_id, Lesson.tenant_id == tenant_id).values(order_index=index)
            )
        if course_ids:
            target_course_id = next(iter(course_ids))
            await _touch_course(db, target_course_id, tenant_id)


async def reorder_lessons_in_module(
    db: AsyncSession,
    *,
    module_id: UUID,
    ids_order: list[UUID],
    tenant_id: UUID,
) -> None:
    """Reorder exactly the complete lesson set belonging to one module."""
    if len(ids_order) != len(set(ids_order)):
        raise ValueError("Lesson order contains duplicate IDs")
    module = await db.scalar(
        select(Module).where(Module.id == module_id, Module.tenant_id == tenant_id).with_for_update()
    )
    if module is None:
        raise LookupError("Module not found")
    lessons = list(
        (
            await db.scalars(
                select(Lesson).where(Lesson.module_id == module_id, Lesson.tenant_id == tenant_id).with_for_update()
            )
        ).all()
    )
    by_id = {lesson.id: lesson for lesson in lessons}
    if len(ids_order) != len(lessons) or set(ids_order) != set(by_id):
        raise ValueError("Lesson order must contain every lesson from the selected module exactly once")
    for index, lesson_id in enumerate(ids_order):
        by_id[lesson_id].order_index = index
    await _touch_course(db, module.course_id, tenant_id)
    await db.flush()


async def get_course_structure(db: AsyncSession, course_id: UUID, tenant_id: UUID):
    """Get full course structure with modules and lessons (eagerly loaded)."""
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id, Course.tenant_id == tenant_id)
        .options(selectinload(Course.modules).selectinload(Module.lessons))
    )
    course = result.scalar_one_or_none()
    if not course:
        raise ValueError("Course not found")
    return course


# ── Content Blocks ──────────────────────────────────────────


async def list_content_blocks(db: AsyncSession, lesson_id: UUID, tenant_id: UUID) -> list[ContentBlock]:
    """List content blocks for a lesson."""
    from app.modules.lessons.models import Lesson

    lesson = await db.get(Lesson, lesson_id)
    if not lesson or lesson.tenant_id != tenant_id:
        return []
    result = await db.execute(
        select(ContentBlock).where(ContentBlock.lesson_id == lesson_id).order_by(ContentBlock.order_index)
    )
    return result.scalars().all()


async def create_content_block(
    db: AsyncSession,
    lesson_id: UUID,
    tenant_id: UUID,
    block_type: str,
    content: str | None = None,
    order_index: int = 0,
    metadata_: str | None = None,
) -> ContentBlock:
    """Create a content block for a lesson."""
    from uuid import uuid4

    from app.modules.lessons.models import Lesson

    lesson = await db.get(Lesson, lesson_id)
    if not lesson or lesson.tenant_id != tenant_id:
        raise ValueError("Lesson not found")
    block = ContentBlock(
        id=uuid4(),
        lesson_id=lesson_id,
        block_type=block_type,
        content=content,
        order_index=order_index,
        metadata_=metadata_,
    )
    db.add(block)
    await _mark_lesson_quizzes_needs_review(db, lesson_id, tenant_id)
    await _touch_course_by_lesson(db, lesson_id, tenant_id)
    await db.flush()
    return block


async def update_content_block(
    db: AsyncSession,
    block_id: UUID,
    tenant_id: UUID,
    content: str | None = None,
    order_index: int | None = None,
    metadata_: str | None = None,
) -> ContentBlock | None:
    """Update a content block."""
    block = await db.get(ContentBlock, block_id)
    if not block:
        return None
    from app.modules.lessons.models import Lesson

    lesson = await db.get(Lesson, block.lesson_id)
    if not lesson or lesson.tenant_id != tenant_id:
        return None
    learner_visible_change = False
    if content is not None and content != block.content:
        block.content = content
        learner_visible_change = True
    if order_index is not None and order_index != block.order_index:
        block.order_index = order_index
        learner_visible_change = True
    if metadata_ is not None:
        block.metadata_ = metadata_
    if learner_visible_change:
        await _mark_lesson_quizzes_needs_review(db, lesson.id, tenant_id)
        await _touch_course_by_lesson(db, lesson.id, tenant_id)
    await db.flush()
    return block


async def delete_content_block(db: AsyncSession, block_id: UUID, tenant_id: UUID) -> bool:
    """Delete a content block."""
    block = await db.get(ContentBlock, block_id)
    if not block:
        return False
    from app.modules.lessons.models import Lesson

    lesson = await db.get(Lesson, block.lesson_id)
    if not lesson or lesson.tenant_id != tenant_id:
        return False
    await _mark_lesson_quizzes_needs_review(db, lesson.id, tenant_id)
    await _touch_course_by_lesson(db, lesson.id, tenant_id)
    await db.delete(block)
    return True


async def reorder_content_blocks(db: AsyncSession, lesson_id: UUID, ids_order: list[UUID], tenant_id: UUID) -> None:
    """Reorder content blocks within a lesson."""
    from sqlalchemy import update as sa_update

    from app.modules.lessons.models import Lesson

    lesson = await db.get(Lesson, lesson_id)
    if not lesson or lesson.tenant_id != tenant_id:
        raise ValueError("Lesson not found")
    changed = False
    for index, block_id in enumerate(ids_order):
        block = await db.get(ContentBlock, block_id)
        if block and block.lesson_id == lesson_id and block.order_index != index:
            changed = True
            await db.execute(sa_update(ContentBlock).where(ContentBlock.id == block_id).values(order_index=index))
    if changed:
        await _mark_lesson_quizzes_needs_review(db, lesson_id, tenant_id)
        await _touch_course_by_lesson(db, lesson_id, tenant_id)
