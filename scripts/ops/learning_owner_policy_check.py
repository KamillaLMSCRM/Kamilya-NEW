"""Transactional non-bypass function-owner contract; synthetic schema only."""

from __future__ import annotations

import ast
import importlib.util
import re

from sqlalchemy import text


async def check_owner_policy(conn, schema: str, *, apply_fix: bool) -> list[str]:
    from learning_reminder_dev_check import ROOT, TABLES, SqlCollector

    assert re.fullmatch(r"r2_reminder_[0-9a-f]{32}", schema)
    owner = schema.replace("r2_reminder_", "r2_owner_")
    caller = schema.replace("r2_reminder_", "r2_caller_")
    q = f'"{schema}"'

    async def sql(statement, params=None):
        return await conn.execute(text(statement), params or {})

    async def actor(statement, params=None, *, tenant="", role="lms_app"):
        assert role in ("lms_app", "lms_recovery", owner)
        async with conn.begin_nested():
            # Supabase's migration login cannot SET ROLE lms_recovery. Its ACL
            # is checked separately; the real SECURITY DEFINER owner still runs
            # the same function body, regardless of this privileged caller.
            if role != "lms_recovery":
                await sql(f'SET LOCAL ROLE "{caller if role == "lms_app" else role}"')
            await sql("SELECT set_config('app.tenant_id',:tid,true)", {"tid": tenant})
            result = await sql(statement, params)
            await sql("RESET ROLE")
            return result

    async def denied(statement, params=None, *, tenant="", role="lms_app"):
        try:
            await actor(statement, params, tenant=tenant, role=role)
        except Exception as exc:
            original = getattr(exc, "orig", exc)
            assert getattr(original, "sqlstate", None) in ("42501", "P0001")
        else:
            raise AssertionError("authorization_must_reject")

    await sql(f'CREATE ROLE "{owner}" NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT')
    await sql(f'GRANT "{owner}" TO CURRENT_USER')
    await sql(f'CREATE ROLE "{caller}" NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT')
    await sql(f'GRANT "{caller}" TO CURRENT_USER')
    await sql(f'GRANT USAGE ON SCHEMA {q} TO "{caller}"')
    await sql(f'GRANT USAGE, CREATE ON SCHEMA {q} TO "{owner}"')
    await sql(f"GRANT USAGE ON SCHEMA {q} TO lms_recovery")
    await sql(f"ALTER TABLE {q}.recurring_learning_rules ADD COLUMN next_run_at timestamptz")
    source = ROOT / "apps/api/alembic/versions/0103_recurring_enrollment_instances.py"
    statements = [
        n.value
        for n in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.startswith("CREATE FUNCTION due_recurring_learning_rules(")
    ]
    assert len(statements) == 1
    await sql(
        statements[0]
        .replace("CREATE FUNCTION due_", f"CREATE FUNCTION {q}.due_")
        .replace("search_path=public,pg_temp", f"search_path={q},pg_temp")
    )
    await sql(f"REVOKE ALL ON FUNCTION {q}.due_recurring_learning_rules(integer) FROM PUBLIC,lms_app")
    await sql(f"GRANT EXECUTE ON FUNCTION {q}.due_recurring_learning_rules(integer) TO lms_recovery")

    for table in TABLES:
        if table != "tenants":  # Live CT125 parity: tenants itself has no RLS.
            await sql(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY")
            await sql(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY")
        column = "id" if table == "tenants" else "tenant_id"
        roles = (
            f'lms_app,"{caller}"'
            if table
            in (
                "recurring_learning_rules",
                "recurring_learning_assignments",
                "learning_path_cycle_instances",
                "learning_path_assignments",
            )
            else "PUBLIC"
        )
        await sql(
            f"CREATE POLICY fixture_tenant ON {q}.{table} TO {roles} "
            f"USING ({column}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
        )
        await sql(f'GRANT SELECT,INSERT,UPDATE ON {q}.{table} TO lms_app,"{caller}"')
        await sql(f'ALTER TABLE {q}.{table} OWNER TO "{owner}"')
    # Recreate the deployed outbox owner's existing policy, not a fixture bypass
    # on any legacy table. All role/object changes roll back in the caller.
    await sql(f'ALTER TABLE {q}.learning_reminder_outbox OWNER TO "{owner}"')
    await sql(f'ALTER POLICY learning_reminder_owner ON {q}.learning_reminder_outbox TO "{owner}"')
    signatures = (
        (
            await sql(
                "SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:s",
                {"s": schema},
            )
        )
        .scalars()
        .all()
    )
    for signature in signatures:
        if (await sql("SELECT has_function_privilege('lms_app',:f,'EXECUTE')", {"f": signature})).scalar():
            await sql(f'GRANT EXECUTE ON FUNCTION {signature} TO "{caller}"')
        await sql(f'ALTER FUNCTION {signature} OWNER TO "{owner}"')
    assert (await actor("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user", role=owner)).one() == (
        False,
        False,
    )

    from uuid import uuid4

    t, other, u, c, r, o, e = [str(uuid4()) for _ in range(7)]
    args = dict(t=t, other=other, u=u, c=c, r=r, o=o, e=e)
    # Admin fixture insertion only; no customer rows or public-table writes.
    for tenant in (t, other):
        await sql(f"INSERT INTO {q}.tenants VALUES (:t,'Synthetic','synthetic','active')", {"t": tenant})
    await sql(
        f"INSERT INTO {q}.users VALUES (:u,:t,'learner@example.invalid','Synthetic','Learner','student',true,'active',NULL,NULL,now())",
        args,
    )
    await sql(f"INSERT INTO {q}.courses VALUES (:c,:t,'Synthetic course','published')", args)
    await sql(
        f"INSERT INTO {q}.recurring_learning_rules (id,tenant_id,course_id,user_id,status,reminder_enabled,next_run_at) VALUES (:r,:t,:c,:u,'active',true,now()-interval '10 minutes')",
        args,
    )
    await sql(f"INSERT INTO {q}.enrollments VALUES (:e,:t,:c,:u,:o,'enrolled',NULL)", args)
    await sql(
        f"INSERT INTO {q}.recurring_learning_assignments VALUES (:o,:t,:r,:u,:c,:e,now()+interval '12 hours','assigned')",
        args,
    )
    assert (await actor(f"SELECT * FROM {q}.due_recurring_learning_rules(100)", role="lms_recovery")).all() == []
    assert (await actor(f"SELECT {q}.enqueue_learning_reminder(:t,:o,NULL)", args, tenant=t)).scalar() is None
    checks = ["production_non_bypass_owner_failure_reproduced"]
    print("OWNER_POLICY|baseline_due_empty=true|baseline_enqueue_empty=true", flush=True)

    migration = None
    if apply_fix:
        path = ROOT / "apps/api/alembic/versions/0153_learning_recovery_owner_policies.py"
        spec = importlib.util.spec_from_file_location("owner_fix", path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        collector = SqlCollector(schema)
        migration.op = collector
        migration.upgrade()
        for statement in collector.statements:
            await sql(statement)
    rows = (await actor(f"SELECT * FROM {q}.due_recurring_learning_rules(100)", role="lms_recovery")).all()
    assert len(rows) == 1 and str(rows[0][0]) == r, "due_rule_must_be_visible_to_bounded_recovery"
    checks.append("bounded_discovery_with_non_bypass_owner")
    assert not (
        await sql(
            "SELECT has_table_privilege('lms_recovery',:table,'SELECT')",
            {"table": f"{schema}.recurring_learning_rules"},
        )
    ).scalar()
    assert (
        await sql(
            "SELECT has_function_privilege('lms_recovery',:function,'EXECUTE')",
            {"function": f"{schema}.due_recurring_learning_rules(integer)"},
        )
    ).scalar()
    await denied(f"SELECT * FROM {q}.due_recurring_learning_rules(100)")
    assert (await actor(f"SELECT count(*) FROM {q}.recurring_learning_rules", tenant=other)).scalar() == 0
    await denied(f"SELECT {q}.enqueue_learning_reminder(:t,:o,NULL)", args, tenant=other)
    assert (await actor(f"SELECT {q}.enqueue_learning_reminder(:other,:o,NULL)", args, tenant=other)).scalar() is None
    reminder = (await actor(f"SELECT {q}.enqueue_learning_reminder(:t,:o,NULL)", args, tenant=t)).scalar()
    assert reminder is not None, "same_tenant_course_reminder_must_enqueue"
    args["id"] = reminder
    claimed = (await actor(f"SELECT * FROM {q}.claim_learning_reminder(:t,:id)", args, tenant=t)).mappings().one()
    args["token"] = claimed["claim_token"]
    payload = (
        (await actor(f"SELECT * FROM {q}.learning_reminder_payload(:t,:id,:token)", args, tenant=t)).mappings().one()
    )
    assert payload["title"] == "Synthetic course" and payload["has_login_access"]
    assert (
        await actor(
            f"SELECT {q}.begin_learning_reminder_send(:t,:id,:token,:hash,'smtp')", {**args, "hash": "a" * 64}, tenant=t
        )
    ).scalar()
    assert (
        await actor(
            f"SELECT {q}.finalize_learning_reminder(:t,:id,:token,'success','synthetic-message',NULL)", args, tenant=t
        )
    ).scalar()
    statuses = (await actor(f"SELECT * FROM {q}.learning_reminder_statuses(:t,:r)", args, tenant=t)).mappings().all()
    assert len(statuses) == 1 and statuses[0]["status"] == "sent"
    assert (await actor(f"SELECT * FROM {q}.learning_reminder_statuses(:other,:r)", args, tenant=other)).all() == []
    checks.extend(["course_ledger_end_to_end_no_provider", "tenant_and_direct_access_negatives"])
    assert (await actor(f"SELECT * FROM {q}.claim_learning_reminder(:t,:id)", args, tenant=t)).all() == []
    # Second tenant owns a real program cycle. Neither tenant can inspect the
    # other's reminder even though the global due selector can discover work.
    u2, path, rule2, cycle, assignment = [str(uuid4()) for _ in range(5)]
    other_args = dict(t=other, u=u2, p=path, r=rule2, cy=cycle, a=assignment)
    await sql(
        f"INSERT INTO {q}.users VALUES (:u,:t,'other@example.invalid','Other','Learner','student',true,'active',NULL,NULL,now())",
        other_args,
    )
    await sql(f"INSERT INTO {q}.learning_paths VALUES (:p,:t,'Synthetic program','published')", other_args)
    await sql(
        f"INSERT INTO {q}.recurring_learning_rules (id,tenant_id,learning_path_id,user_id,status,reminder_enabled,next_run_at) VALUES (:r,:t,:p,:u,'active',true,now()+interval '30 days')",
        other_args,
    )
    await sql(
        f"INSERT INTO {q}.learning_path_cycle_instances VALUES (:cy,:t,:r,:p,:u,now()+interval '12 hours','active',NULL)",
        other_args,
    )
    await sql(
        f"INSERT INTO {q}.learning_path_assignments VALUES (:a,:t,:p,:u,:cy,'active',NULL,'recurring')", other_args
    )
    other_args["id"] = (
        await actor(f"SELECT {q}.enqueue_learning_reminder(:t,NULL,:cy)", other_args, tenant=other)
    ).scalar()
    assert other_args["id"] is not None
    assert (await actor(f"SELECT count(*) FROM {q}.recurring_learning_rules", tenant=t)).scalar() == 1
    assert (await actor(f"SELECT count(*) FROM {q}.recurring_learning_rules", tenant=other)).scalar() == 1
    assert len((await actor(f"SELECT * FROM {q}.due_recurring_learning_rules(100)", role="lms_recovery")).all()) == 1
    assert (await actor(f"SELECT count(*) FROM {q}.learning_path_cycle_instances", tenant=t, role=owner)).scalar() == 0
    assert (await actor(f"SELECT count(*) FROM {q}.learning_path_cycle_instances", role=owner)).scalar() == 0
    await denied(f"SELECT {q}.enqueue_learning_reminder(:t,NULL,:cy)", other_args, tenant=t)
    claim2 = (
        (await actor(f"SELECT * FROM {q}.claim_learning_reminder(:t,:id)", other_args, tenant=other)).mappings().one()
    )
    other_args["token"] = claim2["claim_token"]
    payload2 = (
        (await actor(f"SELECT * FROM {q}.learning_reminder_payload(:t,:id,:token)", other_args, tenant=other))
        .mappings()
        .one()
    )
    assert payload2["target_type"] == "learning_path" and payload2["title"] == "Synthetic program"
    await sql(f"UPDATE {q}.recurring_learning_rules SET reminder_enabled=false WHERE id=:r", other_args)
    assert (
        await actor(f"SELECT * FROM {q}.learning_reminder_payload(:t,:id,:token)", other_args, tenant=other)
    ).all() == []
    assert (
        await actor(
            f"SELECT {q}.finalize_learning_reminder(:t,:id,:token,'skipped',NULL,'ineligible')",
            other_args,
            tenant=other,
        )
    ).scalar()
    checks.extend(
        [
            "second_tenant_program_payload_and_optout",
            "owner_context_and_due_only_visibility",
            "sent_duplicate_suppressed",
        ]
    )
    assert migration is not None
    collector = SqlCollector(schema)
    migration.op = collector
    migration.downgrade()
    for statement in collector.statements:
        await sql(statement)
    assert (await actor(f"SELECT * FROM {q}.due_recurring_learning_rules(100)", role="lms_recovery")).all() == []
    assert (await sql(f"SELECT count(*) FROM {q}.learning_reminder_outbox")).scalar() == 2
    checks.append("downgrade_preserves_delivery_history")
    collector = SqlCollector(schema)
    migration.op = collector
    migration.upgrade()
    for statement in collector.statements:
        await sql(statement)
    assert len((await actor(f"SELECT * FROM {q}.due_recurring_learning_rules(100)", role="lms_recovery")).all()) == 1
    checks.append("reupgrade_restores_bounded_discovery")
    import sys

    from assignment_owner_policy_check import check_assignment_policy

    checks.extend(
        await check_assignment_policy(
            conn,
            schema,
            owner=owner,
            caller=caller,
            t=t,
            other=other,
            u=u,
            c=c,
            e=e,
            assignment=assignment,
            apply_fix="--assignment-baseline" not in sys.argv,
        )
    )
    return checks
