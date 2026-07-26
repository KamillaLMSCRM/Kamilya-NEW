"""Add persistent organization-wide course rules.

Revision ID: 0076
Revises: 0075
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "organization_course_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "course_id", name="uq_organization_course_rules_tenant_course"),
    )
    op.create_index("ix_organization_course_rules_tenant", "organization_course_rules", ["tenant_id"])
    op.create_index("ix_organization_course_rules_course", "organization_course_rules", ["course_id"])

    # A foreign key validates course existence; this trigger also enforces that
    # the course belongs to the rule's tenant for direct SQL and future callers.
    op.execute(
        """
        CREATE FUNCTION validate_organization_course_rule_parent()
        RETURNS trigger AS $$
        DECLARE course_tenant uuid;
        DECLARE author_tenant uuid;
        BEGIN
            SELECT tenant_id INTO course_tenant FROM courses WHERE id = NEW.course_id;
            IF course_tenant IS NULL OR course_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Organization course rule course must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF NEW.created_by IS NOT NULL THEN
                SELECT tenant_id INTO author_tenant FROM users WHERE id = NEW.created_by;
                IF author_tenant IS NULL OR author_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Organization course rule author must belong to the same tenant'
                        USING ERRCODE = 'foreign_key_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER organization_course_rules_validate_parent
        BEFORE INSERT OR UPDATE OF tenant_id, course_id, created_by ON organization_course_rules
        FOR EACH ROW EXECUTE FUNCTION validate_organization_course_rule_parent();
        """
    )
    op.execute("ALTER TABLE organization_course_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organization_course_rules FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON organization_course_rules
        FOR ALL TO lms_app
        USING ({TENANT_EXPR})
        WITH CHECK ({TENANT_EXPR})
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON organization_course_rules TO lms_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON organization_course_rules")
    op.execute("DROP TRIGGER IF EXISTS organization_course_rules_validate_parent ON organization_course_rules")
    op.execute("DROP FUNCTION IF EXISTS validate_organization_course_rule_parent()")
    op.drop_index("ix_organization_course_rules_course", table_name="organization_course_rules")
    op.drop_index("ix_organization_course_rules_tenant", table_name="organization_course_rules")
    op.drop_table("organization_course_rules")
