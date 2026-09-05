"""Opt-in recurring-learning reminder ledger; disabled application rollout.

Revision ID: 0152
Revises: 0151
"""

import re

from alembic import op
from sqlalchemy import text

revision = "0152"
down_revision = "0151"
branch_labels = None
depends_on = None

CONTEXT_GUARD = """
IF p_tenant_id IS NULL OR p_tenant_id IS DISTINCT FROM
  nullif(current_setting('app.tenant_id', true), '')::uuid THEN
  RAISE EXCEPTION 'tenant context mismatch';
END IF;
"""


def _sql(statement: str) -> str:
    # The same migration supports the approved isolated-schema DEV harness.
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe reminder migration schema")
    return statement.replace("__KML_SCHEMA__", '"' + schema + '"')


def _execute(statement: str) -> None:
    op.execute(_sql(statement))


def _function(name: str, arguments: str, returns: str, body: str, declarations: str = "") -> None:
    _execute(f"""
    CREATE FUNCTION __KML_SCHEMA__.{name}({arguments}) RETURNS {returns}
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = __KML_SCHEMA__, pg_temp AS $$
    {('DECLARE ' + declarations) if declarations else ''}
    BEGIN {body} END $$
    """)


def upgrade() -> None:
    _execute(
        "ALTER TABLE __KML_SCHEMA__.recurring_learning_rules ADD COLUMN reminder_enabled boolean NOT NULL DEFAULT false"
    )
    _execute(
        "ALTER TABLE __KML_SCHEMA__.recurring_learning_rules ADD COLUMN reminder_days_before_due integer NOT NULL DEFAULT 1 CHECK (reminder_days_before_due BETWEEN 1 AND 30)"
    )
    _execute("""
    CREATE TABLE __KML_SCHEMA__.learning_reminder_outbox (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES __KML_SCHEMA__.tenants(id) ON DELETE RESTRICT,
      rule_id uuid NOT NULL REFERENCES __KML_SCHEMA__.recurring_learning_rules(id) ON DELETE RESTRICT,
      course_occurrence_id uuid REFERENCES __KML_SCHEMA__.recurring_learning_assignments(id) ON DELETE RESTRICT,
      path_cycle_instance_id uuid REFERENCES __KML_SCHEMA__.learning_path_cycle_instances(id) ON DELETE RESTRICT,
      policy_version integer NOT NULL DEFAULT 1 CHECK (policy_version = 1),
      step text NOT NULL DEFAULT 'before_due' CHECK (step = 'before_due'),
      channel text NOT NULL DEFAULT 'email' CHECK (channel = 'email'),
      scheduled_at timestamptz NOT NULL, due_at timestamptz NOT NULL,
      status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sending','sent','failed','skipped')),
      attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 3),
      first_attempt_at timestamptz, payload_hash text CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
      delivery_transport text CHECK (delivery_transport IN ('resend','smtp')),
      next_attempt_at timestamptz NOT NULL,
      claim_token uuid, claimed_at timestamptz, send_reserved boolean NOT NULL DEFAULT false, delivered_at timestamptz,
      delivery_message_id varchar(255), last_error_category text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((course_occurrence_id IS NULL) <> (path_cycle_instance_id IS NULL)),
      CHECK (scheduled_at < due_at),
      CHECK ((status = 'sending') = (claim_token IS NOT NULL AND claimed_at IS NOT NULL)),
      CHECK ((status = 'sent') = (delivered_at IS NOT NULL)),
      CHECK ((first_attempt_at IS NULL) = (payload_hash IS NULL)),
      CHECK ((first_attempt_at IS NULL) = (delivery_transport IS NULL)),
      CHECK (last_error_category IS NULL OR last_error_category IN (
        'configuration_missing','recipient_missing','activation_required','ineligible','expired',
        'attempt_limit','retry_window_expired','payload_changed','provider_timeout','delivery_uncertain','transport_changed',
        'provider_unreachable','provider_rate_limited','provider_unavailable','provider_rejected','internal_error'))
    )
    """)
    for column in ("course_occurrence_id", "path_cycle_instance_id"):
        _execute(
            f"CREATE UNIQUE INDEX uq_reminder_{column} ON __KML_SCHEMA__.learning_reminder_outbox (tenant_id, {column}, policy_version, step, channel) WHERE {column} IS NOT NULL"
        )
    _execute(
        "CREATE INDEX ix_learning_reminder_due ON __KML_SCHEMA__.learning_reminder_outbox (status,next_attempt_at)"
    )
    _execute("CREATE INDEX ix_learning_reminder_rule ON __KML_SCHEMA__.learning_reminder_outbox (tenant_id,rule_id)")
    _execute("ALTER TABLE __KML_SCHEMA__.learning_reminder_outbox ENABLE ROW LEVEL SECURITY")
    _execute("ALTER TABLE __KML_SCHEMA__.learning_reminder_outbox FORCE ROW LEVEL SECURITY")
    _execute(
        "CREATE POLICY learning_reminder_tenant ON __KML_SCHEMA__.learning_reminder_outbox USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid)"
    )
    # The migration/function owner needs bounded global discovery even without BYPASSRLS.
    _execute(
        "CREATE POLICY learning_reminder_owner ON __KML_SCHEMA__.learning_reminder_outbox TO CURRENT_USER USING (true) WITH CHECK (true)"
    )
    _execute("REVOKE ALL ON __KML_SCHEMA__.learning_reminder_outbox FROM PUBLIC, lms_app, lms_recovery")
    for inherited_role in ("anon", "authenticated", "service_role"):
        _execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{inherited_role}') THEN
          EXECUTE 'REVOKE ALL ON __KML_SCHEMA__.learning_reminder_outbox FROM {inherited_role}';
        END IF; END $$""")
    _execute("""
    CREATE FUNCTION __KML_SCHEMA__._learning_reminder_targets(p_tenant_id uuid,p_course_id uuid,p_path_id uuid)
    RETURNS TABLE(rule_id uuid,course_occurrence_id uuid,path_cycle_instance_id uuid,
      email text,learner_name text,company_name text,title text,target_type text,
      target_id uuid,due_at timestamptz,has_login_access boolean,lead_days integer)
    LANGUAGE sql STABLE SET search_path = __KML_SCHEMA__, pg_temp AS $$
      SELECT r.id,a.id,NULL::uuid,u.email::text,
        trim(concat_ws(' ',u.first_name,u.last_name)),t.name::text,c.title::text,
        'course'::text,c.id,a.due_at,
        (coalesce(u.password_hash,'')<>'' OR u.telegram_id IS NOT NULL OR u.email_verified_at IS NOT NULL),
        r.reminder_days_before_due
      FROM __KML_SCHEMA__.recurring_learning_assignments a
      JOIN __KML_SCHEMA__.recurring_learning_rules r ON r.id=a.rule_id AND r.tenant_id=a.tenant_id
        AND r.course_id=a.course_id AND r.user_id=a.user_id
      JOIN __KML_SCHEMA__.enrollments e ON e.id=a.enrollment_id AND e.recurring_assignment_id=a.id
        AND e.tenant_id=a.tenant_id AND e.user_id=a.user_id AND e.course_id=a.course_id
      JOIN __KML_SCHEMA__.users u ON u.id=a.user_id AND u.tenant_id=a.tenant_id
      JOIN __KML_SCHEMA__.tenants t ON t.id=a.tenant_id
      JOIN __KML_SCHEMA__.courses c ON c.id=a.course_id AND c.tenant_id=a.tenant_id
      WHERE a.tenant_id=p_tenant_id AND a.id=p_course_id AND a.status='assigned'
        AND r.status='active' AND r.reminder_enabled AND e.status<>'completed' AND e.completed_at IS NULL
        AND u.role='student' AND u.is_active AND u.status='active' AND t.status='active'
        AND c.status='published'
      UNION ALL
      SELECT r.id,NULL::uuid,i.id,u.email::text,
        trim(concat_ws(' ',u.first_name,u.last_name)),t.name::text,p.title::text,
        'learning_path'::text,p.id,i.due_at,
        (coalesce(u.password_hash,'')<>'' OR u.telegram_id IS NOT NULL OR u.email_verified_at IS NOT NULL),
        r.reminder_days_before_due
      FROM __KML_SCHEMA__.learning_path_cycle_instances i
      JOIN __KML_SCHEMA__.recurring_learning_rules r ON r.id=i.rule_id AND r.tenant_id=i.tenant_id
        AND r.learning_path_id=i.path_id AND r.user_id=i.user_id
      JOIN __KML_SCHEMA__.learning_path_assignments a ON a.recurrence_instance_id=i.id
        AND a.tenant_id=i.tenant_id AND a.path_id=i.path_id AND a.user_id=i.user_id
      JOIN __KML_SCHEMA__.users u ON u.id=i.user_id AND u.tenant_id=i.tenant_id
      JOIN __KML_SCHEMA__.tenants t ON t.id=i.tenant_id
      JOIN __KML_SCHEMA__.learning_paths p ON p.id=i.path_id AND p.tenant_id=i.tenant_id
      WHERE i.tenant_id=p_tenant_id AND i.id=p_path_id AND i.status='active' AND i.completed_at IS NULL
        AND a.status='active' AND a.completed_at IS NULL AND a.source='recurring'
        AND r.status='active' AND r.reminder_enabled AND i.due_at IS NOT NULL
        AND u.role='student' AND u.is_active AND u.status='active' AND t.status='active'
        AND p.status='published'
    $$
    """)
    _function(
        "enqueue_learning_reminder",
        "p_tenant_id uuid,p_course_id uuid,p_path_id uuid",
        "uuid",
        CONTEXT_GUARD
        + """
      IF (p_course_id IS NULL) = (p_path_id IS NULL) THEN RAISE EXCEPTION 'exactly one occurrence required'; END IF;
      PERFORM 1 FROM __KML_SCHEMA__.tenants t WHERE t.id=p_tenant_id FOR SHARE;
      SELECT * INTO v_target FROM __KML_SCHEMA__._learning_reminder_targets(p_tenant_id,p_course_id,p_path_id) x
      WHERE (x.course_occurrence_id=p_course_id OR x.path_cycle_instance_id=p_path_id);
      IF NOT FOUND OR v_target.due_at <= clock_timestamp() THEN RETURN NULL; END IF;
      INSERT INTO __KML_SCHEMA__.learning_reminder_outbox
        (tenant_id,rule_id,course_occurrence_id,path_cycle_instance_id,scheduled_at,due_at,next_attempt_at)
      VALUES (p_tenant_id,v_target.rule_id,p_course_id,p_path_id,
        v_target.due_at-make_interval(days=>v_target.lead_days),v_target.due_at,
        v_target.due_at-make_interval(days=>v_target.lead_days))
      ON CONFLICT DO NOTHING RETURNING id INTO v_id;
      IF v_id IS NULL THEN
        SELECT o.id INTO v_id FROM __KML_SCHEMA__.learning_reminder_outbox o
        WHERE o.tenant_id=p_tenant_id AND (o.course_occurrence_id=p_course_id OR o.path_cycle_instance_id=p_path_id);
      END IF;
      RETURN v_id;
    """,
        "v_target record; v_id uuid;",
    )
    _function(
        "claim_learning_reminder",
        "p_tenant_id uuid,p_id uuid",
        "TABLE(id uuid,tenant_id uuid,claim_token uuid)",
        CONTEXT_GUARD
        + """
      PERFORM 1 FROM __KML_SCHEMA__.tenants t WHERE t.id=p_tenant_id FOR SHARE;
      RETURN QUERY WITH candidate AS (
        SELECT o.id FROM __KML_SCHEMA__.learning_reminder_outbox o WHERE o.tenant_id=p_tenant_id AND o.id=p_id
          AND ((o.status='queued' AND o.next_attempt_at<=clock_timestamp())
            OR (o.status='sending' AND o.claimed_at<clock_timestamp()-interval '10 minutes'))
        FOR UPDATE SKIP LOCKED
      ) UPDATE __KML_SCHEMA__.learning_reminder_outbox o SET status='sending', claim_token=gen_random_uuid(),
          claimed_at=clock_timestamp(),send_reserved=false,updated_at=clock_timestamp()
        FROM candidate c WHERE o.id=c.id RETURNING o.id,o.tenant_id,o.claim_token;
    """,
    )
    _function(
        "learning_reminder_payload",
        "p_tenant_id uuid,p_id uuid,p_token uuid",
        "TABLE(email text,learner_name text,company_name text,title text,target_type text,target_id uuid,due_at timestamptz,has_login_access boolean)",
        CONTEXT_GUARD
        + """
      RETURN QUERY SELECT x.email,x.learner_name,x.company_name,x.title,x.target_type,x.target_id,o.due_at,x.has_login_access
      FROM __KML_SCHEMA__.learning_reminder_outbox o JOIN LATERAL __KML_SCHEMA__._learning_reminder_targets(p_tenant_id,o.course_occurrence_id,o.path_cycle_instance_id) x
        ON (x.course_occurrence_id=o.course_occurrence_id OR x.path_cycle_instance_id=o.path_cycle_instance_id)
      WHERE o.tenant_id=p_tenant_id AND o.id=p_id AND o.claim_token=p_token AND o.status='sending'
        AND x.due_at=o.due_at
        AND o.due_at>clock_timestamp() AND o.claimed_at>clock_timestamp()-interval '10 minutes';
    """,
    )
    _function(
        "begin_learning_reminder_send",
        "p_tenant_id uuid,p_id uuid,p_token uuid,p_hash text,p_transport text DEFAULT 'resend'",
        "boolean",
        CONTEXT_GUARD
        + """
      IF p_hash IS NULL OR p_hash !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'invalid payload hash'; END IF;
      IF p_transport IS NULL OR p_transport NOT IN ('resend','smtp') THEN RAISE EXCEPTION 'invalid delivery transport'; END IF;
      SELECT * INTO v_row FROM __KML_SCHEMA__.learning_reminder_outbox o
      WHERE o.tenant_id=p_tenant_id AND o.id=p_id AND o.status='sending' AND o.claim_token=p_token FOR UPDATE;
      IF NOT FOUND THEN RETURN false; END IF;
      IF v_row.send_reserved THEN RETURN false; END IF;
      IF v_row.claimed_at<=clock_timestamp()-interval '10 minutes' THEN RETURN false; END IF;
      v_reason := CASE
        WHEN v_row.due_at<=clock_timestamp() THEN 'expired'
        WHEN v_row.first_attempt_at<=clock_timestamp()-interval '23 hours' THEN 'retry_window_expired'
        WHEN v_row.attempt_count>=3 THEN 'attempt_limit'
        WHEN v_row.delivery_transport IS NOT NULL AND v_row.delivery_transport<>p_transport THEN 'transport_changed'
        WHEN v_row.delivery_transport='smtp' AND v_row.attempt_count>0 THEN 'delivery_uncertain'
        WHEN v_row.payload_hash IS NOT NULL AND v_row.payload_hash<>p_hash THEN 'payload_changed'
        WHEN NOT EXISTS (SELECT 1 FROM __KML_SCHEMA__.learning_reminder_payload(p_tenant_id,p_id,p_token)) THEN 'ineligible'
        ELSE NULL END;
      IF v_reason IS NOT NULL THEN
        UPDATE __KML_SCHEMA__.learning_reminder_outbox SET status=CASE WHEN v_reason IN ('expired','ineligible') THEN 'skipped' ELSE 'failed' END,
          last_error_category=v_reason,claim_token=NULL,claimed_at=NULL,updated_at=clock_timestamp() WHERE id=p_id;
        RETURN false;
      END IF;
      UPDATE __KML_SCHEMA__.learning_reminder_outbox SET attempt_count=attempt_count+1,send_reserved=true,
        first_attempt_at=coalesce(first_attempt_at,clock_timestamp()),payload_hash=p_hash,
        delivery_transport=p_transport,updated_at=clock_timestamp() WHERE id=p_id;
      RETURN true;
    """,
        "v_row __KML_SCHEMA__.learning_reminder_outbox%ROWTYPE; v_reason text;",
    )
    _function(
        "finalize_learning_reminder",
        "p_tenant_id uuid,p_id uuid,p_token uuid,p_kind text,p_message_id text,p_error_category text",
        "boolean",
        CONTEXT_GUARD
        + """
      IF p_kind IS NULL OR p_kind NOT IN ('success','transient','terminal','defer','skipped') THEN RAISE EXCEPTION 'invalid finalization kind'; END IF;
      IF p_kind='success' AND (p_message_id IS NULL OR length(btrim(p_message_id))=0) THEN RETURN false; END IF;
      IF p_error_category IS NOT NULL AND p_error_category NOT IN (
        'configuration_missing','recipient_missing','activation_required','ineligible','expired',
        'attempt_limit','retry_window_expired','payload_changed','provider_timeout','delivery_uncertain','transport_changed',
        'provider_unreachable','provider_rate_limited','provider_unavailable','provider_rejected','internal_error')
      THEN p_error_category := 'internal_error'; END IF;
      UPDATE __KML_SCHEMA__.learning_reminder_outbox o SET
        status=CASE WHEN p_kind='success' THEN 'sent' WHEN p_kind='skipped' THEN 'skipped'
          WHEN p_kind='terminal' OR (p_kind='transient' AND o.attempt_count>=3) THEN 'failed' ELSE 'queued' END,
        next_attempt_at=clock_timestamp()+CASE WHEN p_kind='defer' THEN interval '5 minutes'
          ELSE make_interval(secs=>60*power(2,greatest(0,o.attempt_count-1))::integer) END,
        delivered_at=CASE WHEN p_kind='success' THEN clock_timestamp() ELSE NULL END,
        delivery_message_id=CASE WHEN p_kind='success' THEN left(p_message_id,255) ELSE o.delivery_message_id END,
        last_error_category=CASE WHEN p_kind='success' THEN NULL ELSE coalesce(p_error_category,'internal_error') END,
        claim_token=NULL,claimed_at=NULL,updated_at=clock_timestamp()
      WHERE o.tenant_id=p_tenant_id AND o.id=p_id AND o.claim_token=p_token AND o.status='sending'
        AND (p_kind NOT IN ('success','transient') OR o.send_reserved);
      RETURN FOUND;
    """,
    )
    _function(
        "due_learning_reminders",
        "p_limit integer DEFAULT 20",
        "TABLE(id uuid,tenant_id uuid)",
        """
      RETURN QUERY SELECT o.id,o.tenant_id FROM __KML_SCHEMA__.learning_reminder_outbox o
      WHERE (o.status='queued' AND o.next_attempt_at<=clock_timestamp())
        OR (o.status='sending' AND o.claimed_at<clock_timestamp()-interval '10 minutes')
      ORDER BY o.next_attempt_at,o.id LIMIT greatest(1,least(coalesce(p_limit,20),100));
    """,
    )
    _function(
        "learning_reminder_statuses",
        "p_tenant_id uuid,p_rule_id uuid",
        "TABLE(id uuid,course_occurrence_id uuid,path_cycle_instance_id uuid,status text,attempt_count integer,scheduled_at timestamptz,delivered_at timestamptz,last_error_category text)",
        CONTEXT_GUARD
        + """
      RETURN QUERY SELECT o.id,o.course_occurrence_id,o.path_cycle_instance_id,o.status,o.attempt_count,
        o.scheduled_at,o.delivered_at,o.last_error_category FROM __KML_SCHEMA__.learning_reminder_outbox o
      WHERE o.tenant_id=p_tenant_id AND o.rule_id=p_rule_id ORDER BY o.created_at DESC,o.id LIMIT 100;
    """,
    )
    _function(
        "superadmin_purge_tenant_learning_reminders",
        "p_tenant_id uuid,p_confirm_slug text",
        "integer",
        CONTEXT_GUARD
        + """
      SELECT pg_catalog.pg_get_userbyid(d.datdba) INTO v_owner FROM pg_catalog.pg_database d
      WHERE d.datname=pg_catalog.current_database();
      IF coalesce(current_setting('app.is_superadmin',true),'')<>'true'
        OR (session_user<>'lms_app' AND session_user<>v_owner) THEN
        RAISE EXCEPTION 'Active superadmin context is required' USING ERRCODE='insufficient_privilege';
      END IF;
      SELECT slug INTO v_slug FROM __KML_SCHEMA__.tenants WHERE id=p_tenant_id FOR UPDATE;
      IF v_slug IS NULL OR v_slug='kamilya' OR v_slug IS DISTINCT FROM p_confirm_slug THEN
        RAISE EXCEPTION 'Tenant deletion confirmation rejected' USING ERRCODE='insufficient_privilege';
      END IF;
      IF EXISTS (SELECT 1 FROM __KML_SCHEMA__.learning_reminder_outbox
        WHERE tenant_id=p_tenant_id AND status='sending' AND claimed_at>clock_timestamp()-interval '10 minutes') THEN
        RAISE EXCEPTION 'Active reminder delivery prevents tenant deletion';
      END IF;
      DELETE FROM __KML_SCHEMA__.learning_reminder_outbox WHERE tenant_id=p_tenant_id;
      GET DIAGNOSTICS v_count=ROW_COUNT;
      RETURN v_count;
    """,
        "v_owner name; v_slug text; v_count integer;",
    )
    for signature in SIGNATURES:
        _execute(f"REVOKE ALL ON FUNCTION __KML_SCHEMA__.{signature} FROM PUBLIC, lms_app, lms_recovery")
        for inherited_role in ("anon", "authenticated", "service_role"):
            _execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{inherited_role}') THEN
              EXECUTE 'REVOKE ALL ON FUNCTION __KML_SCHEMA__.{signature} FROM {inherited_role}';
            END IF; END $$""")
        if signature.startswith("_learning"):
            continue
        role = "lms_recovery" if signature.startswith("due_") else "lms_app"
        _execute(f"GRANT EXECUTE ON FUNCTION __KML_SCHEMA__.{signature} TO {role}")


SIGNATURES = (
    "_learning_reminder_targets(uuid,uuid,uuid)",
    "enqueue_learning_reminder(uuid,uuid,uuid)",
    "claim_learning_reminder(uuid,uuid)",
    "learning_reminder_payload(uuid,uuid,uuid)",
    "begin_learning_reminder_send(uuid,uuid,uuid,text,text)",
    "finalize_learning_reminder(uuid,uuid,uuid,text,text,text)",
    "due_learning_reminders(integer)",
    "learning_reminder_statuses(uuid,uuid)",
    "superadmin_purge_tenant_learning_reminders(uuid,text)",
)


def downgrade() -> None:
    if op.get_bind().scalar(text(_sql("SELECT EXISTS(SELECT 1 FROM __KML_SCHEMA__.learning_reminder_outbox)"))):
        raise RuntimeError("0152 downgrade blocked: reminder delivery history exists")
    for signature in reversed(SIGNATURES):
        _execute(f"DROP FUNCTION __KML_SCHEMA__.{signature}")
    _execute("DROP TABLE __KML_SCHEMA__.learning_reminder_outbox")
    _execute("ALTER TABLE __KML_SCHEMA__.recurring_learning_rules DROP COLUMN reminder_enabled")
    _execute("ALTER TABLE __KML_SCHEMA__.recurring_learning_rules DROP COLUMN reminder_days_before_due")
