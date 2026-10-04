"""Owned-schema interpretation/admission proof, zero provider or public writes."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import GateBlocked
from workbench_assignment_dev_gate import context, safe_schema


async def verify_intent(owner_engine, runtime_engine, schema, actor, other_tenant, other_actor, learner_id, now):
    from app.modules.ai.budget import check_and_charge_llm_budget
    from app.modules.methodologist_workbench.assignment_schemas import AssignmentInterpretRequest, AssignmentPreviewRequest
    from app.modules.methodologist_workbench.assignment_service import WorkbenchNotFound, create_assignment_preview
    from app.modules.methodologist_workbench.intent_application import interpret_assignment

    qualified = safe_schema(schema)
    async with owner_engine.begin() as connection:
        await connection.execute(text(f"CREATE TABLE {qualified}.tenant_llm_usage (LIKE public.tenant_llm_usage INCLUDING ALL)"))
        await connection.execute(text(f"GRANT SELECT,INSERT,UPDATE ON {qualified}.tenant_llm_usage TO lms_app"))
        await connection.execute(text(f"ALTER TABLE {qualified}.tenant_llm_usage ENABLE ROW LEVEL SECURITY"))
        await connection.execute(text(f"ALTER TABLE {qualified}.tenant_llm_usage FORCE ROW LEVEL SECURITY"))
        await connection.execute(text(f"CREATE POLICY tenant_isolation ON {qualified}.tenant_llm_usage USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"))
        await connection.execute(text(f"CREATE FUNCTION {qualified}.set_current_tenant(tenant_uuid UUID) RETURNS void LANGUAGE plpgsql AS $$ BEGIN PERFORM set_config('app.tenant_id', tenant_uuid::text, true); END; $$"))
        await connection.execute(text(f"REVOKE ALL ON FUNCTION {qualified}.set_current_tenant(UUID) FROM PUBLIC"))
        await connection.execute(text(f"GRANT EXECUTE ON FUNCTION {qualified}.set_current_tenant(UUID) TO lms_app"))
        # Earlier invitation checks already create these settings; update only
        # the exact owned fixture, never insert a second tenant settings row.
        updated = await connection.execute(
            text(f"UPDATE {qualified}.tenant_settings SET monthly_llm_budget_usd_cents=1 WHERE tenant_id=:tenant"),
            {"tenant": actor.tenant_id},
        )
        if updated.rowcount != 1:
            raise GateBlocked("intent_owned_settings_missing")
        # The preceding stale-membership check deliberately deactivates this
        # synthetic learner. Restore only that learner for a fresh preview.
        restored = await connection.execute(
            text(f"UPDATE {qualified}.users SET status='active' WHERE id=:learner AND tenant_id=:tenant"),
            {"learner": learner_id, "tenant": actor.tenant_id},
        )
        if restored.rowcount != 1:
            raise GateBlocked("intent_owned_learner_missing")

    # Dedicated engine: EVERY transaction including post-admission refund has an
    # owned-only search path. Never let unqualified application SQL hit public.
    isolated = create_async_engine(runtime_engine.url, poolclass=NullPool, hide_parameters=True)

    @event.listens_for(isolated.sync_engine, "begin")
    def bind_owned_path(connection):
        connection.exec_driver_sql(f"SET LOCAL search_path TO {qualified}, pg_catalog")

    checks = []
    provider_calls = 0
    due = (now + timedelta(days=4)).date().isoformat()
    content = json.dumps({"action": "assignment_preview", "course_query": "Gate course", "department_query": "Gate department", "due_date": due, "notify": False, "include_descendants": False})

    async def invoke(_messages):
        nonlocal provider_calls
        provider_calls += 1
        return SimpleNamespace(content=content)

    async def resolver(_tenant):
        return SimpleNamespace(ainvoke=invoke)

    body = AssignmentInterpretRequest(instruction=f"Подготовь курс Gate course отделу Gate department до {due}", timezone_name="UTC")
    try:
        # Generation estimate10 cannot insert into an empty monthly budget1.
        async with AsyncSession(isolated) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            try:
                await check_and_charge_llm_budget(db, str(actor.tenant_id))
            except HTTPException as exc:
                if exc.status_code != 429:
                    raise
                await db.rollback()
            else:
                raise GateBlocked("intent_first_insert_budget_bypass")
        checks.append("positive_budget_first_insert_denied")
        async with AsyncSession(isolated, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            result = await interpret_assignment(db, actor, body, provider_resolver=resolver, now=now)
            if result.state != "interpreted" or provider_calls != 1:
                raise GateBlocked("intent_interpretation_mismatch")
            await db.commit()
            await context(db, schema, actor.tenant_id, actor.actor_id)
            preview = await create_assignment_preview(db, actor, AssignmentPreviewRequest(instruction=body.instruction, timezone_name="UTC", candidate=result.candidate), now=now)
            if preview.state != "preview_ready" or preview.notify:
                raise GateBlocked("intent_candidate_preview_mismatch")
            await db.commit()
        checks.append("interpretation_candidate_to_owned_preview")
        async with AsyncSession(isolated, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            quoted = result.candidate.model_copy(update={"course_query": "«Gate course»", "department_query": '"Gate department"'})
            wrapped_preview = await create_assignment_preview(db, actor, AssignmentPreviewRequest(instruction=body.instruction, timezone_name="UTC", candidate=quoted), now=now)
            if wrapped_preview.state != "preview_ready" or wrapped_preview.course_id != preview.course_id or wrapped_preview.department_id != preview.department_id:
                raise GateBlocked("intent_quoted_resource_fallback_mismatch")
            if quoted.course_query != "«Gate course»" or quoted.department_query != '"Gate department"':
                raise GateBlocked("intent_candidate_mutated_by_resolution")
            await db.commit()
        checks.append("quoted_candidate_exact_fallback_owned_and_immutable")
        async with AsyncSession(isolated) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            try:
                await interpret_assignment(db, actor, body, provider_resolver=resolver, now=now)
            except HTTPException as exc:
                if exc.status_code != 429:
                    raise
                await db.rollback()
            else:
                raise GateBlocked("intent_budget_exhaustion_bypass")
        if provider_calls != 1:
            raise GateBlocked("intent_provider_called_after_budget_denial")
        checks.append("budget_denial_before_provider")
        for foreign in (actor.model_copy(update={"actor_id": other_actor}), actor.model_copy(update={"tenant_id": other_tenant})):
            async with AsyncSession(isolated) as db:
                await context(db, schema, foreign.tenant_id, foreign.actor_id)
                try:
                    await interpret_assignment(db, foreign, body.model_copy(update={"previous_plan_id": preview.plan_id}), provider_resolver=resolver)
                except WorkbenchNotFound:
                    await db.rollback()
                else:
                    raise GateBlocked("intent_foreign_previous_plan_visible")
        if provider_calls != 1:
            raise GateBlocked("intent_provider_called_for_foreign_previous")
        checks.append("previous_actor_and_tenant_denied_before_provider")
        async with owner_engine.begin() as connection:
            await connection.execute(text(f"UPDATE {qualified}.tenant_settings SET monthly_llm_budget_usd_cents=2 WHERE tenant_id=:tenant"), {"tenant": actor.tenant_id})

        async def failing_resolver(_tenant):
            raise RuntimeError("synthetic controlled failure")

        async with AsyncSession(isolated) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            failure = await interpret_assignment(db, actor, body, provider_resolver=failing_resolver, now=now)
            if failure.code != "intent_provider_unavailable":
                raise GateBlocked("intent_controlled_failure_mismatch")
            await db.commit()
            await context(db, schema, actor.tenant_id, actor.actor_id)
            cost = await db.scalar(text("SELECT cost_cents FROM tenant_llm_usage WHERE tenant_id=:tenant"), {"tenant": actor.tenant_id})
            if cost != 1:
                raise GateBlocked("intent_post_commit_refund_context_lost")
        checks.append("failure_refund_after_commit_rls_rebound")

        async def reserve():
            async with AsyncSession(isolated) as db:
                await context(db, schema, actor.tenant_id, actor.actor_id)
                try:
                    await check_and_charge_llm_budget(db, str(actor.tenant_id), operation="assignment_intent_parse", estimated_cost_cents=1)
                    await db.commit()
                    return "reserved"
                except HTTPException as exc:
                    await db.rollback()
                    if exc.status_code != 429:
                        raise
                    return "denied"

        if sorted(await asyncio.gather(reserve(), reserve())) != ["denied", "reserved"]:
            raise GateBlocked("intent_concurrent_budget_overrun")
        checks.append("concurrent_budget_reservations_bounded")
        async with AsyncSession(isolated) as db:
            await context(db, schema, other_tenant, other_actor)
            if await db.scalar(text("SELECT count(*) FROM tenant_llm_usage")) != 0:
                raise GateBlocked("intent_foreign_usage_visible")
        checks.append("usage_force_rls_foreign_hidden")
        return checks
    finally:
        await isolated.dispose()
