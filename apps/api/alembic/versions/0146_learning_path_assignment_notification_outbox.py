"""Add durable notifications for recurring learning-path assignments.

Revision ID: 0146
Revises: 0145
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0146"
down_revision = "0145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lms_recovery') THEN
            RAISE EXCEPTION 'Required role lms_recovery is missing';
          END IF;
        END $$;
        """
    )
    op.create_table(
        "learning_path_assignment_notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "learning_path_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("learning_path_assignments.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "assigned_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_message_id", sa.String(255), nullable=True),
        sa.Column("last_error_category", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','retry','sent','dead')",
            name="ck_learning_path_assignment_notification_status",
        ),
    )
    op.create_index(
        "ix_learning_path_assignment_notification_due",
        "learning_path_assignment_notification_outbox",
        ["status", "next_attempt_at"],
    )
    op.execute("ALTER TABLE learning_path_assignment_notification_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE learning_path_assignment_notification_outbox FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY learning_path_assignment_notification_tenant_isolation
        ON learning_path_assignment_notification_outbox
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        "REVOKE ALL ON TABLE learning_path_assignment_notification_outbox FROM PUBLIC, lms_app"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enqueue_learning_path_assignment_notification(
          p_tenant_id uuid,
          p_learning_path_assignment_id uuid,
          p_assigned_by uuid
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
          v_id uuid;
          v_context uuid;
        BEGIN
          v_context := nullif(current_setting('app.tenant_id', true), '')::uuid;
          IF v_context IS NULL OR v_context <> p_tenant_id THEN
            RAISE EXCEPTION 'tenant context mismatch';
          END IF;
          IF p_assigned_by IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM users u WHERE u.id = p_assigned_by AND u.tenant_id = p_tenant_id
          ) THEN
            RAISE EXCEPTION 'assignment actor is outside tenant';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM learning_path_assignments a
            JOIN learning_paths p ON p.id = a.path_id AND p.tenant_id = a.tenant_id
            JOIN users u ON u.id = a.user_id AND u.tenant_id = a.tenant_id
            WHERE a.id = p_learning_path_assignment_id
              AND a.tenant_id = p_tenant_id
              AND a.status = 'active'
              AND p.status = 'published'
          ) THEN
            RAISE EXCEPTION 'active learning-path assignment is missing, unpublished, or outside tenant';
          END IF;

          INSERT INTO learning_path_assignment_notification_outbox (
            id, tenant_id, learning_path_assignment_id, assigned_by
          ) VALUES (
            gen_random_uuid(), p_tenant_id, p_learning_path_assignment_id, p_assigned_by
          )
          ON CONFLICT (learning_path_assignment_id) DO UPDATE
          SET learning_path_assignment_id = EXCLUDED.learning_path_assignment_id
          RETURNING id INTO v_id;
          RETURN v_id;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION claim_learning_path_assignment_notification(
          p_tenant_id uuid,
          p_notification_id uuid
        ) RETURNS TABLE (
          id uuid, tenant_id uuid, learning_path_assignment_id uuid, claim_token uuid
        )
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE v_context uuid;
        BEGIN
          v_context := nullif(current_setting('app.tenant_id', true), '')::uuid;
          IF v_context IS NULL OR v_context <> p_tenant_id THEN
            RAISE EXCEPTION 'tenant context mismatch';
          END IF;
          RETURN QUERY
          WITH candidate AS (
            SELECT o.id
            FROM learning_path_assignment_notification_outbox o
            WHERE o.id = p_notification_id
              AND o.tenant_id = p_tenant_id
              AND (
                (o.status IN ('pending','retry') AND o.next_attempt_at <= now())
                OR (o.status = 'processing' AND o.claimed_at < now() - interval '10 minutes')
              )
            FOR UPDATE SKIP LOCKED
          ), updated AS (
            UPDATE learning_path_assignment_notification_outbox o
            SET status = 'processing',
                claim_token = gen_random_uuid(),
                claimed_at = now(),
                attempt_count = o.attempt_count + 1,
                updated_at = now()
            FROM candidate c
            WHERE o.id = c.id
            RETURNING o.id, o.tenant_id, o.learning_path_assignment_id, o.claim_token
          )
          SELECT * FROM updated;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION finalize_learning_path_assignment_notification(
          p_tenant_id uuid,
          p_notification_id uuid,
          p_claim_token uuid,
          p_kind text,
          p_message_id text DEFAULT NULL,
          p_error_category text DEFAULT NULL
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
        DECLARE
          v_context uuid;
          v_attempts integer;
        BEGIN
          v_context := nullif(current_setting('app.tenant_id', true), '')::uuid;
          IF v_context IS NULL OR v_context <> p_tenant_id THEN
            RAISE EXCEPTION 'tenant context mismatch';
          END IF;
          IF p_kind NOT IN ('success','terminal','transient','defer') THEN
            RAISE EXCEPTION 'invalid finalization kind';
          END IF;
          SELECT attempt_count INTO v_attempts
          FROM learning_path_assignment_notification_outbox
          WHERE id = p_notification_id
            AND tenant_id = p_tenant_id
            AND status = 'processing'
            AND claim_token = p_claim_token
          FOR UPDATE;
          IF NOT FOUND THEN
            RETURN false;
          END IF;

          UPDATE learning_path_assignment_notification_outbox
          SET status = CASE
                WHEN p_kind = 'success' THEN 'sent'
                WHEN p_kind = 'terminal' OR v_attempts >= 3 THEN 'dead'
                ELSE 'retry'
              END,
              next_attempt_at = CASE
                WHEN p_kind = 'defer' THEN now() + interval '5 minutes'
                WHEN p_kind = 'transient' AND v_attempts < 3
                  THEN now() + make_interval(
                    secs => least(3600, 30 * power(2, greatest(0, v_attempts - 1)))::integer
                  )
                ELSE next_attempt_at
              END,
              delivered_at = CASE WHEN p_kind = 'success' THEN now() ELSE delivered_at END,
              delivery_message_id = CASE
                WHEN p_kind = 'success' THEN p_message_id ELSE delivery_message_id
              END,
              last_error_category = CASE
                WHEN p_kind = 'success' THEN NULL ELSE left(p_error_category, 64)
              END,
              claim_token = NULL,
              claimed_at = NULL,
              updated_at = now()
          WHERE id = p_notification_id
            AND tenant_id = p_tenant_id
            AND claim_token = p_claim_token;
          RETURN FOUND;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION due_learning_path_assignment_notifications(
          p_limit integer DEFAULT 20
        ) RETURNS TABLE (id uuid, tenant_id uuid)
        LANGUAGE sql SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
          SELECT o.id, o.tenant_id
          FROM learning_path_assignment_notification_outbox o
          WHERE (o.status IN ('pending','retry') AND o.next_attempt_at <= now())
             OR (o.status = 'processing' AND o.claimed_at < now() - interval '10 minutes')
          ORDER BY o.next_attempt_at, o.created_at
          LIMIT greatest(1,least(p_limit,100))
        $$
        """
    )

    for signature in (
        "enqueue_learning_path_assignment_notification(uuid,uuid,uuid)",
        "claim_learning_path_assignment_notification(uuid,uuid)",
        "finalize_learning_path_assignment_notification(uuid,uuid,uuid,text,text,text)",
        "due_learning_path_assignment_notifications(integer)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION enqueue_learning_path_assignment_notification(uuid,uuid,uuid) TO lms_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION claim_learning_path_assignment_notification(uuid,uuid) TO lms_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION finalize_learning_path_assignment_notification(uuid,uuid,uuid,text,text,text) TO lms_app"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION due_learning_path_assignment_notifications(integer) FROM lms_app"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION due_learning_path_assignment_notifications(integer) TO lms_recovery"
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_rows = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM learning_path_assignment_notification_outbox)")
    ).scalar()
    if has_rows:
        raise RuntimeError("0146 downgrade blocked: learning-path assignment notification rows exist")
    for signature in (
        "due_learning_path_assignment_notifications(integer)",
        "finalize_learning_path_assignment_notification(uuid,uuid,uuid,text,text,text)",
        "claim_learning_path_assignment_notification(uuid,uuid)",
        "enqueue_learning_path_assignment_notification(uuid,uuid,uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.drop_index(
        "ix_learning_path_assignment_notification_due",
        table_name="learning_path_assignment_notification_outbox",
    )
    op.drop_table("learning_path_assignment_notification_outbox")
