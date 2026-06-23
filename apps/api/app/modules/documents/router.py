"""Documents — API router with MIME validation."""
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
    return result.scalars().all()


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
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
        return existing_doc

    ext = os.path.splitext(file.filename or "")[1]
    doc_id = uuid.uuid4()
    s3_key = f"tenants/{user.tenant_id}/documents/{doc_id}{ext}"

    # Save file to disk for ingestion
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
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


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
