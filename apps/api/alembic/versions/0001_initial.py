import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tenants
    op.create_table(
        'tenants',
        sa.Column('id', sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('slug', sa.Text(), nullable=False, unique=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='trial'),
        sa.Column('plan', sa.Text(), nullable=False, server_default='starter'),
        sa.Column('settings', sa.dialects.postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_tenants_slug', 'tenants', ['slug'], unique=False)

    # users
    op.create_table(
        'users',
        sa.Column('id', sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column('tenant_id', sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column('email', sa.Text(), nullable=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=True),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('first_name', sa.Text(), nullable=False),
        sa.Column('last_name', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=False)
    op.create_index('ix_users_tenant_id', 'users', ['tenant_id'], unique=False)
    op.create_foreign_key('fk_users_tenant', 'users', 'tenants', ['tenant_id'], ['id'], ondelete='cascade')
