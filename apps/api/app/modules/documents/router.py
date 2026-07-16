"""Documents — API router with MIME validation."""
import json
import logging
import uuid
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.core.storage import get_storage
from app.models.document import Document
from app.modules.documents.schemas import DocumentResponse

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_tenant_user())],
)

UPLOAD_DIR = "./uploads/documents"
SUMMARIES_DIR = "./summaries"

logger = logging.getLogger(__name__)

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

# Per ADR-0005: 10 MB cap. Documented decision; supersedes the 50 MB
# guidance in AGENTS.md (which was carried over from a pre-product spec
# and not validated against real uploads).
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

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

    printable_count = sum(
        1 for b in sample if b in (0x09, 0x0A, 0x0D) or 0x20 <= b <= 0x7E or b >= 0x80
    )
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
        with open(summary_path, "r", encoding="utf-8") as f:
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


def _hydrate(doc: Document) -> DocumentResponse:
    """Attach short_summary/summary_ready to a Document instance."""
    resp = DocumentResponse.model_validate(doc)
    ready, short = _load_short_summary(str(doc.id), doc.filename)
    resp.summary_ready = ready
    resp.short_summary = short
    return resp


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("superadmin", "methodologist", "teacher")),
):
    result = await db.execute(
        select(Document)
        .where(Document.tenant_id == user.tenant_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [_hydrate(d) for d in docs] if docs else []


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("superadmin", "methodologist", "teacher")),
):
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.tenant_id == user.tenant_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _hydrate(doc)


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form("general"),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("superadmin", "methodologist", "teacher")),
):
    if category not in {"general", "job_instruction"}:
        raise HTTPException(status_code=422, detail="Unsupported document category")
    from app.core.demo_limits import assert_can_create_document
    await assert_can_create_document(db, user.tenant_id)
    content = await file.read()
    file_size = len(content)

    # File size check
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB")

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # MIME type check
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{content_type}' not allowed. Supported: PDF, DOCX, DOC, TXT, CSV, XLS, XLSX"
        )

    # Magic bytes validation
    if not validate_magic_bytes(content, content_type):
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared type"
        )

    # General library uploads remain idempotent by filename. Job instructions
    # are versioned source files, so two uploads with the same filename must
    # remain distinct records.
    if category == "general":
        existing = await db.execute(
            select(Document).where(
                Document.tenant_id == user.tenant_id,
                Document.filename == (file.filename or "unknown"),
                Document.category == category,
            )
        )
        existing_doc = existing.scalar_one_or_none()
        if existing_doc:
            return _hydrate(existing_doc)

    ext = os.path.splitext(file.filename or "")[1]
    doc_id = uuid.uuid4()
    s3_key = f"tenants/{user.tenant_id}/documents/{doc_id}{ext}"

    try:
        get_storage().put_bytes(s3_key, content, content_type)
    except Exception as exc:
        logger.exception("Could not persist document blob %s", doc_id)
        raise HTTPException(status_code=503, detail="Document storage is unavailable") from exc

    # Save file temporarily for ingestion, then embed into pgvector
    file_path = os.path.join(UPLOAD_DIR, str(user.tenant_id), f"{doc_id}{ext}")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(content)

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
    )
    db.add(doc)
    await db.flush()

    # Ingest into pgvector immediately (persistent embeddings)
    try:
        from app.modules.ai.ingestion import DocumentIngestion
        ingestion = DocumentIngestion()
        result = await ingestion.ingest_file(file_path, doc_id=str(doc_id), tenant_id=str(user.tenant_id))
        # IMPORTANT: judge success on embeddings_written (real pgvector rows),
        # NOT on chunks (which only counts chunker output). Previously the
        # status was 'success' even when every embedding was malformed and
        # zero rows landed in pgvector — making the doc silently unusable.
        chunks = result.get("chunks", 0)
        embeddings_written = result.get("embeddings_written", 0)
        if chunks == 0:
            doc.embedding_status = "failed"
            doc.embedding_error = "Ingestion produced 0 chunks (file may be empty or unsupported)"
        elif embeddings_written == 0:
            doc.embedding_status = "failed"
            doc.embedding_error = (
                f"All {chunks} embeddings were malformed and dropped — "
                f"document is not usable for AI generation. Try re-uploading."
            )
        elif embeddings_written < chunks:
            # Partial — some chunks had good embeddings, some didn't.
            # Mark as success so the doc is at least usable, but record
            # how many were lost.
            doc.embedding_status = "success"
            doc.embedding_error = (
                f"Partial: {embeddings_written}/{chunks} chunks embedded; "
                f"the rest were malformed and dropped."
            )
        else:
            doc.embedding_status = "success"
            doc.embedding_error = None
        # Filename can contain sensitive info (e.g. "2025_salary_review.docx").
        # Log only the doc id, not the filename (audit §6.5).
        logger.info(
            "[UPLOAD] Ingested doc_id=%s chunks=%d embeddings_written=%d status=%s",
            doc.id,
            chunks,
            embeddings_written,
            doc.embedding_status,
        )
    except Exception as e:
        doc.embedding_status = "failed"
        doc.embedding_error = str(e)[:500]
        # Filename still excluded from logs (PII risk).
        logger.error("[UPLOAD] Ingestion failed for doc_id=%s: %s", doc.id, e)
    finally:
        # Clean up temp file (Render ephemeral disk)
        try:
            os.remove(file_path)
        except OSError:
            pass
        await db.flush()
        await db.refresh(doc)

    return _hydrate(doc)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("superadmin", "methodologist", "teacher")),
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


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("superadmin", "methodologist", "teacher")),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == user.tenant_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
