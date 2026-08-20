"""Scope survey responses to an exact completed enrollment.

Revision ID: 0118
Revises: 0117
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "survey_responses",
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_survey_responses_enrollment_id",
        "survey_responses",
        "enrollments",
        ["enrollment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_survey_responses_enrollment_id", "survey_responses", ["enrollment_id"])

    # Preserve historical feedback and link it only when the matching course
    # has one unambiguous completed enrollment for that learner.
    op.execute(
        """
        UPDATE survey_responses sr
           SET enrollment_id = matched.enrollment_id
          FROM (
                SELECT sr2.id AS response_id, max(e.id::text)::uuid AS enrollment_id
                  FROM survey_responses sr2
                  JOIN surveys s
                    ON s.id = sr2.survey_id
                   AND s.tenant_id = sr2.tenant_id
                  JOIN enrollments e
                    ON e.tenant_id = sr2.tenant_id
                   AND e.user_id = sr2.user_id
                   AND e.course_id = s.course_id
                   AND e.status = 'completed'
                 GROUP BY sr2.id
                HAVING count(*) = 1
               ) matched
         WHERE sr.id = matched.response_id
        """
    )

    op.drop_constraint("uq_survey_response_user", "survey_responses", type_="unique")
    op.create_index(
        "uq_survey_response_legacy_user",
        "survey_responses",
        ["tenant_id", "survey_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("enrollment_id IS NULL"),
    )
    op.create_index(
        "uq_survey_response_enrollment",
        "survey_responses",
        ["tenant_id", "survey_id", "user_id", "enrollment_id"],
        unique=True,
        postgresql_where=sa.text("enrollment_id IS NOT NULL"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_survey_response_enrollment_scope()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.enrollment_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                  FROM enrollments e
                  JOIN surveys s
                    ON s.id = NEW.survey_id
                   AND s.tenant_id = NEW.tenant_id
                 WHERE e.id = NEW.enrollment_id
                   AND e.tenant_id = NEW.tenant_id
                   AND e.user_id = NEW.user_id
                   AND e.course_id = s.course_id
                   AND e.status = 'completed'
            ) THEN
                RAISE EXCEPTION 'survey response enrollment must match the completed course assignment';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_validate_survey_response_enrollment_scope
        BEFORE INSERT OR UPDATE OF tenant_id, survey_id, user_id, enrollment_id
        ON survey_responses
        FOR EACH ROW
        EXECUTE FUNCTION validate_survey_response_enrollment_scope();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM survey_responses
                 GROUP BY tenant_id, survey_id, user_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION '0118 downgrade refused: multiple enrollment-scoped survey responses exist';
            END IF;
        END $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_validate_survey_response_enrollment_scope ON survey_responses")
    op.execute("DROP FUNCTION IF EXISTS validate_survey_response_enrollment_scope()")
    op.drop_index("uq_survey_response_enrollment", table_name="survey_responses")
    op.drop_index("uq_survey_response_legacy_user", table_name="survey_responses")
    op.create_unique_constraint(
        "uq_survey_response_user",
        "survey_responses",
        ["tenant_id", "survey_id", "user_id"],
    )
    op.drop_index("ix_survey_responses_enrollment_id", table_name="survey_responses")
    op.drop_constraint("fk_survey_responses_enrollment_id", "survey_responses", type_="foreignkey")
    op.drop_column("survey_responses", "enrollment_id")
