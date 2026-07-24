"""Document model."""

import uuid

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    CheckConstraint,
    Column,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    uploaded_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String, nullable=False)
    filename = Column(String, nullable=False, server_default="unknown")
    content_type = Column(String, nullable=False)
    file_url = Column(Text, nullable=True)
    size = Column("file_size", BigInteger, nullable=False, default=0)
    s3_key = Column(String, nullable=False, server_default="")
    description = Column(Text, nullable=False, server_default="")
    category = Column(String, nullable=False, default="general", server_default="general")
    # Status of pgvector ingestion. 'pending' = just created; 'success' =
    # embeddings written; 'failed' = ingestion threw and the file has no
    # embeddings (user must re-upload to use it in AI generation).
    embedding_status = Column(String, nullable=False, server_default="pending")
    embedding_error = Column(Text, nullable=True)
    source_family_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        server_default=func.gen_random_uuid(),
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")
    content_sha256 = Column(String(64), nullable=True)
    lifecycle_status = Column(String, nullable=False, default="active", server_default="active")
    deletion_error_code = Column(Text, nullable=True)
    deletion_error_message = Column(Text, nullable=True)
    deletion_job_id = Column(Text, nullable=True)
    index_status = Column(String, nullable=False, default="processing", server_default="processing")
    index_error_code = Column(Text, nullable=True)
    index_message = Column(Text, nullable=True)
    index_chunks_total = Column(Integer, nullable=True)
    index_chunks_indexed = Column(Integer, nullable=True)
    index_revision = Column(Integer, nullable=False, default=1, server_default="1")
    indexed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "category IN ('general', 'job_instruction')",
            name="ck_document_category",
        ),
        CheckConstraint(
            "lifecycle_status IN ('active', 'deletion_pending', 'delete_failed')",
            name="ck_documents_lifecycle_status",
        ),
        CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_documents_content_sha256",
        ),
        UniqueConstraint(
            "tenant_id",
            "source_family_id",
            "version",
            name="uq_documents_tenant_family_version",
        ),
        Index(
            "ix_documents_tenant_family_version",
            "tenant_id",
            "source_family_id",
            "version",
        ),
        Index(
            "ix_documents_tenant_content_sha256",
            "tenant_id",
            "content_sha256",
        ),
    )
