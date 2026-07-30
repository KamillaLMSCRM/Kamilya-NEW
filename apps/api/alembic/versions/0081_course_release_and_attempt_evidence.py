"""Add immutable course releases and quiz-attempt evidence snapshots.

Revision ID: 0081
Revises: 0080
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "content_releases",
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
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "published_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_content_releases_version_positive",
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_content_releases_sha256",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "course_id",
            "version",
            name="uq_content_releases_tenant_course_version",
        ),
    )
    op.create_index(
        "ix_content_releases_tenant_id",
        "content_releases",
        ["tenant_id"],
    )
    op.create_index(
        "ix_content_releases_course_id",
        "content_releases",
        ["course_id"],
    )
    op.create_index(
        "ix_content_releases_published_by",
        "content_releases",
        ["published_by"],
    )
    op.create_index(
        "ix_content_releases_course_published",
        "content_releases",
        ["tenant_id", "course_id", "published_at"],
    )

    op.add_column(
        "courses",
        sa.Column("current_release_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_courses_current_release_id",
        "courses",
        "content_releases",
        ["current_release_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_courses_current_release_id",
        "courses",
        ["current_release_id"],
    )

    op.add_column(
        "enrollments",
        sa.Column("content_release_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_enrollments_content_release_id",
        "enrollments",
        "content_releases",
        ["content_release_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_enrollments_content_release_id",
        "enrollments",
        ["content_release_id"],
    )

    op.add_column(
        "quiz_attempts",
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "quiz_attempts",
        sa.Column("content_release_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "quiz_attempts",
        sa.Column(
            "evidence_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "quiz_attempts",
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_quiz_attempts_enrollment_id",
        "quiz_attempts",
        "enrollments",
        ["enrollment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_quiz_attempts_content_release_id",
        "quiz_attempts",
        "content_releases",
        ["content_release_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_quiz_attempts_enrollment_id",
        "quiz_attempts",
        ["enrollment_id"],
    )
    op.create_index(
        "ix_quiz_attempts_content_release_id",
        "quiz_attempts",
        ["content_release_id"],
    )
    op.create_index(
        "ix_quiz_attempts_evidence_sha256",
        "quiz_attempts",
        ["evidence_sha256"],
    )
    op.create_check_constraint(
        "ck_quiz_attempts_evidence_sha256",
        "quiz_attempts",
        "evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'",
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_release_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Published course releases are immutable'
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER content_releases_prevent_mutation
        BEFORE UPDATE OR DELETE ON content_releases
        FOR EACH ROW EXECUTE FUNCTION prevent_content_release_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_course_current_release()
        RETURNS trigger AS $$
        DECLARE release_course uuid;
        DECLARE release_tenant uuid;
        BEGIN
            IF NEW.current_release_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT course_id, tenant_id
              INTO release_course, release_tenant
              FROM content_releases
             WHERE id = NEW.current_release_id;
            IF release_course IS NULL
               OR release_course <> NEW.id
               OR release_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Current release must match course and tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER courses_validate_current_release
        BEFORE INSERT OR UPDATE OF current_release_id, tenant_id ON courses
        FOR EACH ROW EXECUTE FUNCTION validate_course_current_release();
        """
    )
    op.execute(
        """
        CREATE FUNCTION bind_enrollment_content_release()
        RETURNS trigger AS $$
        DECLARE course_tenant uuid;
        DECLARE course_release uuid;
        DECLARE release_course uuid;
        DECLARE release_tenant uuid;
        BEGIN
            SELECT tenant_id, current_release_id
              INTO course_tenant, course_release
              FROM courses
             WHERE id = NEW.course_id;
            IF course_tenant IS NULL OR course_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Enrollment course must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF NEW.content_release_id IS NULL THEN
                NEW.content_release_id := course_release;
            END IF;
            IF NEW.content_release_id IS NOT NULL THEN
                SELECT course_id, tenant_id
                  INTO release_course, release_tenant
                  FROM content_releases
                 WHERE id = NEW.content_release_id;
                IF release_course IS NULL
                   OR release_course <> NEW.course_id
                   OR release_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Enrollment release must match course and tenant'
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
        CREATE TRIGGER enrollments_bind_content_release
        BEFORE INSERT OR UPDATE OF course_id, tenant_id, content_release_id ON enrollments
        FOR EACH ROW EXECUTE FUNCTION bind_enrollment_content_release();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_quiz_attempt_evidence_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.evidence_sha256 IS NOT NULL THEN
                RAISE EXCEPTION 'Evidentiary quiz attempts are immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER quiz_attempts_prevent_evidence_mutation
        BEFORE UPDATE OR DELETE ON quiz_attempts
        FOR EACH ROW EXECUTE FUNCTION prevent_quiz_attempt_evidence_mutation();
        """
    )

    op.execute("ALTER TABLE content_releases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_releases FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON content_releases
        FOR ALL TO lms_app
        USING ({TENANT_EXPR})
        WITH CHECK ({TENANT_EXPR})
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON content_releases TO lms_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON content_releases")
    op.execute(
        "DROP TRIGGER IF EXISTS quiz_attempts_prevent_evidence_mutation ON quiz_attempts"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_quiz_attempt_evidence_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS enrollments_bind_content_release ON enrollments"
    )
    op.execute("DROP FUNCTION IF EXISTS bind_enrollment_content_release()")
    op.execute(
        "DROP TRIGGER IF EXISTS courses_validate_current_release ON courses"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_course_current_release()")
    op.execute(
        "DROP TRIGGER IF EXISTS content_releases_prevent_mutation ON content_releases"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_content_release_mutation()")

    op.drop_constraint(
        "ck_quiz_attempts_evidence_sha256",
        "quiz_attempts",
        type_="check",
    )
    op.drop_index("ix_quiz_attempts_evidence_sha256", table_name="quiz_attempts")
    op.drop_index("ix_quiz_attempts_content_release_id", table_name="quiz_attempts")
    op.drop_index("ix_quiz_attempts_enrollment_id", table_name="quiz_attempts")
    op.drop_constraint(
        "fk_quiz_attempts_content_release_id",
        "quiz_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_quiz_attempts_enrollment_id",
        "quiz_attempts",
        type_="foreignkey",
    )
    op.drop_column("quiz_attempts", "evidence_sha256")
    op.drop_column("quiz_attempts", "evidence_snapshot")
    op.drop_column("quiz_attempts", "content_release_id")
    op.drop_column("quiz_attempts", "enrollment_id")

    op.drop_index("ix_enrollments_content_release_id", table_name="enrollments")
    op.drop_constraint(
        "fk_enrollments_content_release_id",
        "enrollments",
        type_="foreignkey",
    )
    op.drop_column("enrollments", "content_release_id")

    op.drop_index("ix_courses_current_release_id", table_name="courses")
    op.drop_constraint(
        "fk_courses_current_release_id",
        "courses",
        type_="foreignkey",
    )
    op.drop_column("courses", "current_release_id")

    op.drop_index("ix_content_releases_course_published", table_name="content_releases")
    op.drop_index("ix_content_releases_published_by", table_name="content_releases")
    op.drop_index("ix_content_releases_course_id", table_name="content_releases")
    op.drop_index("ix_content_releases_tenant_id", table_name="content_releases")
    op.drop_table("content_releases")
