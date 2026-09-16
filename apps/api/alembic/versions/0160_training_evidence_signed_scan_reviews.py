"""Add append-only review decisions for returned signed copies.

Revision ID: 0160
Revises: 0159
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0160"
down_revision = "0159"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _schema_name() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe signed-scan-review schema")
    return schema


def _table(schema: str, name: str) -> str:
    return f'"{schema}".{name}'


def upgrade() -> None:
    schema = _schema_name()
    scans = _table(schema, "training_evidence_signed_scans")
    reviews = _table(schema, "training_evidence_signed_scan_reviews")

    op.execute(f"ALTER TABLE {scans} DISABLE TRIGGER trg_prevent_training_evidence_signed_scan_mutation")
    op.drop_constraint(
        "ck_training_evidence_signed_scans_received",
        "training_evidence_signed_scans",
        type_="check",
        schema=schema,
    )
    op.alter_column(
        "training_evidence_signed_scans",
        "status",
        server_default="received",
        schema=schema,
    )
    op.create_check_constraint(
        "ck_training_evidence_signed_scans_review_status",
        "training_evidence_signed_scans",
        "status IN ('received', 'uploaded_pending_review')",
        schema=schema,
    )
    op.execute(f"ALTER TABLE {scans} ENABLE TRIGGER trg_prevent_training_evidence_signed_scan_mutation")

    op.create_table(
        "training_evidence_signed_scan_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.training_evidence_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signed_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.training_evidence_signed_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{schema}.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(action = 'accept' AND reason IS NULL) OR "
            "(action = 'request_replacement' AND length(btrim(reason)) BETWEEN 1 AND 2000)",
            name="ck_training_evidence_signed_scan_reviews_action_reason",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_training_evidence_signed_scan_reviews_tenant_event_reviewed",
        "training_evidence_signed_scan_reviews",
        ["tenant_id", "event_id", "reviewed_at"],
        schema=schema,
    )
    op.create_index(
        "ix_training_evidence_signed_scan_reviews_scan_reviewed",
        "training_evidence_signed_scan_reviews",
        ["signed_scan_id", "reviewed_at"],
        schema=schema,
    )

    events = _table(schema, "training_evidence_events")
    users = _table(schema, "users")
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".validate_training_evidence_signed_scan_review_ownership()
        RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
        DECLARE event_tenant uuid;
        DECLARE scan_tenant uuid;
        DECLARE scan_event uuid;
        DECLARE reviewer_tenant uuid;
        BEGIN
            SELECT tenant_id INTO event_tenant FROM {events} WHERE id=NEW.event_id;
            SELECT tenant_id, event_id INTO scan_tenant, scan_event
              FROM {scans} WHERE id=NEW.signed_scan_id;
            SELECT tenant_id INTO reviewer_tenant FROM {users} WHERE id=NEW.reviewed_by_user_id;
            IF event_tenant IS NULL OR event_tenant <> NEW.tenant_id
               OR scan_tenant IS NULL OR scan_tenant <> NEW.tenant_id
               OR scan_event <> NEW.event_id
               OR reviewer_tenant IS NULL OR reviewer_tenant <> NEW.tenant_id THEN
                RAISE EXCEPTION 'signed scan review tenant ownership mismatch'
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_validate_training_evidence_signed_scan_review_ownership
        BEFORE INSERT OR UPDATE ON {reviews}
        FOR EACH ROW EXECUTE FUNCTION "{schema}".validate_training_evidence_signed_scan_review_ownership()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION "{schema}".prevent_training_evidence_signed_scan_review_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND training_evidence_retention_purge_authorized() THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Returned signed scan reviews are append-only'
                USING ERRCODE = 'check_violation';
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_prevent_training_evidence_signed_scan_review_mutation
        BEFORE UPDATE OR DELETE ON {reviews}
        FOR EACH ROW EXECUTE FUNCTION "{schema}".prevent_training_evidence_signed_scan_review_mutation()
        """
    )
    op.execute(f"ALTER TABLE {reviews} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {reviews} FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_training_evidence_signed_scan_reviews_isolation "
        f"ON {reviews} FOR ALL TO lms_app "
        f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute(f"REVOKE ALL ON TABLE {reviews} FROM PUBLIC, lms_app")
    op.execute(f"GRANT SELECT, INSERT ON {reviews} TO lms_app")


def downgrade() -> None:
    schema = _schema_name()
    scans = _table(schema, "training_evidence_signed_scans")
    reviews = _table(schema, "training_evidence_signed_scan_reviews")

    op.execute(f"ALTER TABLE {reviews} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM {reviews} LIMIT 1) THEN
            RAISE EXCEPTION
              '0160 downgrade refused: signed-scan reviews exist; archive them under the approved retention procedure before downgrade';
          END IF;
        END $$;
        """
    )
    op.execute(f"ALTER TABLE {reviews} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_prevent_training_evidence_signed_scan_review_mutation ON {reviews}"
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".prevent_training_evidence_signed_scan_review_mutation()')
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_validate_training_evidence_signed_scan_review_ownership ON {reviews}"
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".validate_training_evidence_signed_scan_review_ownership()')
    op.execute(f"DROP POLICY IF EXISTS tenant_training_evidence_signed_scan_reviews_isolation ON {reviews}")
    op.drop_index(
        "ix_training_evidence_signed_scan_reviews_scan_reviewed",
        table_name="training_evidence_signed_scan_reviews",
        schema=schema,
    )
    op.drop_index(
        "ix_training_evidence_signed_scan_reviews_tenant_event_reviewed",
        table_name="training_evidence_signed_scan_reviews",
        schema=schema,
    )
    op.drop_table("training_evidence_signed_scan_reviews", schema=schema)

    op.execute(f"ALTER TABLE {scans} DISABLE TRIGGER trg_prevent_training_evidence_signed_scan_mutation")
    op.drop_constraint(
        "ck_training_evidence_signed_scans_review_status",
        "training_evidence_signed_scans",
        type_="check",
        schema=schema,
    )
    op.execute(f"UPDATE {scans} SET status = 'received'")
    op.alter_column("training_evidence_signed_scans", "status", server_default="received", schema=schema)
    op.create_check_constraint(
        "ck_training_evidence_signed_scans_received",
        "training_evidence_signed_scans",
        "status = 'received'",
        schema=schema,
    )
    op.execute(f"ALTER TABLE {scans} ENABLE TRIGGER trg_prevent_training_evidence_signed_scan_mutation")
