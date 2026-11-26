"""Tenant-scoped delivery of prepared source illustrations."""

from __future__ import annotations

import hashlib
import re
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.models.enrollment import Enrollment
from app.modules.courses.access import AUTHORING_ROLES, require_course_access
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256
from app.modules.lessons.illustrations import (
    illustration_descriptor,
    illustration_urls,
    lesson_image_url,
    owns_illustration_lesson,
)
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.source_editorial_review.models import DocumentEditorialEvent
from app.modules.source_editorial_review.service import owned_document
from app.modules.source_preparation.domain import POLICY, PreparedSource, validate_binding

_ASSET = re.compile(r"asset-([a-f0-9]{64})\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _missing() -> HTTPException:
    return HTTPException(status_code=404, detail="Source image not found")


def _descriptor(value: object, tenant_id: UUID, asset_id: str) -> dict[str, str] | None:
    if not isinstance(value, dict) or set(value) != {"id", "document_id", "sha256", "mime_type", "storage_key", "preparation_sha256"}:
        return None
    match = _ASSET.fullmatch(asset_id)
    if match is None or value.get("id") != asset_id or value.get("sha256") != match.group(1):
        return None
    try:
        document_id = str(UUID(value["document_id"]))
    except (TypeError, ValueError, AttributeError, KeyError):
        return None
    mime = value.get("mime_type")
    ext = {"image/png": "png", "image/jpeg": "jpg"}.get(mime) if isinstance(mime, str) else None
    preparation = value.get("preparation_sha256")
    if not ext or not isinstance(preparation, str) or not _SHA.fullmatch(preparation):
        return None
    key = f"source-assets/{tenant_id}/{document_id}/{match.group(1)}.{ext}"
    if value.get("document_id") != document_id or value.get("storage_key") != key:
        return None
    return value


def _response(descriptor: dict[str, str]) -> Response:
    blob = get_storage().get_bytes(descriptor["storage_key"])
    if blob is None or hashlib.sha256(blob).hexdigest() != descriptor["sha256"]:
        raise _missing()
    return Response(content=blob, media_type=descriptor["mime_type"], headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    })


def _snapshot_descriptor(snapshot: object, course_id: UUID, lesson_id: UUID,
                         tenant_id: UUID, asset_id: str) -> dict[str, str] | None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("course"), dict):
        return None
    course = snapshot["course"]
    if course.get("id") != str(course_id) or course.get("tenant_id") != str(tenant_id):
        return None
    uploaded = illustration_descriptor(tenant_id, course_id, lesson_id, asset_id)
    sources = snapshot.get("source_documents")
    modules = snapshot.get("modules")
    if not isinstance(sources, list) or not isinstance(modules, list):
        return None
    source_ids = {row["id"] for row in sources if isinstance(row, dict) and isinstance(row.get("id"), str)}
    for module in modules:
        if not isinstance(module, dict):
            continue
        lessons = module.get("lessons")
        if not isinstance(lessons, list):
            continue
        for lesson in lessons:
            if not isinstance(lesson, dict) or lesson.get("id") != str(lesson_id):
                continue
            if uploaded and lesson_image_url(course_id, lesson_id, asset_id) in illustration_urls(lesson.get("content")):
                return uploaded
            blocks = lesson.get("content_blocks")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                metadata = block.get("metadata") if isinstance(block, dict) else None
                value = metadata.get("source_asset") if isinstance(metadata, dict) else None
                descriptor = _descriptor(value, tenant_id, asset_id)
                if descriptor and descriptor["document_id"] in source_ids:
                    return descriptor
    return None


async def preview_asset(db: AsyncSession, tenant_id: UUID, document_id: UUID,
                        asset_id: str, preparation_sha256: str) -> Response:
    if _ASSET.fullmatch(asset_id) is None or _SHA.fullmatch(preparation_sha256) is None:
        raise _missing()
    doc = await owned_document(db, tenant_id, document_id)
    source_sha = cast(str | None, doc.content_sha256)
    if source_sha is None:
        raise _missing()

    event = DocumentEditorialEvent
    checkpoint = and_(event.kind == "analysis_block",
                      event.payload["key"].astext == f"{POLICY}:manifest:{source_sha}")
    analyzed = event.kind == "analyzed"
    binding = event.payload["preparation"]
    checkpoint_manifest = event.payload["result"]["manifest"]
    contains_asset = [{"id": asset_id}]
    query = select(
        event.kind,
        case((analyzed, binding), else_=checkpoint_manifest),
        case((analyzed, event.payload["original"])),
    ).where(
        event.tenant_id == tenant_id,
        event.document_id == document_id,
        event.original_blob_sha256 == source_sha,
        or_(
            and_(checkpoint, checkpoint_manifest["assets"].contains(contains_asset)),
            and_(analyzed, binding["sha256"].astext == preparation_sha256,
                 binding["manifest"]["assets"].contains(contains_asset)),
        ),
    ).order_by(event.sequence.desc())

    # Read matching candidates one at a time. An older document may have
    # several checkpoints and a newer candidate can fail validation.
    candidates = await db.stream(query.execution_options(yield_per=1))
    try:
        async for kind, preparation, original in candidates:
            try:
                if kind == "analyzed":
                    package, _ = validate_binding(preparation, source_sha, original)
                else:
                    package = PreparedSource.model_validate(preparation)
                if package.original_blob_sha256 != source_sha or package.sha256 != preparation_sha256:
                    continue
                for asset in package.assets:
                    if asset.id != asset_id:
                        continue
                    descriptor = _descriptor({
                        "id": asset.id, "document_id": str(document_id), "sha256": asset.sha256,
                        "mime_type": asset.mime_type, "storage_key": asset.storage_key,
                        "preparation_sha256": preparation_sha256,
                    }, tenant_id, asset_id)
                    if descriptor:
                        return _response(descriptor)
            except (ValueError, TypeError, KeyError):
                continue
    finally:
        await candidates.close()
    raise _missing()


async def course_asset(db: AsyncSession, course_id: UUID, lesson_id: UUID, asset_id: str, user: Any) -> Response:
    tenant_id = UUID(str(user.tenant_id))
    uploaded = illustration_descriptor(tenant_id, course_id, lesson_id, asset_id)
    if uploaded is None and _ASSET.fullmatch(asset_id) is None:
        raise _missing()
    try:
        await require_course_access(db, course_id, user)
    except HTTPException as exc:
        if exc.status_code in (403, 404, 409):
            raise _missing() from exc
        raise
    if user.role in AUTHORING_ROLES:
        if uploaded:
            if not await owns_illustration_lesson(db, tenant_id, course_id, lesson_id):
                raise _missing()
            return _response(uploaded)
        rows = (await db.scalars(select(ContentBlock).join(Lesson, Lesson.id == ContentBlock.lesson_id)
                    .join(Module, Module.id == Lesson.module_id)
                    .where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id,
                           Module.tenant_id == tenant_id, Module.course_id == course_id))).all()
        for block in rows:
            metadata = block.metadata_
            descriptor = _descriptor(metadata.get("source_asset") if isinstance(metadata, dict) else None,
                                     tenant_id, asset_id)
            if descriptor:
                return _response(descriptor)
    elif user.role == "student":
        criteria = [Enrollment.tenant_id == tenant_id, Enrollment.user_id == user.id,
                    Enrollment.course_id == course_id, Enrollment.status.in_(("enrolled", "in_progress", "completed"))]
        exact = getattr(user, "assignment_access_enrollment_id", None)
        if exact is not None:
            criteria.append(Enrollment.id == exact)
        releases = (await db.scalars(select(ContentRelease).join(Enrollment, Enrollment.content_release_id == ContentRelease.id)
                    .where(*criteria, ContentRelease.tenant_id == tenant_id, ContentRelease.course_id == course_id))).all()
        for release in releases:
            if canonical_json_sha256(cast(dict[str, Any], release.snapshot)) != release.snapshot_sha256:
                continue
            descriptor = _snapshot_descriptor(release.snapshot, course_id, lesson_id, tenant_id, asset_id)
            if descriptor:
                return _response(descriptor)
    raise _missing()
