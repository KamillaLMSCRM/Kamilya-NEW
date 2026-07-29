"""Preserve certificate artifacts and support revocation.

Revision ID: 0080
Revises: 0079
"""

import sqlalchemy as sa

from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificates",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "certificates",
        sa.Column("revoked_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "certificates",
        sa.Column("template_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "certificates",
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE certificates SET template_version = 'v2' WHERE template_version IS NULL")
    op.alter_column(
        "certificates",
        "template_version",
        nullable=False,
        server_default="v3",
    )


def downgrade() -> None:
    op.drop_column("certificates", "pdf_sha256")
    op.drop_column("certificates", "template_version")
    op.drop_column("certificates", "revoked_reason")
    op.drop_column("certificates", "revoked_at")
