"""Allow bounded recurring discovery and tenant-bound reminder owner reads.

Revision ID: 0153
Revises: 0152

Production uses a non-bypass migration/function owner. FORCE RLS applies to
that owner too; policies granted only to lms_app silently hide its input rows.
No role, grant, function body, existing policy or row is changed here.
"""

import re

from alembic import op

revision = "0153"
down_revision = "0152"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"
POLICIES = (
    (
        "recurring_learning_rules",
        "recurring_due_function_owner",
        "due_recurring_learning_rules(integer)",
        "status='active' AND next_run_at<=now()",
    ),
    ("recurring_learning_rules", "reminder_rule_function_owner", "enqueue_learning_reminder(uuid,uuid,uuid)", TENANT),
    (
        "recurring_learning_assignments",
        "reminder_occurrence_function_owner",
        "enqueue_learning_reminder(uuid,uuid,uuid)",
        TENANT,
    ),
    (
        "learning_path_cycle_instances",
        "reminder_cycle_function_owner",
        "enqueue_learning_reminder(uuid,uuid,uuid)",
        TENANT,
    ),
    (
        "learning_path_assignments",
        "reminder_assignment_function_owner",
        "enqueue_learning_reminder(uuid,uuid,uuid)",
        TENANT,
    ),
)


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe learning owner policy schema")
    return schema


def upgrade() -> None:
    schema = _schema()
    # All reminder functions execute as the same owner in the deployed contract.
    # Refuse unexpected ownership drift instead of granting another role access.
    op.execute(f"""
    DO $$ DECLARE owners integer; BEGIN
      SELECT count(DISTINCT proowner) INTO owners FROM pg_proc p
      JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='{schema}' AND p.proname IN
        ('enqueue_learning_reminder','claim_learning_reminder','learning_reminder_payload',
         'begin_learning_reminder_send','finalize_learning_reminder','_learning_reminder_targets');
      IF owners<>1 THEN RAISE EXCEPTION 'Reminder function owner mismatch'; END IF;
    END $$;
    """)
    for table, policy, signature, predicate in POLICIES:
        op.execute(f"""
        DO $$ DECLARE owner_name name; owner_id oid; definer boolean; BEGIN
          SELECT proowner,pg_get_userbyid(proowner),prosecdef
            INTO owner_id,owner_name,definer FROM pg_proc
            WHERE oid='"{schema}".{signature}'::regprocedure;
          IF owner_name IS NULL OR NOT definer THEN
            RAISE EXCEPTION 'Bounded function owner unavailable';
          END IF;
          IF owner_name IN ('lms_app','lms_recovery','anon','authenticated','service_role')
             OR pg_has_role('lms_app',owner_id,'MEMBER')
             OR pg_has_role('lms_recovery',owner_id,'MEMBER') THEN
            RAISE EXCEPTION 'Runtime role cannot own bounded learning functions';
          END IF;
          EXECUTE format('CREATE POLICY {policy} ON "{schema}".{table} '
            'FOR SELECT TO %I USING (%s)',owner_name,$predicate${predicate}$predicate$);
        END $$;
        """)


def downgrade() -> None:
    schema = _schema()
    for table, policy, _, _ in reversed(POLICIES):
        op.execute(f'DROP POLICY IF EXISTS {policy} ON "{schema}".{table}')
