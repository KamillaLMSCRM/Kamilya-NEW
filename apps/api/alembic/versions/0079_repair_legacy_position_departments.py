"""Repair departments created as legacy position text.

Revision ID: 0079
Revises: 0078

Some staff imports ran after the original department backfill but before the
import service started creating canonical Department rows. The structure API
can still group those positions by their legacy text, while selectors backed
by the departments table cannot see them. Normalize every non-empty legacy
department and restore Position.department_id.
"""

from alembic import op


revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO departments (
            id,
            tenant_id,
            name,
            slug,
            description,
            parent_id
        )
        SELECT
            gen_random_uuid(),
            p.tenant_id,
            MIN(trim(p.department)),
            lower(trim(p.department)),
            '',
            NULL
        FROM positions AS p
        JOIN tenants AS t ON t.id = p.tenant_id
        WHERE p.department IS NOT NULL
          AND trim(p.department) <> ''
        GROUP BY p.tenant_id, lower(trim(p.department))
        ON CONFLICT (tenant_id, slug) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE positions AS p
        SET
            department_id = d.id,
            department = d.name
        FROM departments AS d
        WHERE d.tenant_id = p.tenant_id
          AND d.slug = lower(trim(p.department))
          AND (
              p.department_id IS DISTINCT FROM d.id
              OR p.department IS DISTINCT FROM d.name
          )
        """
    )


def downgrade() -> None:
    # Data normalization is intentionally irreversible. Removing generated
    # departments would break positions and any rules attached after repair.
    pass
