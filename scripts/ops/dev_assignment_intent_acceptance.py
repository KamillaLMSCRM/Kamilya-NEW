"""One-shot actual DEV intent application, synthetic fixed actor, no assignment.

Invoked only behind dev_private_model_acceptance's expiring API-only gate.
No HTTP endpoint, global provider mutation, customer input or ASUS call.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

TENANT = UUID("a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0")
ACTOR = UUID("5187fa5f-c046-4e35-945e-5c95f469a886")


def receipt_key(run_id: str) -> str:
    return f"qa:dev-private-models:{run_id}:api:receipt"


async def hanging(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        async with asyncio.timeout(35):
            await reader.readuntil(b"\r\n\r\n")
            # Deliberate local no-response, longer than the actual primary30s cap.
            await reader.read()
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def run_assignment() -> dict:
    from redis.asyncio import Redis
    from sqlalchemy import select, text
    from app.core.auth import _set_tenant_security_context, _set_user_security_context
    from app.core.config import get_settings
    from app.core.db import async_session_factory, engine
    from app.models.users import User
    from app.models.tenants import Tenant
    from app.modules.ai import llm_client as llm
    from app.modules.methodologist_workbench.intent_application import interpret_assignment
    from app.modules.methodologist_workbench.assignment_schemas import AssignmentInterpretRequest
    from app.modules.methodologist_workbench.plan_contract import ActorContext
    from dev_private_model_acceptance import enabled

    env = dict(os.environ)
    if not enabled(env, datetime.now(UTC)) or env.get("DEV_MODEL_ACCEPTANCE_SCOPE") != "assignment_intent":
        return {"status": "DISABLED_OR_EXPIRED_NO_INFERENCE"}
    run_id = env["DEV_MODEL_ACCEPTANCE_ID"]
    prefix = f"qa:dev-private-models:{run_id}:api"
    report = {"run_id": run_id, "role": "api", "executed_scope": "assignment_intent",
        "release_sha": env.get("RENDER_GIT_COMMIT", "unknown"), "cases": [],
        "fault_mode": "invocation_local_primary_hang", "production_writes": 0,
        "persisted_failure_overrides": 0,
        "glm": "NOT_RUN_OWNER_DEFERRED_ASUS_DOWN", "status": "FAIL"}
    redis = Redis.from_url(get_settings().REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    claimed = False
    try:
        claimed = bool(await redis.set(prefix, "claimed", nx=True, ex=3600))
        if not claimed:
            return {**report, "status": "ALREADY_CLAIMED_NO_INFERENCE"}
        # Wait for normal saved runtime initialization, without making model calls.
        from app.modules.admin.model_routing.runtime import resolve_runtime_generation_model_order
        async with asyncio.timeout(90):
            while await resolve_runtime_generation_model_order() != ("deepseek", "chatgpt_reserve", "glm53_flash"):
                await asyncio.sleep(3)
        server = await asyncio.start_server(hanging, "127.0.0.1", 0, limit=8192)
        try:
            for forced in (False, True):
                if not enabled(env, datetime.now(UTC)):
                    raise TimeoutError("acceptance_expired")
                attempts = []
                async def resolver(tenant_id):
                    if tenant_id != TENANT:
                        raise ValueError("tenant_mismatch")
                    source = await llm.ResilientLLMClient.from_settings_async(
                        tenant_id=tenant_id, temperature=0, max_tokens=1200, max_retries_per_provider=0)
                    if source.provider_names != ["deepseek", "chatgpt-reserve", "glm53-flash-asus"]:
                        raise ValueError("route_mismatch")
                    configs = [client.config for client in source._clients[:2 if forced else 1]]
                    if forced:
                        configs[0] = replace(configs[0], base_url=f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1",
                            api_key="synthetic-control", max_retries=0, trust_env=False)
                    return llm.ResilientLLMClient(configs, temperature=0, max_tokens=1200, max_retries_per_provider=0)

                # Instrument transport only in this isolated probe process. The
                # real application creates bounded clones, not shared instances.
                original = llm.LLMClient._request
                async def recorded(client, payload):
                    attempts.append(client.name)
                    return await original(client, payload)
                llm.LLMClient._request = recorded
                row = {"case": "primary_hang_to_chatgpt" if forced else "real_deepseek"}
                started = time.monotonic()
                try:
                    async with async_session_factory() as db:
                        await _set_tenant_security_context(db, str(TENANT))
                        await _set_user_security_context(db, ACTOR)
                        user = (await db.execute(select(User).where(User.id == ACTOR, User.tenant_id == TENANT))).scalar_one()
                        if user.role != "methodologist" or not user.is_active:
                            raise ValueError("actor_identity_mismatch")
                        tenant = (await db.execute(select(Tenant).where(Tenant.id == TENANT))).scalar_one()
                        if tenant.slug != "kamilya-dev-qa" or tenant.notes != "KAMILYA_PERSISTENT_DEV_QA_V1":
                            raise ValueError("qa_fixture_marker_mismatch")
                        async def snapshot():
                            await _set_tenant_security_context(db, str(TENANT))
                            await _set_user_security_context(db, ACTOR)
                            values = (await db.execute(text("""
                                SELECT
                                  (SELECT count(*) FROM workbench_assignment_plans WHERE tenant_id=:t),
                                  (SELECT count(*) FROM enrollments WHERE tenant_id=:t),
                                  COALESCE((SELECT cost_cents FROM tenant_llm_usage WHERE tenant_id=:t AND month_key=:m),0),
                                  COALESCE((SELECT request_count FROM tenant_llm_usage WHERE tenant_id=:t AND month_key=:m),0)
                            """), {"t": TENANT, "m": datetime.now(UTC).strftime("%Y-%m")})).one()
                            return tuple(values)
                        before = await snapshot()
                        body = AssignmentInterpretRequest(
                            instruction='Срок — 20 декабря 2026 года в 18:00. Назначаем всему отделу, без дочерних подразделений и без уведомлений.',
                            instruction_history=['Назначь курс "QA TIMEOUT58" всему отделу "QA DIALOGUE52" завтра, без уведомлений.'],
                            timezone_name="Asia/Almaty", notify=False, include_descendants=False)
                        remaining = (datetime.fromisoformat(env["DEV_MODEL_ACCEPTANCE_UNTIL"]) - datetime.now(UTC)).total_seconds()
                        async with asyncio.timeout(min(95, remaining)):
                            answer = await interpret_assignment(db, ActorContext(tenant_id=TENANT, actor_id=ACTOR,
                                active_role="methodologist"), body, provider_resolver=resolver)
                        await db.commit()
                        after = await snapshot()
                        delta = tuple(end - start for start, end in zip(before, after, strict=True))
                        expected_charge = 1 if answer.state == "interpreted" else 0
                        side_effects_valid = delta == (0, 0, expected_charge, expected_charge)
                        await db.rollback()  # end the read-only readback transaction
                        valid = answer.state == "interpreted" and answer.candidate.model_dump() == {
                            "course_query": "QA TIMEOUT58", "department_query": "QA DIALOGUE52",
                            "due_date": "2026-12-20", "due_time": "18:00:00", "notify": False, "include_descendants": False}
                        expected = ["deepseek", "chatgpt-reserve"] if forced else ["deepseek"]
                        row.update(status="PASS" if valid and attempts == expected and side_effects_valid else "FAIL",
                            candidate_exact=valid, response_state=answer.state,
                            plans_created=delta[0], enrollments_created=delta[1],
                            usage_estimate_cents_delta=delta[2], usage_request_count_delta=delta[3],
                            side_effects_and_accounting_exact=side_effects_valid,
                            clarification_code=getattr(answer, "code", None))
                except Exception as exc:
                    row.update(status="FAIL", error_class=type(exc).__name__)
                finally:
                    llm.LLMClient._request = original
                row.update(elapsed_ms=round((time.monotonic() - started) * 1000), attempt_order=attempts)
                report["cases"].append(row)
                # Durable content-free receipts survive provider stdout loss.
                await redis.set(receipt_key(run_id), json.dumps(report), ex=3600)
                if row["status"] != "PASS":
                    break
            report["status"] = "PARTIAL_PASS" if len(report["cases"]) == 2 and all(row["status"] == "PASS" for row in report["cases"]) else "FAIL"
        finally:
            server.close()
            await server.wait_closed()
    except Exception as exc:
        report.update(status="FAIL", error_class=type(exc).__name__)
    finally:
        if claimed:
            await redis.set(receipt_key(run_id), json.dumps(report), ex=3600)
            await redis.set(prefix + ":terminal", report["status"], ex=3600)
        await redis.aclose()
        await engine.dispose()
    return report
