"""Add opt-in Telegram delivery on the DEV localization schema lineage.

The production candidate has a distinct revision 0192 after its 0191.
"""

import re

from alembic import op

revision = "0193"
down_revision = "0190"
branch_labels = depends_on = None


def schema_name() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe notification schema")
    return schema


TRIGGERS = {
    "enrollments": "course",
    "learning_path_assignments": "program",
    "knowledge_check_assignments": "check",
    "learning_reminder_outbox": "reminder",
}
ROLES = ("lms_app", "lms_recovery", "anon", "authenticated", "service_role")


def restrict(kind: str, qualified_name: str, grant: str | None = None) -> None:
    op.execute(f"REVOKE ALL ON {kind} {qualified_name} FROM PUBLIC")
    for role in ROLES:
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {kind} {qualified_name} FROM {role}'; END IF; END $$""")
    if grant:
        op.execute(f"GRANT EXECUTE ON FUNCTION {qualified_name} TO {grant}")


def upgrade() -> None:
    s = schema_name()
    routes = f"{s}.telegram_reminder_workspaces"
    links = f"{s}.telegram_reminder_subscriptions"
    outbox = f"{s}.telegram_reminder_outbox"
    tenant = "nullif(current_setting('app.tenant_id',true),'')::uuid"
    actor = "nullif(current_setting('app.user_id',true),'')::uuid"
    op.execute(f"""CREATE TABLE {routes} (
        tenant_id uuid PRIMARY KEY REFERENCES {s}.tenants(id) ON DELETE CASCADE,
        workspace_label text NOT NULL CHECK (length(btrim(workspace_label)) BETWEEN 1 AND 120),
        public_origin text NOT NULL CHECK (public_origin ~ '^https://[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$'),
        enabled boolean NOT NULL DEFAULT false,
        overdue_enabled boolean NOT NULL DEFAULT false
    )""")
    op.execute(f"""CREATE TABLE {links} (
        tenant_id uuid NOT NULL REFERENCES {routes}(tenant_id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES {s}.users(id) ON DELETE CASCADE,
        chat_id bigint CHECK (chat_id > 0),
        connected_at timestamptz,
        pending_link_hash text UNIQUE CHECK (pending_link_hash ~ '^[0-9a-f]{{64}}$'),
        pending_until timestamptz,
        pending_chat_id bigint CHECK (pending_chat_id > 0),
        pending_code_hash text CHECK (pending_code_hash ~ '^[0-9a-f]{{64}}$'),
        PRIMARY KEY (tenant_id,user_id),
        UNIQUE (tenant_id,chat_id),
        CHECK ((chat_id IS NULL) = (connected_at IS NULL)),
        CHECK ((pending_chat_id IS NULL) = (pending_code_hash IS NULL))
    )""")
    op.execute(f"""CREATE TABLE {outbox} (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES {routes}(tenant_id) ON DELETE CASCADE,
        source text NOT NULL CHECK (source IN ('course','program','check','reminder')),
        source_id uuid NOT NULL,
        step text NOT NULL CHECK (step IN ('assigned','before_due','overdue')),
        due_to_send_at timestamptz NOT NULL,
        status text NOT NULL DEFAULT 'queued'
          CHECK (status IN ('queued','dispatching','sent','skipped','failed','uncertain')),
        reason text CHECK (reason IN ('ineligible','not_connected','expired','provider_rejected','delivery_uncertain')),
        claimed_at timestamptz,
        message_id bigint CHECK (message_id > 0),
        sent_at timestamptz,
        UNIQUE (tenant_id,source,source_id,step),
        CHECK ((status='sent') = (message_id IS NOT NULL AND sent_at IS NOT NULL))
    )""")
    op.execute(f"CREATE INDEX ix_telegram_reminder_due ON {outbox}(due_to_send_at,id) WHERE status='queued'")
    op.execute(f"CREATE INDEX ix_telegram_reminder_claimed ON {outbox}(claimed_at,id) WHERE status='dispatching'")
    for table in (routes, links, outbox):
        restrict("TABLE", table)
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY telegram_owner ON {table} TO CURRENT_USER USING (true) WITH CHECK (true)")
    op.execute(f"CREATE POLICY telegram_routes_read ON {routes} FOR SELECT TO lms_app USING (tenant_id={tenant})")
    op.execute(f"""CREATE POLICY telegram_subscriptions_self ON {links} TO lms_app
          USING (tenant_id={tenant} AND user_id={actor})
          WITH CHECK (tenant_id={tenant} AND user_id={actor}
            AND EXISTS (SELECT 1 FROM {s}.users u WHERE u.id=telegram_reminder_subscriptions.user_id AND u.tenant_id=telegram_reminder_subscriptions.tenant_id
              AND u.is_active AND u.status='active'))""")
    op.execute(f"GRANT SELECT ON {routes} TO lms_app")
    op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {links} TO lms_app")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_project_learning_event()
    RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path={s},pg_temp AS $$
    DECLARE source_kind text := TG_ARGV[0];
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM {routes} r WHERE r.tenant_id=NEW.tenant_id AND r.enabled) THEN
        RETURN NEW;
      END IF;
      IF source_kind='reminder' THEN
        IF TG_OP='UPDATE' THEN
          UPDATE {outbox} SET due_to_send_at=CASE WHEN step='overdue' THEN NEW.due_at ELSE NEW.scheduled_at END
            WHERE tenant_id=NEW.tenant_id AND source='reminder' AND source_id=NEW.id AND status='queued';
        ELSE
          INSERT INTO {outbox}(tenant_id,source,source_id,step,due_to_send_at)
          VALUES (NEW.tenant_id,source_kind,NEW.id,'before_due',NEW.scheduled_at)
          ON CONFLICT DO NOTHING;
          INSERT INTO {outbox}(tenant_id,source,source_id,step,due_to_send_at)
          SELECT NEW.tenant_id,source_kind,NEW.id,'overdue',NEW.due_at
          FROM {routes} r WHERE r.tenant_id=NEW.tenant_id AND r.overdue_enabled
          ON CONFLICT DO NOTHING;
        END IF;
      ELSE
        IF source_kind='course' THEN
          IF NEW.learning_path_assignment_id IS NOT NULL OR NEW.source='learning_path' OR
             NEW.status NOT IN ('enrolled','in_progress') THEN RETURN NEW; END IF;
        ELSIF source_kind='program' THEN
          IF NEW.status<>'active' THEN RETURN NEW; END IF;
        END IF;
        INSERT INTO {outbox}(tenant_id,source,source_id,step,due_to_send_at)
        VALUES (NEW.tenant_id,source_kind,NEW.id,'assigned',clock_timestamp())
        ON CONFLICT DO NOTHING;
      END IF;
      RETURN NEW;
    END $$""")
    restrict("FUNCTION", f"{s}.telegram_project_learning_event()")
    for table, kind in TRIGGERS.items():
        events = "INSERT OR UPDATE OF scheduled_at,due_at" if kind == "reminder" else "INSERT"
        op.execute(f"""CREATE TRIGGER telegram_project_learning_event AFTER {events} ON {s}.{table}
            FOR EACH ROW EXECUTE FUNCTION {s}.telegram_project_learning_event('{kind}')""")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_accept_learning_start(p_link text,p_chat bigint,p_code text)
    RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path={s},pg_temp AS $$
    BEGIN
      IF p_chat IS NULL OR p_chat<=0 OR p_link IS NULL OR p_link !~ '^[a-f0-9]{{64}}$'
        OR p_code IS NULL OR p_code !~ '^[a-f0-9]{{64}}$' THEN RETURN false; END IF;
      UPDATE {links} b SET pending_chat_id=p_chat,pending_code_hash=p_code,pending_link_hash=NULL
      FROM {routes} r
      WHERE b.pending_link_hash=p_link AND b.pending_until>clock_timestamp()
        AND r.tenant_id=b.tenant_id AND r.enabled;
      RETURN FOUND;
    END $$""")
    restrict("FUNCTION", f"{s}.telegram_accept_learning_start(text,bigint,text)", "lms_app")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_toggle_learning_workspace(p_chat bigint,p_tenant uuid)
    RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path={s},pg_temp AS $$
    BEGIN
      DELETE FROM {links} WHERE tenant_id=p_tenant AND chat_id=p_chat;
      RETURN FOUND;
    END $$""")
    restrict("FUNCTION", f"{s}.telegram_toggle_learning_workspace(bigint,uuid)", "lms_app")
    op.execute(f"""
    CREATE FUNCTION {s}.telegram_bound_learning_workspaces(p_chat bigint)
    RETURNS TABLE(tenant_id uuid,workspace text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path={s},pg_temp AS $$
      SELECT b.tenant_id,r.workspace_label FROM {links} b
      JOIN {routes} r ON r.tenant_id=b.tenant_id AND r.enabled
      WHERE b.chat_id=p_chat AND p_chat>0 ORDER BY r.workspace_label,b.tenant_id LIMIT 25
    $$""")
    restrict("FUNCTION", f"{s}.telegram_bound_learning_workspaces(bigint)", "lms_app")

    # Notification eligibility is business state, independent of SMTP/Resend state.
    op.execute(f"""
    CREATE FUNCTION {s}.telegram_learning_target(p_tenant uuid,p_source text,p_id uuid)
    RETURNS TABLE(user_id uuid,target_type text,target_id uuid,title text,deadline timestamptz,
                  rule_id uuid, reminder_scheduled_at timestamptz)
    LANGUAGE sql STABLE SET search_path={s},pg_temp AS $$
      SELECT e.user_id,'course',c.id,c.title::text,a.effective_due_at,NULL::uuid,NULL::timestamptz
      FROM {s}.enrollments e
      JOIN {s}.courses c ON c.id=e.course_id AND c.tenant_id=e.tenant_id AND c.status='published'
      LEFT JOIN {s}.recurring_learning_assignments a ON a.id=e.recurring_assignment_id AND a.tenant_id=e.tenant_id
      WHERE p_source='course' AND e.tenant_id=p_tenant AND e.id=p_id
        AND e.status IN ('enrolled','in_progress') AND e.completed_at IS NULL
      UNION ALL
      SELECT a.user_id,'program',p.id,p.title::text,coalesce(i.effective_due_at,a.due_at),NULL,NULL
      FROM {s}.learning_path_assignments a
      JOIN {s}.learning_paths p ON p.id=a.path_id AND p.tenant_id=a.tenant_id AND p.status='published'
      LEFT JOIN {s}.learning_path_cycle_instances i ON i.id=a.recurrence_instance_id AND i.tenant_id=a.tenant_id
      WHERE p_source='program' AND a.tenant_id=p_tenant AND a.id=p_id
        AND a.status='active' AND a.cancelled_at IS NULL AND a.completed_at IS NULL
      UNION ALL
      SELECT a.user_id,'check',a.id,a.snapshot->>'title',a.due_at,NULL,NULL
      FROM {s}.knowledge_check_assignments a
      JOIN {s}.knowledge_checks c ON c.id=a.check_id AND c.tenant_id=a.tenant_id AND c.status='published'
      WHERE p_source='check' AND a.tenant_id=p_tenant AND a.id=p_id
        AND NOT EXISTS (SELECT 1 FROM {s}.knowledge_check_attempts n
          WHERE n.tenant_id=a.tenant_id AND n.assignment_id=a.id AND n.status='submitted' AND n.passed)
      UNION ALL
      SELECT r.user_id,x.target_type,x.target_id,x.title,x.due_at,x.rule_id,
        x.due_at-make_interval(days=>x.lead_days)
      FROM {s}.learning_reminder_outbox o
      JOIN LATERAL {s}._learning_reminder_targets(p_tenant,o.course_occurrence_id,o.path_cycle_instance_id) x
        ON (x.course_occurrence_id=o.course_occurrence_id OR x.path_cycle_instance_id=o.path_cycle_instance_id)
      JOIN {s}.recurring_learning_rules r ON r.id=x.rule_id AND r.tenant_id=o.tenant_id
      WHERE p_source='reminder' AND o.tenant_id=p_tenant AND o.id=p_id
    $$""")
    restrict("FUNCTION", f"{s}.telegram_learning_target(uuid,text,uuid)")
    # Extend read access only for the function owner, and only under the requested tenant.
    for table in ("users", "tenants", "courses", "enrollments", "recurring_learning_assignments",
                  "recurring_learning_rules", "learning_path_assignments", "learning_paths",
                  "learning_path_cycle_instances", "knowledge_checks", "knowledge_check_assignments",
                  "knowledge_check_attempts", "learning_reminder_outbox", "tenant_settings"):
        column = "id" if table == "tenants" else "tenant_id"
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n
             ON c.relnamespace=n.oid WHERE n.nspname='{s}' AND c.relname='{table}' AND c.relrowsecurity)
             THEN CREATE POLICY telegram_reminder_source_owner ON {s}.{table}
               FOR SELECT TO CURRENT_USER USING ({column}={tenant}); END IF; END $$""")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_due_learning_events(p_limit integer)
    RETURNS TABLE(id uuid,tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path={s},pg_temp AS $$
    BEGIN
      WITH stale AS (SELECT o.id FROM {outbox} o WHERE o.status='dispatching'
        AND o.claimed_at<clock_timestamp()-interval '10 minutes'
        ORDER BY o.claimed_at,o.id LIMIT 100 FOR UPDATE SKIP LOCKED)
      UPDATE {outbox} o SET status='uncertain',reason='delivery_uncertain' FROM stale WHERE stale.id=o.id;
      RETURN QUERY SELECT o.id,o.tenant_id FROM {outbox} o
        JOIN {routes} r ON r.tenant_id=o.tenant_id AND r.enabled
      WHERE o.status='queued' AND o.due_to_send_at<=clock_timestamp()
      ORDER BY o.due_to_send_at,o.id LIMIT greatest(1,least(coalesce(p_limit,20),50));
    END $$""")
    restrict("FUNCTION", f"{s}.telegram_due_learning_events(integer)", "lms_recovery")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_claim_learning_event(p_tenant uuid,p_id uuid)
    RETURNS TABLE(chat_id bigint,workspace text,origin text,title text,target_type text,target_id uuid,
                  deadline timestamptz,step text,language text)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path={s},pg_temp AS $$
    DECLARE event {outbox}%ROWTYPE; target record; destination record; failure text; send_at timestamptz;
    BEGIN
      IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM {tenant} THEN RETURN; END IF;
      SELECT o.* INTO event FROM {outbox} o
      WHERE o.tenant_id=p_tenant AND o.id=p_id AND o.status='queued'
        AND o.due_to_send_at<=clock_timestamp() FOR UPDATE SKIP LOCKED;
      IF NOT FOUND THEN RETURN; END IF;
      SELECT x.* INTO target FROM {s}.telegram_learning_target(p_tenant,event.source,event.source_id) x;
      IF NOT FOUND THEN
        failure := 'ineligible';
      ELSE
        SELECT b.chat_id,b.connected_at,r.workspace_label,r.public_origin,r.overdue_enabled,
               coalesce(ts.default_language,'ru') AS language INTO destination
        FROM {routes} r JOIN {s}.tenants t ON t.id=r.tenant_id
        JOIN {s}.users u ON u.id=target.user_id AND u.tenant_id=r.tenant_id
        LEFT JOIN {links} b ON b.tenant_id=r.tenant_id AND b.user_id=u.id
        LEFT JOIN {s}.tenant_settings ts ON ts.tenant_id=r.tenant_id
        WHERE r.tenant_id=p_tenant AND r.enabled AND t.status='active' AND u.is_active AND u.status='active';
        send_at := CASE event.step WHEN 'before_due' THEN target.reminder_scheduled_at
          WHEN 'overdue' THEN target.deadline ELSE event.due_to_send_at END;
        IF NOT FOUND OR send_at IS NULL OR (event.step='overdue' AND NOT destination.overdue_enabled) THEN
          failure := 'ineligible';
        ELSIF send_at>clock_timestamp() THEN
          UPDATE {outbox} SET due_to_send_at=send_at WHERE tenant_id=p_tenant AND id=p_id;
          RETURN;
        ELSIF (event.step='before_due' AND target.deadline<=clock_timestamp())
          OR send_at<clock_timestamp()-interval '1 day' THEN
          failure := 'expired';
        ELSIF destination.chat_id IS NULL OR destination.connected_at>send_at THEN
          failure := 'not_connected';
        END IF;
      END IF;
      IF failure IS NOT NULL THEN
        UPDATE {outbox} SET status='skipped',reason=failure WHERE tenant_id=p_tenant AND id=p_id;
        RETURN;
      END IF;
      UPDATE {outbox} SET status='dispatching',claimed_at=clock_timestamp() WHERE tenant_id=p_tenant AND id=p_id;
      RETURN QUERY SELECT destination.chat_id,destination.workspace_label,destination.public_origin,target.title,
        target.target_type,target.target_id,target.deadline,event.step,destination.language::text;
    END $$""")
    restrict("FUNCTION", f"{s}.telegram_claim_learning_event(uuid,uuid)", "lms_app")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_finish_learning_event(p_tenant uuid,p_id uuid,p_status text,p_message bigint)
    RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path={s},pg_temp AS $$
    BEGIN
      IF p_tenant IS NULL OR p_tenant IS DISTINCT FROM {tenant} OR p_status IS NULL
        OR p_status NOT IN ('sent','failed','uncertain') OR
         ((p_status='sent') IS DISTINCT FROM (p_message IS NOT NULL AND p_message>0)) THEN RETURN false; END IF;
      UPDATE {outbox} SET status=p_status,message_id=p_message,
        sent_at=CASE WHEN p_status='sent' THEN clock_timestamp() END,
        reason=CASE p_status WHEN 'failed' THEN 'provider_rejected' WHEN 'uncertain' THEN 'delivery_uncertain' END
      WHERE tenant_id=p_tenant AND id=p_id AND status='dispatching';
      RETURN FOUND;
    END $$""")
    restrict("FUNCTION", f"{s}.telegram_finish_learning_event(uuid,uuid,text,bigint)", "lms_app")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_learning_delivery_statuses(p_tenant uuid,p_source text,p_id uuid)
    RETURNS TABLE(id uuid,step text,status text,reason text,scheduled_at timestamptz,sent_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path={s},pg_temp AS $$
      SELECT o.id,o.step,o.status,o.reason,o.due_to_send_at,o.sent_at FROM {outbox} o
      WHERE p_tenant={tenant} AND o.tenant_id=p_tenant AND (
          (p_source<>'rule' AND o.source=p_source AND o.source_id=p_id)
          OR (p_source='rule' AND o.source='reminder' AND EXISTS (
            SELECT 1 FROM {s}.learning_reminder_outbox m
            WHERE m.tenant_id=p_tenant AND m.id=o.source_id AND m.rule_id=p_id)))
        AND EXISTS (SELECT 1 FROM {s}.users u WHERE u.tenant_id=p_tenant AND u.id={actor}
          AND u.is_active AND u.status='active')
      ORDER BY o.due_to_send_at DESC,o.id LIMIT 50
    $$""")
    restrict("FUNCTION", f"{s}.telegram_learning_delivery_statuses(uuid,text,uuid)", "lms_app")

    op.execute(f"""
    CREATE FUNCTION {s}.telegram_learner_is_connected(p_tenant uuid,p_user uuid)
    RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path={s},pg_temp AS $$
      SELECT EXISTS (
        SELECT 1 FROM {links} b JOIN {routes} r ON r.tenant_id=b.tenant_id AND r.enabled
        WHERE p_tenant={tenant} AND b.tenant_id=p_tenant AND b.user_id=p_user AND b.chat_id IS NOT NULL
      )
    $$""")
    restrict("FUNCTION", f"{s}.telegram_learner_is_connected(uuid,uuid)", "lms_app")


def downgrade() -> None:
    s = schema_name()
    for table in TRIGGERS:
        op.execute(f"DROP TRIGGER telegram_project_learning_event ON {s}.{table}")
    for name in (
        "telegram_learning_delivery_statuses(uuid,text,uuid)",
        "telegram_learner_is_connected(uuid,uuid)",
        "telegram_finish_learning_event(uuid,uuid,text,bigint)",
        "telegram_claim_learning_event(uuid,uuid)",
        "telegram_due_learning_events(integer)",
        "telegram_learning_target(uuid,text,uuid)",
        "telegram_bound_learning_workspaces(bigint)",
        "telegram_toggle_learning_workspace(bigint,uuid)",
        "telegram_accept_learning_start(text,bigint,text)",
        "telegram_project_learning_event()",
    ):
        op.execute(f"DROP FUNCTION {s}.{name}")
    for table in ("users", "tenants", "courses", "enrollments", "recurring_learning_assignments",
                  "recurring_learning_rules", "learning_path_assignments", "learning_paths",
                  "learning_path_cycle_instances", "knowledge_checks", "knowledge_check_assignments",
                  "knowledge_check_attempts", "learning_reminder_outbox", "tenant_settings"):
        op.execute(f"DROP POLICY IF EXISTS telegram_reminder_source_owner ON {s}.{table}")
    for table in ("telegram_reminder_outbox", "telegram_reminder_subscriptions", "telegram_reminder_workspaces"):
        op.execute(f"DROP TABLE {s}.{table}")
