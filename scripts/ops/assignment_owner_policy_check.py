"""Transactional non-bypass owner-policy contract for assignment outboxes.

The caller owns the surrounding transaction, synthetic schema, temporary roles,
and cleanup.  This sidecar only adds objects in that schema and executes the
actual 0097/0146 SQL functions against minimal fixture tables.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

_SCHEMA_RE = re.compile(r"r2_reminder_[0-9a-f]{32}")
_FUNCTIONS = (
    (
        "0097_course_assignment_notification_outbox.py",
        (
            "enqueue_course_assignment_notification",
            "claim_course_assignment_notification",
            "finalize_course_assignment_notification",
            "due_course_assignment_notifications",
            "course_assignment_notification_statuses",
            "requeue_course_assignment_notification",
        ),
    ),
    (
        "0146_learning_path_assignment_notification_outbox.py",
        (
            "enqueue_learning_path_assignment_notification",
            "claim_learning_path_assignment_notification",
            "finalize_learning_path_assignment_notification",
            "due_learning_path_assignment_notifications",
        ),
    ),
)


def _extract_function_sql(source: Path, schema: str, name: str) -> str:
    """Extract and schema-qualify one migration CREATE FUNCTION statement."""

    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    candidates = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.search(
            rf"\bCREATE(?: OR REPLACE)? FUNCTION\s+{re.escape(name)}\s*\(",
            node.value,
            flags=re.IGNORECASE,
        )
    ]
    assert len(candidates) == 1, f"expected_one_function_sql:{name}"
    statement = candidates[0]
    statement = re.sub(
        r"(?i)(CREATE(?: OR REPLACE)? FUNCTION\s+)" + re.escape(name) + r"(?=\s*\()",
        lambda match: f'{match.group(1)}"{schema}".{name}',
        statement,
        count=1,
    )
    statement = re.sub(
        r"(?i)search_path\s*=\s*public\s*,\s*pg_temp",
        f'search_path = "{schema}", pg_temp',
        statement,
    )
    return statement


async def check_assignment_policy(
    conn,
    schema: str,
    *,
    owner: str,
    caller: str,
    t: str,
    other: str,
    u: str,
    c: str,
    e: str,
    assignment: str,
    apply_fix: bool = True,
) -> list[str]:
    """Run the 0154 owner-policy contract inside the root helper's transaction."""

    from learning_reminder_dev_check import ROOT, SqlCollector

    assert _SCHEMA_RE.fullmatch(schema)
    assert owner == schema.replace("r2_reminder_", "r2_owner_")
    assert caller == schema.replace("r2_reminder_", "r2_caller_")
    q = f'"{schema}"'
    course_table = f"{schema}.course_assignment_notification_outbox"
    path_table = f"{schema}.learning_path_assignment_notification_outbox"

    async def sql(statement: str, params=None):
        return await conn.execute(text(statement), params or {})

    async def actor(statement: str, params=None, *, tenant: str | None = None, role: str = "lms_app", mode="raw"):
        """Run as the production caller or bounded owner, restoring local state."""

        assert role in ("lms_app", "lms_recovery", "owner", "caller")
        role_name = {"lms_app": caller, "caller": caller, "owner": owner}.get(role)
        async with conn.begin_nested():
            try:
                # The migration login cannot SET ROLE lms_recovery on Supabase.
                # Its EXECUTE ACL is checked independently; the SECURITY
                # DEFINER function still executes as the temporary owner.
                if role_name is not None:
                    await sql(f'SET LOCAL ROLE "{role_name}"')
                await sql(
                    "SELECT set_config('app.tenant_id',:tenant_id,true)",
                    {"tenant_id": tenant or ""},
                )
                result = await sql(statement, params)
                if mode == "scalar":
                    value = result.scalar()
                elif mode == "all":
                    value = result.all()
                elif mode == "mappings":
                    value = result.mappings().all()
                else:
                    value = result
                await sql("RESET ROLE")
                await sql("SELECT set_config('app.tenant_id','',true)")
                return value
            except Exception:
                # Savepoint rollback restores SET LOCAL ROLE and tenant
                # context. Do not issue SQL inside the aborted savepoint.
                raise

    async def denied(statement: str, params=None, *, tenant: str | None = None, role: str = "lms_app"):
        try:
            await actor(statement, params, tenant=tenant, role=role)
        except Exception as exc:
            original = getattr(exc, "orig", exc)
            sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
            assert sqlstate in {"42501", "P0001"}, f"unexpected_denial:{sqlstate}"
        else:
            raise AssertionError("authorization_must_reject")

    args = {"t": t, "other": other, "u": u, "c": c, "e": e, "a": assignment}

    # Root fixtures were inserted before this sidecar runs. The legacy course
    # function requires source, whose deployed default is recurring.
    await sql(f"ALTER TABLE {q}.enrollments ADD COLUMN source text NOT NULL DEFAULT 'recurring'")

    # These are the deployed 0097/0146 columns and defaults, without foreign
    # keys or indexes that are irrelevant to this isolated owner/RLS contract.
    await sql(
        f"""
        CREATE TABLE {q}.course_assignment_notification_outbox (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL,
          enrollment_id uuid NOT NULL UNIQUE,
          assigned_by uuid,
          status text NOT NULL DEFAULT 'pending',
          attempt_count integer NOT NULL DEFAULT 0,
          next_attempt_at timestamptz,
          claimed_at timestamptz,
          claim_token uuid UNIQUE,
          delivered_at timestamptz,
          terminal_at timestamptz,
          delivery_message_id text,
          last_error_category text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_course_assignment_notification_status
            CHECK (status IN ('pending','claimed','retry','delivered','dead')),
          CONSTRAINT ck_course_assignment_notification_attempts
            CHECK (attempt_count >= 0 AND attempt_count <= 3)
        )
        """
    )
    await sql(
        f"""
        CREATE TABLE {q}.learning_path_assignment_notification_outbox (
          id uuid PRIMARY KEY,
          tenant_id uuid NOT NULL,
          learning_path_assignment_id uuid NOT NULL UNIQUE,
          assigned_by uuid,
          status varchar(16) NOT NULL DEFAULT 'pending',
          attempt_count integer NOT NULL DEFAULT 0,
          next_attempt_at timestamptz NOT NULL DEFAULT now(),
          claim_token uuid,
          claimed_at timestamptz,
          delivered_at timestamptz,
          delivery_message_id varchar(255),
          last_error_category varchar(64),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_learning_path_assignment_notification_status
            CHECK (status IN ('pending','processing','retry','sent','dead'))
        )
        """
    )
    for table in ("course_assignment_notification_outbox", "learning_path_assignment_notification_outbox"):
        await sql(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY")
        await sql(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY")
        await sql(f'REVOKE ALL ON TABLE {q}.{table} FROM PUBLIC,lms_app,"{caller}"')
        await sql(f'ALTER TABLE {q}.{table} OWNER TO "{owner}"')

    # This is the deployed 0146 tenant policy: PUBLIC policy, no runtime table
    # grant. It is intentionally present before 0154; course has zero policies.
    await sql(
        f"""
        CREATE POLICY learning_path_assignment_notification_tenant_isolation
        ON {q}.learning_path_assignment_notification_outbox
        USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    assert (
        await sql(
            "SELECT count(*) FROM pg_policies WHERE schemaname=:schema AND tablename='course_assignment_notification_outbox'",
            {"schema": schema},
        )
    ).scalar() == 0
    assert (
        await sql(
            "SELECT count(*) FROM pg_policies WHERE schemaname=:schema AND tablename='learning_path_assignment_notification_outbox' AND policyname='learning_path_assignment_notification_tenant_isolation'",
            {"schema": schema},
        )
    ).scalar() == 1
    assert (
        await sql(
            "SELECT has_table_privilege(:role,:table,'INSERT'), has_table_privilege(:role,:table,'UPDATE')",
            {"role": owner, "table": course_table},
        )
    ).one() == (True, True)

    # The source functions deliberately keep unqualified fixture-table names;
    # the patched SECURITY DEFINER search_path makes them resolve in this schema.
    for filename, names in _FUNCTIONS:
        source = ROOT / "apps/api/alembic/versions" / filename
        for name in names:
            await sql(_extract_function_sql(source, schema, name))

    all_signatures = [
        f'"{schema}".enqueue_course_assignment_notification(uuid,uuid,uuid)',
        f'"{schema}".claim_course_assignment_notification(uuid,uuid)',
        f'"{schema}".finalize_course_assignment_notification(uuid,uuid,uuid,text,text,text)',
        f'"{schema}".due_course_assignment_notifications(integer)',
        f'"{schema}".course_assignment_notification_statuses(uuid,uuid)',
        f'"{schema}".requeue_course_assignment_notification(uuid,uuid)',
        f'"{schema}".enqueue_learning_path_assignment_notification(uuid,uuid,uuid)',
        f'"{schema}".claim_learning_path_assignment_notification(uuid,uuid)',
        f'"{schema}".finalize_learning_path_assignment_notification(uuid,uuid,uuid,text,text,text)',
        f'"{schema}".due_learning_path_assignment_notifications(integer)',
    ]
    due_signatures = {all_signatures[3], all_signatures[9]}
    for signature in all_signatures:
        await sql(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        if signature in due_signatures:
            await sql(f"GRANT EXECUTE ON FUNCTION {signature} TO lms_recovery")
        else:
            # caller is the exact temporary ACL mirror of production lms_app.
            await sql(f'GRANT EXECUTE ON FUNCTION {signature} TO "{caller}"')
        await sql(f'ALTER FUNCTION {signature} OWNER TO "{owner}"')
    assert (
        await sql(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname=:schema AND p.prosecdef AND pg_get_userbyid(p.proowner)=:owner "
            "AND p.proname IN ('enqueue_course_assignment_notification',"
            "'claim_course_assignment_notification','finalize_course_assignment_notification',"
            "'due_course_assignment_notifications','course_assignment_notification_statuses',"
            "'requeue_course_assignment_notification','enqueue_learning_path_assignment_notification',"
            "'claim_learning_path_assignment_notification','finalize_learning_path_assignment_notification',"
            "'due_learning_path_assignment_notifications')",
            {"schema": schema, "owner": owner},
        )
    ).scalar() == len(all_signatures)
    assert (
        await sql(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=:schema AND c.relname IN "
            "('course_assignment_notification_outbox','learning_path_assignment_notification_outbox') "
            "AND pg_get_userbyid(c.relowner)=:owner",
            {"schema": schema, "owner": owner},
        )
    ).scalar() == 2
    assert (
        await sql(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:role",
            {"role": owner},
        )
    ).one() == (False, False)

    # Red seam before 0154: the production non-bypass function owner has table
    # ACLs but no RLS policy, so course enqueue fails. The existing PUBLIC path
    # tenant policy still permits enqueue, while global path due discovery is
    # correctly invisible without the new owner policy.
    await denied(
        f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,:u)",
        args,
        tenant=t,
    )
    path_id = await actor(
        f"SELECT {q}.enqueue_learning_path_assignment_notification(:other,:a,NULL)",
        args,
        tenant=other,
        mode="scalar",
    )
    assert path_id is not None
    path_id = str(path_id)
    assert (
        await actor(
            f"SELECT * FROM {q}.due_learning_path_assignment_notifications(100)",
            role="lms_recovery",
            mode="all",
        )
        == []
    )
    checks = ["baseline_course_enqueue_42501", "baseline_path_due_hidden"]
    if not apply_fix:
        # Baseline mode is intentionally red on the same real enqueue seam.
        await actor(f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,:u)", args, tenant=t)
        raise AssertionError("baseline_unexpectedly_succeeded")

    migration_path = ROOT / "apps/api/alembic/versions/0154_assignment_notification_owner_policies.py"
    spec = importlib.util.spec_from_file_location("assignment_owner_fix", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def apply_migration(method: str) -> None:
        collector = SqlCollector(schema)
        migration.op = collector
        getattr(migration, method)()
        migration_statements.append(collector.statements)

    migration_statements: list[list[str]] = []
    apply_migration("upgrade")
    for statement in migration_statements.pop():
        await sql(statement)

    # A second valid course enrollment gives the owner no-context check a
    # non-due row to exclude. Its user is resolved from the actual path fixture.
    u2 = (
        await sql(
            f"SELECT user_id FROM {q}.learning_path_assignments WHERE id=:assignment",
            {"assignment": assignment},
        )
    ).scalar()
    assert u2 is not None
    c2, e2 = str(uuid4()), str(uuid4())
    other_args = {"other": other, "c2": c2, "e2": e2, "u2": str(u2)}
    await sql(f"INSERT INTO {q}.courses VALUES (:c2,:other,'Synthetic other course','published')", other_args)
    await sql(
        f"INSERT INTO {q}.enrollments (id,tenant_id,course_id,user_id,status) VALUES (:e2,:other,:c2,:u2,'enrolled')",
        other_args,
    )

    course_id = await actor(
        f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,NULL)", args, tenant=t, mode="scalar"
    )
    assert course_id is not None
    course_id = str(course_id)
    nonnull_course_id = await actor(
        f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,:u)", args, tenant=t, mode="scalar"
    )
    assert str(nonnull_course_id) == course_id
    duplicate_course_id = await actor(
        f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,:u)", args, tenant=t, mode="scalar"
    )
    assert str(duplicate_course_id) == course_id
    await denied(
        f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,:u2)",
        {**args, "u2": str(u2)},
        tenant=t,
    )
    await denied(
        f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,NULL)",
        args,
        tenant=other,
    )
    await denied(
        f"SELECT {q}.enqueue_learning_path_assignment_notification(:other,:a,:u)",
        args,
        tenant=other,
    )

    other_course_id = await actor(
        f"SELECT {q}.enqueue_course_assignment_notification(:other,:e2,NULL)",
        other_args,
        tenant=other,
        mode="scalar",
    )
    assert other_course_id is not None
    other_course_id = str(other_course_id)
    await actor(
        f"UPDATE {q}.course_assignment_notification_outbox SET status='delivered',next_attempt_at=now()+interval '1 hour' WHERE id=:id",
        {"id": other_course_id},
        tenant=other,
        role="owner",
    )

    course_due = await actor(
        f"SELECT * FROM {q}.due_course_assignment_notifications(100)", role="lms_recovery", mode="all"
    )
    path_due = await actor(
        f"SELECT * FROM {q}.due_learning_path_assignment_notifications(100)", role="lms_recovery", mode="all"
    )
    assert any(str(row[0]) == str(course_id) and str(row[1]) == t for row in course_due)
    assert any(str(row[0]) == str(path_id) and str(row[1]) == other for row in path_due)
    checks.append("owner_policy_restores_no_context_due_discovery")

    claimed_course = await actor(
        f"SELECT * FROM {q}.claim_course_assignment_notification(:t,:id)",
        {"t": t, "id": course_id},
        tenant=t,
        mode="mappings",
    )
    assert len(claimed_course) == 1
    course_token = claimed_course[0]["claim_token"]
    assert not await actor(
        f"SELECT {q}.finalize_course_assignment_notification(:t,:id,:token,'success','wrong',NULL)",
        {"t": t, "id": course_id, "token": str(uuid4())},
        tenant=t,
        mode="scalar",
    )
    assert await actor(
        f"SELECT {q}.finalize_course_assignment_notification(:t,:id,:token,'success','synthetic-course',NULL)",
        {"t": t, "id": course_id, "token": course_token},
        tenant=t,
        mode="scalar",
    )
    course_status = await actor(
        f"SELECT * FROM {q}.course_assignment_notification_statuses(:t,:c)",
        {"t": t, "c": c},
        tenant=t,
        mode="mappings",
    )
    assert len(course_status) == 1 and course_status[0]["status"] == "delivered"
    assert (
        str(await actor(f"SELECT {q}.requeue_course_assignment_notification(:t,:e)", args, tenant=t, mode="scalar"))
        == course_id
    )
    course_status = await actor(
        f"SELECT * FROM {q}.course_assignment_notification_statuses(:t,:c)",
        {"t": t, "c": c},
        tenant=t,
        mode="mappings",
    )
    assert course_status[0]["status"] == "pending"
    checks.extend(
        [
            "course_nullable_and_nonnull_actor_dedup",
            "course_claim_wrong_token_and_finalize",
            "course_status_and_requeue",
        ]
    )

    claimed_path = await actor(
        f"SELECT * FROM {q}.claim_learning_path_assignment_notification(:other,:id)",
        {"other": other, "id": path_id},
        tenant=other,
        mode="mappings",
    )
    assert len(claimed_path) == 1
    path_token = claimed_path[0]["claim_token"]
    assert not await actor(
        f"SELECT {q}.finalize_learning_path_assignment_notification(:other,:id,:token,'success','wrong',NULL)",
        {"other": other, "id": path_id, "token": str(uuid4())},
        tenant=other,
        mode="scalar",
    )
    assert await actor(
        f"SELECT {q}.finalize_learning_path_assignment_notification(:other,:id,:token,'success','synthetic-path',NULL)",
        {"other": other, "id": path_id, "token": path_token},
        tenant=other,
        mode="scalar",
    )
    path_status = await actor(
        f"SELECT status FROM {q}.learning_path_assignment_notification_outbox WHERE id=:id",
        {"id": path_id},
        tenant=other,
        role="owner",
        mode="all",
    )
    assert path_status == [("sent",)]
    # Re-open a real due row using the pre-existing PUBLIC tenant policy. This
    # keeps downgrade/re-upgrade checks about rows and discovery, not fixtures.
    await actor(
        f"UPDATE {q}.learning_path_assignment_notification_outbox SET status='pending',next_attempt_at=now(),claim_token=NULL,claimed_at=NULL WHERE id=:id",
        {"id": path_id},
        tenant=other,
        role="owner",
    )
    checks.append("path_enqueue_due_claim_wrong_token_and_finalize")

    # Direct table access remains denied to the runtime caller, including all
    # write verbs. No DELETE ACL or DELETE policy is introduced by 0154.
    for table in (course_table, path_table):
        await denied(f"SELECT * FROM {table}", role="caller")
        await denied(f"UPDATE {table} SET updated_at=updated_at", role="caller")
        await denied(
            f"INSERT INTO {table} (tenant_id) VALUES (:t)",
            {"t": t},
            role="caller",
        )
        assert not (
            await sql(
                "SELECT has_table_privilege(:role,:table,'DELETE')",
                {"role": caller, "table": table},
            )
        ).scalar()
        assert (
            await sql(
                "SELECT count(*) FROM pg_policies WHERE schemaname=:schema AND tablename=:table AND cmd='DELETE'",
                {"schema": schema, "table": table.split(".")[-1]},
            )
        ).scalar() == 0
    await denied(
        f"INSERT INTO {q}.course_assignment_notification_outbox (tenant_id,enrollment_id) VALUES (:t,:e)",
        {"t": t, "e": str(uuid4())},
        role="owner",
    )
    # UPDATE has no visible target without a tenant context, so assert the
    # attempted mutation had no effect rather than mistaking zero rows for a
    # SQL authorization exception.
    owner_update = await actor(
        f"UPDATE {q}.course_assignment_notification_outbox SET updated_at=now() WHERE id=:id RETURNING id",
        {"id": course_id},
        role="owner",
        mode="all",
    )
    assert owner_update == []
    owner_course_rows = await actor(
        f"SELECT id,tenant_id FROM {q}.course_assignment_notification_outbox ORDER BY id",
        role="owner",
        mode="all",
    )
    owner_path_rows = await actor(
        f"SELECT id,tenant_id FROM {q}.learning_path_assignment_notification_outbox ORDER BY id",
        role="owner",
        mode="all",
    )
    assert [(str(row[0]), str(row[1])) for row in owner_course_rows] == [(course_id, t)]
    assert [(str(row[0]), str(row[1])) for row in owner_path_rows] == [(path_id, other)]
    checks.extend(["runtime_direct_table_acl_denied", "owner_no_context_due_only_and_no_delete_policy"])

    # Downgrade changes only policies/function guard and preserves delivery
    # rows. It must restore the real red behavior on the same call seam.
    migration_statements = []
    apply_migration("downgrade")
    for statement in migration_statements.pop():
        await sql(statement)
    assert (await sql(f"SELECT count(*) FROM {q}.course_assignment_notification_outbox")).scalar() == 2
    assert (await sql(f"SELECT count(*) FROM {q}.learning_path_assignment_notification_outbox")).scalar() == 1
    assert (
        await actor(f"SELECT * FROM {q}.due_course_assignment_notifications(100)", role="lms_recovery", mode="all")
        == []
    )
    assert (
        await actor(
            f"SELECT * FROM {q}.due_learning_path_assignment_notifications(100)", role="lms_recovery", mode="all"
        )
        == []
    )
    await denied(f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,NULL)", args, tenant=t)
    checks.append("downgrade_preserves_rows_and_restores_failure")

    migration_statements = []
    apply_migration("upgrade")
    for statement in migration_statements.pop():
        await sql(statement)
    assert (
        str(
            await actor(f"SELECT {q}.enqueue_course_assignment_notification(:t,:e,NULL)", args, tenant=t, mode="scalar")
        )
        == course_id
    )
    assert any(
        str(row[0]) == str(path_id)
        for row in await actor(
            f"SELECT * FROM {q}.due_learning_path_assignment_notifications(100)",
            role="lms_recovery",
            mode="all",
        )
    )
    checks.append("reupgrade_restores_nullable_actor_and_due_discovery")
    return checks
