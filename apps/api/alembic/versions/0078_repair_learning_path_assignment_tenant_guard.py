"""Repair tenant validation for learning-program assignments.

Revision ID: 0078
Revises: 0077
"""

from alembic import op


revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migration 0075 was applied in some environments before its validation
    # function covered learner and assigner tenant ownership. Replacing the
    # function in a new migration repairs those already-migrated databases.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_learning_path_assignment_parent()
        RETURNS trigger AS $$
        DECLARE path_tenant uuid;
        DECLARE path_status text;
        DECLARE learner_tenant uuid;
        DECLARE assigner_tenant uuid;
        BEGIN
            SELECT tenant_id, status INTO path_tenant, path_status
            FROM learning_paths
            WHERE id = NEW.path_id;
            IF path_tenant IS NULL OR path_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Learning-program assignment path must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF path_status <> 'published' THEN
                RAISE EXCEPTION 'Learning-program assignments require a published version'
                    USING ERRCODE = 'check_violation';
            END IF;

            SELECT tenant_id INTO learner_tenant
            FROM users
            WHERE id = NEW.user_id;
            IF learner_tenant IS NULL OR learner_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Learning-program assignment learner must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            IF NEW.assigned_by IS NOT NULL THEN
                SELECT tenant_id INTO assigner_tenant
                FROM users
                WHERE id = NEW.assigned_by;
                IF assigner_tenant IS NULL OR assigner_tenant <> NEW.tenant_id THEN
                    RAISE EXCEPTION 'Learning-program assignment author must belong to the same tenant'
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
        DROP TRIGGER IF EXISTS learning_path_assignments_validate_parent
        ON learning_path_assignments
        """
    )
    op.execute(
        """
        CREATE TRIGGER learning_path_assignments_validate_parent
        BEFORE INSERT OR UPDATE OF path_id, tenant_id, user_id, assigned_by
        ON learning_path_assignments
        FOR EACH ROW EXECUTE FUNCTION validate_learning_path_assignment_parent()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS learning_path_assignments_validate_parent
        ON learning_path_assignments
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_learning_path_assignment_parent()
        RETURNS trigger AS $$
        DECLARE path_tenant uuid;
        DECLARE path_status text;
        BEGIN
            SELECT tenant_id, status INTO path_tenant, path_status
            FROM learning_paths
            WHERE id = NEW.path_id;
            IF path_tenant IS NULL OR path_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Learning-program assignment path must belong to the same tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF path_status <> 'published' THEN
                RAISE EXCEPTION 'Learning-program assignments require a published version'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER learning_path_assignments_validate_parent
        BEFORE INSERT OR UPDATE OF path_id, tenant_id
        ON learning_path_assignments
        FOR EACH ROW EXECUTE FUNCTION validate_learning_path_assignment_parent()
        """
    )
