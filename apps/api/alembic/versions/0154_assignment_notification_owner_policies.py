"""Restore non-bypass assignment outbox operations and nullable system actors.

Revision ID: 0154
Revises: 0153
"""

import re

from alembic import op

revision = "0154"
down_revision = "0153"
branch_labels = None
depends_on = None

TENANT = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
COURSE_DUE = "((status IN ('pending','retry') AND (next_attempt_at IS NULL OR next_attempt_at<=now())) OR (status='claimed' AND claimed_at<=now()-interval '2 minutes'))"
PATH_DUE = "((status IN ('pending','retry') AND next_attempt_at<=now()) OR (status='processing' AND claimed_at<now()-interval '10 minutes'))"
POLICIES = (
    (
        "course_assignment_notification_outbox",
        "course_notification_owner_select",
        "SELECT",
        f"({TENANT}) OR {COURSE_DUE}",
    ),
    ("course_assignment_notification_outbox", "course_notification_owner_insert", "INSERT", TENANT),
    ("course_assignment_notification_outbox", "course_notification_owner_update", "UPDATE", TENANT),
    ("learning_path_assignment_notification_outbox", "path_notification_owner_due", "SELECT", PATH_DUE),
)
ACTOR_OLD = "IF NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN"
ACTOR_NEW = "IF p_assigned_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN"


def _schema():
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe assignment policy schema")
    return schema


def _actor_guard(schema, old, new):
    op.execute(f"""
    DO $fix$ DECLARE definition text; BEGIN
      SELECT pg_get_functiondef('"{schema}".enqueue_course_assignment_notification(uuid,uuid,uuid)'::regprocedure) INTO definition;
      IF strpos(definition,$old${old}$old$)=0 THEN
        RAISE EXCEPTION 'Assignment actor guard drift';
      END IF;
      EXECUTE replace(definition,$old${old}$old$,$new${new}$new$);
    END $fix$;
    """)


def upgrade():
    schema = _schema()
    # Grant only owner policy coverage, never table privileges to application
    # or recovery callers. Existing bounded function grants remain authoritative.
    for table, policy, command, predicate in POLICIES:
        stem = "course" if table.startswith("course_") else "learning_path"
        check = f"WITH CHECK ({TENANT})" if command in ("INSERT", "UPDATE") else ""
        using = "" if command == "INSERT" else f"USING ({predicate})"
        op.execute(f"""
        DO $policy$ DECLARE owner_id oid; owner_name name; BEGIN
          SELECT proowner,pg_get_userbyid(proowner) INTO owner_id,owner_name FROM pg_proc
            WHERE oid='"{schema}".enqueue_{stem}_assignment_notification(uuid,uuid,uuid)'::regprocedure AND prosecdef;
          IF owner_id IS NULL OR owner_name IN ('lms_app','lms_recovery','anon','authenticated','service_role')
             OR pg_has_role('lms_app',owner_id,'MEMBER') OR pg_has_role('lms_recovery',owner_id,'MEMBER') THEN
            RAISE EXCEPTION 'Unsafe assignment function owner';
          END IF;
          IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='{schema}' AND p.proname IN
             ('claim_{stem}_assignment_notification','finalize_{stem}_assignment_notification',
              'due_{stem}_assignment_notifications') AND (p.proowner<>owner_id OR NOT p.prosecdef)) THEN
            RAISE EXCEPTION 'Assignment function ownership drift';
          END IF;
          EXECUTE format($ddl$CREATE POLICY {policy} ON "{schema}".{table} FOR {command} TO %I {using} {check}$ddl$,owner_name);
        END $policy$;
        """)
    # Recurring rules created through audited platform impersonation have no
    # tenant-local actor. The FK is already nullable; reject foreign non-null
    # actors exactly as before, while allowing this legitimate system actor.
    _actor_guard(schema, ACTOR_OLD, ACTOR_NEW)


def downgrade():
    schema = _schema()
    _actor_guard(schema, ACTOR_NEW, ACTOR_OLD)
    for table, policy, _, _ in reversed(POLICIES):
        op.execute(f'DROP POLICY IF EXISTS {policy} ON "{schema}".{table}')
