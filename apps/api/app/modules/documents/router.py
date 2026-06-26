"""Documents — API router with MIME validation."""
import json
import logging
import uuid
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.document import Document
from app.modules.documents.schemas import DocumentResponse

router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_DIR = "./uploads/documents"
SUMMARIES_DIR = "./summaries"

logger = logging.getLogger(__name__)

# Allowed MIME types and their magic bytes
ALLOWED_MIME_TYPES = {
    "application/pdf": b"%PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK",
    "application/msword": b"\xd0\xcf\x11\xe0",
    "text/plain": None,  # No magic bytes check for text
    "text/markdown": None,
    "text/csv": None,
    "application/vnd.ms-excel": b"\xd0\xcf\x11\xe0",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def validate_magic_bytes(content: bytes, content_type: str) -> bool:
    """Validate file content against expected magic bytes."""
    expected_magic = ALLOWED_MIME_TYPES.get(content_type)
    if expected_magic is None:
        return True  # No magic bytes check needed (text files)
    if len(content) < len(expected_magic):
        return False
    return content[:len(expected_magic)] == expected_magic


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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
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

    # Check for duplicate by filename in same tenant
    existing = await db.execute(
        select(Document).where(
            Document.tenant_id == user.tenant_id,
            Document.filename == (file.filename or "unknown"),
        )
    )
    existing_doc = existing.scalar_one_or_none()
    if existing_doc:
        return _hydrate(existing_doc)

    ext = os.path.splitext(file.filename or "")[1]
    doc_id = uuid.uuid4()
    s3_key = f"tenants/{user.tenant_id}/documents/{doc_id}{ext}"

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
        embedding_status="pending",
    )
    db.add(doc)
    await db.flush()

    # Ingest into pgvector immediately (persistent embeddings)
    try:
        from app.modules.ai.ingestion import DocumentIngestion
        ingestion = DocumentIngestion()
        result = await ingestion.ingest_file(file_path, doc_id=str(doc_id), tenant_id=str(user.tenant_id))
        chunks = result.get("chunks", 0)
        doc.embedding_status = "success" if chunks > 0 else "failed"
        if chunks == 0:
            doc.embedding_error = "Ingestion produced 0 chunks (file may be empty or unsupported)"
        print(f"[UPLOAD] Ingested {file.filename}: {chunks} chunks", flush=True)
    except Exception as e:
        doc.embedding_status = "failed"
        doc.embedding_error = str(e)[:500]
        print(f"[UPLOAD] Ingestion failed for {file.filename}: {e}", flush=True)
    finally:
        # Clean up temp file (Render ephemeral disk)
        try:
            os.remove(file_path)
        except OSError:
            pass
        await db.flush()
        await db.refresh(doc)

    return _hydrate(doc)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == user.tenant_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
