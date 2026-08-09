"""Durable email outbox for manual course assignments.

Revision ID: 0097
Revises: 0096
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


def _grant(signature: str, role: str = "lms_app") -> None:
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")


def upgrade() -> None:
    op.execute(
        """DO $$ DECLARE recovery_role record; BEGIN SELECT rolsuper,rolbypassrls INTO recovery_role FROM pg_roles WHERE rolname='lms_recovery'; IF NOT FOUND THEN RAISE EXCEPTION 'Required role lms_recovery is missing; provision LOGIN NOSUPERUSER NOBYPASSRLS before 0097'; END IF; IF recovery_role.rolsuper OR recovery_role.rolbypassrls THEN RAISE EXCEPTION 'Role lms_recovery must be NOSUPERUSER NOBYPASSRLS'; END IF; END $$"""
    )
    op.execute("GRANT USAGE ON SCHEMA public TO lms_recovery")
    op.create_table(
        "course_assignment_notification_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "enrollment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrollments.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "assigned_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_message_id", sa.Text()),
        sa.Column("last_error_category", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending','claimed','retry','delivered','dead')",
            name="ck_course_assignment_notification_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3", name="ck_course_assignment_notification_attempts"
        ),
    )
    op.create_index(
        "ix_course_assignment_notification_due",
        "course_assignment_notification_outbox",
        ["tenant_id", "status", "next_attempt_at", "created_at"],
    )
    op.execute("ALTER TABLE course_assignment_notification_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE course_assignment_notification_outbox FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE course_assignment_notification_outbox FROM PUBLIC, lms_app")

    op.execute("""
        CREATE FUNCTION enqueue_course_assignment_notification(
            p_tenant_id uuid, p_enrollment_id uuid, p_assigned_by uuid
        ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp AS $$
        DECLARE item_id uuid;
        BEGIN
            IF current_setting('app.tenant_id', true) IS DISTINCT FROM p_tenant_id::text THEN
                RAISE EXCEPTION 'tenant context mismatch';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM enrollments e JOIN users u ON u.id=e.user_id
                WHERE e.id=p_enrollment_id AND e.tenant_id=p_tenant_id
                  AND e.source IN ('manual','recurring') AND u.tenant_id=p_tenant_id
                  AND u.email IS NOT NULL AND length(btrim(u.email)) > 0
            ) THEN RETURN NULL; END IF;
            IF NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN
                RAISE EXCEPTION 'assignment actor tenant mismatch';
            END IF;
            INSERT INTO course_assignment_notification_outbox(tenant_id,enrollment_id,assigned_by)
            VALUES(p_tenant_id,p_enrollment_id,p_assigned_by)
            ON CONFLICT(enrollment_id) DO UPDATE SET enrollment_id=EXCLUDED.enrollment_id
            RETURNING id INTO item_id;
            RETURN item_id;
        END $$
    """)
    _grant("enqueue_course_assignment_notification(uuid, uuid, uuid)")

    op.execute("""
        CREATE FUNCTION claim_course_assignment_notification(
            p_tenant_id uuid, p_notification_id uuid
        ) RETURNS TABLE(id uuid, tenant_id uuid, enrollment_id uuid, claim_token uuid)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
            IF current_setting('app.tenant_id', true) IS DISTINCT FROM p_tenant_id::text THEN
                RAISE EXCEPTION 'tenant context mismatch';
            END IF;
            RETURN QUERY WITH candidate AS (
                SELECT o.id FROM course_assignment_notification_outbox o
                WHERE o.id=p_notification_id AND o.tenant_id=p_tenant_id AND (
                    (o.status IN ('pending','retry') AND (o.next_attempt_at IS NULL OR o.next_attempt_at<=now()))
                    OR (o.status='claimed' AND o.claimed_at<=now()-interval '2 minutes')
                ) FOR UPDATE SKIP LOCKED
            ), changed AS (
                UPDATE course_assignment_notification_outbox o
                SET status='claimed', claimed_at=now(), claim_token=gen_random_uuid(), updated_at=now()
                FROM candidate c WHERE o.id=c.id
                RETURNING o.id,o.tenant_id,o.enrollment_id,o.claim_token
            ) SELECT * FROM changed;
        END $$
    """)
    _grant("claim_course_assignment_notification(uuid, uuid)")

    op.execute("""
        CREATE FUNCTION finalize_course_assignment_notification(
            p_tenant_id uuid, p_id uuid, p_token uuid, p_kind text,
            p_message_id text, p_error_category text
        ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = public, pg_temp AS $$
        BEGIN
            IF current_setting('app.tenant_id', true) IS DISTINCT FROM p_tenant_id::text THEN
                RAISE EXCEPTION 'tenant context mismatch';
            END IF;
            IF p_kind NOT IN ('success','terminal','transient','defer') THEN
                RAISE EXCEPTION 'invalid outbox finalization kind';
            END IF;
            UPDATE course_assignment_notification_outbox SET
                attempt_count=attempt_count+CASE WHEN p_kind='defer' THEN 0 ELSE 1 END,
                status=CASE WHEN p_kind='success' THEN 'delivered'
                    WHEN p_kind='terminal' OR (p_kind='transient' AND attempt_count+1>=3) THEN 'dead'
                    ELSE 'retry' END,
                delivered_at=CASE WHEN p_kind='success' THEN now() END,
                terminal_at=CASE WHEN p_kind='terminal' OR (p_kind='transient' AND attempt_count+1>=3) THEN now() END,
                next_attempt_at=CASE
                    WHEN p_kind='transient' AND attempt_count+1<3 THEN now()+make_interval(secs=>least(300,5*power(2,attempt_count+1))::int)
                    WHEN p_kind='defer' THEN now()+interval '5 minutes' END,
                delivery_message_id=COALESCE(p_message_id,delivery_message_id),
                last_error_category=NULLIF(left(p_error_category,64),''),
                claim_token=NULL, claimed_at=NULL, updated_at=now()
            WHERE id=p_id AND tenant_id=p_tenant_id AND status='claimed' AND claim_token=p_token;
            RETURN FOUND;
        END $$
    """)
    _grant("finalize_course_assignment_notification(uuid, uuid, uuid, text, text, text)")

    # This bounded recovery interface has no caller-controlled tenant or id.
    # It exposes only rows that are currently due, never arbitrary tenant rows.
    op.execute("""
        CREATE FUNCTION due_course_assignment_notifications(p_limit integer DEFAULT 20)
        RETURNS TABLE(id uuid, tenant_id uuid) LANGUAGE sql SECURITY DEFINER
        SET search_path = public, pg_temp AS $$
            SELECT o.id,o.tenant_id FROM course_assignment_notification_outbox o
            WHERE (o.status IN ('pending','retry') AND (o.next_attempt_at IS NULL OR o.next_attempt_at<=now()))
               OR (o.status='claimed' AND o.claimed_at<=now()-interval '2 minutes')
            ORDER BY o.created_at,o.id LIMIT greatest(1,least(p_limit,100))
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION due_course_assignment_notifications(integer) FROM lms_app")
    op.execute("REVOKE ALL ON FUNCTION due_course_assignment_notifications(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_course_assignment_notifications(integer) TO lms_recovery")

    op.execute("""
        CREATE FUNCTION course_assignment_notification_statuses(p_tenant_id uuid,p_course_id uuid)
        RETURNS TABLE(enrollment_id uuid,status text,attempt_count integer,delivered_at timestamptz,last_error_category text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
            IF current_setting('app.tenant_id', true) IS DISTINCT FROM p_tenant_id::text THEN
                RAISE EXCEPTION 'tenant context mismatch';
            END IF;
            RETURN QUERY SELECT o.enrollment_id,o.status,o.attempt_count,o.delivered_at,o.last_error_category
            FROM course_assignment_notification_outbox o JOIN enrollments e ON e.id=o.enrollment_id
            WHERE o.tenant_id=p_tenant_id AND e.tenant_id=p_tenant_id AND e.course_id=p_course_id;
        END $$
    """)
    _grant("course_assignment_notification_statuses(uuid, uuid)")

    op.execute("""
        CREATE FUNCTION requeue_course_assignment_notification(p_tenant_id uuid,p_enrollment_id uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE changed_id uuid;
        BEGIN
            IF current_setting('app.tenant_id', true) IS DISTINCT FROM p_tenant_id::text THEN
                RAISE EXCEPTION 'tenant context mismatch';
            END IF;
            UPDATE course_assignment_notification_outbox SET status='pending',attempt_count=0,
                next_attempt_at=NULL,claimed_at=NULL,claim_token=NULL,delivered_at=NULL,
                terminal_at=NULL,last_error_category='methodologist_resend',updated_at=now()
            WHERE enrollment_id=p_enrollment_id AND tenant_id=p_tenant_id AND status<>'claimed'
            RETURNING id INTO changed_id;
            RETURN changed_id;
        END $$
    """)
    _grant("requeue_course_assignment_notification(uuid, uuid)")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM course_assignment_notification_outbox) THEN
                RAISE EXCEPTION '0097 downgrade blocked: drain or archive assignment notification outbox first';
            END IF;
        END $$
    """)
    for signature in (
        "requeue_course_assignment_notification(uuid, uuid)",
        "course_assignment_notification_statuses(uuid, uuid)",
        "due_course_assignment_notifications(integer)",
        "finalize_course_assignment_notification(uuid, uuid, uuid, text, text, text)",
        "claim_course_assignment_notification(uuid, uuid)",
        "enqueue_course_assignment_notification(uuid, uuid, uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute("REVOKE USAGE ON SCHEMA public FROM lms_recovery")
    op.drop_index("ix_course_assignment_notification_due", table_name="course_assignment_notification_outbox")
    op.drop_table("course_assignment_notification_outbox")
