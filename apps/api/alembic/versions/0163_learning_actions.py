"""Occurrence-bound methodologist actions and immutable action events.

Revision ID: 0163
Revises: 0162
"""

import re

from alembic import op

revision = "0163"
down_revision = "0162"
branch_labels = None
depends_on = None


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe learning-actions schema")
    return f'"{schema}"'


def upgrade() -> None:
    schema = _schema()
    actions = f"{schema}.learning_actions"
    events = f"{schema}.learning_action_events"
    op.execute(f"""
        CREATE TABLE {actions} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            target_type varchar(16) NOT NULL CHECK (target_type IN ('enrollment','question')),
            target_key varchar(320) NOT NULL,
            enrollment_id uuid,
            course_id uuid NOT NULL,
            quiz_id uuid,
            content_release_id uuid,
            question_id uuid,
            question_key varchar(64),
            issue_type varchar(32) NOT NULL CHECK
                (issue_type IN ('not_started','stalled','overdue','failed_required_quiz','weak_question')),
            action_type varchar(32) NOT NULL CHECK
                (action_type IN ('reminder','reassignment','supplemental_material','manual_review')),
            owner_id uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            created_by uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            due_at timestamptz,
            comment text CHECK (comment IS NULL OR length(comment) <= 4000),
            baseline_snapshot jsonb NOT NULL,
            outcome_snapshot jsonb,
            status varchar(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open','completed','cancelled')),
            resolution varchar(16) CHECK (resolution IS NULL OR resolution IN ('observed','manual','cancelled')),
            resolution_note text CHECK (resolution_note IS NULL OR length(resolution_note) <= 4000),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            closed_at timestamptz,
            CONSTRAINT ck_learning_action_target_identity CHECK (
                (target_type = 'enrollment' AND enrollment_id IS NOT NULL AND quiz_id IS NULL
                    AND content_release_id IS NULL AND question_id IS NULL AND question_key IS NULL
                    AND issue_type <> 'weak_question') OR
                (target_type = 'question' AND enrollment_id IS NULL AND quiz_id IS NOT NULL
                    AND question_id IS NOT NULL AND question_key ~ '^[0-9a-f]{{64}}$'
                    AND issue_type = 'weak_question')
            ),
            CONSTRAINT ck_learning_action_closure_state CHECK (
                (status = 'open' AND resolution IS NULL AND closed_at IS NULL AND outcome_snapshot IS NULL)
                OR (status <> 'open' AND resolution IS NOT NULL AND closed_at IS NOT NULL
                    AND outcome_snapshot IS NOT NULL)
            ),
            CONSTRAINT uq_learning_action_tenant_id UNIQUE (tenant_id,id)
        )
    """)
    op.execute(f"""
        CREATE UNIQUE INDEX uq_learning_action_active_target_issue_action
            ON {actions} (tenant_id,target_key,issue_type,action_type) WHERE status = 'open'
    """)
    op.execute(f"CREATE INDEX ix_learning_action_tenant_status_created ON {actions}(tenant_id,status,created_at DESC)")
    op.execute(f"ALTER TABLE {actions} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {actions} FORCE ROW LEVEL SECURITY")
    tenant = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"
    ownership = f"""EXISTS (SELECT 1 FROM {schema}.courses c
            WHERE c.id=learning_actions.course_id AND c.tenant_id=learning_actions.tenant_id)
        AND (learning_actions.target_type <> 'enrollment' OR EXISTS (
            SELECT 1 FROM {schema}.enrollments e WHERE e.id=learning_actions.enrollment_id
              AND e.tenant_id=learning_actions.tenant_id AND e.course_id=learning_actions.course_id))
        AND (learning_actions.owner_id IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=learning_actions.owner_id
              AND u.tenant_id=learning_actions.tenant_id))
        AND (learning_actions.created_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=learning_actions.created_by
              AND u.tenant_id=learning_actions.tenant_id))"""
    op.execute(f"CREATE POLICY learning_actions_tenant ON {actions} USING ({tenant}) WITH CHECK ({tenant} AND {ownership})")
    op.execute(f"REVOKE ALL ON {actions} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {actions} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT SELECT, INSERT ON {actions} TO lms_app")
    op.execute(f"GRANT UPDATE (status,resolution,resolution_note,outcome_snapshot,updated_at,closed_at) ON {actions} TO lms_app")

    op.execute(f"""
        CREATE TABLE {events} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES {schema}.tenants(id) ON DELETE CASCADE,
            action_id uuid NOT NULL REFERENCES {schema}.learning_actions(id) ON DELETE CASCADE,
            event_type varchar(16) NOT NULL CHECK (event_type IN ('created','closed')),
            actor_id uuid REFERENCES {schema}.users(id) ON DELETE SET NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_learning_action_event_transition UNIQUE (tenant_id,action_id,event_type)
        )
    """)
    op.execute(f"CREATE INDEX ix_learning_action_event_tenant_created ON {events}(tenant_id,created_at DESC)")
    op.execute(f"ALTER TABLE {events} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {events} FORCE ROW LEVEL SECURITY")
    event_action_ownership = f"""EXISTS (SELECT 1 FROM {schema}.learning_actions a
            WHERE a.id=learning_action_events.action_id AND a.tenant_id=learning_action_events.tenant_id)"""
    event_actor_ownership = f"""(learning_action_events.actor_id IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=learning_action_events.actor_id
              AND u.tenant_id=learning_action_events.tenant_id))"""
    op.execute(f"""
        CREATE POLICY learning_action_events_tenant ON {events}
        USING ({tenant} AND {event_action_ownership})
        WITH CHECK ({tenant} AND {event_action_ownership} AND {event_actor_ownership})
    """)
    op.execute(f"REVOKE ALL ON {events} FROM PUBLIC, lms_app")
    for role in ("anon", "authenticated", "service_role", "lms_recovery"):
        op.execute(f"""DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN
            EXECUTE 'REVOKE ALL ON {events} FROM {role}'; END IF; END $$""")
    op.execute(f"GRANT SELECT, INSERT ON {events} TO lms_app")


def downgrade() -> None:
    schema = _schema()
    op.execute(f"DROP TABLE {schema}.learning_action_events")
    op.execute(f"DROP TABLE {schema}.learning_actions")
