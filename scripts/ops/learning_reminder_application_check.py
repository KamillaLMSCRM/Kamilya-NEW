"""Synthetic assembled-chain check, invoked only by the isolated DEV runner.

Real handlers/ORM/materializer/store/renderer and migration0152; schema-only
legacy table copies, test tenant policies, synthetic identity, memory broker and
recording transport. This is NOT historical-migration or production acceptance.
"""

from __future__ import annotations

import asyncio
import ast
import re
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


async def check_application(admin, app_engine, schema: str) -> list[str]:
    assert re.fullmatch(r"r2_reminder_[0-9a-f]{32}", schema)
    from learning_reminder_dev_check import TABLES

    from app.core import config

    # Never bind imported application defaults to real providers or databases.
    settings = config.Settings(
        _env_file=None,
        APP_ENV="test",
        JWT_SECRET="synthetic-reminder-gate-only-000000000000",
        DATABASE_URL="postgresql+asyncpg://unused:unused@invalid.invalid/unused",
        REDIS_URL="redis://invalid.invalid:1/0",
        LEARNING_REMINDERS_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="synthetic-no-network",
        PUBLIC_URL="https://synthetic.example",
    )
    checks: list[str] = []
    async with admin.begin() as conn:
        # LIKE INCLUDING ALL does not copy triggers. Preserve the real historical
        # ownership guard at this boundary so impersonation cannot evade it in tests.
        source = Path(__file__).resolve().parents[2] / "apps/api/alembic/versions/0143_learning_path_cycle_instances.py"
        statements = [
            node.value for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.startswith("CREATE OR REPLACE FUNCTION validate_recurring_learning_rule_ownership()")
            and "NEW.learning_path_id" in node.value
        ]
        assert len(statements) == 1, "canonical_ownership_guard_ambiguous"
        guard = statements[0].replace(
            "FUNCTION validate_recurring_learning_rule_ownership()",
            f'FUNCTION "{schema}".validate_recurring_learning_rule_ownership()',
        ).replace("search_path=public,pg_temp", f'search_path="{schema}",pg_temp')
        assert "public" not in guard
        await conn.execute(text(f'CREATE TABLE "{schema}".user_roles (user_id uuid,tenant_id uuid,role text)'))
        await conn.execute(text(f'GRANT SELECT ON "{schema}".user_roles TO lms_app'))
        await conn.execute(text(guard))
        await conn.execute(text(
            f'CREATE TRIGGER synthetic_real_rule_ownership BEFORE INSERT OR UPDATE ON "{schema}".recurring_learning_rules '
            f'FOR EACH ROW EXECUTE FUNCTION "{schema}".validate_recurring_learning_rule_ownership()'
        ))
        for table in (*TABLES, "content_releases"):
            key = "id" if table == "tenants" else "tenant_id"
            await conn.execute(text(f'ALTER TABLE "{schema}".{table} ENABLE ROW LEVEL SECURITY'))
            await conn.execute(text(f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY'))
            await conn.execute(
                text(
                    f'CREATE POLICY synthetic_tenant ON "{schema}".{table} TO lms_app '
                    f"USING ({key}=nullif(current_setting('app.tenant_id',true),'')::uuid) "
                    f"WITH CHECK ({key}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
                )
            )
            await conn.execute(text(f'CREATE POLICY fixture_owner ON "{schema}".{table} TO CURRENT_USER USING(true)'))
            await conn.execute(text(f'REVOKE ALL ON "{schema}".{table} FROM PUBLIC'))
            await conn.execute(text(f'GRANT SELECT,INSERT,UPDATE ON "{schema}".{table} TO lms_app'))
        await conn.execute(
            text(
                f'CREATE FUNCTION "{schema}".set_current_tenant(p_tid text) RETURNS text '
                "LANGUAGE sql AS $$ SELECT set_config('app.tenant_id',p_tid,true) $$"
            )
        )

    function_names = (
        "enqueue_learning_reminder",
        "claim_learning_reminder",
        "learning_reminder_payload",
        "begin_learning_reminder_send",
        "finalize_learning_reminder",
        "learning_reminder_statuses",
    )
    pattern = re.compile(r"\bpublic\.(" + "|".join(function_names) + r")\b")

    def namespace(_conn, _cursor, statement, parameters, _context, _many):
        # Test adapter only: exact module function names, never arbitrary public SQL.
        statement = pattern.sub(lambda m: f'"{schema}".{m[1]}', statement)
        assert not re.search(r'\bpublic\.|"public"\.', statement), "unexpected_public_sql"
        return statement, parameters

    def begin(conn):
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}",pg_catalog')

    worker_engine = create_async_engine(
        app_engine.url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"timeout": 12, "command_timeout": 20},
    )
    for engine in (app_engine, worker_engine):
        event.listen(engine.sync_engine, "before_cursor_execute", namespace, retval=True)
        event.listen(engine.sync_engine, "begin", begin)
    sessions = async_sessionmaker(
        app_engine.execution_options(schema_translate_map={None: schema}), expire_on_commit=False
    )
    worker_sessions = async_sessionmaker(
        worker_engine.execution_options(schema_translate_map={None: schema}), expire_on_commit=False
    )
    owner_sessions = async_sessionmaker(
        admin.execution_options(schema_translate_map={None: schema}), expire_on_commit=False
    )

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(config, "get_settings", return_value=settings))
            from celery import Celery
            from celery.contrib.testing.worker import start_worker
            from fastapi import FastAPI, Request
            from httpx import ASGITransport, AsyncClient

            from app.core.auth import get_current_active_user
            from app.core.db import get_db
            from app.core.email import EmailDeliveryError, EmailService
            from app.models.courses import Course
            from app.models.tenants import Tenant
            from app.models.users import User
            from app.modules.courses.release_models import ContentRelease
            from app.modules.learning_cycles import router, service
            from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
            from app.modules.learning_reminders import tasks

            stack.enter_context(patch.object(service, "async_session_factory", sessions))
            stack.enter_context(patch.object(service, "get_settings", return_value=settings))
            # Initial assignment delivery is a separate unchanged module, not this gate.
            stack.enter_context(
                patch.object(service, "queue_manual_enrollment_notification", AsyncMock(return_value=None))
            )
            tenant, other, methodologist, learner, course, release = [uuid4() for _ in range(6)]
            platform_actor = uuid4()
            async with owner_sessions() as db:
                db.add_all(
                    [
                        Tenant(
                            id=tid,
                            name="Synthetic <tenant>",
                            slug=f"synthetic-{tid.hex}",
                            status="active",
                            plan="free",
                            settings={},
                        )
                        for tid in (tenant, other)
                    ]
                )
                db.add_all(
                    [
                        User(
                            id=methodologist,
                            tenant_id=tenant,
                            first_name="Synthetic",
                            last_name="Methodologist",
                            role="methodologist",
                            status="active",
                            is_active=True,
                        ),
                        User(
                            id=learner,
                            tenant_id=tenant,
                            first_name="Synthetic",
                            last_name="Learner",
                            email="learner@example.invalid",
                            role="student",
                            status="active",
                            is_active=True,
                            email_verified_at=datetime.now(UTC),
                        ),
                    ]
                )
                db.add(
                    Course(
                        id=course,
                        tenant_id=tenant,
                        title="Synthetic <training>",
                        description="",
                        status="published",
                        delivery_type="native",
                        current_release_id=release,
                        created_by=methodologist,
                        review_status="approved",
                    )
                )
                db.add(
                    ContentRelease(
                        id=release,
                        tenant_id=tenant,
                        course_id=course,
                        version=1,
                        snapshot={"synthetic": True},
                        snapshot_sha256="0" * 64,
                    )
                )
                await db.commit()

            api = FastAPI()
            api.include_router(router.router, prefix="/api/v1")

            async def identity(request: Request):
                impersonating = request.headers.get("x-test-impersonating") == "true"
                return SimpleNamespace(
                    id=platform_actor if impersonating else methodologist,
                    tenant_id=UUID(request.headers.get("x-test-tenant", str(tenant))),
                    role=request.headers.get("x-test-role", "methodologist"),
                    is_impersonating=impersonating,
                )

            # Annotation binding is explicit because Request is a local import.
            identity.__annotations__["request"] = Request

            async def db_override(request: Request):
                async with sessions() as db:
                    await db.execute(
                        text("SELECT set_current_tenant(:tid)"),
                        {"tid": request.headers.get("x-test-tenant", str(tenant))},
                    )
                    yield db
                    await db.commit()

            db_override.__annotations__["request"] = Request
            api.dependency_overrides[get_current_active_user] = identity
            api.dependency_overrides[get_db] = db_override
            deliveries: list[dict] = []
            transient_once = {"enabled": False}

            async def record_transport(_self, **payload):
                assert payload["to_email"] == "learner@example.invalid"
                assert "&lt;training&gt;" in payload["html"]
                assert payload["idempotency_key"].startswith("learning-reminder/")
                deliveries.append(payload)
                if transient_once["enabled"]:
                    transient_once["enabled"] = False
                    raise EmailDeliveryError("provider_timeout", "synthetic timeout")
                return "synthetic-message-id"

            stack.enter_context(patch.object(EmailService, "_send_resend", record_transport))
            stack.enter_context(patch.object(EmailService, "_send_smtp", side_effect=AssertionError("smtp_forbidden")))
            # A network escape must fail, including if a future renderer changes transport.
            stack.enter_context(patch("httpx.AsyncClient.post", side_effect=AssertionError("external_http_forbidden")))
            original_deliver = tasks.deliver
            stack.enter_context(
                patch.object(
                    tasks,
                    "deliver",
                    partial(original_deliver, session_factory=worker_sessions, settings_factory=lambda: settings),
                )
            )
            queue = Celery("synthetic_reminder_gate", broker="memory://", backend="cache+memory://")
            queue.conf.update(
                task_always_eager=False,
                task_default_queue="notifications",
                task_serializer="json",
                accept_content=["json"],
                result_serializer="json",
                worker_hijack_root_logger=False,
            )
            queued_task = queue.task(name="learning_reminders.deliver")(tasks.deliver_learning_reminder_task.run)

            def consume(reminder_id):
                with start_worker(queue, pool="solo", concurrency=1, perform_ping_check=False, loglevel="ERROR"):
                    result = queued_task.apply_async(args=[str(tenant), str(reminder_id)], queue="notifications")
                    return result.get(timeout=35, disable_sync_subtasks=False)

            async with AsyncClient(transport=ASGITransport(app=api), base_url="http://synthetic") as client:
                # Use request(), leaving post() blocked globally for transport escape detection.
                response = await client.request(
                    "POST",
                    "/api/v1/learning-cycles",
                    headers={"x-test-impersonating": "true"},
                    json={"course_id": str(course), "user_id": str(learner), "cadence_days": 30, "due_days": 1},
                )
                assert response.status_code == 201, "create_rule_failed"
                checks.append("actual_HTTP_impersonated_rule_create_with_historical_tenant_author_guard")
                rule_id = UUID(response.json()["id"])
                path = f"/api/v1/learning-cycles/{rule_id}"
                assert response.json()["reminder_enabled"] is False
                for invalid in (0, 31):
                    assert (await client.patch(path, json={"reminder_days_before_due": invalid})).status_code == 422
                for role in ("student", "admin", "superadmin"):
                    assert (
                        await client.patch(path, headers={"x-test-role": role}, json={"reminder_enabled": True})
                    ).status_code == 403
                    assert (await client.get(path + "/reminders", headers={"x-test-role": role})).status_code == 403
                foreign = {"x-test-tenant": str(other)}
                assert (await client.patch(path, headers=foreign, json={"reminder_enabled": True})).status_code == 404
                assert (await client.get(path + "/reminders", headers=foreign)).status_code == 404
                assert (await client.get("/api/v1/learning-cycles", headers=foreign)).json() == []
                saved = await client.patch(path, json={"reminder_enabled": True, "reminder_days_before_due": 1})
                assert saved.status_code == 200 and saved.json()["reminder_enabled"] is True
                assert (saved.json()["cadence_days"], saved.json()["due_days"]) == (30, 1)
                assert (await client.get(path + "/reminders")).json() == []
                checks.append("actual_HTTP_rule_validation_roles_tenants_and_settings")
                assert (await client.request("POST", path + "/activate")).status_code == 200
                assert (await service.materialize_rule(rule_id, tenant))["status"] == "materialized"
                assert (await service.materialize_rule(rule_id, tenant))["status"] == "skipped"
                statuses = (await client.get(path + "/reminders")).json()
                assert len(statuses) == 1 and statuses[0]["status"] == "queued"
                reminder_id = UUID(statuses[0]["id"])
                async with owner_sessions() as db:
                    occurrence = (
                        await db.scalars(
                            select(RecurringLearningAssignment).where(RecurringLearningAssignment.rule_id == rule_id)
                        )
                    ).one()
                    assert occurrence.enrollment_id is not None
                checks.append("actual_materialization_commits_occurrence_enrollment_and_one_reminder")
                # Time eligibility is now (lead=due=1); no outbox fixture insertion.
                result = await asyncio.to_thread(consume, reminder_id)
                assert result["status"] == "sent", "queued_worker_not_sent"
                assert len(deliveries) == 1
                statuses = (await client.get(path + "/reminders")).json()
                assert statuses[0]["status"] == "sent" and statuses[0]["attempt_count"] == 1
                assert statuses[0]["delivered_at"]
                assert not ({"email", "payload_hash", "claim_token", "delivery_message_id"} & statuses[0].keys())
                assert (await asyncio.to_thread(consume, reminder_id))["status"] == "skipped"
                assert len(deliveries) == 1
                checks.append("memory_broker_actual_Celery_wrapper_store_renderer_durable_sent_and_duplicate")
                # Second real materialization, temporary timeout then deterministic same-key retry.
                async with owner_sessions() as db:
                    rule = await db.get(RecurringLearningRule, rule_id)
                    rule.next_run_at = datetime.now(UTC) - timedelta(seconds=2)
                    await db.commit()
                assert (await service.materialize_rule(rule_id, tenant))["status"] == "materialized"
                statuses = (await client.get(path + "/reminders")).json()
                retry_id = UUID(next(item["id"] for item in statuses if item["status"] == "queued"))
                transient_once["enabled"] = True
                assert (await asyncio.to_thread(consume, retry_id))["status"] == "transient"
                async with admin.begin() as conn:
                    row = (
                        await conn.execute(
                            text(f'SELECT status,attempt_count FROM "{schema}".learning_reminder_outbox WHERE id=:id'),
                            {"id": retry_id},
                        )
                    ).one()
                    assert tuple(row) == ("queued", 1)
                    # Advance retry clock only for this generated synthetic row.
                    await conn.execute(
                        text(f'UPDATE "{schema}".learning_reminder_outbox SET next_attempt_at=now() WHERE id=:id'),
                        {"id": retry_id},
                    )
                assert (await asyncio.to_thread(consume, retry_id))["status"] == "sent"
                assert deliveries[-1] == deliveries[-2]
                checks.append("real_worker_timeout_retry_same_payload_and_idempotency_key")

                # A failure after enqueue must roll back all three durable records.
                async with owner_sessions() as db:
                    rule = await db.get(RecurringLearningRule, rule_id)
                    rule.next_run_at = datetime.now(UTC) - timedelta(seconds=2)
                    await db.commit()
                original_queue = service._queue_reminder

                async def fail_after_enqueue(*args, **kwargs):
                    await original_queue(*args, **kwargs)
                    raise RuntimeError("synthetic_after_enqueue")

                with patch.object(service, "_queue_reminder", fail_after_enqueue):
                    try:
                        await service.materialize_rule(rule_id, tenant)
                    except RuntimeError as exc:
                        assert str(exc) == "synthetic_after_enqueue"
                    else:
                        raise AssertionError("rollback_failure_not_injected")
                async with admin.begin() as conn:
                    for table in ("recurring_learning_assignments", "enrollments", "learning_reminder_outbox"):
                        count = await conn.scalar(
                            text(f'SELECT count(*) FROM "{schema}".{table} WHERE tenant_id=:t'), {"t": tenant}
                        )
                        assert count == 2, "materialization_rollback_incomplete"
                checks.append("transaction_rollback_occurrence_enrollment_and_outbox")

                assert (await service.materialize_rule(rule_id, tenant))["status"] == "materialized"
                statuses = (await client.get(path + "/reminders")).json()
                suppressed_id = UUID(next(item["id"] for item in statuses if item["status"] == "queued"))
                assert (await client.patch(path, json={"reminder_enabled": False})).status_code == 200
                assert (await asyncio.to_thread(consume, suppressed_id))["status"] == "skipped"
                statuses = (await client.get(path + "/reminders")).json()
                suppressed = next(item for item in statuses if item["id"] == str(suppressed_id))
                assert suppressed["status"] == "skipped" and suppressed["attempt_count"] == 0
                assert len(deliveries) == 3
                assert (await client.patch(path, json={"reminder_enabled": True})).status_code == 200
                checks.append("API_opt_out_suppresses_queued_delivery_without_provider_attempt")

            # SQL login property parity: all supported login proofs and empty case.
            async with admin.begin() as conn:
                for password, telegram, verified, expected in (
                    (None, None, None, False),
                    ("", None, None, False),
                    ("synthetic-hash", None, None, True),
                    (None, 0, None, True),
                    (None, None, datetime.now(UTC), True),
                ):
                    await conn.execute(
                        text(
                            f'UPDATE "{schema}".users SET password_hash=:p,telegram_id=:t,email_verified_at=:v WHERE id=:id'
                        ),
                        {"p": password, "t": telegram, "v": verified, "id": learner},
                    )
                    value = await conn.scalar(
                        text(f'SELECT has_login_access FROM "{schema}"._learning_reminder_targets(:tid,:occ,NULL)'),
                        {"tid": tenant, "occ": occurrence.id},
                    )
                    user = User(password_hash=password, telegram_id=telegram, email_verified_at=verified)
                    assert value == user.has_login_access == expected
            checks.append("login_property_physical_column_parity")
            queue.close()
    finally:
        for engine in (app_engine, worker_engine):
            event.remove(engine.sync_engine, "before_cursor_execute", namespace)
            event.remove(engine.sync_engine, "begin", begin)
        await worker_engine.dispose()
    return checks
