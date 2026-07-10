"""Add courses.delivery_type column

Revision ID: 0054
Revises: 0053
Create Date: 2026-07-10

Bug fix — schema drift discovered 2026-07-10 during live P1 QA:
Course model declared `delivery_type TEXT NOT NULL DEFAULT 'native'`
CHECK IN ('native','scorm') but the column was never added to the
production schema. /admin/dashboard returned 500 because
get_recent_courses() selects the full Course model and the missing
column raised UndefinedColumnError.

Fix:
- Add delivery_type to courses table with the same default + CHECK
  as the ORM model.
- Server-side DEFAULT 'native' so existing rows backfill correctly.
- Nullable=False matches model.

Production hot-fix applied directly via SQL on 2026-07-10; this
migration brings any fresh DB up to the same shape.
"""
from alembic import op
import sqlalchemy as sa


revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "delivery_type",
            sa.Text(),
            nullable=False,
            server_default="native",
        ),
    )
    op.create_check_constraint(
        "ck_course_delivery_type",
        "courses",
        "delivery_type IN ('native', 'scorm')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_course_delivery_type", "courses", type_="check")
    op.drop_column("courses", "delivery_type")