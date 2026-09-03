"""Harden notification ownership, content, and delivery recovery.

Revision ID: 0151
Revises: 0150
"""

from alembic import op

revision = "0151"
down_revision = "0150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_notification_inbox_safe_context",
        "notification_inbox",
        "jsonb_typeof(context) = 'object' "
        "AND context ? 'course_title' "
        "AND jsonb_typeof(context->'course_title') = 'string' "
        "AND length(context->>'course_title') BETWEEN 1 AND 500 "
        "AND context ? 'due_at' "
        "AND (context->'due_at' = 'null'::jsonb OR jsonb_typeof(context->'due_at') = 'string') "
        "AND context - ARRAY['course_title','due_at']::text[] = '{}'::jsonb",
    )
    op.create_check_constraint(
        "ck_notification_inbox_safe_action",
        "notification_inbox",
        r"action_path ~ '^(/course-review-requests/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|/admin/course-approvals\?courseId=[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$'",
    )
    op.execute("DROP POLICY IF EXISTS notification_inbox_tenant_policy ON notification_inbox")
    op.execute(
        """
        CREATE POLICY notification_inbox_select ON notification_inbox
        FOR SELECT TO lms_app
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND recipient_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY notification_inbox_insert ON notification_inbox
        FOR INSERT TO lms_app
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY notification_inbox_update ON notification_inbox
        FOR UPDATE TO lms_app
        USING (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND recipient_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            AND recipient_user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION due_course_approval_deliveries(batch_limit integer)
        RETURNS TABLE(tenant_id uuid, id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT d.tenant_id, d.id
          FROM workflow_deliveries d
          WHERE (
              d.status IN ('queued','failed')
              AND d.attempt_count < 8
              AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= now())
            ) OR (
              d.status = 'accepted'
              AND d.next_attempt_at IS NOT NULL
              AND d.next_attempt_at <= now()
            )
          ORDER BY d.created_at
          LIMIT LEAST(GREATEST(batch_limit, 1), 100)
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION due_course_approval_deliveries(batch_limit integer)
        RETURNS TABLE(tenant_id uuid, id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT d.tenant_id, d.id
          FROM workflow_deliveries d
          WHERE d.status IN ('queued','failed')
            AND d.attempt_count < 8
            AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= now())
          ORDER BY d.created_at
          LIMIT LEAST(GREATEST(batch_limit, 1), 100)
        $$
        """
    )
    op.execute("DROP POLICY notification_inbox_update ON notification_inbox")
    op.execute("DROP POLICY notification_inbox_insert ON notification_inbox")
    op.execute("DROP POLICY notification_inbox_select ON notification_inbox")
    op.execute(
        """
        CREATE POLICY notification_inbox_tenant_policy ON notification_inbox FOR ALL TO lms_app
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.drop_constraint("ck_notification_inbox_safe_action", "notification_inbox", type_="check")
    op.drop_constraint("ck_notification_inbox_safe_context", "notification_inbox", type_="check")
