"""Immutable recurring occurrences and participant deadline history.

Revision ID: 0167
Revises: 0166
"""

import re

from alembic import op

revision = "0167"
down_revision = "0166"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe recurring-learning schema")
    return f'"{schema}"'


def _revoke_other_roles(object_name: str) -> None:
    op.execute(f"REVOKE ALL ON {object_name} FROM PUBLIC, lms_app, lms_recovery")
    for role in ("anon", "authenticated", "service_role"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {object_name} FROM {role}'; END IF; END $$""")


def _restore_original_reminder_targets(schema: str) -> None:
    """Restore the 0152 projection before removing 0167 deadline columns."""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {schema}._learning_reminder_targets(p_tenant_id uuid,p_course_id uuid,p_path_id uuid)
        RETURNS TABLE(rule_id uuid,course_occurrence_id uuid,path_cycle_instance_id uuid,
          email text,learner_name text,company_name text,title text,target_type text,
          target_id uuid,due_at timestamptz,has_login_access boolean,lead_days integer)
        LANGUAGE sql STABLE SET search_path={schema},pg_temp AS $$
          SELECT r.id,a.id,NULL::uuid,u.email::text,
            trim(concat_ws(' ',u.first_name,u.last_name)),t.name::text,c.title::text,
            'course'::text,c.id,a.due_at,
            (coalesce(u.password_hash,'')<>'' OR u.telegram_id IS NOT NULL OR u.email_verified_at IS NOT NULL),
            r.reminder_days_before_due
          FROM {schema}.recurring_learning_assignments a
          JOIN {schema}.recurring_learning_rules r ON r.id=a.rule_id AND r.tenant_id=a.tenant_id
            AND r.course_id=a.course_id AND r.user_id=a.user_id
          JOIN {schema}.enrollments e ON e.id=a.enrollment_id AND e.recurring_assignment_id=a.id
            AND e.tenant_id=a.tenant_id AND e.user_id=a.user_id AND e.course_id=a.course_id
          JOIN {schema}.users u ON u.id=a.user_id AND u.tenant_id=a.tenant_id
          JOIN {schema}.tenants t ON t.id=a.tenant_id
          JOIN {schema}.courses c ON c.id=a.course_id AND c.tenant_id=a.tenant_id
          WHERE a.tenant_id=p_tenant_id AND a.id=p_course_id AND a.status='assigned'
            AND r.status='active' AND r.reminder_enabled AND e.status<>'completed' AND e.completed_at IS NULL
            AND u.role='student' AND u.is_active AND u.status='active' AND t.status='active' AND c.status='published'
          UNION ALL
          SELECT r.id,NULL::uuid,i.id,u.email::text,
            trim(concat_ws(' ',u.first_name,u.last_name)),t.name::text,p.title::text,
            'learning_path'::text,p.id,i.due_at,
            (coalesce(u.password_hash,'')<>'' OR u.telegram_id IS NOT NULL OR u.email_verified_at IS NOT NULL),
            r.reminder_days_before_due
          FROM {schema}.learning_path_cycle_instances i
          JOIN {schema}.recurring_learning_rules r ON r.id=i.rule_id AND r.tenant_id=i.tenant_id
            AND r.learning_path_id=i.path_id AND r.user_id=i.user_id
          JOIN {schema}.learning_path_assignments a ON a.recurrence_instance_id=i.id
            AND a.tenant_id=i.tenant_id AND a.path_id=i.path_id AND a.user_id=i.user_id
          JOIN {schema}.users u ON u.id=i.user_id AND u.tenant_id=i.tenant_id
          JOIN {schema}.tenants t ON t.id=i.tenant_id
          JOIN {schema}.learning_paths p ON p.id=i.path_id AND p.tenant_id=i.tenant_id
          WHERE i.tenant_id=p_tenant_id AND i.id=p_path_id AND i.status='active' AND i.completed_at IS NULL
            AND a.status='active' AND a.completed_at IS NULL AND a.source='recurring'
            AND r.status='active' AND r.reminder_enabled AND i.due_at IS NOT NULL
            AND u.role='student' AND u.is_active AND u.status='active' AND t.status='active' AND p.status='published'
        $$
    """)


def upgrade() -> None:
    schema = _schema()
    course_occurrences = f"{schema}.recurring_learning_assignments"
    path_occurrences = f"{schema}.learning_path_cycle_instances"
    events = f"{schema}.learning_cycle_participant_events"
    reminders = f"{schema}.learning_reminder_outbox"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"

    # Production keeps both occurrence tables under FORCE RLS and the migration
    # owner does not have BYPASSRLS.  The backfill is intentionally global, so
    # bounded runtime/owner policies cannot expose every tenant to it.  Relax
    # FORCE only inside this transactional migration and restore it immediately
    # after the backfill.  A failed migration rolls the ALTERs back together
    # with every other statement, preserving the pre-migration FORCE state.
    op.execute(f"ALTER TABLE {course_occurrences} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {path_occurrences} NO FORCE ROW LEVEL SECURITY")

    op.execute(f"ALTER TABLE {course_occurrences} ADD COLUMN sequence_no integer")
    op.execute(f"""
        WITH ranked AS (
          SELECT id,row_number() OVER (PARTITION BY tenant_id,rule_id ORDER BY scheduled_for,id)::integer AS value
          FROM {course_occurrences}
        )
        UPDATE {course_occurrences} a SET sequence_no=ranked.value FROM ranked WHERE ranked.id=a.id
    """)
    op.execute(f"ALTER TABLE {course_occurrences} ALTER COLUMN sequence_no SET NOT NULL")
    op.execute(f"ALTER TABLE {course_occurrences} ADD CONSTRAINT ck_recurring_assignment_sequence CHECK (sequence_no >= 1)")
    op.execute(f"ALTER TABLE {course_occurrences} ADD CONSTRAINT uq_recurring_assignment_occurrence UNIQUE (tenant_id,rule_id,sequence_no)")
    op.execute(f"ALTER TABLE {course_occurrences} ADD COLUMN content_release_id uuid REFERENCES {schema}.content_releases(id) ON DELETE RESTRICT")
    op.execute(f"""
        UPDATE {course_occurrences} a SET content_release_id=e.content_release_id
        FROM {schema}.enrollments e
        WHERE e.id=a.enrollment_id AND e.tenant_id=a.tenant_id AND e.recurring_assignment_id=a.id
    """)
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM {course_occurrences} a
            LEFT JOIN {schema}.enrollments e ON e.id=a.enrollment_id
              AND e.tenant_id=a.tenant_id AND e.recurring_assignment_id=a.id
              AND e.user_id=a.user_id AND e.course_id=a.course_id
            WHERE a.status<>'skipped'
              AND (e.id IS NULL OR e.content_release_id IS NULL OR a.content_release_id IS NULL)
          ) THEN
            RAISE EXCEPTION '0167 repair required: recurring occurrence lacks reciprocal enrollment release anchor';
          END IF;
        END $$
    """)
    op.execute(f"ALTER TABLE {course_occurrences} ADD COLUMN effective_due_at timestamptz")
    op.execute(f"UPDATE {course_occurrences} SET effective_due_at=due_at")
    op.execute(f"ALTER TABLE {course_occurrences} ALTER COLUMN effective_due_at SET NOT NULL")
    op.execute(f"ALTER TABLE {course_occurrences} ADD CONSTRAINT ck_recurring_assignment_effective_due CHECK (effective_due_at >= scheduled_for)")
    op.execute(f"REVOKE DELETE ON {course_occurrences} FROM lms_app")

    op.execute(f"ALTER TABLE {path_occurrences} ADD COLUMN effective_due_at timestamptz")
    op.execute(f"UPDATE {path_occurrences} SET effective_due_at=due_at")
    op.execute(f"ALTER TABLE {path_occurrences} ADD CONSTRAINT ck_learning_path_cycle_effective_due CHECK (effective_due_at IS NULL OR effective_due_at >= coalesce(starts_at,scheduled_for))")
    op.execute(f"ALTER TABLE {course_occurrences} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {path_occurrences} FORCE ROW LEVEL SECURITY")

    op.execute(f"""
        CREATE TABLE {events} (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
          course_occurrence_id uuid REFERENCES {course_occurrences}(id) ON DELETE CASCADE,
          path_cycle_instance_id uuid REFERENCES {path_occurrences}(id) ON DELETE CASCADE,
          user_id uuid NOT NULL REFERENCES {schema}.users(id) ON DELETE RESTRICT,
          event_type varchar(32) NOT NULL DEFAULT 'deadline_override'
            CHECK (event_type='deadline_override'),
          previous_effective_due_at timestamptz NOT NULL,
          effective_due_at timestamptz NOT NULL,
          reason text NOT NULL CHECK (length(reason) BETWEEN 20 AND 1000),
          actor_id uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK ((course_occurrence_id IS NULL) <> (path_cycle_instance_id IS NULL)),
          CHECK (previous_effective_due_at <> effective_due_at)
        )
    """)
    op.execute(f"CREATE INDEX ix_learning_cycle_events_target_course ON {events}(tenant_id,course_occurrence_id,created_at DESC) WHERE course_occurrence_id IS NOT NULL")
    op.execute(f"CREATE INDEX ix_learning_cycle_events_target_path ON {events}(tenant_id,path_cycle_instance_id,created_at DESC) WHERE path_cycle_instance_id IS NOT NULL")
    op.execute(f"ALTER TABLE {events} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {events} FORCE ROW LEVEL SECURITY")
    ownership = f"""(
      (learning_cycle_participant_events.course_occurrence_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM {course_occurrences} a
        WHERE a.id=learning_cycle_participant_events.course_occurrence_id
          AND a.tenant_id=learning_cycle_participant_events.tenant_id
          AND a.user_id=learning_cycle_participant_events.user_id))
      OR
      (learning_cycle_participant_events.path_cycle_instance_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM {path_occurrences} i
        WHERE i.id=learning_cycle_participant_events.path_cycle_instance_id
          AND i.tenant_id=learning_cycle_participant_events.tenant_id
          AND i.user_id=learning_cycle_participant_events.user_id))
    ) AND (learning_cycle_participant_events.actor_id IS NULL OR EXISTS (
      SELECT 1 FROM {schema}.users u WHERE u.id=learning_cycle_participant_events.actor_id
        AND u.tenant_id=learning_cycle_participant_events.tenant_id))"""
    op.execute(f"CREATE POLICY learning_cycle_events_select ON {events} FOR SELECT TO lms_app USING ({tenant})")
    op.execute(f"CREATE POLICY learning_cycle_events_insert ON {events} FOR INSERT TO lms_app WITH CHECK ({tenant} AND {ownership})")
    op.execute(f"CREATE POLICY learning_cycle_events_owner ON {events} TO CURRENT_USER USING (true) WITH CHECK (true)")
    _revoke_other_roles(events)
    op.execute(f"GRANT SELECT, INSERT ON {events} TO lms_app")

    op.execute(f"""
        CREATE FUNCTION {schema}.freeze_recurring_occurrence_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path={schema},pg_temp AS $$
        BEGIN
          IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            OR NEW.rule_id IS DISTINCT FROM OLD.rule_id
            OR NEW.user_id IS DISTINCT FROM OLD.user_id
            OR NEW.course_id IS DISTINCT FROM OLD.course_id
            OR NEW.sequence_no IS DISTINCT FROM OLD.sequence_no
            OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for
            OR NEW.due_at IS DISTINCT FROM OLD.due_at
            OR NEW.content_release_id IS DISTINCT FROM OLD.content_release_id
            OR (OLD.enrollment_id IS NOT NULL AND NEW.enrollment_id IS DISTINCT FROM OLD.enrollment_id) THEN
            RAISE EXCEPTION 'recurring course occurrence identity is immutable' USING ERRCODE='check_violation';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(f"CREATE TRIGGER trg_freeze_recurring_occurrence_identity BEFORE UPDATE ON {course_occurrences} FOR EACH ROW EXECUTE FUNCTION {schema}.freeze_recurring_occurrence_identity()")
    op.execute(f"""
        CREATE FUNCTION {schema}.validate_recurring_occurrence_evidence_anchor()
        RETURNS trigger LANGUAGE plpgsql SET search_path={schema},pg_temp AS $$
        BEGIN
          IF NEW.status<>'skipped' AND NOT EXISTS (
            SELECT 1 FROM {course_occurrences} a
            JOIN {schema}.enrollments e ON e.id=a.enrollment_id
              AND e.tenant_id=a.tenant_id AND e.recurring_assignment_id=a.id
              AND e.user_id=a.user_id AND e.course_id=a.course_id
              AND e.content_release_id=a.content_release_id
            WHERE a.id=NEW.id AND a.tenant_id=NEW.tenant_id
              AND a.enrollment_id IS NOT NULL AND a.content_release_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'recurring occurrence evidence anchor is incomplete' USING ERRCODE='check_violation';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(f"""
        CREATE CONSTRAINT TRIGGER trg_validate_recurring_occurrence_evidence_anchor
        AFTER INSERT OR UPDATE OF status,enrollment_id,content_release_id ON {course_occurrences}
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION {schema}.validate_recurring_occurrence_evidence_anchor()
    """)
    op.execute(f"""
        CREATE FUNCTION {schema}.freeze_learning_path_cycle_identity()
        RETURNS trigger LANGUAGE plpgsql SET search_path={schema},pg_temp AS $$
        BEGIN
          IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            OR NEW.rule_id IS DISTINCT FROM OLD.rule_id
            OR NEW.path_id IS DISTINCT FROM OLD.path_id
            OR NEW.user_id IS DISTINCT FROM OLD.user_id
            OR NEW.sequence_no IS DISTINCT FROM OLD.sequence_no
            OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for
            OR NEW.starts_at IS DISTINCT FROM OLD.starts_at
            OR NEW.due_at IS DISTINCT FROM OLD.due_at THEN
            RAISE EXCEPTION 'recurring learning-path occurrence identity is immutable' USING ERRCODE='check_violation';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(f"CREATE TRIGGER trg_freeze_learning_path_cycle_identity BEFORE UPDATE ON {path_occurrences} FOR EACH ROW EXECUTE FUNCTION {schema}.freeze_learning_path_cycle_identity()")

    op.execute(f"""
        CREATE OR REPLACE FUNCTION {schema}._learning_reminder_targets(p_tenant_id uuid,p_course_id uuid,p_path_id uuid)
        RETURNS TABLE(rule_id uuid,course_occurrence_id uuid,path_cycle_instance_id uuid,
          email text,learner_name text,company_name text,title text,target_type text,
          target_id uuid,due_at timestamptz,has_login_access boolean,lead_days integer)
        LANGUAGE sql STABLE SET search_path={schema},pg_temp AS $$
          SELECT r.id,a.id,NULL::uuid,u.email::text,
            trim(concat_ws(' ',u.first_name,u.last_name)),t.name::text,c.title::text,
            'course'::text,c.id,a.effective_due_at,
            (coalesce(u.password_hash,'')<>'' OR u.telegram_id IS NOT NULL OR u.email_verified_at IS NOT NULL),
            r.reminder_days_before_due
          FROM {course_occurrences} a
          JOIN {schema}.recurring_learning_rules r ON r.id=a.rule_id AND r.tenant_id=a.tenant_id
            AND r.course_id=a.course_id AND r.user_id=a.user_id
          JOIN {schema}.enrollments e ON e.id=a.enrollment_id AND e.recurring_assignment_id=a.id
            AND e.tenant_id=a.tenant_id AND e.user_id=a.user_id AND e.course_id=a.course_id
          JOIN {schema}.users u ON u.id=a.user_id AND u.tenant_id=a.tenant_id
          JOIN {schema}.tenants t ON t.id=a.tenant_id
          JOIN {schema}.courses c ON c.id=a.course_id AND c.tenant_id=a.tenant_id
          WHERE a.tenant_id=p_tenant_id AND a.id=p_course_id AND a.status='assigned'
            AND r.status='active' AND r.reminder_enabled AND e.status<>'completed' AND e.completed_at IS NULL
            AND u.role='student' AND u.is_active AND u.status='active' AND t.status='active' AND c.status='published'
          UNION ALL
          SELECT r.id,NULL::uuid,i.id,u.email::text,
            trim(concat_ws(' ',u.first_name,u.last_name)),t.name::text,p.title::text,
            'learning_path'::text,p.id,i.effective_due_at,
            (coalesce(u.password_hash,'')<>'' OR u.telegram_id IS NOT NULL OR u.email_verified_at IS NOT NULL),
            r.reminder_days_before_due
          FROM {path_occurrences} i
          JOIN {schema}.recurring_learning_rules r ON r.id=i.rule_id AND r.tenant_id=i.tenant_id
            AND r.learning_path_id=i.path_id AND r.user_id=i.user_id
          JOIN {schema}.learning_path_assignments a ON a.recurrence_instance_id=i.id
            AND a.tenant_id=i.tenant_id AND a.path_id=i.path_id AND a.user_id=i.user_id
          JOIN {schema}.users u ON u.id=i.user_id AND u.tenant_id=i.tenant_id
          JOIN {schema}.tenants t ON t.id=i.tenant_id
          JOIN {schema}.learning_paths p ON p.id=i.path_id AND p.tenant_id=i.tenant_id
          WHERE i.tenant_id=p_tenant_id AND i.id=p_path_id AND i.status='active' AND i.completed_at IS NULL
            AND a.status='active' AND a.completed_at IS NULL AND a.source='recurring'
            AND r.status='active' AND r.reminder_enabled AND i.effective_due_at IS NOT NULL
            AND u.role='student' AND u.is_active AND u.status='active' AND t.status='active' AND p.status='published'
        $$
    """)
    op.execute(f"""
        CREATE FUNCTION {schema}.reschedule_learning_reminder(
          p_tenant_id uuid,p_course_id uuid,p_path_id uuid,p_due_at timestamptz)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path={schema},pg_temp AS $$
        DECLARE v_lead_days integer; v_due_at timestamptz; v_scheduled_at timestamptz;
        BEGIN
          IF p_tenant_id IS NULL OR p_tenant_id IS DISTINCT FROM
            nullif(current_setting('app.tenant_id',true),'')::uuid THEN
            RAISE EXCEPTION 'tenant context mismatch';
          END IF;
          IF (p_course_id IS NULL)=(p_path_id IS NULL) THEN
            RAISE EXCEPTION 'exactly one occurrence required';
          END IF;
          SELECT x.lead_days,x.due_at INTO v_lead_days,v_due_at FROM {schema}._learning_reminder_targets(
            p_tenant_id,p_course_id,p_path_id) x
          WHERE x.course_occurrence_id=p_course_id OR x.path_cycle_instance_id=p_path_id;
          IF NOT FOUND THEN RETURN false; END IF;
          IF p_due_at IS DISTINCT FROM v_due_at THEN RAISE EXCEPTION 'deadline projection mismatch'; END IF;
          v_scheduled_at := v_due_at-make_interval(days=>v_lead_days);
          UPDATE {reminders} SET
            scheduled_at=v_scheduled_at,due_at=v_due_at,next_attempt_at=v_scheduled_at,
            last_error_category=NULL,updated_at=clock_timestamp()
          WHERE tenant_id=p_tenant_id
            AND (course_occurrence_id=p_course_id OR path_cycle_instance_id=p_path_id)
            AND status='queued' AND attempt_count=0 AND first_attempt_at IS NULL
            AND payload_hash IS NULL AND delivery_transport IS NULL
            AND send_reserved=false AND delivered_at IS NULL;
          RETURN FOUND;
        END $$
    """)
    signature = f"{schema}.reschedule_learning_reminder(uuid,uuid,uuid,timestamptz)"
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC, lms_app, lms_recovery")
    for role in ("anon", "authenticated", "service_role"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON FUNCTION {signature} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO lms_app")


def downgrade() -> None:
    schema = _schema()
    events = f"{schema}.learning_cycle_participant_events"
    op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {events}) THEN RAISE EXCEPTION '0167 downgrade refused: deadline history exists'; END IF; END $$")
    op.execute(f"DROP FUNCTION IF EXISTS {schema}.reschedule_learning_reminder(uuid,uuid,uuid,timestamptz)")
    op.execute(f"DROP TRIGGER IF EXISTS trg_freeze_learning_path_cycle_identity ON {schema}.learning_path_cycle_instances")
    op.execute(f"DROP FUNCTION IF EXISTS {schema}.freeze_learning_path_cycle_identity()")
    op.execute(f"DROP TRIGGER IF EXISTS trg_freeze_recurring_occurrence_identity ON {schema}.recurring_learning_assignments")
    op.execute(f"DROP FUNCTION IF EXISTS {schema}.freeze_recurring_occurrence_identity()")
    op.execute(f"DROP TRIGGER IF EXISTS trg_validate_recurring_occurrence_evidence_anchor ON {schema}.recurring_learning_assignments")
    op.execute(f"DROP FUNCTION IF EXISTS {schema}.validate_recurring_occurrence_evidence_anchor()")
    op.execute(f"DROP TABLE {events}")
    _restore_original_reminder_targets(schema)
    op.execute(f"ALTER TABLE {schema}.learning_path_cycle_instances DROP CONSTRAINT ck_learning_path_cycle_effective_due")
    op.execute(f"ALTER TABLE {schema}.learning_path_cycle_instances DROP COLUMN effective_due_at")
    op.execute(f"ALTER TABLE {schema}.recurring_learning_assignments DROP CONSTRAINT ck_recurring_assignment_effective_due")
    op.execute(f"ALTER TABLE {schema}.recurring_learning_assignments DROP COLUMN effective_due_at")
    op.execute(f"ALTER TABLE {schema}.recurring_learning_assignments DROP COLUMN content_release_id")
    op.execute(f"ALTER TABLE {schema}.recurring_learning_assignments DROP CONSTRAINT uq_recurring_assignment_occurrence")
    op.execute(f"ALTER TABLE {schema}.recurring_learning_assignments DROP CONSTRAINT ck_recurring_assignment_sequence")
    op.execute(f"ALTER TABLE {schema}.recurring_learning_assignments DROP COLUMN sequence_no")
    op.execute(f"GRANT DELETE ON {schema}.recurring_learning_assignments TO lms_app")
