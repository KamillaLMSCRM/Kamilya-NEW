"""Add immutable program metadata to learning paths.

Revision ID: 0142
Revises: 0141
Create Date: 2026-09-02

The existing LearningPath remains the canonical versioned program record. The
new fields are additive, retain safe defaults for legacy rows, and are guarded
by the existing published-version immutability trigger.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0142"
down_revision = "0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learning_paths",
        sa.Column("scenario", sa.Text(), nullable=False, server_default="custom"),
    )
    op.add_column(
        "learning_paths",
        sa.Column(
            "responsible_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column("learning_paths", sa.Column("default_due_days", sa.Integer(), nullable=True))
    op.add_column(
        "learning_paths",
        sa.Column("certificate_mode", sa.Text(), nullable=False, server_default="none"),
    )
    op.add_column(
        "learning_paths",
        sa.Column("certificate_validity_months", sa.Integer(), nullable=True),
    )
    op.add_column(
        "learning_paths",
        sa.Column("recurrence_mode", sa.Text(), nullable=False, server_default="none"),
    )
    op.add_column(
        "learning_paths",
        sa.Column("recurrence_cadence_days", sa.Integer(), nullable=True),
    )
    op.add_column("learning_paths", sa.Column("recurrence_due_days", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_learning_paths_responsible_user_id",
        "learning_paths",
        "users",
        ["responsible_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_learning_path_scenario",
        "learning_paths",
        "scenario IN ('onboarding', 'mandatory_training', 'process_update', "
        "'product_certification', 'knowledge_refresh', 'custom')",
    )
    op.create_check_constraint(
        "ck_learning_path_default_due_days",
        "learning_paths",
        "default_due_days IS NULL OR default_due_days BETWEEN 1 AND 3650",
    )
    op.create_check_constraint(
        "ck_learning_path_certificate_mode",
        "learning_paths",
        "certificate_mode IN ('none', 'final_course')",
    )
    op.create_check_constraint(
        "ck_learning_path_certificate_validity_months",
        "learning_paths",
        "certificate_validity_months IS NULL OR certificate_validity_months BETWEEN 1 AND 120",
    )
    op.create_check_constraint(
        "ck_learning_path_recurrence_mode",
        "learning_paths",
        "recurrence_mode IN ('none', 'fixed_interval_after_completion')",
    )
    op.create_check_constraint(
        "ck_learning_path_recurrence_cadence_days",
        "learning_paths",
        "recurrence_cadence_days IS NULL OR recurrence_cadence_days BETWEEN 1 AND 3650",
    )
    op.create_check_constraint(
        "ck_learning_path_recurrence_due_days",
        "learning_paths",
        "recurrence_due_days IS NULL OR recurrence_due_days BETWEEN 1 AND 3650",
    )
    op.create_check_constraint(
        "ck_learning_path_certificate_policy",
        "learning_paths",
        "(certificate_mode = 'none' AND certificate_validity_months IS NULL) "
        "OR (certificate_mode = 'final_course')",
    )
    op.create_check_constraint(
        "ck_learning_path_recurrence_policy",
        "learning_paths",
        "(recurrence_mode = 'none' AND recurrence_cadence_days IS NULL AND recurrence_due_days IS NULL) "
        "OR (recurrence_mode = 'fixed_interval_after_completion' "
        "AND recurrence_cadence_days IS NOT NULL AND recurrence_due_days IS NOT NULL "
        "AND recurrence_due_days <= recurrence_cadence_days)",
    )

    # A plain trigger follows the established learning-path ownership pattern:
    # it validates the referenced user against the path tenant while the
    # existing RLS policy remains authoritative for row visibility.
    op.execute(
        """
        CREATE FUNCTION validate_learning_path_responsible_user()
        RETURNS trigger AS $$
        DECLARE responsible_tenant uuid;
        BEGIN
            IF NEW.responsible_user_id IS NOT NULL THEN
                SELECT tenant_id INTO responsible_tenant
                FROM users
                WHERE id = NEW.responsible_user_id;
                IF responsible_tenant IS NULL OR responsible_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Learning-program responsible user must belong to the same tenant'
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
        CREATE TRIGGER learning_paths_validate_responsible_user
        BEFORE INSERT OR UPDATE OF tenant_id, responsible_user_id ON learning_paths
        FOR EACH ROW EXECUTE FUNCTION validate_learning_path_responsible_user();
        """
    )


def downgrade() -> None:
    # Do not silently discard configured program policy. The migration owner
    # temporarily disables FORCE RLS only for this destructive emptiness check;
    # a raised exception rolls the transaction back and restores FORCE RLS.
    op.execute("ALTER TABLE learning_paths NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1
                FROM learning_paths
                WHERE scenario <> 'custom'
                   OR responsible_user_id IS NOT NULL
                   OR default_due_days IS NOT NULL
                   OR certificate_mode <> 'none'
                   OR certificate_validity_months IS NOT NULL
                   OR recurrence_mode <> 'none'
                   OR recurrence_cadence_days IS NOT NULL
                   OR recurrence_due_days IS NOT NULL
            ) THEN
                RAISE EXCEPTION '0142 downgrade refused: learning-path program metadata is in use';
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE learning_paths FORCE ROW LEVEL SECURITY")

    op.execute(
        "DROP TRIGGER IF EXISTS learning_paths_validate_responsible_user ON learning_paths"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_learning_path_responsible_user()")
    for name in (
        "ck_learning_path_recurrence_policy",
        "ck_learning_path_certificate_policy",
        "ck_learning_path_recurrence_due_days",
        "ck_learning_path_recurrence_cadence_days",
        "ck_learning_path_recurrence_mode",
        "ck_learning_path_certificate_validity_months",
        "ck_learning_path_certificate_mode",
        "ck_learning_path_default_due_days",
        "ck_learning_path_scenario",
    ):
        op.drop_constraint(name, "learning_paths", type_="check")
    op.drop_constraint(
        "fk_learning_paths_responsible_user_id",
        "learning_paths",
        type_="foreignkey",
    )
    for column in (
        "recurrence_due_days",
        "recurrence_cadence_days",
        "recurrence_mode",
        "certificate_validity_months",
        "certificate_mode",
        "default_due_days",
        "responsible_user_id",
        "scenario",
    ):
        op.drop_column("learning_paths", column)
