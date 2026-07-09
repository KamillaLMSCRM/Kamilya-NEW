"""Add staff_import_mappings for reusable per-tenant column mappings.

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-09

P0.4 first-tenant hardening — let methodologists save the column mapping
they just verified, so the next staff import of the same Excel template
doesn't require re-picking every column.

Schema:
  id           UUID primary key
  tenant_id    UUID NOT NULL (indexed, FK tenants.id CASCADE)
  name         TEXT NOT NULL   — human label, e.g. «Штатка АО КазМунайГаз»
  mapping_json JSONB NOT NULL — {canonical_field: raw_column_name, …}
  is_default   BOOLEAN NOT NULL DEFAULT false — auto-apply on upload
  created_by   UUID NOT NULL  — users.id (no FK declared — circular import)
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()

Only one row per (tenant_id, name) — enforced via partial unique index
that excludes soft-deleted (we use active rows only here, no soft delete).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_import_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mapping_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_staff_import_mappings_tenant_id",
        "staff_import_mappings",
        ["tenant_id"],
    )
    # One row per (tenant, name) — names must be unique within tenant.
    op.create_index(
        "uq_staff_import_mappings_tenant_name",
        "staff_import_mappings",
        ["tenant_id", "name"],
        unique=True,
    )
    # Common lookup: list mappings for a tenant, newest first.
    op.create_index(
        "ix_staff_import_mappings_tenant_created",
        "staff_import_mappings",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_staff_import_mappings_tenant_created", table_name="staff_import_mappings")
    op.drop_index("uq_staff_import_mappings_tenant_name", table_name="staff_import_mappings")
    op.drop_index("ix_staff_import_mappings_tenant_id", table_name="staff_import_mappings")
    op.drop_table("staff_import_mappings")