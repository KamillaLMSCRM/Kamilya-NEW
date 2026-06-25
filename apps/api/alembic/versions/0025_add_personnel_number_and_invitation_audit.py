"""add personnel_number + invitation audit fields

Stage 1a patch:
1. users.personnel_number — universal employee identifier (Chamilo "Official code",
   Moodle "idnumber"). Nullable (not all tenants have personnel numbers, e.g.
   small offices). Unique within tenant.

2. user_invitations.accepted_ip + accepted_user_agent — audit trail. When a magic
   link is accepted via messenger delivery, if someone other than the intended
   recipient clicks it, the HR admin can see the IP/UA mismatch in the
   /users/invitations listing and revoke the activation.

Identity flow (effective from this migration):
- Phase 1a: HR imports user via bulk-invite. invitation.email is the only
  identifier HR has. Magic-link accept does NOT require personnel_number (form
  is: first_name, last_name, password).
- If invitation has personnel_number (from staff import), form asks for it as
  soft 2FA. Server checks invitation.personnel_number == form.personnel_number.

This is a non-destructive additive change: existing rows get NULLs, behavior
unchanged for users who don't have personnel_number set.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users.personnel_number
    op.add_column(
        "users",
        sa.Column("personnel_number", sa.Text, nullable=True),
    )
    # Unique per tenant (where not null). Partial index — many users may have NULL
    # (office workers without personnel_number).
    op.execute("""
        CREATE UNIQUE INDEX uq_users_tenant_personnel
        ON users (tenant_id, personnel_number)
        WHERE personnel_number IS NOT NULL
    """)
    # Regular index for lookups
    op.create_index(
        "ix_users_tenant_personnel",
        "users",
        ["tenant_id", "personnel_number"],
    )

    # 2. user_invitations.audit fields
    op.add_column(
        "user_invitations",
        sa.Column("personnel_number", sa.Text, nullable=True),
    )
    # If HR has personnel_number (e.g., imported staff), they include it
    # in the invitation so the accept form can verify it (soft 2FA).

    op.add_column(
        "user_invitations",
        sa.Column("accepted_ip", sa.Text, nullable=True),
    )
    op.add_column(
        "user_invitations",
        sa.Column("accepted_user_agent", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_invitations", "accepted_user_agent")
    op.drop_column("user_invitations", "accepted_ip")
    op.drop_column("user_invitations", "personnel_number")

    op.drop_index("ix_users_tenant_personnel", table_name="users")
    op.execute("DROP INDEX IF EXISTS uq_users_tenant_personnel")
    op.drop_column("users", "personnel_number")
