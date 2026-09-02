"""Add immutable LearningPath anchors to certificates.

Revision ID: 0144
Revises: 0143
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0144"
down_revision = "0143"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificates",
        sa.Column("learning_path_assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_certificates_learning_path_assignment",
        "certificates",
        "learning_path_assignments",
        ["learning_path_assignment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_certificates_tenant_learning_path_assignment",
        "certificates",
        ["tenant_id", "learning_path_assignment_id"],
    )
    op.create_index(
        "uq_certificates_learning_path_assignment",
        "certificates",
        ["learning_path_assignment_id"],
        unique=True,
        postgresql_where=sa.text("learning_path_assignment_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_certificate_learning_path_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
        BEGIN
          IF NEW.learning_path_assignment_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM learning_path_assignments a
            WHERE a.id = NEW.learning_path_assignment_id
              AND a.tenant_id = NEW.tenant_id
              AND a.user_id = NEW.user_id
          ) THEN
            RAISE EXCEPTION 'certificate learning path assignment tenant ownership mismatch';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_validate_certificate_learning_path_ownership
        BEFORE INSERT OR UPDATE OF tenant_id, user_id, learning_path_assignment_id
        ON certificates FOR EACH ROW
        EXECUTE FUNCTION validate_certificate_learning_path_ownership()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM certificates WHERE learning_path_assignment_id IS NOT NULL) THEN
            RAISE EXCEPTION '0144 downgrade refused: program certificates exist';
          END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_validate_certificate_learning_path_ownership ON certificates")
    op.execute("DROP FUNCTION IF EXISTS validate_certificate_learning_path_ownership()")
    op.drop_index("uq_certificates_learning_path_assignment", table_name="certificates")
    op.drop_index("ix_certificates_tenant_learning_path_assignment", table_name="certificates")
    op.drop_constraint("fk_certificates_learning_path_assignment", "certificates", type_="foreignkey")
    op.drop_column("certificates", "learning_path_assignment_id")
