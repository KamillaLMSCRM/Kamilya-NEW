"""Allow the audited Luna 6 model setting while retaining old model history.

Revision ID: 0194
Revises: 0193
"""

import re

from alembic import op

revision = "0194"
down_revision = "0193"
branch_labels = depends_on = None


def _replace_condition(choices: str) -> None:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise RuntimeError("unapproved_runtime_settings_schema")
    table = f'"{schema}".runtime_settings'
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_runtime_settings_luna")
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT ck_runtime_settings_luna "
        "CHECK(NOT overrides ? 'provider.chatgpt.model' "
        f"OR overrides->>'provider.chatgpt.model' IN ({choices}))"
    )


def upgrade() -> None:
    _replace_condition("'gpt-5.6-luna', 'gpt-6-luna'")


def downgrade() -> None:
    # Old settings must be restored through the audited API before downgrade.
    # Validation rejects an incompatible current row without rewriting history.
    _replace_condition("'gpt-5.6-luna'")
