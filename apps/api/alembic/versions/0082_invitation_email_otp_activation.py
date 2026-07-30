"""Add verified email identity evidence for invitation activation.

Revision ID: 0082
Revises: 0081
"""

import sqlalchemy as sa

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_invitations",
        sa.Column("verification_method", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_user_invitations_verification_method",
        "user_invitations",
        "verification_method IS NULL OR verification_method IN ('email_otp', 'telegram', 'sso')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_invitations_verification_method",
        "user_invitations",
        type_="check",
    )
    op.drop_column("user_invitations", "verification_method")
    op.drop_column("users", "email_verified_at")
