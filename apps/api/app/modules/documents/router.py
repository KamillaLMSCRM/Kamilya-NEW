"""Documents — API router with MIME validation."""

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.core.storage import get_storage, put_file_async
from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.ai.job_service import create_ai_job
from app.modules.documents.archive_preflight import ArchivePreflightError, preflight_ooxml
from app.modules.documents.schemas import (
    DocumentCatalogResponse,
    DocumentCategory,
    DocumentDeleteAccepted,
    DocumentHashBackfillAccepted,
    DocumentIndexStatus,
    DocumentLifecycleStatus,
    DocumentReindexAccepted,
    DocumentResponse,
    DocumentUsageResponse,
)
from app.modules.documents.service import (
    CatalogFilters,
    CatalogSort,
    list_catalog,
    list_document_usages,
)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_tenant_user())],
)

SUMMARIES_DIR = "./summaries"

logger = logging.getLogger(__name__)


def _duplicate_document_detail(document: Document) -> dict:
    return {
        "code": "duplicate_document",
        "message": "This exact file already exists in the document library.",
        "existing": {
            "id": str(document.id),
            "title": document.title,
            "filename": document.filename,
            "version": document.version,
            "route": f"/documents?q={quote(document.title)}",
        },
    }


def _is_active_document_hash_unique_violation(exc: IntegrityError) -> bool:
    """Identify only the database backstop for same-tenant active hashes."""
    current = getattr(exc, "orig", None)
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        constraint_name = getattr(current, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(current, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name == "uq_documents_active_tenant_content_sha256":
            return True
        current = getattr(current, "__cause__", None) or getattr(
            current,
            "__context__",
            None,
        )
    return False

# Allowed MIME types and their magic bytes
ALLOWED_MIME_TYPES = {
    "application/pdf": b"%PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK",
    "application/msword": b"\xd0\xcf\x11\xe0",
    "text/plain": b"TEXT_HEURISTIC",  # Sentinel — actual check via validate_text_content()
    "text/markdown": b"TEXT_HEURISTIC",
    "text/csv": b"TEXT_HEURISTIC",
    "application/vnd.ms-excel": b"\xd0\xcf\x11\xe0",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK",
}

# Scanned policies and instructions routinely exceed 10 MB. Keep the limit
# configurable while accepting normal business documents by default.
MAX_FILE_SIZE_MB = int(os.getenv("MAX_DOCUMENT_SIZE_MB", "50"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024

# Heuristic thresholds for text-content validation (audit §4.7):
# a binary blob declared as text/plain must NOT pass. We accept UTF-8
# decodable content where at most 1% of bytes are non-printable
# (excluding tab, newline, carriage return — common in markdown).
TEXT_PRINTABLE_MIN_RATIO = 0.99
TEXT_MAX_SAMPLE_BYTES = 64 * 1024  # check first 64 KB; enough to catch binary


def validate_magic_bytes(content: bytes, content_type: str) -> bool:
    """Validate file content against expected magic bytes.

    For text/* MIME types, dispatches to validate_text_content() which
    applies the printable-ASCII / UTF-8 heuristic from ADR-0005.
    """
    expected_magic = ALLOWED_MIME_TYPES.get(content_type)
    if expected_magic is None:
        return True  # Unknown content_type → caller rejects separately
    if expected_magic == b"TEXT_HEURISTIC":
        return _validate_text_content(content)
    if len(content) < len(expected_magic):
        return False
    return content[: len(expected_magic)] == expected_magic


def _validate_text_content(content: bytes) -> bool:
    """Heuristic check for text MIME types (audit §4.7, ADR-0005).

    Returns True iff:
      - content decodes as UTF-8 (strict), AND
      - first TEXT_MAX_SAMPLE_BYTES contain at least TEXT_PRINTABLE_MIN_RATIO
        printable characters (excluding tab, newline, carriage return).

    This blocks the "binary blob declared as text/plain" bypass where
    a user uploads an executable but tags it as text so the magic-byte
    check returns True.
    """
    sample = content[:TEXT_MAX_SAMPLE_BYTES]
    try:
        # Strict UTF-8 — invalid sequences raise immediately.
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False

    if not sample:
        return False

    printable_count = sum(1 for b in sample if b in (0x09, 0x0A, 0x0D) or 0x20 <= b <= 0x7E or b >= 0x80)
    ratio = printable_count / len(sample)
    return ratio >= TEXT_PRINTABLE_MIN_RATIO


def _load_short_summary(doc_id: str, filename: str | None = None) -> tuple[bool, str | None]:
    """Read ./summaries/{doc_id}.json (produced by ingestion) and return
    a 3-7 word summary that captures what the document is about. Falls
    back to a derived label from the filename if no summary file exists.

    Returns (summary_ready, short_summary_text).
    """
    summary_path = os.path.join(SUMMARIES_DIR, f"{doc_id}.json")
    try:
        with open(summary_path, encoding="utf-8") as f:
            data = json.load(f)
        # Prefer educational_summary.core_topics[0] (1 phrase)
        topics = (data.get("educational_summary") or {}).get("core_topics") or []
        for topic in topics:
            if isinstance(topic, str) and topic.strip():
                return True, topic.strip()[:120]
        # Then global_description (full sentence — extract head phrase)
        desc = (data.get("educational_summary") or {}).get("global_description")
        if isinstance(desc, str) and desc.strip():
            head = desc.split(".")[0].strip()
            # Trim to ~7 words
            words = head.split()
            return True, " ".join(words[:7])[:120] if len(words) > 7 else head[:120]
        # Then headings[0]
        toc = data.get("toc") or ""
        for line in toc.splitlines():
            if line.lstrip("- ").strip():
                return True, line.lstrip("- ").strip()[:120]
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"Failed to load summary for {doc_id}: {e}")

    # Fallback: derive from filename (e.g. "02_client_onboarding_process.md"
    # → "Client onboarding process")
    if filename:
        stem = os.path.splitext(os.path.basename(filename))[0]
        # Strip leading numeric prefix like "02_" or "2-"
        import re

        stem = re.sub(r"^\d+[_\-\.\s]+", "", stem)
        stem = stem.replace("_", " ").replace("-", " ").strip()
        if stem:
            return False, stem[:120]
    return False, None


def _hydrate(
    doc: Document,
    *,
    indexing_job_id: str | None = None,
) -> DocumentResponse:
    """Attach short_summary/summary_ready to a Document instance."""
    resp = DocumentResponse.model_validate(doc)
    ready, short = _load_short_summary(str(doc.id), doc.filename)
    resp.summary_ready = ready
    resp.short_summary = short
    resp.indexing_job_id = indexing_job_id
    if indexing_job_id:
        resp.status_url = f"/api/v1/ai/jobs/{indexing_job_id}"
    return resp


@router.get("", response_model=list[DocumentResponse], deprecated=True)
async def list_documents(
    response: Response,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    """Compatibility list for the current frontend; use /catalog for new clients."""
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/v1/documents/catalog>; rel="successor-version"'
    result = await db.execute(
        select(Document)
        .where(
            Document.tenant_id == user.tenant_id,
            Document.lifecycle_status == "active",
        )
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(100)
    )
    return [_hydrate(document) for document in result.scalars().all()]


@router.get("/catalog", response_model=DocumentCatalogResponse)
async def catalog_documents(
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: DocumentCategory | None = None,
    index_status: DocumentIndexStatus | None = None,
    lifecycle_status: DocumentLifecycleStatus = "active",
    used: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: CatalogSort = "created_desc",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    include: Literal["usages_summary"] | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    try:
        return await list_catalog(
            db,
            user.tenant_id,
            CatalogFilters(
                q=q,
                category=category,
                index_status=index_status,
                lifecycle_status=lifecycle_status,
                used=used,
                created_from=created_from,
                created_to=created_to,
                sort=sort,
                cursor=cursor,
                limit=limit,
                include_usages_summary=include == "usages_summary",
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/maintenance/hash-backfill",
    response_model=DocumentHashBackfillAccepted,
    status_code=202,
)
async def backfill_document_hashes(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    active_job = await db.scalar(
        select(AIJob)
        .where(
            AIJob.tenant_id == user.tenant_id,
            AIJob.status.in_(("pending", "running")),
            AIJob.params["action"].as_string() == "document_hash_backfill",
        )
        .order_by(AIJob.created_at.desc())
    )
    if active_job:
        return DocumentHashBackfillAccepted(
            job_id=active_job.id,
            status_url=f"/api/v1/ai/jobs/{active_job.id}",
        )

    job = await create_ai_job(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        params={"action": "document_hash_backfill"},
    )
    await db.commit()
    try:
        _dispatch_document_hash_backfill(job.id, user.tenant_id)
    except Exception as exc:
        logger.exception("Could not enqueue document hash backfill job %s", job.id)
        failed_job = await db.scalar(
            select(AIJob)
            .where(AIJob.id == job.id, AIJob.tenant_id == user.tenant_id)
            .with_for_update()
        )
        if failed_job and failed_job.status not in {"completed", "cancelled"}:
            now = datetime.now(UTC)
            failed_job.status = "failed"
            failed_job.stage = "failed"
            failed_job.message = "Document hash backfill worker is unavailable"
            failed_job.errors = [{"code": "hash_backfill_enqueue_failed"}]
            failed_job.updated_at = now
            failed_job.completed_at = now
            await db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "hash_backfill_enqueue_failed",
                "message": "Document maintenance worker is unavailable.",
            },
        ) from exc
    return DocumentHashBackfillAccepted(
        job_id=job.id,
        status_url=f"/api/v1/ai/jobs/{job.id}",
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    result = await db.execute(select(Document).where(Document.id == doc_id, Document.tenant_id == user.tenant_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _hydrate(doc)


@router.get("/{document_id}/usages", response_model=DocumentUsageResponse)
async def get_document_usages(
    document_id: uuid.UUID,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        return await list_document_usages(
            db,
            user.tenant_id,
            document_id,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{document_id}/reindex",
    response_model=DocumentReindexAccepted,
    status_code=202,
)
async def reindex_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    document = await db.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.tenant_id == user.tenant_id,
        )
        .with_for_update()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.lifecycle_status != "active":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_not_active",
                "message": "Only active documents can be reindexed.",
            },
        )

    active_job = await db.scalar(
        select(AIJob)
        .where(
            AIJob.tenant_id == user.tenant_id,
            AIJob.status.in_(("pending", "running")),
            AIJob.params["action"].as_string() == "document_reindex",
            AIJob.params["document_id"].as_string() == str(document_id),
        )
        .order_by(AIJob.created_at.desc())
    )
    if active_job:
        return DocumentReindexAccepted(
            document_id=document_id,
            index_status="processing",
            revision=int((active_job.params or {}).get("revision", document.index_revision)),
            job_id=active_job.id,
            status_url=f"/api/v1/ai/jobs/{active_job.id}",
        )
    if document.index_status == "processing":
        raise HTTPException(
            status_code=423,
            detail={
                "code": "document_processing",
                "message": "Document indexing is already in progress.",
            },
        )

    usages = await list_document_usages(
        db,
        user.tenant_id,
        document_id,
        limit=1,
    )
    if usages.summary.active_jobs:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_in_active_job",
                "message": "Wait until the AI task using this document finishes.",
                "active_jobs": usages.summary.active_jobs,
            },
        )

    revision = document.index_revision + 1
    job = await create_ai_job(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        params={
            "action": "document_reindex",
            "document_id": str(document_id),
            "revision": revision,
        },
    )
    document.index_revision = revision
    document.index_status = "processing"
    document.embedding_status = "pending"
    document.index_error_code = None
    document.index_message = None
    await db.commit()
    try:
        _dispatch_document_reindex(
            job.id,
            document_id,
            user.tenant_id,
            revision,
        )
    except Exception as exc:
        logger.exception("Could not enqueue document reindex job %s", job.id)
        document = await db.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
        failed_job = await db.scalar(
            select(AIJob)
            .where(AIJob.id == job.id, AIJob.tenant_id == user.tenant_id)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if document and document.index_revision == revision:
            document.embedding_status = "failed"
            document.embedding_error = "Document reindex worker is unavailable"
            document.index_status = "failed"
            document.index_error_code = "reindex_enqueue_failed"
            document.index_message = "Document reindex worker is unavailable"
        if failed_job and failed_job.status not in {"completed", "cancelled"}:
            failed_job.status = "failed"
            failed_job.stage = "failed"
            failed_job.message = "Document reindex worker is unavailable"
            failed_job.errors = [{"code": "reindex_enqueue_failed"}]
            failed_job.updated_at = now
            failed_job.completed_at = now
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "reindex_enqueue_failed",
                "message": "Document reindex worker is unavailable. Retry later.",
            },
        ) from exc

    return DocumentReindexAccepted(
        document_id=document_id,
        index_status="processing",
        revision=revision,
        job_id=job.id,
        status_url=f"/api/v1/ai/jobs/{job.id}",
    )


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form("general"),
    new_version_of: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    if category not in {"general", "job_instruction"}:
        raise HTTPException(status_code=422, detail="Unsupported document category")
    from app.core.demo_limits import assert_can_create_document

    digest = hashlib.sha256()
    sample = bytearray()
    file_size = 0
    await file.seek(0)
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        file_size += len(chunk)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
            )
        digest.update(chunk)
        if len(sample) < TEXT_MAX_SAMPLE_BYTES:
            sample.extend(chunk[: TEXT_MAX_SAMPLE_BYTES - len(sample)])
    await file.seek(0)

    # File size check
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # MIME type check
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{content_type}' not allowed. Supported: PDF, DOCX, DOC, TXT, CSV, XLS, XLSX",
        )

    # Magic bytes validation
    if not validate_magic_bytes(bytes(sample), content_type):
        raise HTTPException(status_code=400, detail="File content does not match declared type")

    ext = os.path.splitext(file.filename or "")[1].lower()
    ooxml_suffix = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }.get(content_type)
    if ooxml_suffix:
        if ext != ooxml_suffix:
            raise HTTPException(status_code=400, detail="File extension does not match declared OOXML type")
        try:
            preflight_ooxml(file.file, ooxml_suffix)
        except ArchivePreflightError as exc:
            raise HTTPException(status_code=400, detail="Invalid or unsafe OOXML document") from exc

    content_sha256 = digest.hexdigest()
    duplicate = await db.scalar(
        select(Document)
        .where(
            Document.tenant_id == user.tenant_id,
            Document.content_sha256 == content_sha256,
            Document.lifecycle_status == "active",
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=_duplicate_document_detail(duplicate),
        )

    doc_id = uuid.uuid4()
    source_family_id = doc_id
    version = 1
    if new_version_of:
        source = await db.scalar(
            select(Document)
            .where(
                Document.id == new_version_of,
                Document.tenant_id == user.tenant_id,
                Document.lifecycle_status == "active",
            )
            .with_for_update()
        )
        if not source:
            raise HTTPException(status_code=404, detail="Source document version not found")
        source_family_id = source.source_family_id
        latest_version = await db.scalar(
            select(func.max(Document.version)).where(
                Document.tenant_id == user.tenant_id,
                Document.source_family_id == source_family_id,
            )
        )
        version = int(latest_version or 0) + 1
        category = source.category
        title = title.strip() or source.title
        description = description.strip() or source.description

    await assert_can_create_document(db, user.tenant_id)

    s3_key = f"tenants/{user.tenant_id}/documents/{doc_id}{ext}"

    doc = Document(
        id=doc_id,
        tenant_id=user.tenant_id,
        uploaded_by=user.id,
        title=title or file.filename or "Untitled",
        filename=file.filename or "unknown",
        content_type=content_type,
        size=file_size,
        s3_key=s3_key,
        description=description,
        category=category,
        embedding_status="pending",
        source_family_id=source_family_id,
        version=version,
        content_sha256=content_sha256,
        lifecycle_status="active",
        index_status="processing",
        index_revision=1,
    )
    db.add(doc)
    blob_persisted = False
    try:
        # Reserve the database row before writing object storage. Under a
        # concurrent exact upload, the partial unique index makes the loser
        # fail here without ever creating an orphan blob.
        job = await create_ai_job(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            params={
                "action": "document_reindex",
                "document_id": str(doc_id),
                "revision": 1,
            },
        )
        try:
            await file.seek(0)
            await put_file_async(get_storage(), s3_key, file.file, content_type)
            blob_persisted = True
        except Exception as exc:
            await db.rollback()
            logger.exception("Could not persist document blob %s", doc_id)
            raise HTTPException(
                status_code=503,
                detail="Document storage is unavailable",
            ) from exc
        await db.commit()
        logger.info("Persisted document upload doc_id=%s job_id=%s", doc_id, job.id)
    except IntegrityError as exc:
        if not _is_active_document_hash_unique_violation(exc):
            if blob_persisted:
                try:
                    get_storage().delete_bytes(s3_key)
                except Exception:
                    logger.exception("Could not remove orphaned document blob %s", doc_id)
            raise
        await db.rollback()
        # Rollback clears the transaction-local RLS setting. Re-establish it
        # before retrieving the winner so this compensation remains tenant-safe.
        await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(user.tenant_id)})
        duplicate = await db.scalar(
            select(Document)
            .where(
                Document.tenant_id == user.tenant_id,
                Document.content_sha256 == content_sha256,
                Document.lifecycle_status == "active",
            )
            .order_by(Document.created_at.desc())
            .limit(1)
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=_duplicate_document_detail(duplicate),
            ) from exc
        # The named constraint was reported but no row is visible after
        # tenant-scoped re-read; never report a duplicate without a survivor.
        raise
    except Exception:
        if blob_persisted:
            try:
                get_storage().delete_bytes(s3_key)
            except Exception:
                logger.exception("Could not remove orphaned document blob %s", doc_id)
        raise

    try:
        _dispatch_document_reindex(
            job.id,
            doc_id,
            user.tenant_id,
            1,
        )
        logger.info("Queued document indexing doc_id=%s job_id=%s", doc_id, job.id)
    except Exception:
        logger.exception("Could not enqueue initial document indexing job %s", job.id)
        stored_doc = await db.scalar(
            select(Document)
            .where(
                Document.id == doc_id,
                Document.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
        failed_job = await db.scalar(
            select(AIJob)
            .where(AIJob.id == job.id, AIJob.tenant_id == user.tenant_id)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if stored_doc:
            stored_doc.embedding_status = "failed"
            stored_doc.embedding_error = "Document indexing worker is unavailable"
            stored_doc.index_status = "failed"
            stored_doc.index_error_code = "index_enqueue_failed"
            stored_doc.index_message = "Document indexing worker is unavailable"
        if failed_job and failed_job.status not in {"completed", "cancelled"}:
            failed_job.status = "failed"
            failed_job.stage = "failed"
            failed_job.message = "Document indexing worker is unavailable"
            failed_job.errors = [{"code": "index_enqueue_failed"}]
            failed_job.updated_at = now
            failed_job.completed_at = now
        await db.commit()

    return _hydrate(doc, indexing_job_id=job.id)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == user.tenant_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    blob = get_storage().get_bytes(doc.s3_key)
    if blob is None:
        raise HTTPException(status_code=404, detail="Document file is unavailable")

    filename = quote(doc.filename or "document")
    return Response(
        content=blob,
        media_type=doc.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


def _dispatch_document_cleanup(job_id: str, document_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    from app.modules.ai.tasks import document_cleanup_task

    if document_cleanup_task is None:
        raise RuntimeError("Document cleanup worker is unavailable")
    document_cleanup_task.delay(
        job_id=job_id,
        document_id=str(document_id),
        tenant_id=str(tenant_id),
    )


def _dispatch_document_reindex(
    job_id: str,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    revision: int,
) -> None:
    from app.modules.ai.tasks import document_reindex_task

    if document_reindex_task is None:
        raise RuntimeError("Document reindex worker is unavailable")
    document_reindex_task.delay(
        job_id=job_id,
        document_id=str(document_id),
        tenant_id=str(tenant_id),
        revision=revision,
    )


def _dispatch_document_hash_backfill(job_id: str, tenant_id: uuid.UUID) -> None:
    from app.modules.ai.tasks import document_hash_backfill_task

    if document_hash_backfill_task is None:
        raise RuntimeError("Document hash backfill worker is unavailable")
    document_hash_backfill_task.delay(
        job_id=job_id,
        tenant_id=str(tenant_id),
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteAccepted,
    status_code=202,
)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    doc = await db.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.tenant_id == user.tenant_id,
        )
        .with_for_update()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.index_status == "processing":
        raise HTTPException(
            status_code=423,
            detail={
                "code": "document_processing",
                "message": "Wait until document indexing finishes before deleting it.",
            },
        )

    job = None
    if doc.lifecycle_status == "deletion_pending" and doc.deletion_job_id:
        job = await db.scalar(
            select(AIJob).where(
                AIJob.id == doc.deletion_job_id,
                AIJob.tenant_id == user.tenant_id,
            )
        )

    if job is None:
        usages = await list_document_usages(
            db,
            user.tenant_id,
            document_id,
            limit=20,
        )
        if usages.summary.total:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "document_in_use",
                    "message": "Document is still used by product objects.",
                    "summary": usages.summary.model_dump(),
                    "items": [item.model_dump() for item in usages.items],
                    "truncated": usages.page.has_more,
                },
            )
        job = await create_ai_job(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            params={
                "action": "document_cleanup",
                "document_id": str(document_id),
            },
        )
        doc.deletion_job_id = job.id

    doc.lifecycle_status = "deletion_pending"
    doc.deletion_error_code = None
    doc.deletion_error_message = None
    await db.commit()

    try:
        _dispatch_document_cleanup(job.id, document_id, user.tenant_id)
    except Exception as exc:
        logger.exception("Could not enqueue document cleanup job %s", job.id)
        doc = await db.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
        failed_job = await db.scalar(
            select(AIJob)
            .where(
                AIJob.id == job.id,
                AIJob.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if doc and doc.deletion_job_id == job.id:
            doc.lifecycle_status = "delete_failed"
            doc.deletion_error_code = "cleanup_enqueue_failed"
            doc.deletion_error_message = "Document cleanup worker is unavailable"
        if failed_job and failed_job.status not in {"completed", "cancelled"}:
            failed_job.status = "failed"
            failed_job.stage = "failed"
            failed_job.message = "Document cleanup worker is unavailable"
            failed_job.errors = [{"code": "cleanup_enqueue_failed"}]
            failed_job.updated_at = now
            failed_job.completed_at = now
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "cleanup_enqueue_failed",
                "message": "Document cleanup worker is unavailable. Retry deletion later.",
            },
        ) from exc

    return DocumentDeleteAccepted(
        document_id=document_id,
        lifecycle_status="deletion_pending",
        job_id=job.id,
        status_url=f"/api/v1/ai/jobs/{job.id}",
    )
