"""Retention checks consumed ONLY by the canonical disposable workbench DEV gate."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def verify_retention_upgrade(connection, schema, migrate, path):
    from workbench_assignment_dev_gate import GateBlocked, safe_schema

    table = f"{safe_schema(schema)}.workbench_assignment_plans"
    # Test empty upgrade without keeping its DDL, then upgrade populated0169.
    savepoint = await connection.begin_nested()
    await migrate(connection, schema, path=path)
    await savepoint.rollback()
    tenant, actor, ready, succeeded = (uuid4() for _ in range(4))
    await connection.execute(
        text(
            f"INSERT INTO {safe_schema(schema)}.tenants(id,name,slug,status,plan,settings) "
            "VALUES(:id,'Synthetic migration',:slug,'trial','free','{}')"
        ),
        {"id": tenant, "slug": f"retention-{tenant.hex}"},
    )
    for plan_id, status in ((ready, "ready"), (succeeded, "succeeded")):
        await connection.execute(
            text(
                f"INSERT INTO {table}(id,tenant_id,actor_id,snapshot,preview,fingerprint,expires_at,status,receipt) "
                "VALUES(:id,:tenant,:actor,CAST(:snapshot AS jsonb),CAST(:preview AS jsonb),:fp,"
                "transaction_timestamp()-interval '100 days',:status,CAST(:receipt AS jsonb))"
            ),
            {
                "id": plan_id,
                "tenant": tenant,
                "actor": actor,
                "fp": "a" * 64,
                "status": status,
                "snapshot": json.dumps(
                    {
                        "tenant_id": str(tenant),
                        "actor_id": str(actor),
                        "plan_id": str(plan_id),
                    }
                ),
                "preview": json.dumps(
                    {"plan_id": str(plan_id), "fingerprint": "a" * 64}
                ),
                "receipt": None if status == "ready" else "{}",
            },
        )
    await migrate(connection, schema, path=path)
    rows = (
        await connection.execute(
            text(f"SELECT status,executed_at FROM {table} ORDER BY status")
        )
    ).all()
    if rows != [("ready", None), ("succeeded", None)]:
        raise GateBlocked("retention_legacy_timestamp_guessed")
    await connection.execute(
        text(f"DELETE FROM {table} WHERE tenant_id=:tenant"), {"tenant": tenant}
    )
    await connection.execute(
        text(f"DELETE FROM {safe_schema(schema)}.tenants WHERE id=:tenant"),
        {"tenant": tenant},
    )
    return ["retention_empty_upgrade", "retention_populated_upgrade_no_backfill"]


async def verify_retention(
    owner_engine, runtime_engine, schema, actor, other_tenant, request
):
    from app.modules.methodologist_workbench.assignment_service import (
        WorkbenchNotFound,
        confirm_assignment_plan,
        get_assignment_plan,
    )
    from app.modules.methodologist_workbench.plan_contract import ConfirmationRequest
    from workbench_assignment_dev_gate import (
        GateBlocked,
        TABLES,
        context,
        safe_failure,
        safe_schema,
    )

    qualified = safe_schema(schema)
    checks = []
    fn = text("SELECT * FROM cleanup_workbench_assignment_plans(:limit,:apply)")

    async def execute(db, *, limit=500, apply=False):
        return (await db.execute(fn, {"limit": limit, "apply": apply})).all()

    async def reject(db, statement, parameters, state, name):
        try:
            async with db.begin_nested():
                await db.execute(text(statement), parameters)
        except Exception as exc:
            if state not in safe_failure(exc):
                raise GateBlocked(name + "_wrong_error") from None
        else:
            raise GateBlocked(name + "_accepted")

    async def domain_snapshot():
        # Entire domain contents are synthetic; compare every row, not just counts.
        async with owner_engine.begin() as db:
            await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
            return {
                name: await db.scalar(
                    text(
                        f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM {name} t"
                    )
                )
                for name in TABLES
            }

    # Real committed assignment timestamp exists; replay and rollback leave it stable.
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        timestamp = await db.scalar(
            text("SELECT executed_at FROM workbench_assignment_plans WHERE id=:id"),
            {"id": request.plan_id},
        )
        if timestamp is None:
            raise GateBlocked("retention_success_timestamp_missing")
        result = await confirm_assignment_plan(db, actor, request)
        if result.dispatch_ids:
            raise GateBlocked("retention_replay_dispatched")
        await db.commit()
        await context(db, schema, actor.tenant_id, actor.actor_id)
        if timestamp != await db.scalar(
            text("SELECT executed_at FROM workbench_assignment_plans WHERE id=:id"),
            {"id": request.plan_id},
        ):
            raise GateBlocked("retention_replay_extended_timestamp")
        await reject(
            db,
            "UPDATE workbench_assignment_plans SET executed_at=transaction_timestamp() WHERE id=:id",
            {"id": request.plan_id},
            "42501",
            "retention_timestamp_acl",
        )
        await reject(
            db,
            "UPDATE workbench_assignment_plans SET receipt='{}'::jsonb WHERE id=:id",
            {"id": request.plan_id},
            "23514",
            "retention_receipt_immutable",
        )
        await reject(
            db,
            "UPDATE workbench_assignment_plans SET status='ready',receipt=NULL WHERE id=:id",
            {"id": request.plan_id},
            "23514",
            "retention_success_terminal",
        )
        await reject(
            db,
            "SELECT * FROM cleanup_workbench_assignment_plans()",
            {},
            "42501",
            "retention_ordinary_denied",
        )
        await context(db, schema, "", "", superadmin=True)
        await reject(
            db,
            "SELECT * FROM cleanup_workbench_assignment_plans()",
            {},
            "42501",
            "retention_no_tenant_denied",
        )
    checks += [
        "retention_db_success_time",
        "retention_replay_time_unchanged",
        "retention_timestamp_acl_denied",
        "retention_receipt_terminal_immutable",
        "retention_ordinary_no_context_denied",
    ]

    # Seed ready clones and convert successes through the real trigger. Privileged
    # fixture-only trigger suspension backdates known synthetic receipts afterwards.
    ids = {
        name: uuid4()
        for name in (
            "ready_old",
            "ready_boundary",
            "ready_young",
            "success_old",
            "success_boundary",
            "success_young",
            "legacy",
            "foreign",
            "future",
        )
    }
    async with owner_engine.begin() as db:
        await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
        source = (
            (
                await db.execute(
                    text("SELECT * FROM workbench_assignment_plans WHERE id=:id"),
                    {"id": request.plan_id},
                )
            )
            .mappings()
            .one()
        )
        for name, plan_id in ids.items():
            tenant = other_tenant if name == "foreign" else actor.tenant_id
            snapshot, preview = dict(source["snapshot"]), dict(source["preview"])
            snapshot.update(plan_id=str(plan_id), tenant_id=str(tenant))
            preview.update(plan_id=str(plan_id))
            await db.execute(
                text(
                    "INSERT INTO workbench_assignment_plans(id,tenant_id,actor_id,snapshot,preview,fingerprint,expires_at) "
                    "VALUES(:id,:tenant,:actor,CAST(:snapshot AS jsonb),CAST(:preview AS jsonb),:fp,transaction_timestamp())"
                ),
                {
                    "id": plan_id,
                    "tenant": tenant,
                    "actor": actor.actor_id,
                    "fp": source["fingerprint"],
                    "snapshot": json.dumps(snapshot),
                    "preview": json.dumps(preview),
                },
            )
            if name.startswith("success") or name == "legacy":
                receipt = dict(source["receipt"])
                receipt["plan_id"] = str(plan_id)
                await db.execute(
                    text(
                        "UPDATE workbench_assignment_plans SET status='succeeded',receipt=CAST(:receipt AS jsonb) WHERE id=:id"
                    ),
                    {"id": plan_id, "receipt": json.dumps(receipt)},
                )
        await db.execute(
            text(
                f"ALTER TABLE {qualified}.workbench_assignment_plans DISABLE TRIGGER workbench_execution_time"
            )
        )
        for name, age in (
            ("success_old", "91 days"),
            ("success_boundary", "90 days"),
            ("success_young", "89 days"),
        ):
            await db.execute(
                text(
                    "UPDATE workbench_assignment_plans SET executed_at=transaction_timestamp()-CAST(:age AS interval) WHERE id=:id"
                ),
                {"id": ids[name], "age": age},
            )
        await db.execute(
            text("UPDATE workbench_assignment_plans SET executed_at=NULL WHERE id=:id"),
            {"id": ids["legacy"]},
        )
        await db.execute(
            text(
                f"ALTER TABLE {qualified}.workbench_assignment_plans ENABLE TRIGGER workbench_execution_time"
            )
        )
        for name, age in (
            ("ready_old", "25 hours"),
            ("ready_boundary", "24 hours"),
            ("ready_young", "23 hours"),
            ("foreign", "30 hours"),
            ("future", "-1 day"),
        ):
            await db.execute(
                text(
                    "UPDATE workbench_assignment_plans SET expires_at=transaction_timestamp()-CAST(:age AS interval) WHERE id=:id"
                ),
                {"id": ids[name], "age": age},
            )
    before = await domain_snapshot()

    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
        boundary_clock = await db.scalar(text("SELECT transaction_timestamp()"))
        async with owner_engine.begin() as fixture:
            await context(
                fixture, schema, actor.tenant_id, actor.actor_id, superadmin=True
            )
            await fixture.execute(
                text(
                    f"ALTER TABLE {qualified}.workbench_assignment_plans DISABLE TRIGGER workbench_execution_time"
                )
            )
            for name, age in (
                ("ready_boundary", "24 hours"),
                ("ready_young", "23:59:59.999999"),
                ("success_boundary", "90 days"),
                ("success_young", "89 days 23:59:59.999999"),
            ):
                column = "expires_at" if name.startswith("ready") else "executed_at"
                await fixture.execute(
                    text(
                        f"UPDATE workbench_assignment_plans SET {column}=CAST(:clock AS timestamptz)-CAST(:age AS interval) WHERE id=:id"
                    ),
                    {"id": ids[name], "clock": boundary_clock, "age": age},
                )
            await fixture.execute(
                text(
                    f"ALTER TABLE {qualified}.workbench_assignment_plans ENABLE TRIGGER workbench_execution_time"
                )
            )
        for limit, apply in ((0, False), (501, False), (None, False), (1, None)):
            await reject(
                db,
                str(fn),
                {"limit": limit, "apply": apply},
                "22023",
                "retention_invalid_batch",
            )
        chosen = await execute(db)
        expected = {
            ids[name]
            for name in (
                "ready_old",
                "ready_boundary",
                "success_old",
                "success_boundary",
            )
        }
        if {row.plan_id for row in chosen} != expected:
            raise GateBlocked("retention_cutoffs_or_scope")
        # Exact same database transaction clock: inclusive cutoff eligible,
        # one microsecond short ineligible. Restore roomy recent ages for later
        # transactions so wall-clock passage cannot turn those fixtures eligible.
        async with owner_engine.begin() as fixture:
            await context(
                fixture, schema, actor.tenant_id, actor.actor_id, superadmin=True
            )
            await fixture.execute(
                text(
                    f"ALTER TABLE {qualified}.workbench_assignment_plans DISABLE TRIGGER workbench_execution_time"
                )
            )
            await fixture.execute(
                text(
                    "UPDATE workbench_assignment_plans SET expires_at=transaction_timestamp()-interval '23 hours' WHERE id=:id"
                ),
                {"id": ids["ready_young"]},
            )
            await fixture.execute(
                text(
                    "UPDATE workbench_assignment_plans SET executed_at=transaction_timestamp()-interval '89 days' WHERE id=:id"
                ),
                {"id": ids["success_young"]},
            )
            await fixture.execute(
                text(
                    f"ALTER TABLE {qualified}.workbench_assignment_plans ENABLE TRIGGER workbench_execution_time"
                )
            )
        ordered = await execute(db, limit=1)
        if ordered != chosen[:1]:
            raise GateBlocked("retention_deterministic_batch")
        await db.commit()
        await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
        if await execute(db) != chosen:
            raise GateBlocked("retention_dry_run_changed_rows")
        removed = await execute(db, limit=1, apply=True)
        if {row.plan_id for row in removed} != {chosen[0].plan_id}:
            raise GateBlocked("retention_batch_cap")
        await db.rollback()
        await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
        if await execute(db) != chosen:
            raise GateBlocked("retention_delete_rollback")
    checks += [
        "retention_invalid_batch_denied",
        "retention_cutoffs_24h_90d",
        "retention_legacy_future_recent_protected",
        "retention_tenant_scope",
        "retention_dry_run_no_mutation",
        "retention_batch_order_cap",
        "retention_delete_rollback",
    ]
    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, other_tenant, actor.actor_id, superadmin=True)
        if {row.plan_id for row in await execute(db)} != {ids["foreign"]}:
            raise GateBlocked("retention_foreign_context_scope")
    checks.append("retention_foreign_context_exact_tenant")

    # An app-role lock skips only that eligible record; retry cleans it later.
    async with (
        AsyncSession(runtime_engine) as locker,
        AsyncSession(runtime_engine) as cleaner,
    ):
        await context(locker, schema, actor.tenant_id, actor.actor_id)
        await locker.execute(
            text("SELECT id FROM workbench_assignment_plans WHERE id=:id FOR UPDATE"),
            {"id": ids["success_old"]},
        )
        await context(cleaner, schema, actor.tenant_id, actor.actor_id, superadmin=True)
        removed = await asyncio.wait_for(execute(cleaner, apply=True), timeout=15)
        if {row.plan_id for row in removed} != expected - {ids["success_old"]}:
            raise GateBlocked("retention_skip_locked")
        await cleaner.commit()
        replay_request = ConfirmationRequest(
            plan_id=ids["success_old"],
            revision=request.revision,
            fingerprint=request.fingerprint,
        )
        replay = await confirm_assignment_plan(locker, actor, replay_request)
        if replay.dispatch_ids:
            raise GateBlocked("retention_locked_replay_dispatched")
        await locker.commit()
    checks += [
        "retention_cleanup_skips_real_app_lock",
        "retention_locked_receipt_replay_no_dispatch",
    ]

    async def cleanup_once():
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
            removed = await execute(db, apply=True)
            await db.commit()
            return {row.plan_id for row in removed}

    first, second = await asyncio.wait_for(
        asyncio.gather(cleanup_once(), cleanup_once()), timeout=25
    )
    if first & second or first | second != {ids["success_old"]}:
        raise GateBlocked("retention_concurrent_delete_duplicate")
    if await cleanup_once():
        raise GateBlocked("retention_repeat_delete_not_empty")
    checks += ["retention_concurrent_delete_once", "retention_repeat_cleanup_zero"]

    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        for plan_id in expected:
            for operation in (
                get_assignment_plan(db, actor, plan_id),
                confirm_assignment_plan(
                    db,
                    actor,
                    ConfirmationRequest(
                        plan_id=plan_id,
                        revision=request.revision,
                        fingerprint=request.fingerprint,
                    ),
                ),
            ):
                try:
                    await operation
                except WorkbenchNotFound:
                    pass
                else:
                    raise GateBlocked("retention_deleted_locator_reexecuted")
        await db.rollback()
    async with owner_engine.begin() as db:
        await context(db, schema, actor.tenant_id, actor.actor_id, superadmin=True)
        remaining = set(
            (
                await db.scalars(
                    text(
                        "SELECT id FROM workbench_assignment_plans WHERE id IN (SELECT unnest(CAST(:ids AS uuid[])))"
                    ),
                    {"ids": list(ids.values())},
                )
            ).all()
        )
        if remaining != set(ids.values()) - expected:
            raise GateBlocked("retention_protected_fixture_removed")
    if before != await domain_snapshot():
        raise GateBlocked("retention_domain_history_changed")
    checks += [
        "retention_deleted_get_confirm_not_found",
        "retention_domain_all_rows_unchanged",
    ]
    return checks
