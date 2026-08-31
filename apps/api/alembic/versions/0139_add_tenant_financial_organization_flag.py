"""Add explicit financial-organization classification to tenants.

Revision ID: 0139
Revises: 0138
Create Date: 2026-08-31

Existing and newly created tenants default to false. Classification is an
explicit superadmin decision; names, billing identifiers, and uploaded content
must never be used to infer a regulated industry automatically.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0139"
down_revision = "0138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "is_financial_organization",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "is_financial_organization")
