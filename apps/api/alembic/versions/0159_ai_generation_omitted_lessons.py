"""Allow terminal quality omissions in AI generation checkpoints.

Revision ID: 0159
Revises: 0158
"""

import re

from alembic import op

revision = "0159"
down_revision = "0158"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe ai-generation-omissions schema")
    return f'"{schema}"'


def _replace_status_constraint(table: str, column: str) -> None:
    constraint = f"ck_ai_generation_checkpoint_{column}_status"
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
        f"CHECK ({column}_status IN ('pending', 'completed', 'failed', 'omitted'))"
    )


def upgrade() -> None:
    checkpoints = f"{_schema()}.ai_generation_lesson_checkpoints"
    for column in ("content", "review", "assessment"):
        _replace_status_constraint(checkpoints, column)
    op.execute(
        f"ALTER TABLE {checkpoints} ADD CONSTRAINT "
        "ck_ai_generation_checkpoint_omission_consistency CHECK ("
        "(content_status = 'omitted' AND review_status = 'omitted' "
        "AND assessment_status = 'omitted' AND content_payload IS NOT NULL "
        "AND jsonb_typeof(content_payload) = 'object' AND review_payload IS NULL "
        "AND assessment_payload IS NULL) OR (content_status <> 'omitted' "
        "AND review_status <> 'omitted' AND assessment_status <> 'omitted'))"
    )


def downgrade() -> None:
    checkpoints = f"{_schema()}.ai_generation_lesson_checkpoints"
    op.execute(
        f"UPDATE {checkpoints} SET content_status = 'pending', "
        "review_status = 'pending', assessment_status = 'pending', "
        "content_payload = NULL, review_payload = NULL, assessment_payload = NULL, "
        "lease_owner = NULL, lease_expires_at = NULL, updated_at = now() "
        "WHERE content_status = 'omitted'"
    )
    op.execute(
        f"ALTER TABLE {checkpoints} DROP CONSTRAINT "
        "ck_ai_generation_checkpoint_omission_consistency"
    )
    for column in ("content", "review", "assessment"):
        constraint = f"ck_ai_generation_checkpoint_{column}_status"
        op.execute(f"ALTER TABLE {checkpoints} DROP CONSTRAINT {constraint}")
        op.execute(
            f"ALTER TABLE {checkpoints} ADD CONSTRAINT {constraint} "
            f"CHECK ({column}_status IN ('pending', 'completed', 'failed'))"
        )
