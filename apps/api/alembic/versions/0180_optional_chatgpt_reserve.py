"""Expand optional generation catalog without enabling or reordering providers.

Revision ID: 0180
Revises: 0179
"""

import re

from alembic import op

revision = "0180"
down_revision = "0179"
branch_labels = None
depends_on = None


def _table() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe generation-model-routing schema")
    return f'"{schema}".generation_model_routing'


def _constraint(table: str, ids: str, maximum: int) -> None:
    uniqueness = " AND ".join(
        f"(jsonb_array_length(ordered_model_ids) <= {right} "
        f"OR ordered_model_ids ->> {left} <> ordered_model_ids ->> {right})"
        for right in range(1, maximum) for left in range(right)
    )
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT ck_generation_model_routing_array CHECK ("
               "jsonb_typeof(ordered_model_ids) = 'array' "
               f"AND jsonb_array_length(ordered_model_ids) BETWEEN 1 AND {maximum} "
               "AND ordered_model_ids ->> 0 = 'deepseek' "
               f"AND ordered_model_ids <@ '{ids}'::jsonb AND {uniqueness})")


def upgrade() -> None:
    table = _table()
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_generation_model_routing_array")
    _constraint(table, '["deepseek","qwen38_flash_next","glm53_flash","chatgpt_reserve"]', 4)


def downgrade() -> None:
    # The old constraint rejects an enabled reserve transactionally. Operators
    # must disable explicitly first: no silent route mutation during rollback.
    table = _table()
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_generation_model_routing_array")
    _constraint(table, '["deepseek","qwen38_flash_next","glm53_flash"]', 3)
