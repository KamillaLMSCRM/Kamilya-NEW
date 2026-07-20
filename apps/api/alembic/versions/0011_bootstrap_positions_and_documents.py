"""bootstrap: create positions + sync documents columns

Revision ID: 0011
Revises: 0010_sync_schema_positions_and_documents
Create Date: 2026-06-22
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def column_exists(bind, table, column):
    result = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c)"),
        {"t": table, "c": column},
    )
    return result.scalar()


def table_exists(bind, table):
    result = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name=:t)"),
        {"t": table},
    )
    return result.scalar()


def upgrade() -> None:
    bind = op.get_bind()

    # Documents: add missing columns
    for col, typ, default in [
        ("filename", "TEXT", "'unknown'"),
        ("s3_key", "TEXT", "''"),
        ("description", "TEXT", "''"),
    ]:
        if not column_exists(bind, "documents", col):
            bind.execute(sa.text(f'ALTER TABLE documents ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}'))

    # Positions: create if not exists
    if not table_exists(bind, "positions"):
        op.create_table(
            "positions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("department", sa.Text, nullable=False, server_default=""),
            sa.Column("level", sa.Text, nullable=False, server_default=""),
            sa.Column("responsibilities", sa.Text, nullable=False, server_default=""),
            sa.Column("requirements", sa.Text, nullable=False, server_default=""),
            sa.Column("course_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("employee_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    else:
        # Add missing columns to existing positions table
        for col, typ, _nullable, default in [
            ("responsibilities", "TEXT", False, "''"),
            ("requirements", "TEXT", False, "''"),
            ("course_id", "UUID", True, None),
        ]:
            if not column_exists(bind, "positions", col):
                if default:
                    bind.execute(sa.text(f"ALTER TABLE positions ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}"))
                else:
                    bind.execute(sa.text(f"ALTER TABLE positions ADD COLUMN {col} {typ}"))

    # The original production schema had this association table, but no
    # Alembic revision created it. Revision 0036 extends it, so bootstrap it
    # here for clean installations.
    if not table_exists(bind, "position_courses"):
        op.create_table(
            "position_courses",
            sa.Column(
                "position_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("positions.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("course_id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        )
        op.create_index("ix_position_courses_tenant_id", "position_courses", ["tenant_id"])

    # These core auth/settings tables existed in the original deployed schema
    # but were missing from the Alembic bootstrap chain. Later migrations apply
    # RLS and add columns to them, so a clean database must create them here.
    if not table_exists(bind, "tenant_settings"):
        op.create_table(
            "tenant_settings",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("logo_url", sa.Text(), nullable=True),
            sa.Column("primary_color", sa.Text(), nullable=True),
            sa.Column("default_language", sa.Text(), nullable=False, server_default="ru"),
            sa.Column("self_enrollment", sa.Text(), nullable=False, server_default="false"),
            sa.Column("quiz_pass_threshold", sa.Text(), nullable=False, server_default="80"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("default_language IN ('ru', 'kk', 'en')", name="ck_tenant_lang"),
        )
        op.create_index("ix_tenant_settings_tenant_id", "tenant_settings", ["tenant_id"], unique=True)

    if not table_exists(bind, "user_roles"):
        op.create_table(
            "user_roles",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "role IN ('superadmin', 'admin', 'org_admin', 'teacher', 'student')",
                name="ck_user_role_role",
            ),
            sa.UniqueConstraint("user_id", "tenant_id", "role", name="uq_user_role"),
        )
        op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
        op.create_index("ix_user_roles_tenant_id", "user_roles", ["tenant_id"])

    if not table_exists(bind, "user_sessions"):
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("refresh_token", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("ip_address", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("refresh_token", name="uq_session_refresh_token"),
        )
        op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
        op.create_index("ix_user_sessions_tenant_id", "user_sessions", ["tenant_id"])
        op.create_index("ix_user_sessions_refresh_token", "user_sessions", ["refresh_token"])

    if not table_exists(bind, "quiz_assignments"):
        op.create_table(
            "quiz_assignments",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "quiz_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("quizzes.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "assigned_by",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="assigned"),
            sa.Column("score_percent", sa.Integer(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_quiz_assignments_quiz_id", "quiz_assignments", ["quiz_id"])
        op.create_index("ix_quiz_assignments_user_id", "quiz_assignments", ["user_id"])
        op.create_index("ix_quiz_assignments_tenant_id", "quiz_assignments", ["tenant_id"])


def downgrade() -> None:
    pass
