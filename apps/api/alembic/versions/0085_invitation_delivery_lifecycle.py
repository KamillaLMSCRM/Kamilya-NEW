"""Track transactional delivery attempts for learner invitations.

Revision ID: 0085
Revises: 0084
"""

import sqlalchemy as sa

from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_invitations",
        sa.Column("delivery_status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "user_invitations",
        sa.Column("delivery_message_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_invitations",
        sa.Column("delivery_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_invitations",
        sa.Column("delivery_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_invitations",
        sa.Column("delivery_failure_category", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_invitations",
        sa.Column("delivery_failure_message", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_user_invitations_delivery_status",
        "user_invitations",
        "delivery_status IN ('pending', 'sent', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_user_invitations_delivery_status",
        "user_invitations",
        type_="check",
    )
    for column in (
        "delivery_failure_message",
        "delivery_failure_category",
        "delivery_attempt_count",
        "delivery_last_attempt_at",
        "delivery_message_id",
        "delivery_status",
    ):
        op.drop_column("user_invitations", column)
