"""Uploaded lesson images use native storage and exact published lesson references."""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.storage import get_storage
from app.models.courses import Course
from app.modules.lessons.models import Lesson, Module

LessonImageScope = tuple[UUID | str, UUID | str]

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg")}
ILLUSTRATION_ID = re.compile(r"illustration-([a-f0-9]{64})\.(png|jpg)\Z")
_REFERENCE = re.compile(
    r"^[ \t]*!\[[^\r\n]*?\]\((/v1/courses/[^/\s]+/lessons/[^/\s]+/source-assets/"
    r"illustration-[a-f0-9]{64}\.(?:png|jpg))(?=[ )])",
    re.MULTILINE,
)


def _normalize(raw: bytes) -> tuple[bytes, str, str]:
    try:
        with Image.open(BytesIO(raw), formats=list(FORMATS)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(413, detail="lesson_illustration_too_large")
            image_format = image.format
            if image_format not in FORMATS or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Expected a single PNG or JPEG")
            extension, mime = FORMATS[image_format]
            oriented = ImageOps.exif_transpose(image)
            alpha = "A" in oriented.getbands() or "transparency" in oriented.info
            clean = oriented.convert("RGBA" if extension == "png" and alpha else "RGB")
            clean.info.clear()
            output = BytesIO()
            clean.save(output, format=image_format)
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, detail="lesson_illustration_too_large") from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(422, detail="lesson_illustration_invalid") from exc
    payload = output.getvalue()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(413, detail="lesson_illustration_too_large")
    return payload, extension, mime


def illustration_descriptor(tenant_id: UUID, course_id: UUID, lesson_id: UUID,
                            asset_id: str) -> dict[str, str] | None:
    match = ILLUSTRATION_ID.fullmatch(asset_id)
    if match is None:
        return None
    digest, extension = match.groups()
    return {"sha256": digest, "mime_type": "image/png" if extension == "png" else "image/jpeg",
            "storage_key": f"lesson-illustrations/{tenant_id}/{course_id}/{lesson_id}/{digest}.{extension}"}


def lesson_image_url(course_id: UUID | str, lesson_id: UUID | str, asset_id: str) -> str:
    return f"/v1/courses/{course_id}/lessons/{lesson_id}/source-assets/{asset_id}"


def illustration_urls(content: object) -> set[str]:
    if not isinstance(content, str):
        return set()
    return set(_REFERENCE.findall(content))


def rebind_lesson_illustrations(content: str, previous: LessonImageScope,
                               current: LessonImageScope) -> str:
    original = lesson_image_url(*previous, "")
    target = lesson_image_url(*current, "")

    def replace(match: re.Match[str]) -> str:
        url = match[1]
        if not url.startswith(original):
            return match[0]
        return match[0][:match.start(1) - match.start()] + target + url[len(original):]

    return _REFERENCE.sub(replace, content)


async def copy_lesson_illustrations(tenant_id: UUID, content: str | None,
                                    previous_course_id: UUID, previous_lesson_id: UUID,
                                    course_id: UUID, lesson_id: UUID) -> str | None:
    if content is None:
        return None
    prefix = lesson_image_url(previous_course_id, previous_lesson_id, "")
    ids = {url[len(prefix):] for url in illustration_urls(content) if url.startswith(prefix)}
    for asset_id in sorted(ids):
        old = illustration_descriptor(tenant_id, previous_course_id, previous_lesson_id, asset_id)
        new = illustration_descriptor(tenant_id, course_id, lesson_id, asset_id)
        if old is None or new is None:
            raise HTTPException(409, detail="lesson_illustration_missing")
        storage = get_storage()
        raw = await run_in_threadpool(storage.get_bytes, old["storage_key"])
        if raw is None or hashlib.sha256(raw).hexdigest() != old["sha256"]:
            raise HTTPException(409, detail="lesson_illustration_missing")
        await run_in_threadpool(storage.put_bytes, new["storage_key"], raw, new["mime_type"])
    return rebind_lesson_illustrations(content, (previous_course_id, previous_lesson_id),
                                       (course_id, lesson_id)) if ids else content


def snapshot_illustration_content(snapshot: dict[str, Any]) -> dict[str, str | None]:
    return {lesson["id"]: lesson.get("content") for module in snapshot.get("modules", [])
            for lesson in module.get("lessons", [])}


async def owns_illustration_lesson(db: AsyncSession, tenant_id: UUID,
                                  course_id: UUID, lesson_id: UUID) -> bool:
    owned = await db.scalar(
        select(Lesson.id).join(Module, Module.id == Lesson.module_id).join(Course, Course.id == Module.course_id)
        .where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id, Module.tenant_id == tenant_id,
               Course.id == course_id, Course.tenant_id == tenant_id, Course.delivery_type == "native")
    )
    return owned == lesson_id


async def upload_illustration(db: AsyncSession, tenant_id: UUID, course_id: UUID,
                              lesson_id: UUID, file: UploadFile) -> str:
    if not await owns_illustration_lesson(db, tenant_id, course_id, lesson_id):
        raise HTTPException(404, detail="lesson_not_found")
    posted = await file.read(MAX_IMAGE_BYTES + 1)
    if len(posted) > MAX_IMAGE_BYTES:
        raise HTTPException(413, detail="lesson_illustration_too_large")
    raw, extension, mime = await run_in_threadpool(_normalize, posted)
    digest = hashlib.sha256(raw).hexdigest()
    asset_id = f"illustration-{digest}.{extension}"
    key = f"lesson-illustrations/{tenant_id}/{course_id}/{lesson_id}/{digest}.{extension}"
    await run_in_threadpool(get_storage().put_bytes, key, raw, mime)
    return lesson_image_url(course_id, lesson_id, asset_id)
