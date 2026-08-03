"""Bind regulated evidence events to an active tenant procedure.

Revision ID: 0089
Revises: 0088
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "training_evidence_events",
        sa.Column(
            "training_procedure_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_procedures.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_training_evidence_events_training_procedure_id",
        "training_evidence_events",
        ["training_procedure_id"],
    )
    op.create_check_constraint(
        "ck_training_evidence_event_procedure_binding",
        "training_evidence_events",
        "((procedure_type IN ('acknowledgement', 'internal_attestation', 'admission_decision') "
        "AND training_procedure_id IS NOT NULL) OR "
        "(procedure_type IN ('training', 'knowledge_check') AND training_procedure_id IS NULL))",
    )
    op.execute(
        """
        CREATE FUNCTION validate_training_evidence_procedure_ownership()
        RETURNS trigger AS $$
        DECLARE procedure_tenant uuid;
        DECLARE procedure_kind text;
        DECLARE procedure_status text;
        BEGIN
            IF NEW.training_procedure_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT tenant_id, procedure_type, status
              INTO procedure_tenant, procedure_kind, procedure_status
              FROM training_procedures
             WHERE id = NEW.training_procedure_id;

            IF procedure_tenant IS NULL THEN
                RAISE EXCEPTION 'Training procedure does not exist'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF procedure_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'Training procedure must belong to the event tenant'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF procedure_kind <> NEW.procedure_type THEN
                RAISE EXCEPTION 'Training procedure type must match evidence procedure type'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF procedure_status <> 'active' THEN
                RAISE EXCEPTION 'Training procedure must be active for evidence'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER training_evidence_events_validate_procedure
        BEFORE INSERT OR UPDATE ON training_evidence_events
        FOR EACH ROW EXECUTE FUNCTION validate_training_evidence_procedure_ownership();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS training_evidence_events_validate_procedure "
        "ON training_evidence_events"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_training_evidence_procedure_ownership()")
    op.drop_constraint(
        "ck_training_evidence_event_procedure_binding",
        "training_evidence_events",
        type_="check",
    )
    op.drop_index(
        "ix_training_evidence_events_training_procedure_id",
        table_name="training_evidence_events",
    )
    op.drop_column("training_evidence_events", "training_procedure_id")
