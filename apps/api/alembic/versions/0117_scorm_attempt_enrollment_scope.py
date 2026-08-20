"""Scope SCORM attempts to an exact enrollment.

Revision ID: 0117
Revises: 0116
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0117"
down_revision = "0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scorm_attempts",
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_scorm_attempts_enrollment_id",
        "scorm_attempts",
        "enrollments",
        ["enrollment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_scorm_attempts_enrollment_id", "scorm_attempts", ["enrollment_id"])


def downgrade() -> None:
    op.drop_index("ix_scorm_attempts_enrollment_id", table_name="scorm_attempts")
    op.drop_constraint("fk_scorm_attempts_enrollment_id", "scorm_attempts", type_="foreignkey")
    op.drop_column("scorm_attempts", "enrollment_id")
