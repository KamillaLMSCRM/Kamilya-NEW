"""Documents — API router"""
import uuid
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.config import get_settings
from app.models.document import Document
from app.modules.documents.schemas import DocumentResponse

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()


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
    title: str = "",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    content = await file.read()
    file_size = len(content)

    ext = os.path.splitext(file.filename or "")[1]
    s3_key = f"tenants/{user.tenant_id}/documents/{uuid.uuid4()}{ext}"

    doc = Document(
        tenant_id=user.tenant_id,
        uploaded_by=user.id,
        title=title or file.filename or "Untitled",
        filename=file.filename or "unknown",
        content_type=file.content_type or "application/octet-stream",
        size=file_size,
        s3_key=s3_key,
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
