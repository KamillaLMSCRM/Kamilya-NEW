"""Read-only document catalog queries."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import String, and_, cast, exists, func, literal, or_, select, union
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.courses.models import Course
from app.modules.documents.schemas import (
    DocumentCatalogItem,
    DocumentCatalogPage,
    DocumentCatalogResponse,
    DocumentIndexResponse,
    DocumentUsageDetailSummary,
    DocumentUsageItem,
    DocumentUsagePage,
    DocumentUsageResponse,
    DocumentUsageSummary,
)
from app.modules.lessons.models import Lesson, Module
from app.modules.positions.models import Position

CatalogSort = Literal["created_desc", "created_asc", "title_asc", "size_desc"]


@dataclass(frozen=True)
class CatalogFilters:
    q: str | None = None
    category: str | None = None
    index_status: str | None = None
    lifecycle_status: str = "active"
    used: bool | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: CatalogSort = "created_desc"
    cursor: str | None = None
    limit: int = 25
    include_usages_summary: bool = False


def _usage_cursor(index: int) -> str:
    return _sign_cursor({"sort": "document_usages", "value": index, "id": str(UUID(int=0))})


def _decode_usage_cursor(cursor: str) -> int:
    value, _ = _decode_cursor(cursor, "document_usages")
    try:
        index = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid document usage cursor") from exc
    if index < 0:
        raise ValueError("Invalid document usage cursor")
    return index


def _jsonb_contains_document(column):
    return column.op("@>")(func.jsonb_build_array(cast(Document.id, String)))


def _usage_expressions(tenant_id: UUID):
    position_usage = exists(
        select(Position.id).where(
            Position.tenant_id == tenant_id,
            Position.instruction_document_id == Document.id,
        )
    )
    direct_course_usage = exists(
        select(Course.id).where(
            Course.tenant_id == tenant_id,
            or_(
                Course.source_instruction_id == Document.id,
                _jsonb_contains_document(Course.source_document_ids),
            ),
        )
    )
    lesson_usage = exists(
        select(Lesson.id)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Lesson.tenant_id == tenant_id,
            Module.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
            _jsonb_contains_document(Lesson.source_document_ids),
        )
    )
    active_job_usage = exists(
        select(AIJob.id).where(
            AIJob.tenant_id == tenant_id,
            AIJob.status.in_(("pending", "running")),
            cast(AIJob.params, JSONB)["documents"].contains(
                func.jsonb_build_array(cast(Document.id, String))
            ),
        )
    )
    return position_usage, direct_course_usage, lesson_usage, active_job_usage


def _usage_counts(tenant_id: UUID):
    position_count = (
        select(func.count(Position.id))
        .where(
            Position.tenant_id == tenant_id,
            Position.instruction_document_id == Document.id,
        )
        .correlate(Document)
        .scalar_subquery()
    )
    direct_courses = (
        select(Course.id.label("course_id"))
        .where(
            Course.tenant_id == tenant_id,
            or_(
                Course.source_instruction_id == Document.id,
                _jsonb_contains_document(Course.source_document_ids),
            ),
        )
        .correlate(Document)
    )
    lesson_courses = (
        select(Course.id.label("course_id"))
        .join(Module, Module.course_id == Course.id)
        .join(Lesson, Lesson.module_id == Module.id)
        .where(
            Course.tenant_id == tenant_id,
            Module.tenant_id == tenant_id,
            Lesson.tenant_id == tenant_id,
            _jsonb_contains_document(Lesson.source_document_ids),
        )
        .correlate(Document)
    )
    course_ids = union(direct_courses, lesson_courses).subquery()
    course_count = select(func.count()).select_from(course_ids).scalar_subquery()
    lesson_count = (
        select(func.count(Lesson.id))
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Lesson.tenant_id == tenant_id,
            Module.tenant_id == tenant_id,
            Course.tenant_id == tenant_id,
            _jsonb_contains_document(Lesson.source_document_ids),
        )
        .correlate(Document)
        .scalar_subquery()
    )
    active_job_count = (
        select(func.count(AIJob.id))
        .where(
            AIJob.tenant_id == tenant_id,
            AIJob.status.in_(("pending", "running")),
            cast(AIJob.params, JSONB)["documents"].contains(
                func.jsonb_build_array(cast(Document.id, String))
            ),
        )
        .correlate(Document)
        .scalar_subquery()
    )
    return position_count, course_count, lesson_count, active_job_count


def _escape_search(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _sort_value(document: Document, sort: CatalogSort) -> str | int:
    if sort.startswith("created_"):
        return document.created_at.isoformat()
    if sort == "title_asc":
        return document.title.lower()
    return int(document.size)


def _sign_cursor(payload: dict[str, str | int]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=")
    signature = hmac.new(
        get_settings().JWT_SECRET.encode(),
        encoded,
        hashlib.sha256,
    ).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _decode_cursor(cursor: str, sort: str) -> tuple[str | int, UUID]:
    try:
        encoded_text, signature_text = cursor.split(".", 1)
        encoded = encoded_text.encode()
        expected = hmac.new(
            get_settings().JWT_SECRET.encode(),
            encoded,
            hashlib.sha256,
        ).digest()
        provided = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        if not hmac.compare_digest(expected, provided):
            raise ValueError("invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4)))
        if payload.get("sort") != sort:
            raise ValueError("cursor sort mismatch")
        value = payload["value"]
        document_id = UUID(payload["id"])
        if sort.startswith("created_"):
            datetime.fromisoformat(str(value))
        elif sort in {"size_desc", "document_usages"}:
            value = int(value)
        elif not isinstance(value, str):
            raise ValueError("invalid title cursor")
        return value, document_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid catalog cursor") from exc


async def list_document_usages(
    db: AsyncSession,
    tenant_id: UUID,
    document_id: UUID,
    *,
    cursor: str | None = None,
    limit: int = 25,
) -> DocumentUsageResponse:
    """Return every tenant-scoped product object that currently uses a document."""

    items: list[DocumentUsageItem] = []

    positions = (
        await db.execute(
            select(Position.id, Position.name).where(
                Position.tenant_id == tenant_id,
                Position.instruction_document_id == document_id,
            )
        )
    ).all()
    items.extend(
        DocumentUsageItem(
            type="position_instruction",
            id=str(position_id),
            title=name,
            status="active",
            route="/positions",
        )
        for position_id, name in positions
    )

    direct_courses = (
        await db.execute(
            select(
                Course.id,
                Course.title,
                Course.status,
                Course.source_instruction_id,
                Course.source_document_ids,
            ).where(
                Course.tenant_id == tenant_id,
                or_(
                    Course.source_instruction_id == document_id,
                    Course.source_document_ids.op("@>")(
                        func.jsonb_build_array(str(document_id))
                    ),
                ),
            )
        )
    ).all()
    course_usage_ids = {str(row[0]) for row in direct_courses}
    for course_id, title, status, instruction_id, source_ids in direct_courses:
        if instruction_id == document_id:
            items.append(
                DocumentUsageItem(
                    type="course_instruction",
                    id=str(course_id),
                    title=title,
                    status=status,
                    route=f"/courses/{course_id}",
                )
            )
        if str(document_id) in {str(value) for value in (source_ids or [])}:
            items.append(
                DocumentUsageItem(
                    type="course_source",
                    id=str(course_id),
                    title=title,
                    status=status,
                    route=f"/courses/{course_id}",
                )
            )

    lesson_rows = (
        await db.execute(
            select(Lesson.id, Lesson.title, Course.id, Course.status)
            .join(Module, Module.id == Lesson.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(
                Lesson.tenant_id == tenant_id,
                Module.tenant_id == tenant_id,
                Course.tenant_id == tenant_id,
                Lesson.source_document_ids.op("@>")(
                    func.jsonb_build_array(str(document_id))
                ),
            )
        )
    ).all()
    course_usage_ids.update(str(row[2]) for row in lesson_rows)
    items.extend(
        DocumentUsageItem(
            type="lesson_source",
            id=str(lesson_id),
            title=lesson_title,
            status=course_status,
            route=f"/courses/{course_id}/edit",
        )
        for lesson_id, lesson_title, course_id, course_status in lesson_rows
    )

    active_jobs = (
        await db.execute(
            select(AIJob.id, AIJob.stage, AIJob.message).where(
                AIJob.tenant_id == tenant_id,
                AIJob.status.in_(("pending", "running")),
                cast(AIJob.params, JSONB)["documents"].contains([str(document_id)]),
            )
        )
    ).all()
    items.extend(
        DocumentUsageItem(
            type="active_ai_job",
            id=job_id,
            title=message or "AI generation",
            status=stage,
            route="/ai/generate",
        )
        for job_id, stage, message in active_jobs
    )

    order = {
        "position_instruction": 0,
        "course_instruction": 1,
        "course_source": 2,
        "lesson_source": 3,
        "active_ai_job": 4,
    }
    items.sort(key=lambda item: (order[item.type], item.title.casefold(), item.id))
    start = _decode_usage_cursor(cursor) if cursor else 0
    page_items = items[start : start + limit]
    next_index = start + len(page_items)
    has_more = next_index < len(items)
    return DocumentUsageResponse(
        summary=DocumentUsageDetailSummary(
            total=len(items),
            positions=sum(item.type == "position_instruction" for item in items),
            courses=len(course_usage_ids),
            lessons=sum(item.type == "lesson_source" for item in items),
            active_jobs=sum(item.type == "active_ai_job" for item in items),
        ),
        items=page_items,
        page=DocumentUsagePage(
            next_cursor=_usage_cursor(next_index) if has_more else None,
            has_more=has_more,
            limit=limit,
        ),
    )


def _cursor_predicate(sort: CatalogSort, value: str | int, document_id: UUID):
    if sort.startswith("created_"):
        sort_column = Document.created_at
        typed_value = datetime.fromisoformat(str(value))
    elif sort == "title_asc":
        sort_column = func.lower(Document.title)
        typed_value = str(value)
    else:
        sort_column = Document.size
        typed_value = int(value)

    if sort in {"created_desc", "size_desc"}:
        return or_(
            sort_column < typed_value,
            and_(sort_column == typed_value, Document.id < document_id),
        )
    return or_(
        sort_column > typed_value,
        and_(sort_column == typed_value, Document.id > document_id),
    )


def _order_by(sort: CatalogSort):
    if sort == "created_desc":
        return Document.created_at.desc(), Document.id.desc()
    if sort == "created_asc":
        return Document.created_at.asc(), Document.id.asc()
    if sort == "title_asc":
        return func.lower(Document.title).asc(), Document.id.asc()
    return Document.size.desc(), Document.id.desc()


async def list_catalog(
    db: AsyncSession,
    tenant_id: UUID,
    filters: CatalogFilters,
) -> DocumentCatalogResponse:
    """Return a tenant-scoped, deterministic catalog page."""

    if filters.include_usages_summary:
        position_count, course_count, lesson_count, active_job_count = _usage_counts(tenant_id)
    else:
        position_count, course_count = literal(0), literal(0)
        lesson_count, active_job_count = literal(0), literal(0)
    latest = aliased(Document)
    is_latest = ~exists(
        select(latest.id).where(
            latest.tenant_id == tenant_id,
            latest.source_family_id == Document.source_family_id,
            latest.lifecycle_status == filters.lifecycle_status,
            latest.version > Document.version,
        )
    )
    statement = select(
        Document,
        position_count.label("position_count"),
        course_count.label("course_count"),
        lesson_count.label("lesson_count"),
        active_job_count.label("active_job_count"),
        is_latest.label("is_latest"),
    ).where(
        Document.tenant_id == tenant_id,
        Document.lifecycle_status == filters.lifecycle_status,
    )

    if filters.q:
        pattern = f"%{_escape_search(filters.q.strip())}%"
        statement = statement.where(
            or_(
                Document.title.ilike(pattern, escape="\\"),
                Document.filename.ilike(pattern, escape="\\"),
                Document.description.ilike(pattern, escape="\\"),
            )
        )
    if filters.category:
        statement = statement.where(Document.category == filters.category)
    if filters.index_status:
        statement = statement.where(Document.index_status == filters.index_status)
    if filters.created_from:
        statement = statement.where(Document.created_at >= filters.created_from)
    if filters.created_to:
        statement = statement.where(Document.created_at <= filters.created_to)
    if filters.used is not None:
        usages = or_(*_usage_expressions(tenant_id))
        statement = statement.where(usages if filters.used else ~usages)
    if filters.cursor:
        value, document_id = _decode_cursor(filters.cursor, filters.sort)
        statement = statement.where(_cursor_predicate(filters.sort, value, document_id))

    statement = statement.order_by(*_order_by(filters.sort)).limit(filters.limit + 1)
    rows = (await db.execute(statement)).all()
    has_more = len(rows) > filters.limit
    page_rows = rows[: filters.limit]

    items = []
    for document, positions, courses, lessons, active_jobs, latest_flag in page_rows:
        usage_summary = None
        if filters.include_usages_summary:
            usage_summary = DocumentUsageSummary(
                total=int(positions) + int(courses) + int(lessons) + int(active_jobs),
                positions=int(positions),
                courses=int(courses),
                lessons=int(lessons),
                active_jobs=int(active_jobs),
            )
        items.append(
            DocumentCatalogItem(
                id=document.id,
                source_family_id=document.source_family_id,
                title=document.title,
                filename=document.filename,
                content_type=document.content_type,
                size=document.size,
                description=document.description,
                category=document.category,
                index=DocumentIndexResponse(
                    status=document.index_status,
                    error_code=document.index_error_code,
                    message=document.index_message,
                    chunks_total=document.index_chunks_total,
                    chunks_indexed=document.index_chunks_indexed,
                    indexed_at=document.indexed_at,
                    revision=document.index_revision,
                ),
                version=document.version,
                is_latest=bool(latest_flag),
                lifecycle_status=document.lifecycle_status,
                deletion_error_code=document.deletion_error_code,
                deletion_error_message=document.deletion_error_message,
                deletion_job_id=document.deletion_job_id,
                created_at=document.created_at,
                updated_at=document.updated_at,
                usages_summary=usage_summary,
            )
        )

    next_cursor = None
    if has_more and page_rows:
        last_document = page_rows[-1][0]
        next_cursor = _sign_cursor(
            {
                "sort": filters.sort,
                "value": _sort_value(last_document, filters.sort),
                "id": str(last_document.id),
            }
        )
    return DocumentCatalogResponse(
        items=items,
        page=DocumentCatalogPage(
            next_cursor=next_cursor,
            has_more=has_more,
            limit=filters.limit,
        ),
    )
