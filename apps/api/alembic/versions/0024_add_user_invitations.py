"""add user_invitations + tenant_settings.invite_expiry_days

Phase 1 of employee onboarding epic (see docs/plans/employee-onboarding.md).

user_invitations
- Stores pending invitations with token-based accept links
- One row per (tenant, email) where status='pending' (partial unique index)
- Old pending rows are 'superseded' when re-invited (new row created)
- Resend flow: old.status='superseded', new row with fresh token + expires_at

tenant_settings.invite_expiry_days
- Per-tenant setting (default 3 days, range 1-30)
- Methodologist/admin can edit via /admin/settings (separate UI in Phase 1d)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. tenant_settings.invite_expiry_days
    op.add_column(
        "tenant_settings",
        sa.Column(
            "invite_expiry_days",
            sa.Integer,
            nullable=False,
            server_default="3",
        ),
    )
    op.create_check_constraint(
        "ck_tenant_invite_expiry",
        "tenant_settings",
        "invite_expiry_days BETWEEN 1 AND 30",
    )

    # 2. user_invitations table
    op.create_table(
        "user_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("first_name", sa.Text, nullable=False, server_default=""),
        sa.Column("last_name", sa.Text, nullable=False, server_default=""),
        sa.Column("role", sa.Text, nullable=False, server_default="student"),
        sa.Column("invited_by", UUID(as_uuid=True), nullable=False),  # FK users (no FK declared — circular import risk)
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default="pending",
        ),  # pending | accepted | expired | revoked | superseded
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # Only one PENDING invitation per (tenant, email) at a time.
    # Multiple historical rows allowed (superseded/accepted/expired/revoked).
    op.execute("""
        CREATE UNIQUE INDEX uq_user_invitations_pending
        ON user_invitations (tenant_id, email)
        WHERE status = 'pending'
    """)
    op.create_index(
        "ix_user_invitations_token",
        "user_invitations",
        ["token"],
    )
    op.create_index(
        "ix_user_invitations_tenant_status",
        "user_invitations",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_invitations_tenant_status", table_name="user_invitations")
    op.drop_index("ix_user_invitations_token", table_name="user_invitations")
    op.execute("DROP INDEX IF EXISTS uq_user_invitations_pending")
    op.drop_table("user_invitations")

    op.drop_constraint("ck_tenant_invite_expiry", "tenant_settings", type_="check")
    op.drop_column("tenant_settings", "invite_expiry_days")
