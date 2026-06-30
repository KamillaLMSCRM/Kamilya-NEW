"""Add tenant_courses table — level-1 (tenant-wide) course assignment.

Per Lesson 22 (docs/LESSONS.md, 2026-06-30), the course
assignment model has 4 levels: tenant-wide, department,
position, personal. This migration adds the missing level 1.

The table was created directly in production via asyncpg on
2026-06-30 (see commit log + apps/api/.epic_a_step1.py in repo
history) so IF NOT EXISTS guards make this a no-op for prod.
Fresh environments (preview, staging) created from this model
will get the table automatically.

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent — table may already exist in prod (created
    # directly on 2026-06-30 to keep render.yaml deploys atomic).
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS tenant_courses (
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                course_id UUID NOT NULL,
                required BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (tenant_id, course_id)
            )
            """
        )
    )


def downgrade() -> None:
    # Downgrade intentionally does NOT drop tenant_courses — it
    # would orphan existing enrollments with source='tenant' and
    # break recompute_enrollments. One-way migration.
    pass
