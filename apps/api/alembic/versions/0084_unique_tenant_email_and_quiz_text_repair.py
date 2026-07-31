"""Enforce one normalized email identity per tenant and repair quiz text.

Revision ID: 0084
Revises: 0083
"""

import sqlalchemy as sa

from alembic import op

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def _repair_utf8_mojibake(value: str | None) -> str | None:
    """Recover UTF-8 text that was historically decoded as Windows-1251."""
    if not value:
        return None
    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return repaired if repaired != value else None


def _repair_column(table: str, column: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, {column} AS value FROM {table} WHERE {column} IS NOT NULL")
    ).mappings()
    for row in rows:
        repaired = _repair_utf8_mojibake(row["value"])
        if repaired is not None:
            bind.execute(
                sa.text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                {"id": row["id"], "value": repaired},
            )


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM (
                SELECT tenant_id, lower(btrim(email))
                FROM users
                WHERE tenant_id IS NOT NULL
                  AND email IS NOT NULL
                  AND btrim(email) <> ''
                GROUP BY tenant_id, lower(btrim(email))
                HAVING count(*) > 1
            ) duplicates
            """
        )
    ).scalar_one()
    if duplicate_count:
        raise RuntimeError(
            "Cannot enforce tenant email identity: duplicate normalized emails exist"
        )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_tenant_email_ci
        ON users (tenant_id, lower(btrim(email)))
        WHERE tenant_id IS NOT NULL
          AND email IS NOT NULL
          AND btrim(email) <> ''
        """
    )

    _repair_column("quiz_choices", "text")
    _repair_column("questions", "explanation")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_tenant_email_ci")
