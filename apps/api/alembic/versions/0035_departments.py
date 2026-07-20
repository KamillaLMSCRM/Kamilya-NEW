"""Add departments table and Position.department_id FK (ADR-0011).

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-28

Adds:
  - departments table with (tenant_id, slug) uniqueness
  - positions.department_id nullable FK
  - Backfill: one Department per (tenant_id, lower(department)) triple
    found in positions.department. Sets Position.department_id to the
    matching row. Position.department (text) is KEPT for v1.0
    backward compat; will be dropped in 0036 once the FK column is
    confirmed stable.
"""
import sqlalchemy as sa

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create departments table.
    op.create_table(
        "departments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column(
            "head_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_departments_tenant_slug"),
    )
    op.create_index("idx_departments_tenant", "departments", ["tenant_id"])

    # 2. Add nullable FK column on positions.
    op.add_column(
        "positions",
        sa.Column(
            "department_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_positions_department", "positions", ["department_id"])

    # 3. Backfill: insert one row per (tenant_id, lower(department))
    #    into departments, then point positions.department_id at the
    #    new row.
    #
    #    We use lower(trim(department)) to collapse "HR", "hr ", " Hr" etc.
    #    into the same slug. The display name keeps the first-seen
    #    capitalization (PostgreSQL MIN(name) is deterministic but
    #    arbitrary — for v1.0 that's acceptable; v1.1 can do a
    #    proper "merge" UX when the user picks a canonical form).
    op.execute("""
        INSERT INTO departments (id, tenant_id, name, slug, parent_id)
        SELECT
            gen_random_uuid() AS id,
            tenant_id,
            MIN(department) AS name,
            lower(trim(department)) AS slug,
            NULL AS parent_id
        FROM (
            SELECT DISTINCT tenant_id, department
            FROM positions
            WHERE department IS NOT NULL
              AND trim(department) <> ''
        ) AS distinct_depts
        GROUP BY tenant_id, lower(trim(department))
        ON CONFLICT (tenant_id, slug) DO NOTHING;
    """)

    # 4. Link positions.department_id to the matching department.
    op.execute("""
        UPDATE positions AS p
        SET department_id = d.id
        FROM departments AS d
        WHERE d.tenant_id = p.tenant_id
          AND d.slug = lower(trim(p.department));
    """)

    # 5. Set NOT NULL on positions.department_id for positions that
    #    have a non-empty department text. Positions with empty
    #    department (unassigned) stay NULL.
    op.execute("""
        UPDATE positions
        SET department_id = NULL
        WHERE department IS NULL OR trim(department) = '';
    """)


def downgrade() -> None:
    # Drop FK first (Postgres won't drop a column that's referenced).
    op.drop_index("idx_positions_department", "positions")
    op.drop_column("positions", "department_id")
    op.drop_index("idx_departments_tenant", "departments")
    op.drop_table("departments")
