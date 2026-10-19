"""Additional real transaction checks; called only inside the owned DEV schema."""

from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


async def verify_changes(owner, runtime, schema, ids, context, checks):
    from app.modules.organization_units.change_service import confirm_change, preview_change, purge_change_plans
    from app.modules.organization_units.workspace_router import is_change_conflict
    from app.modules.positions.assignment_service import recompute_enrollments

    tenant, actor = ids["ta"], ids["ma"]

    async def state():
        async with owner.connect() as db:
            await context(db, schema)
            return {table: (await db.execute(text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY {key}"))).scalars().all()
                    for table, key in (("users", "id"), ("departments", "id"), ("enrollments", "id"),
                                       ("organization_transfer_retained_enrollments", "enrollment_id"), ("organization_change_plans", "id"))}

    async def student():
        user, enrollment = uuid4(), uuid4()
        async with owner.begin() as db:
            await context(db, schema)
            await db.execute(text("INSERT INTO users(id,tenant_id,first_name,last_name,role,is_active,status,position_id) VALUES (:u,:t,'Synthetic','Move','student',true,'active',:p)"),
                             {"u": user, "t": tenant, "p": ids["pa"]})
            await db.execute(text("INSERT INTO enrollments(id,tenant_id,user_id,course_id,status,source,content_release_id) VALUES (:e,:t,:u,:c,'enrolled','department',:r)"),
                             {"e": enrollment, "t": tenant, "u": user, "c": ids["c1"], "r": ids["r1"]})
        return user

    def command(user):
        return {"kind": "employee", "target_id": str(user), "organization_unit_id": str(ids["ub"]),
                "position_id": str(ids["pa"]), "reason": "Isolated transaction proof"}

    async def preview(body):
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, tenant, actor)
            view = await preview_change(db, tenant_id=tenant, actor_id=actor, command=body)
            await db.commit()
            return UUID(view["id"]), view

    # FORCE-RLS actor scope and database guards, independently of HTTP filters.
    other_actor = uuid4()
    async with owner.begin() as db:
        await context(db, schema)
        await db.execute(text("INSERT INTO users(id,tenant_id,first_name,last_name,role,is_active,status) VALUES (:id,:t,'Other','Reviewer','methodologist',true,'active')"),
                         {"id": other_actor, "t": tenant})
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, other_actor)
        assert await db.scalar(text("SELECT count(*) FROM organization_change_plans")) == 0
        checks.append("same_tenant_other_methodologist_cannot_read_owned_plans")
    denied = [
        ("UPDATE positions SET department_id=:foreign WHERE id=:id", {"foreign": ids["ua"], "id": ids["pb"]}, ids["tb"], ids["mb"], "23514"),
        ("UPDATE departments SET tenant_id=:foreign WHERE id=:id", {"foreign": ids["tb"], "id": ids["ua"]}, tenant, actor, "23514"),
        ("UPDATE organization_change_plans SET preview='{}' WHERE status='ready'", {}, tenant, actor, "23514"),
        ("INSERT INTO organization_change_plans(id,tenant_id,actor_id,command,preview,fingerprint,status,receipt,expires_at,executed_at) VALUES (:id,:t,:a,'{}','{}',:f,'succeeded','{}',now(),now())",
         {"id": uuid4(), "t": tenant, "a": actor, "f": "a"*64}, tenant, actor, "23514"),
        ("INSERT INTO organization_transfer_retained_enrollments(enrollment_id,tenant_id,plan_id,original_source) VALUES (:e,:t,NULL,'department')",
         {"e": ids["e1"], "t": ids["tb"]}, ids["tb"], ids["mb"], "23514"),
    ]
    before = await state()
    for sql, values, active_tenant, active_actor, code in denied:
        async with AsyncSession(runtime) as db:
            await context(db, schema, active_tenant, active_actor)
            try:
                await db.execute(text(sql), values)
            except DBAPIError as exc:
                assert exc.orig.sqlstate == code
                await db.rollback()
            else:
                raise AssertionError("database invariant bypassed")
    assert await state() == before
    checks.extend(["database_position_department_and_unit_tenant_guards", "plan_command_immutable_and_initial_success_denied", "foreign_enrollment_marker_insert_denied"])

    # An application account cannot elevate into retention by setting context.
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        try:
            await purge_change_plans(db, tenant, dry_run=False)
        except PermissionError:
            checks.append("retention_adapter_rejects_runtime_principal")
        else:
            raise AssertionError("ordinary maintenance accepted")
        try:
            await db.execute(text("DELETE FROM organization_change_plans WHERE false"))
        except DBAPIError as exc:
            assert exc.orig.sqlstate == "42501"
            await db.rollback()
            checks.append("ordinary_plan_delete_privilege_denied")
        else:
            raise AssertionError("ordinary DELETE privilege granted")

    # Retention fixtures are inserted with final dates through valid ready->success.
    old_success, old_ready, young_ready, young_success, foreign = [uuid4() for _ in range(5)]
    async with owner.begin() as db:
        await context(db, schema)
        for plan_id, plan_tenant, plan_actor, expiry in (
            (old_success, tenant, actor, "now()-interval '92 days'"),
            (old_ready, tenant, actor, "now()-interval '25 hours'"),
            (young_ready, tenant, actor, "now()-interval '23 hours'"),
            (young_success, tenant, actor, "now()-interval '89 days'"),
            (foreign, ids["tb"], ids["mb"], "now()-interval '92 days'"),
        ):
            await db.execute(text(f"INSERT INTO organization_change_plans(id,tenant_id,actor_id,command,preview,fingerprint,status,expires_at) VALUES (:id,:t,:a,'{{}}','{{}}',:f,'ready',{expiry})"),
                             {"id": plan_id, "t": plan_tenant, "a": plan_actor, "f": "a"*64})
        for plan_id, executed in ((old_success, "now()-interval '91 days'"), (young_success, "now()-interval '89 days'")):
            await db.execute(text(f"UPDATE organization_change_plans SET status='succeeded',receipt='{{}}',executed_at={executed} WHERE id=:id"), {"id": plan_id})
        # Fixture aging, owned schema only; source and enrollment remain untouched.
        await db.execute(text("UPDATE organization_transfer_retained_enrollments SET plan_id=:p WHERE enrollment_id=:e"), {"p": old_success, "e": ids["e1"]})
    before = await state()
    async with AsyncSession(owner) as db:
        await context(db, schema)
        assert await purge_change_plans(db, tenant) == 2
        await db.rollback()
    assert await state() == before
    async with AsyncSession(owner) as db:
        await context(db, schema)
        assert await purge_change_plans(db, tenant, dry_run=False, batch_size=1) == 1
        await db.rollback()
    assert await state() == before
    async with AsyncSession(owner) as db:
        await context(db, schema)
        assert await purge_change_plans(db, tenant, dry_run=False) == 2
        await db.commit()
    after = await state()
    assert after["users"] == before["users"] and after["enrollments"] == before["enrollments"]
    retained = next(r for r in after["organization_transfer_retained_enrollments"] if r["enrollment_id"] == str(ids["e1"]))
    assert retained["plan_id"] is None and retained["original_source"] == "department"
    surviving = {p["id"] for p in after["organization_change_plans"]}
    assert {str(young_ready), str(young_success), str(foreign)} <= surviving
    assert str(old_ready) not in surviving and str(old_success) not in surviving
    checks.extend(["retention_dry_run_and_rollback_unchanged", "retention_exact_tenant_cutoffs_and_batch", "marker_survives_plan_purge_set_null"])

    # Even if another rule later wants a different source, original provenance stays.
    async with owner.begin() as db:
        await context(db, schema)
        await db.execute(text("INSERT INTO position_courses(tenant_id,position_id,course_id) VALUES (:t,:p,:c)"),
                         {"t": tenant, "p": ids["pa"], "c": ids["c1"]})
    before_rows = (await state())["enrollments"]
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        result = await recompute_enrollments(db, ids["sa"])
        assert result.updated == 0 and result.removed == 0 and result.skipped_protected == 1
        await db.commit()
    assert (await state())["enrollments"] == before_rows
    checks.append("purged_marker_still_blocks_generic_source_rewrite")
    async with owner.begin() as db:
        await context(db, schema)
        await db.execute(text("DELETE FROM position_courses WHERE tenant_id=:t AND position_id=:p AND course_id=:c"),
                         {"t": tenant, "p": ids["pa"], "c": ids["c1"]})

    # Late failure after real SQL flush must roll back placement, additions, markers,
    # status and receipt together. This is not merely a mocked no-write assertion.
    user = await student()
    async with owner.begin() as db:
        await context(db, schema)
        for source, status in (("position", "completed"), ("manual", "enrolled"), ("cohort", "in_progress"), ("learning_path", "enrolled")):
            course, release_id = uuid4(), uuid4()
            await db.execute(text("INSERT INTO courses(id,tenant_id,title,description,status,review_status,delivery_type,current_release_id) VALUES (:c,:t,'Protected synthetic','','published','approved','native',:r)"),
                             {"c": course, "t": tenant, "r": release_id})
            await db.execute(text("INSERT INTO content_releases(id,tenant_id,course_id,version,snapshot,snapshot_sha256) VALUES (:r,:t,:c,1,'{}',:hash)"),
                             {"r": release_id, "t": tenant, "c": course, "hash": "b"*64})
            await db.execute(text("INSERT INTO enrollments(id,tenant_id,user_id,course_id,status,source,content_release_id,completed_at) VALUES (:e,:t,:u,:c,:status,:source,:r,CASE WHEN :status='completed' THEN now() ELSE NULL END)"),
                             {"e": uuid4(), "t": tenant, "u": user, "c": course, "r": release_id, "source": source, "status": status})
    plan_id, view = await preview(command(user))
    assert view["training"]["added"] == 1
    assert view["training"]["preserved_completed"] == 1 and view["training"]["preserved_other_sources"] == 3
    before = await state()
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        original_flush = db.flush
        async def late_failure(*args, **kwargs):
            await original_flush(*args, **kwargs)
            raise RuntimeError("injected_after_flush")
        with patch.object(db, "flush", new=late_failure):
            try:
                await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=plan_id)
            except RuntimeError as exc:
                assert str(exc) == "injected_after_flush"
                await db.rollback()
            else:
                raise AssertionError("late failure not injected")
    assert await state() == before
    checks.append("late_failure_rolls_back_all_placement_training_marker_receipt_writes")

    # Real concurrent confirmation: exactly one commit, loser conflict, same receipt
    # available on a new request. Hold both SERIALIZABLE snapshots before racing.
    entered, release = asyncio.Event(), asyncio.Event()
    ready_count = 0
    async def contender():
        nonlocal ready_count
        async with AsyncSession(runtime) as db:
            await context(db, schema, tenant, actor)
            ready_count += 1
            if ready_count == 2:
                entered.set()
            await release.wait()
            try:
                result = await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=plan_id)
                await db.commit()
                return ("committed", result)
            except DBAPIError as exc:
                assert is_change_conflict(exc)
                await db.rollback()
                return ("conflict", None)
    tasks = [asyncio.create_task(contender()) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), timeout=30)
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), timeout=60)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert sorted(o[0] for o in outcomes) == ["committed", "conflict"]
    receipt = next(o[1] for o in outcomes if o[0] == "committed")
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        assert await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=plan_id) == receipt
        assert await db.scalar(text("SELECT count(*) FROM enrollments WHERE user_id=:u"), {"u": user}) == 6
    after = await state()
    old_rows = {row["id"]: row for row in before["enrollments"]}
    new_rows = {row["id"]: row for row in after["enrollments"]}
    assert all(new_rows[key] == row for key, row in old_rows.items())
    checks.append("two_serializable_confirmations_commit_once_and_replay_exact_receipt")
    checks.append("completed_manual_cohort_and_program_enrollments_byte_unchanged")

    # Competing assignment insertion between preview snapshot and write. A real
    # PostgreSQL unique/serialization conflict must not leave half a transfer.
    user2 = await student()
    plan2, _ = await preview(command(user2))
    before = await state()
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        from app.modules.organization_units import change_service
        calculate = change_service._calculate
        original_snapshot = change_service.load_impact_snapshot
        async def insert_competitor(session, tenant_id, *, command):
            snapshot = await original_snapshot(session, tenant_id, command=command)
            async with owner.begin() as other:
                await context(other, schema)
                await other.execute(text("INSERT INTO enrollments(id,tenant_id,user_id,course_id,status,source,content_release_id) VALUES (:id,:t,:u,:c,'enrolled','manual',:r)"),
                                    {"id": uuid4(), "t": tenant, "u": user2, "c": ids["c2"], "r": ids["r2"]})
            # Validate that the captured snapshot genuinely requires an addition.
            assert len(calculate(snapshot, command)["additions"]) == 1
            return snapshot
        with patch.object(change_service, "load_impact_snapshot", new=insert_competitor):
            try:
                await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=plan2)
                await db.commit()
            except DBAPIError as exc:
                if not is_change_conflict(exc):
                    raise
                await db.rollback()
            else:
                raise AssertionError("competing insertion did not conflict")
    after = await state()
    assert after["users"] == before["users"]
    assert after["organization_change_plans"] == before["organization_change_plans"]
    assert after["organization_transfer_retained_enrollments"] == before["organization_transfer_retained_enrollments"]
    assert len(after["enrollments"]) == len(before["enrollments"]) + 1
    checks.append("competing_assignment_insert_conflict_no_partial_transfer")

    # Unit move operates on primary effective placement, including position fallback.
    plan3, view = await preview({"kind": "unit", "target_id": str(ids["ua"]), "organization_unit_id": str(ids["ub"]), "reason": "Move synthetic subtree"})
    assert view["affected_employees"] == 1 and view["training"]["added"] == 0  # user2 has the competing manual course already
    before_rows = (await state())["enrollments"]
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        receipt = await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=plan3)
        await db.commit()
        assert receipt["affected_employees"] == 1
    assert (await state())["enrollments"] == before_rows
    checks.append("unit_move_includes_fallback_members_and_preserves_existing_learning")

    # Cancelled/superseded historical occurrences are preserved, not mistaken
    # for current access. Completed history still satisfies the training rule.
    for status in ("cancelled", "superseded", "completed"):
        historical_user = await student()
        historical_id = uuid4()
        async with owner.begin() as db:
            await context(db, schema)
            await db.execute(text("INSERT INTO enrollments(id,tenant_id,user_id,course_id,status,source,content_release_id,completed_at) VALUES (:e,:t,:u,:c,:status,'manual',:r,CASE WHEN :status='completed' THEN now() ELSE NULL END)"),
                {"e": historical_id, "t": tenant, "u": historical_user, "c": ids["c2"], "r": ids["r2"], "status": status})
        previous = next(row for row in (await state())["enrollments"] if row["id"] == str(historical_id))
        next_plan, view = await preview(command(historical_user))
        expected = 0 if status == "completed" else 1
        assert view["training"]["added"] == expected
        async with AsyncSession(runtime) as db:
            await context(db, schema, tenant, actor)
            result = await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=next_plan)
            await db.commit()
        async with AsyncSession(runtime) as db:
            await context(db, schema, tenant, actor)
            assert await confirm_change(db, tenant_id=tenant, actor_id=actor, plan_id=next_plan) == result
            count = await db.scalar(text("SELECT count(*) FROM enrollments WHERE user_id=:u AND course_id=:c AND status IN ('enrolled','in_progress')"),
                {"u": historical_user, "c": ids["c2"]})
            assert count == expected
        current = next(row for row in (await state())["enrollments"] if row["id"] == str(historical_id))
        assert current == previous
        checks.append("historical_" + status + "_preserved_correct_current_access_and_replay")

    # A normal employee transfer must not load >25k unrelated historic rows.
    # All rows live only in this disposable owned schema and disappear on cleanup.
    unrelated_user = await student()
    async with owner.begin() as db:
        await context(db, schema)
        await db.execute(text("INSERT INTO enrollments(id,tenant_id,user_id,course_id,status,source,content_release_id) SELECT gen_random_uuid(),:t,:u,:c,'cancelled','manual',:r FROM generate_series(1,25001)"),
            {"t": tenant, "u": unrelated_user, "c": ids["c1"], "r": ids["r1"]})
    from app.modules.organization_units.change_service import load_impact_snapshot
    async with AsyncSession(runtime) as db:
        await context(db, schema, tenant, actor)
        count = await db.scalar(text("SELECT count(*) FROM enrollments WHERE tenant_id=:t"), {"t": tenant})
        assert count > 25000
        snapshot = await load_impact_snapshot(db, tenant, command=command(ids["sa"]))
        assert snapshot["enrollments"] and len(snapshot["enrollments"]) < 10
        assert {row["user_id"] for row in snapshot["enrollments"]} == {str(ids["sa"])}
    await preview(command(ids["sa"]))
    checks.append("employee_preview_succeeds_with_25001_unrelated_historical_rows")
