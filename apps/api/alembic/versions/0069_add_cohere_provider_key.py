"""Allow Cohere API keys in provider_keys.

Revision ID: 0069
Revises: 0068
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_provider_keys_provider", "provider_keys", type_="check")
    op.create_check_constraint(
        "ck_provider_keys_provider",
        "provider_keys",
        "provider IN ('deepseek', 'voyage', 'cohere')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_provider_keys_provider", "provider_keys", type_="check")
    op.create_check_constraint(
        "ck_provider_keys_provider",
        "provider_keys",
        "provider IN ('deepseek', 'voyage')",
    )
