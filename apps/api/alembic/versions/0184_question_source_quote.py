"""Retain the generation-time quotation attached to a question.

Revision ID: 0184
Revises: 0183
"""
import re

from alembic import op

revision = "0184"
down_revision = "0183"
branch_labels = None
depends_on = None


def _schema():
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("unsafe_schema")
    return f'"{schema}"'


def upgrade():
    op.execute(f"ALTER TABLE {_schema()}.questions ADD COLUMN source_quote TEXT")


def downgrade():
    schema = _schema()
    if schema == '"public"':
        raise RuntimeError("question_source_quote_retained_use_binary_rollback")
    op.execute(f"ALTER TABLE {schema}.questions DROP COLUMN source_quote")
