"""Course assignment refactor (B1a).

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-29

Adds the rule→enrollment materialization layer:

  - position_courses.required: BOOLEAN NOT NULL DEFAULT TRUE.
    required=True → counted in ready_percent; required=False → enrolled
    but not counted in ready_percent.

  - department_courses: new association table. Same semantics as
    position_courses, but scoped to a department. ON DELETE CASCADE
    on department_id so deleting a department cleans up its rules.

  - enrollments.source: TEXT NOT NULL DEFAULT 'manual'.
    Values: 'manual' (UI) | 'position' (via position_courses) |
    'department' (via department_courses). Lets us distinguish
    rule-driven enrollments from ad-hoc ones in the UI and the
    recompute diff.

  - Partial unique index on enrollments to prevent duplicate
    active rows (race-safe). partial WHERE clause keeps the door
    open for a future 'unenrolled' status without conflict.

Backfill:
  - Sets source='position' for existing enrollments that match a
    position_courses row for the user's current position. Rows with
    no match stay 'manual' (correct default).
  - Dedupes any existing duplicate active rows by keeping the
    newest enrolled_at. Idempotent — safe to re-run.
"""
from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add required column to position_courses.
    #    server_default so existing rows get required=True without
    #    requiring a per-row update.
    op.add_column(
        "position_courses",
        sa.Column(
            "required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. Create department_courses table.
    op.create_table(
        "department_courses",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "department_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "department_id", "course_id", name="uq_department_courses_tenant_dept_course"),
    )
    op.create_index("idx_department_courses_tenant", "department_courses", ["tenant_id"])
    op.create_index("idx_department_courses_department", "department_courses", ["department_id"])
    op.create_index("idx_department_courses_course", "department_courses", ["course_id"])

    # 3. Add source column to enrollments.
    op.add_column(
        "enrollments",
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default="manual",
        ),
    )
    op.create_index("idx_enrollments_source", "enrollments", ["source"])

    # 4. Backfill source for existing rows where the user's current
    #    position has a matching position_courses row.
    #    Rows with no match stay 'manual' (the default).
    op.execute("""
        UPDATE enrollments AS e
        SET source = 'position'
        FROM users AS u, position_courses AS pc, positions AS p
        WHERE e.user_id = u.id
          AND u.position_id = p.id
          AND p.id = pc.position_id
          AND e.course_id = pc.course_id
          AND e.tenant_id = u.tenant_id
          AND e.tenant_id = pc.tenant_id;
    """)

    # 5. Dedupe existing rows by (user_id, course_id, tenant_id) for
    #    active statuses. Keep the newest enrolled_at. Required before
    #    adding the unique partial index below.
    op.execute("""
        DELETE FROM enrollments
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY user_id, course_id, tenant_id
                    ORDER BY enrolled_at DESC NULLS LAST
                ) AS rn
                FROM enrollments
                WHERE status IN ('enrolled', 'completed')
            ) t
            WHERE rn > 1
        );
    """)

    # 6. Partial unique index — race-safe dedup for active rows.
    #    Partial so a future 'unenrolled' status can coexist without
    #    conflict.
    op.create_index(
        "uq_enrollments_user_course_tenant",
        "enrollments",
        ["user_id", "course_id", "tenant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('enrolled', 'completed')"),
    )


def downgrade() -> None:
    # Drop unique first.
    op.drop_index("uq_enrollments_user_course_tenant", table_name="enrollments")
    op.drop_index("idx_enrollments_source", table_name="enrollments")

    # Drop source column. NOTE: downgrading loses the backfilled
    # source information (it will fall back to 'manual' for all rows).
    op.drop_column("enrollments", "source")

    # Drop department_courses.
    op.drop_index("idx_department_courses_course", table_name="department_courses")
    op.drop_index("idx_department_courses_department", table_name="department_courses")
    op.drop_index("idx_department_courses_tenant", table_name="department_courses")
    op.drop_table("department_courses")

    # Drop required column from position_courses.
    op.drop_column("position_courses", "required")
