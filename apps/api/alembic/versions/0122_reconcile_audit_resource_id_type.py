"""Reconcile audit resource identifiers with the canonical text contract.

Revision ID: 0122
Revises: 0121
"""

import sqlalchemy as sa

from alembic import op

revision = "0122"
down_revision = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    column = bind.execute(
        sa.text(
            """
            SELECT data_type, udt_name, character_maximum_length
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'audit_logs'
               AND column_name = 'resource_id'
            """
        )
    ).mappings().one_or_none()

    if column is None:
        raise RuntimeError("audit_logs.resource_id is missing")

    if (
        column["data_type"] == "character varying"
        and column["character_maximum_length"] == 100
    ):
        return

    if column["udt_name"] not in {"uuid", "varchar", "text"}:
        raise RuntimeError(
            "audit_logs.resource_id has unsupported type "
            f"{column['data_type']} ({column['udt_name']})"
        )

    op.alter_column(
        "audit_logs",
        "resource_id",
        existing_nullable=True,
        type_=sa.String(length=100),
        postgresql_using="resource_id::text",
    )


def downgrade() -> None:
    # Revision 0006 already defines this column as VARCHAR(100), so the schema
    # expected at revision 0121 is identical to the reconciled schema.
    pass
