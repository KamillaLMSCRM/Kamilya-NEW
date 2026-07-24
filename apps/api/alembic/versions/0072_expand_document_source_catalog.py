"""Expand documents for source versions, lifecycle and index metadata.

Revision ID: 0072
Revises: 0071
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("source_family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("documents", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "documents",
        sa.Column("lifecycle_status", sa.Text(), nullable=False, server_default="active"),
    )
    op.add_column("documents", sa.Column("deletion_error_code", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("deletion_error_message", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("deletion_job_id", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("index_status", sa.Text(), nullable=False, server_default="processing"),
    )
    op.add_column("documents", sa.Column("index_error_code", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("index_message", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("index_chunks_total", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("index_chunks_indexed", sa.Integer(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("index_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "documents",
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.execute("UPDATE documents SET source_family_id = id WHERE source_family_id IS NULL")
    op.execute(
        """
        UPDATE documents
        SET index_status = CASE
            WHEN embedding_status = 'pending' THEN 'processing'
            WHEN embedding_status = 'failed' THEN 'failed'
            WHEN embedding_status = 'success'
                 AND embedding_error LIKE 'Partial:%' THEN 'partial'
            WHEN embedding_status = 'success' THEN 'ready'
            ELSE 'processing'
        END,
        index_message = embedding_error
        """
    )
    op.alter_column("documents", "source_family_id", nullable=False)
    op.alter_column(
        "documents",
        "source_family_id",
        server_default=sa.text("gen_random_uuid()"),
    )

    op.create_check_constraint(
        "ck_documents_lifecycle_status",
        "documents",
        "lifecycle_status IN ('active', 'deletion_pending', 'delete_failed')",
    )
    op.create_check_constraint(
        "ck_documents_content_sha256",
        "documents",
        "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_documents_index_status",
        "documents",
        "index_status IN ('processing', 'ready', 'partial', 'failed')",
    )
    op.create_check_constraint(
        "ck_documents_version_positive",
        "documents",
        "version > 0",
    )
    op.create_check_constraint(
        "ck_documents_index_revision_positive",
        "documents",
        "index_revision > 0",
    )
    op.create_check_constraint(
        "ck_documents_index_chunks_nonnegative",
        "documents",
        "(index_chunks_total IS NULL OR index_chunks_total >= 0) "
        "AND (index_chunks_indexed IS NULL OR index_chunks_indexed >= 0)",
    )
    op.create_check_constraint(
        "ck_documents_index_chunks_order",
        "documents",
        "index_chunks_total IS NULL OR index_chunks_indexed IS NULL "
        "OR index_chunks_indexed <= index_chunks_total",
    )
    op.execute(
        "CREATE INDEX ix_documents_tenant_category_created_id ON documents (tenant_id, category, created_at DESC, id)"
    )
    op.execute(
        "CREATE INDEX ix_documents_tenant_family_version ON documents (tenant_id, source_family_id, version DESC)"
    )
    op.create_unique_constraint(
        "uq_documents_tenant_family_version",
        "documents",
        ["tenant_id", "source_family_id", "version"],
    )
    op.create_index(
        "ix_documents_tenant_content_sha256",
        "documents",
        ["tenant_id", "content_sha256"],
    )
    op.execute(
        "CREATE INDEX ix_documents_tenant_lifecycle_created_id "
        "ON documents (tenant_id, lifecycle_status, created_at DESC, id)"
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE documents
        SET embedding_status = CASE
            WHEN index_status = 'processing' THEN 'pending'
            WHEN index_status = 'failed' THEN 'failed'
            ELSE 'success'
        END,
        embedding_error = CASE
            WHEN index_status = 'partial'
                THEN COALESCE(index_message, 'Partial: exact chunk counts unavailable')
            WHEN index_status = 'failed' THEN COALESCE(index_message, index_error_code)
            ELSE NULL
        END
        """
    )

    op.drop_index("ix_documents_tenant_lifecycle_created_id", table_name="documents")
    op.drop_index("ix_documents_tenant_content_sha256", table_name="documents")
    op.drop_constraint("uq_documents_tenant_family_version", "documents", type_="unique")
    op.drop_index("ix_documents_tenant_family_version", table_name="documents")
    op.drop_index("ix_documents_tenant_category_created_id", table_name="documents")
    op.drop_constraint("ck_documents_index_chunks_order", "documents", type_="check")
    op.drop_constraint("ck_documents_index_chunks_nonnegative", "documents", type_="check")
    op.drop_constraint("ck_documents_index_revision_positive", "documents", type_="check")
    op.drop_constraint("ck_documents_version_positive", "documents", type_="check")
    op.drop_constraint("ck_documents_index_status", "documents", type_="check")
    op.drop_constraint("ck_documents_content_sha256", "documents", type_="check")
    op.drop_constraint("ck_documents_lifecycle_status", "documents", type_="check")
    op.drop_column("documents", "indexed_at")
    op.drop_column("documents", "index_revision")
    op.drop_column("documents", "index_chunks_indexed")
    op.drop_column("documents", "index_chunks_total")
    op.drop_column("documents", "index_message")
    op.drop_column("documents", "index_error_code")
    op.drop_column("documents", "index_status")
    op.drop_column("documents", "deletion_job_id")
    op.drop_column("documents", "deletion_error_message")
    op.drop_column("documents", "deletion_error_code")
    op.drop_column("documents", "lifecycle_status")
    op.drop_column("documents", "content_sha256")
    op.drop_column("documents", "version")
    op.drop_column("documents", "source_family_id")
