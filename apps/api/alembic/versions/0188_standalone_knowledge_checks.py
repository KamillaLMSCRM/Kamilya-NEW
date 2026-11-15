"""Add standalone employee knowledge checks without changing course quizzes.

Revision ID: 0188
Revises: 0187
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0188"
down_revision = "0187"
branch_labels = depends_on = None
TABLES = ("knowledge_checks", "knowledge_check_assignments", "knowledge_check_attempts")


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe knowledge checks schema")
    return schema


def upgrade() -> None:
    schema = _schema()

    def common():
        return [
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey(f"{schema}.tenants.id", ondelete="RESTRICT"), nullable=False),
        ]

    op.create_table(
        TABLES[0], *common(),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("create_sha256", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey(f"{schema}.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_checks_tenant_id"),
        sa.CheckConstraint("revision > 0 AND status IN ('draft','published')", name="ck_knowledge_checks_state"),
        sa.CheckConstraint("jsonb_typeof(content)='object' AND length(create_sha256)=64", name="ck_knowledge_checks_content"),
        schema=schema,
    )
    op.create_table(
        TABLES[1], *common(),
        sa.Column("check_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey(f"{schema}.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_by", UUID(as_uuid=True), sa.ForeignKey(f"{schema}.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id", "check_id"], [f"{schema}.knowledge_checks.tenant_id", f"{schema}.knowledge_checks.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_assignment_tenant_id"),
        sa.UniqueConstraint("check_id", "revision", "user_id", name="uq_knowledge_assignment_revision_user"),
        sa.CheckConstraint("revision > 0 AND length(snapshot_sha256)=64 AND jsonb_typeof(snapshot)='object'", name="ck_knowledge_assignment_snapshot"),
        schema=schema,
    )
    op.create_table(
        TABLES[2], *common(),
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("answers", JSONB, nullable=False, server_default="[]"),
        sa.Column("submission_sha256", sa.String(64)),
        sa.Column("status", sa.Text, nullable=False, server_default="started"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("score_percent", sa.Integer),
        sa.Column("passed", sa.Boolean),
        sa.Column("earned_points", sa.Integer),
        sa.Column("total_points", sa.Integer),
        sa.ForeignKeyConstraint(["tenant_id", "assignment_id"], [f"{schema}.knowledge_check_assignments.tenant_id", f"{schema}.knowledge_check_assignments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assignment_id", "number", name="uq_knowledge_attempt_number"),
        sa.CheckConstraint("number>0 AND length(snapshot_sha256)=64", name="ck_knowledge_attempt_identity"),
        sa.CheckConstraint("status IN ('started','submitted','expired')", name="ck_knowledge_attempt_status"),
        sa.CheckConstraint("(status='started' AND completed_at IS NULL AND score_percent IS NULL AND passed IS NULL AND earned_points IS NULL AND total_points IS NULL AND submission_sha256 IS NULL) OR (status IN ('submitted','expired') AND completed_at IS NOT NULL AND score_percent IS NOT NULL AND score_percent BETWEEN 0 AND 100 AND passed IS NOT NULL AND earned_points IS NOT NULL AND total_points IS NOT NULL AND earned_points>=0 AND total_points>0 AND earned_points<=total_points AND submission_sha256 IS NOT NULL AND length(submission_sha256)=64)", name="ck_knowledge_attempt_result"),
        schema=schema,
    )
    op.create_index("ix_knowledge_checks_tenant_created", TABLES[0], ["tenant_id", "created_at"], schema=schema)
    op.create_index("ix_knowledge_assignment_user", TABLES[1], ["tenant_id", "user_id", "created_at"], schema=schema)
    op.create_index("ix_knowledge_assignment_check", TABLES[1], ["tenant_id", "check_id", "created_at"], schema=schema)
    op.create_index("ix_knowledge_attempt_assignment", TABLES[2], ["tenant_id", "assignment_id"], schema=schema)
    op.create_index("uq_knowledge_active_attempt", TABLES[2], ["assignment_id"], unique=True, postgresql_where=sa.text("status='started'"), schema=schema)

    op.execute(f'''CREATE FUNCTION "{schema}".knowledge_check_integrity() RETURNS trigger
        LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
        DECLARE actor uuid; parent_snapshot jsonb; parent_hash text;
        BEGIN
          IF TG_TABLE_NAME='knowledge_checks' THEN
            actor:=NEW.created_by;
            IF TG_OP='UPDATE' AND (NEW.id,NEW.tenant_id,NEW.created_by,NEW.created_at,NEW.create_sha256)
              IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.created_by,OLD.created_at,OLD.create_sha256) THEN
              RAISE EXCEPTION 'knowledge_check_identity_immutable' USING ERRCODE='check_violation';
            END IF;
          ELSIF TG_TABLE_NAME='knowledge_check_assignments' THEN
            IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'knowledge_assignment_immutable' USING ERRCODE='check_violation'; END IF;
            IF NOT EXISTS(SELECT 1 FROM "{schema}".knowledge_checks WHERE id=NEW.check_id AND tenant_id=NEW.tenant_id AND revision=NEW.revision AND status='published' AND content=NEW.snapshot) THEN
              RAISE EXCEPTION 'knowledge_assignment_revision_mismatch' USING ERRCODE='check_violation';
            END IF;
            IF NOT EXISTS(SELECT 1 FROM "{schema}".users WHERE id=NEW.user_id AND tenant_id=NEW.tenant_id AND role='student' AND is_active AND status='active') THEN
              RAISE EXCEPTION 'knowledge_employee_tenant_mismatch' USING ERRCODE='foreign_key_violation';
            END IF;
            actor:=NEW.assigned_by;
          ELSE
            IF TG_OP='UPDATE' AND (OLD.status<>'started' OR
              (NEW.id,NEW.tenant_id,NEW.assignment_id,NEW.number,NEW.snapshot,NEW.snapshot_sha256,NEW.started_at,NEW.deadline_at)
              IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.assignment_id,OLD.number,OLD.snapshot,OLD.snapshot_sha256,OLD.started_at,OLD.deadline_at)) THEN
              RAISE EXCEPTION 'knowledge_attempt_immutable' USING ERRCODE='check_violation';
            END IF;
            IF TG_OP='INSERT' THEN
              SELECT snapshot,snapshot_sha256 INTO parent_snapshot,parent_hash FROM "{schema}".knowledge_check_assignments
                WHERE id=NEW.assignment_id AND tenant_id=NEW.tenant_id;
              IF NEW.snapshot IS DISTINCT FROM parent_snapshot OR NEW.snapshot_sha256 IS DISTINCT FROM parent_hash THEN
                RAISE EXCEPTION 'knowledge_attempt_snapshot_mismatch' USING ERRCODE='check_violation';
              END IF;
            END IF;
          END IF;
          IF actor IS NOT NULL AND NOT EXISTS(SELECT 1 FROM "{schema}".users WHERE id=actor AND tenant_id=NEW.tenant_id) THEN
            IF NOT "{schema}".course_approval_platform_actor_bound(actor,NEW.tenant_id) THEN
              RAISE EXCEPTION 'knowledge_actor_tenant_mismatch' USING ERRCODE='foreign_key_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$''')
    tenant = "tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid"
    for table in TABLES:
        target = f'"{schema}"."{table}"'
        op.execute(f"ALTER TABLE {target} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_read ON {target} FOR SELECT TO lms_app USING ({tenant})")
        op.execute(f"CREATE POLICY {table}_insert ON {target} FOR INSERT TO lms_app WITH CHECK ({tenant})")
        op.execute(f"CREATE POLICY {table}_update ON {target} FOR UPDATE TO lms_app USING ({tenant}) WITH CHECK ({tenant})")
        op.execute(f"CREATE POLICY {table}_purge ON {target} FOR DELETE TO lms_app USING ({tenant} AND COALESCE(current_setting('app.is_superadmin',true),'false')='true')")
        op.execute(f"CREATE TRIGGER {table}_integrity BEFORE INSERT OR UPDATE ON {target} FOR EACH ROW EXECUTE FUNCTION \"{schema}\".knowledge_check_integrity()")
        op.execute(f"REVOKE ALL ON {target} FROM PUBLIC,lms_app")
        for role in ("anon", "authenticated", "service_role", "lms_recovery"):
            op.execute(f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN EXECUTE 'REVOKE ALL ON {target} FROM {role}'; END IF; END $$")
        op.execute(f"GRANT SELECT,INSERT,DELETE ON {target} TO lms_app")
    op.execute(f'GRANT UPDATE(content,revision,status,updated_at) ON "{schema}".knowledge_checks TO lms_app')
    # Row locking requires UPDATE privilege; immutable trigger rejects any write.
    op.execute(f'GRANT UPDATE(id) ON "{schema}".knowledge_check_assignments TO lms_app')
    op.execute(f'GRANT UPDATE(answers,submission_sha256,status,completed_at,score_percent,passed,earned_points,total_points) ON "{schema}".knowledge_check_attempts TO lms_app')


def downgrade() -> None:
    schema = _schema()
    targets = [f'"{schema}"."{table}"' for table in TABLES]
    # Match the existing owner-maintenance pattern: a non-BYPASS migration owner
    # must not mistake FORCE-RLS-hidden evidence for empty tables (MIGRATION-007).
    op.execute("SET LOCAL lock_timeout='5s'")
    op.execute("LOCK TABLE " + ",".join(targets) + " IN ACCESS EXCLUSIVE MODE")
    for target in targets:
        op.execute(f"ALTER TABLE {target} NO FORCE ROW LEVEL SECURITY")
    try:
        for target in targets:
            if op.get_bind().execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM {target})")).scalar():
                raise RuntimeError("Knowledge check downgrade requires empty tables; preserve assignments/results")
    finally:
        for target in targets:
            op.execute(f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY")
    for table in reversed(TABLES):
        op.drop_table(table, schema=schema)
    op.execute(f'DROP FUNCTION "{schema}".knowledge_check_integrity()')
