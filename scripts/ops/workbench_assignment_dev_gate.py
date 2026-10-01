#!/usr/bin/env python3
"""Migration/service gate in one owned disposable Supabase DEV schema.

No public DDL/DML, provider calls or email. Canonical env identities are checked
before connection; failures expose classes/stage only, never DSNs or payloads.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from kb_rag_isolated_dev_gate import (
    GateBlocked,
    assert_sanitized_evidence,
    normalize_database_url,
    same_supabase_project,
)
from source_actuality_dev_gate import public_snapshot, verify_runtime_role
from sqlalchemy import event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
MIGRATION = API_ROOT / "alembic" / "versions" / "0169_workbench_assignment_plans.py"
SCHEMA_RE = re.compile(r"^workbench_[0-9a-f]{12}$")
TABLES = (
    "tenants",
    "users",
    "user_roles",
    "departments",
    "positions",
    "courses",
    "content_releases",
    "enrollments",
    "enrollment_access_policies",
    "course_assignment_notification_outbox",
)


def safe_schema(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return f'"{value}"'


def safe_failure(exc: Exception) -> str:
    """Expose only code/schema identifiers, never SQL, values or DSNs."""
    if isinstance(exc, GateBlocked):
        return str(exc)
    identifiers = []
    current = exc
    for _ in range(6):
        class_name = type(current).__name__
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,80}", class_name)
            and class_name not in identifiers
        ):
            identifiers.append(class_name)
        for attribute in ("sqlstate", "constraint_name", "table_name", "column_name"):
            value = getattr(current, attribute, None)
            if isinstance(value, str) and re.fullmatch(
                r"[A-Za-z_][A-Za-z_0-9]{0,80}|[0-9A-Z]{5}", value
            ):
                if value not in identifiers:
                    identifiers.append(value)
        # Known static PostgreSQL diagnostics only; never echo arbitrary text.
        message = str(getattr(current, "message", ""))
        for fragment, category in (
            ("nullable side of an outer join", "outer_join_lock"),
            ("cached plan must not change result type", "cached_plan_type"),
            ("DISTINCT", "distinct_lock"),
            ("not implemented", "unsupported_operation"),
            ("transaction blocks", "transaction_operation"),
        ):
            if fragment in message and category not in identifiers:
                identifiers.append(category)
        current = getattr(current, "orig", None) or current.__cause__
        if current is None:
            break
    return ":".join(identifiers)


async def migration(connection, schema: str, operation: str = "upgrade") -> None:
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_action")
    spec = importlib.util.spec_from_file_location("workbench_migration0169", MIGRATION)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def apply(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(
            MigrationContext.configure(sync, opts={"version_table_schema": schema})
        ):
            getattr(module, operation)()

    await connection.run_sync(apply)


async def install_isolated_enqueue(connection, schema: str) -> None:
    """Use the canonical enqueue body, never the public SECURITY DEFINER target.

    A live body mismatch is a hard gate; do not copy arbitrary database DDL or
    call public enqueue from the test schema. No delivery/recovery functions
    are installed, so existing workers cannot discover these synthetic rows.
    """
    qualified = safe_schema(schema)
    source = (
        API_ROOT
        / "alembic"
        / "versions"
        / "0097_course_assignment_notification_outbox.py"
    )
    candidates = [
        node.value
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "CREATE FUNCTION enqueue_course_assignment_notification(" in node.value
    ]
    if len(candidates) != 1:
        raise GateBlocked("enqueue_source_ambiguous")
    original = candidates[0]
    old = "IF NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN"
    new = "IF p_assigned_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN"
    if (
        original.count(old) != 1
        or original.count("SET search_path = public, pg_temp") != 1
    ):
        raise GateBlocked("enqueue_source_drift")
    accepted = original.replace(old, new)
    expected_body = accepted.split("AS $$", 1)[1].rsplit("$$", 1)[0]
    live = (
        await connection.execute(
            text(
                "SELECT p.prosrc,p.prosecdef,l.lanname FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang "
                "WHERE p.oid='public.enqueue_course_assignment_notification(uuid,uuid,uuid)'::regprocedure"
            )
        )
    ).one()
    if (
        not live.prosecdef
        or live.lanname != "plpgsql"
        or " ".join(live.prosrc.split()) != " ".join(expected_body.split())
    ):
        raise GateBlocked("live_enqueue_body_not_accepted_source")
    ddl = accepted.replace(
        "CREATE FUNCTION enqueue_course_assignment_notification(",
        f"CREATE FUNCTION {qualified}.enqueue_course_assignment_notification(",
    )
    ddl = ddl.replace(
        "SET search_path = public, pg_temp", f"SET search_path = {qualified}, pg_temp"
    )
    await connection.execute(text(ddl))
    table = f"{qualified}.course_assignment_notification_outbox"
    await connection.execute(
        text(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app,lms_recovery")
    )
    await connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    await connection.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
    await connection.execute(
        text(
            f"CREATE POLICY gate_enqueue_owner ON {table} TO CURRENT_USER "
            "USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) "
            "WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)"
        )
    )
    signature = f"{qualified}.enqueue_course_assignment_notification(uuid,uuid,uuid)"
    await connection.execute(
        text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,lms_recovery")
    )
    await connection.execute(text(f"GRANT EXECUTE ON FUNCTION {signature} TO lms_app"))
    resolved = await connection.scalar(
        text(
            "SELECT n.nspname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE p.oid=to_regprocedure(:signature)"
        ),
        {"signature": signature},
    )
    if resolved != schema:
        raise GateBlocked("isolated_enqueue_missing")


async def context(session, schema: str, tenant_id, actor_id, *, superadmin=False):
    await session.execute(
        text(f"SET LOCAL search_path TO {safe_schema(schema)}, public")
    )
    await session.execute(
        text(
            "SELECT set_config('app.tenant_id', :tenant, true), "
            "set_config('app.user_id', :actor, true), "
            "set_config('app.is_superadmin', :super, true)"
        ),
        {
            "tenant": str(tenant_id),
            "actor": str(actor_id),
            "super": str(superadmin).lower(),
        },
    )


async def verify_notification_and_manual_overlap(
    owner_engine, runtime_engine, schema, actor, course_id, now
):
    """Actual transactions with activated synthetic learners; never dispatch."""
    from app.models.department import Department
    from app.models.users import User
    from app.modules.courses.models import Course
    from app.modules.enrollments.service import enroll_users
    from app.modules.methodologist_workbench.assignment_schemas import (
        AssignmentPreviewRequest,
    )
    from app.modules.methodologist_workbench.assignment_service import (
        WorkbenchConflict,
        confirm_assignment_plan,
        create_assignment_preview,
        get_assignment_plan,
    )
    from app.modules.methodologist_workbench.plan_contract import ConfirmationRequest

    department_ids, learner_ids = [uuid4(), uuid4()], [uuid4(), uuid4()]
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        for index, name in enumerate(("Notify department", "Overlap department")):
            db.add(
                Department(
                    id=department_ids[index],
                    tenant_id=actor.tenant_id,
                    name=name,
                    normalized_name=name.lower(),
                    slug=f"extended-{index}",
                )
            )
            db.add(
                User(
                    id=learner_ids[index],
                    tenant_id=actor.tenant_id,
                    role="student",
                    first_name="Synthetic",
                    last_name=f"Extended{index}",
                    organization_unit_id=department_ids[index],
                    password_hash="synthetic-non-credential",
                    email=f"workbench-{index}@example.invalid",
                )
            )
        await db.commit()

    async def preview(name, *, notify):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            resolved = await db.scalar(
                text(
                    "SELECT to_regprocedure('enqueue_course_assignment_notification(uuid,uuid,uuid)')::oid="
                    "to_regprocedure(:signature)::oid"
                ),
                {
                    "signature": f"{safe_schema(schema)}.enqueue_course_assignment_notification(uuid,uuid,uuid)"
                },
            )
            if resolved is not True:
                raise GateBlocked("runtime_enqueue_resolved_public")
            result = await create_assignment_preview(
                db,
                actor,
                AssignmentPreviewRequest(
                    instruction=f'Назначь курс "Gate course" отделу "{name}" до {(now + timedelta(days=3)).date()}',
                    timezone_name="UTC",
                    notify=notify,
                ),
                now=now,
            )
            if result.state != "preview_ready" or result.new_count != 1:
                raise GateBlocked("extended_preview_mismatch")
            await db.commit()
            request = ConfirmationRequest(
                plan_id=result.plan_id,
                revision=result.revision,
                fingerprint=result.fingerprint,
            )
            return request

    async def confirm(request):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            try:
                outcome = await confirm_assignment_plan(db, actor, request, now=now)
                await db.commit()
                return outcome
            except WorkbenchConflict as exc:
                await db.rollback()
                if str(exc) != "stale":
                    raise
                return None

    first, other = (
        await preview("Notify department", notify=True),
        await preview("Notify department", notify=True),
    )
    # A simulated post-flush failure must remove the outbox and receipt too.
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        outcome = await confirm_assignment_plan(db, actor, first, now=now)
        if (
            len(outcome.dispatch_ids) != 1
            or outcome.receipt.notification_state != "queued"
        ):
            raise GateBlocked("notification_not_queued")
        await db.rollback()
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        count = await db.scalar(
            text("SELECT count(*) FROM course_assignment_notification_outbox")
        )
        enrollment_count = await db.scalar(
            text("SELECT count(*) FROM enrollments WHERE user_id=:id"),
            {"id": learner_ids[0]},
        )
        ready = await db.scalar(
            text(
                "SELECT status='ready' AND receipt IS NULL FROM workbench_assignment_plans WHERE id=:id"
            ),
            {"id": first.plan_id},
        )
        if count != 0 or enrollment_count != 0 or ready is not True:
            raise GateBlocked("notification_rollback_not_atomic")
    outcomes = await asyncio.wait_for(
        asyncio.gather(confirm(first), confirm(other)), timeout=45
    )
    if sum(outcome is not None for outcome in outcomes) != 1:
        raise GateBlocked("distinct_plans_did_not_conflict")
    winner_index = next(
        index for index, outcome in enumerate(outcomes) if outcome is not None
    )
    request, winner = (first, other)[winner_index], outcomes[winner_index]
    replay = await confirm(request)
    if (
        replay is None
        or replay.receipt != winner.receipt
        or replay.dispatch_ids
        or len(winner.dispatch_ids) != 1
    ):
        raise GateBlocked("notification_replay_repeated_dispatch")
    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        readback = await get_assignment_plan(db, actor, request.plan_id)
        if readback != winner.receipt:
            raise GateBlocked("notification_receipt_reload_mismatch")
        try:
            async with db.begin_nested():
                await db.execute(
                    text("SELECT id FROM course_assignment_notification_outbox")
                )
        except DBAPIError as exc:
            if "42501" not in safe_failure(exc):
                raise
        else:
            raise GateBlocked("runtime_direct_outbox_access_allowed")
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        rows = (
            await db.execute(
                text(
                    "SELECT id,enrollment_id,status,attempt_count FROM course_assignment_notification_outbox"
                )
            )
        ).all()
        if (
            len(rows) != 1
            or rows[0].id != winner.dispatch_ids[0]
            or rows[0].status != "pending"
            or rows[0].attempt_count != 0
        ):
            raise GateBlocked("outbox_duplicate_or_delivery_started")
        if rows[0].enrollment_id != winner.receipt.created[0].enrollment_id:
            raise GateBlocked("outbox_receipt_identity_mismatch")

    manual_request = await preview("Overlap department", notify=False)
    manual_due = now + timedelta(days=10)
    # The established manual path owns the course lock before workbench tries
    # to confirm; after it commits, workbench must reject its outdated audience.
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        await db.scalar(select(Course).where(Course.id == course_id).with_for_update())
        pending = asyncio.create_task(confirm(manual_request))
        try:
            created = await enroll_users(
                db, course_id, actor.tenant_id, [learner_ids[1]], due_at=manual_due
            )
            await db.commit()
            overlap = await asyncio.wait_for(pending, timeout=45)
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        if len(created) != 1 or overlap is not None:
            raise GateBlocked("manual_overlap_not_rejected")
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        policies = (
            await db.execute(
                text(
                    "SELECT p.due_at FROM enrollments e JOIN enrollment_access_policies p ON p.enrollment_id=e.id "
                    "WHERE e.user_id=:id"
                ),
                {"id": learner_ids[1]},
            )
        ).all()
        if len(policies) != 1 or policies[0].due_at != manual_due:
            raise GateBlocked("manual_deadline_overwritten")
    return [
        "notify_true_outbox_receipt_atomic",
        "notification_rollback_atomic",
        "distinct_plans_one_success_other_stale",
        "notification_replay_no_redispatch",
        "owned_receipt_reload",
        "runtime_outbox_direct_read_denied",
        "outbox_not_delivered",
        "manual_overlap_rejected_deadline_preserved",
    ]


async def run_gate(owner_url, runtime_url, supabase_url):
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")
    schema = f"workbench_{uuid4().hex[:12]}"
    qualified = safe_schema(schema)
    owner_engine = create_async_engine(
        owner_url, poolclass=NullPool, hide_parameters=True
    )
    runtime_engine = create_async_engine(
        runtime_url, poolclass=NullPool, hide_parameters=True
    )
    owned, cleanup_ok, neutral = False, False, False
    stage, failure, checks = "preflight", None, []
    before = None
    last_query = "none"

    @event.listens_for(runtime_engine.sync_engine, "before_cursor_execute")
    def record_query(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        nonlocal last_query
        operation = statement.lstrip().split(None, 1)[0].upper()
        if operation not in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            operation = "context"
        tables = [
            name
            for name in (*TABLES, "workbench_assignment_plans")
            if re.search(rf"\b{name}\b", statement)
        ]
        last_query = ":".join((operation, *tables))

    try:
        async with runtime_engine.connect() as connection:
            await verify_runtime_role(connection)
        checks.append("runtime_non_bypass")
        async with owner_engine.begin() as connection:
            before = await public_snapshot(connection)
            stage = "isolated_schema"
            await connection.execute(text(f"CREATE SCHEMA {qualified}"))
            owned = True
            await connection.execute(
                text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC")
            )
            await connection.execute(
                text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app")
            )
            for table in TABLES:
                # Copy definitions/constraints, NEVER rows or public FK pointers.
                await connection.execute(
                    text(
                        f"CREATE TABLE {qualified}.{table} (LIKE public.{table} INCLUDING ALL)"
                    )
                )
                await connection.execute(
                    text(
                        f"GRANT SELECT, INSERT, UPDATE ON {qualified}.{table} TO lms_app"
                    )
                )
            await migration(connection, schema)
            await install_isolated_enqueue(connection, schema)
            flags = (
                await connection.execute(
                    text(
                        "SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND c.relname='workbench_assignment_plans'"
                    ),
                    {"schema": schema},
                )
            ).one()
            if flags != (True, True):
                raise GateBlocked("force_rls_missing")
        checks += [
            "migration_upgrade",
            "enable_force_rls",
            "accepted_enqueue_body_isolated",
        ]
        stage = "application_import"
        sys.path.insert(0, str(API_ROOT))
        from app.models.registry import load_all_models

        load_all_models()
        from app.models.department import Department
        from app.models.enrollment import Enrollment
        from app.models.tenants import Tenant
        from app.models.users import User
        from app.modules.courses.models import Course
        from app.modules.courses.release_models import ContentRelease
        from app.modules.methodologist_workbench.assignment_models import AssignmentPlan
        from app.modules.methodologist_workbench.assignment_schemas import (
            AssignmentPreview,
            AssignmentPreviewRequest,
        )
        from app.modules.methodologist_workbench.assignment_service import (
            WorkbenchConflict,
            confirm_assignment_plan,
            create_assignment_preview,
        )
        from app.modules.methodologist_workbench.plan_contract import (
            ActorContext,
            ConfirmationRequest,
        )

        (
            tenant_id,
            other_tenant,
            actor_id,
            other_actor,
            learner_id,
            dept_id,
            course_id,
            release_id,
        ) = (uuid4() for _ in range(8))
        now = datetime.now(UTC)
        stage = "synthetic_fixture"
        async with AsyncSession(owner_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant_id, actor_id)
            db.add_all(
                [
                    Tenant(
                        id=tenant_id,
                        name="Synthetic workbench",
                        slug=f"gate-{tenant_id.hex}",
                    ),
                    Tenant(
                        id=other_tenant,
                        name="Foreign synthetic",
                        slug=f"gate-{other_tenant.hex}",
                    ),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    User(
                        id=actor_id,
                        tenant_id=tenant_id,
                        first_name="Owner",
                        last_name="Synthetic",
                        role="methodologist",
                    ),
                    User(
                        id=other_actor,
                        tenant_id=tenant_id,
                        first_name="Other",
                        last_name="Synthetic",
                        role="methodologist",
                    ),
                    Department(
                        id=dept_id,
                        tenant_id=tenant_id,
                        name="Gate department",
                        slug="gate",
                        normalized_name="gate department",
                    ),
                ]
            )
            await db.flush()
            db.add(
                User(
                    id=learner_id,
                    tenant_id=tenant_id,
                    first_name="Learner",
                    last_name="Synthetic",
                    role="student",
                    organization_unit_id=dept_id,
                    password_hash="synthetic-non-credential",
                )
            )
            db.add(
                Course(
                    id=course_id,
                    tenant_id=tenant_id,
                    title="Gate course",
                    status="published",
                )
            )
            await db.flush()
            db.add(
                ContentRelease(
                    id=release_id,
                    tenant_id=tenant_id,
                    course_id=course_id,
                    version=1,
                    snapshot={},
                    snapshot_sha256="a" * 64,
                )
            )
            await db.flush()
            course = await db.get(Course, course_id)
            course.current_release_id = release_id
            await db.commit()
        actor = ActorContext(
            tenant_id=tenant_id, actor_id=actor_id, active_role="methodologist"
        )
        body = AssignmentPreviewRequest(
            instruction=f'Назначь курс "Gate course" отделу "Gate department" до {(now + timedelta(days=3)).date()}',
            timezone_name="UTC",
            notify=False,
        )
        stage = "application_preview"
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant_id, actor_id)
            preview = await create_assignment_preview(db, actor, body, now=now)
            if not isinstance(preview, AssignmentPreview) or preview.new_count != 1:
                raise GateBlocked("preview_mismatch")
            await db.commit()
        checks.append("persisted_preview_no_enrollment")
        async with AsyncSession(runtime_engine) as db:
            for tenant, user, expected in (
                (other_tenant, actor_id, 0),
                (tenant_id, other_actor, 0),
                (tenant_id, actor_id, 1),
            ):
                await context(db, schema, tenant, user)
                rows = list((await db.scalars(select(AssignmentPlan))).all())
                if len(rows) != expected:
                    raise GateBlocked("owner_tenant_rls_visibility")
                await db.rollback()
        checks += ["cross_tenant_hidden", "other_actor_hidden", "owner_visible"]
        stage = "immutable_acl"
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, tenant_id, actor_id)
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(
                            "UPDATE workbench_assignment_plans SET snapshot=snapshot WHERE id=:id"
                        ),
                        {"id": preview.plan_id},
                    )
            except DBAPIError as exc:
                if "42501" not in safe_failure(exc):
                    raise
            else:
                raise GateBlocked("immutable_snapshot_update_allowed")
            deleted = await db.execute(
                text("DELETE FROM workbench_assignment_plans WHERE id=:id"),
                {"id": preview.plan_id},
            )
            if deleted.rowcount != 0:
                raise GateBlocked("ordinary_delete_allowed")
            await db.rollback()
        checks += ["immutable_snapshot_update_denied", "ordinary_delete_denied"]
        request = ConfirmationRequest(
            plan_id=preview.plan_id,
            revision=preview.revision,
            fingerprint=preview.fingerprint,
        )
        stage = "confirm_rollback"
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant_id, actor_id)
            await confirm_assignment_plan(db, actor, request, now=now)
            await db.rollback()
            await context(db, schema, tenant_id, actor_id)
            row = await db.get(AssignmentPlan, preview.plan_id)
            count = await db.scalar(text("SELECT count(*) FROM enrollments"))
            policy_count = await db.scalar(
                text("SELECT count(*) FROM enrollment_access_policies")
            )
            if (
                row.status != "ready"
                or row.receipt is not None
                or count != 0
                or policy_count != 0
            ):
                raise GateBlocked("receipt_domain_rollback_not_atomic")
        checks.append("rollback_receipt_enrollment_policy_atomic")
        stage = "confirm_concurrent"

        async def confirm_once():
            async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
                await context(db, schema, tenant_id, actor_id)
                outcome = await confirm_assignment_plan(db, actor, request, now=now)
                await db.commit()
                return outcome

        first, concurrent = await asyncio.wait_for(
            asyncio.gather(confirm_once(), confirm_once()), timeout=45
        )
        if first.receipt != concurrent.receipt:
            raise GateBlocked("concurrent_receipts_differ")
        checks.append("concurrent_same_plan_one_receipt")
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant_id, actor_id)
            second = await confirm_assignment_plan(
                db, actor, request, now=now + timedelta(days=20)
            )
            await db.commit()
            if (
                first.receipt != second.receipt
                or second.dispatch_ids
                or len(first.receipt.created) != 1
            ):
                raise GateBlocked("receipt_replay_mismatch")
            await context(db, schema, tenant_id, actor_id)
            rows = list((await db.scalars(select(Enrollment))).all())
            if len(rows) != 1 or rows[0].user_id != learner_id:
                raise GateBlocked("duplicate_or_foreign_enrollment")
        checks += [
            "atomic_assignment_receipt",
            "expired_receipt_replay_no_duplicate",
            "notify_false_no_dispatch",
        ]
        stage = "notification_and_overlap"
        checks += await verify_notification_and_manual_overlap(
            owner_engine, runtime_engine, schema, actor, course_id, now
        )
        stage = "stale_membership"
        # New preview with existing assignment, then a membership removal.
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant_id, actor_id)
            stale_preview = await create_assignment_preview(db, actor, body, now=now)
            await db.commit()
        async with AsyncSession(owner_engine) as db:
            await context(db, schema, tenant_id, actor_id)
            await db.execute(
                text("UPDATE users SET status='inactive' WHERE id=:id"),
                {"id": learner_id},
            )
            await db.commit()
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, tenant_id, actor_id)
            try:
                await confirm_assignment_plan(
                    db,
                    actor,
                    ConfirmationRequest(
                        plan_id=stale_preview.plan_id,
                        revision=1,
                        fingerprint=stale_preview.fingerprint,
                    ),
                    now=now,
                )
            except WorkbenchConflict:
                await db.rollback()
            else:
                raise GateBlocked("stale_membership_was_accepted")
        checks.append("changed_membership_blocks")
    except Exception as exc:
        failure = safe_failure(exc)
    finally:
        if owned:
            try:
                async with owner_engine.begin() as connection:
                    await connection.execute(
                        text(f"DROP SCHEMA IF EXISTS {qualified} CASCADE")
                    )
                async with owner_engine.connect() as connection:
                    exists = await connection.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                        ),
                        {"schema": schema},
                    )
                    cleanup_ok = not exists
                    neutral = before == await public_snapshot(connection)
            except Exception:
                cleanup_ok = False
        await runtime_engine.dispose()
        await owner_engine.dispose()
    result = {
        "status": "PASS" if failure is None and cleanup_ok and neutral else "BLOCKED",
        "scope": "isolated_supabase_dev_workbench",
        "stage": stage,
        "failure": failure,
        "checks": checks,
        "cleanup": cleanup_ok,
        "public_schema_neutral": neutral,
        "last_query_kind": last_query if failure else None,
    }
    assert_sanitized_evidence(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    config = dotenv_values(args.env_file)
    # Match canonical source-actuality gate: app imports must use this same
    # approved contour, never a missing-worktree dotenv/default local config.
    load_dotenv(args.env_file, override=True)
    urls = [
        normalize_database_url(config.get(name) or "")
        for name in ("MIGRATION_DATABASE_URL", "DATABASE_URL")
    ]
    try:
        result = asyncio.run(run_gate(*urls, config.get("SUPABASE_URL") or ""))
    except Exception as exc:
        result = {
            "status": "BLOCKED",
            "reason": str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__,
        }
    assert_sanitized_evidence(result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
