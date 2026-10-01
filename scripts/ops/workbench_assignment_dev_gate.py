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
RETENTION_MIGRATION = (
    API_ROOT / "alembic" / "versions" / "0171_workbench_plan_retention.py"
)
SCHEMA_RE = re.compile(r"^workbench_[0-9a-f]{12}$")
TABLES = (
    "tenants",
    "users",
    "user_roles",
    "user_invitations",
    "tenant_settings",
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


def classify_pending_policy(command, permissive, applies_to_app, expression) -> str:
    """Recognize only the exact accepted0046 exception; never emit raw SQL."""
    normalized = re.sub(r"[\s()]", "", expression or "").replace("::text", "")
    if (
        command == "r"
        and permissive
        and applies_to_app
        and normalized == "status='pending'"
    ):
        return "unscoped_pending_select"
    return "not_classified"


async def inspect_neighbor_metadata(owner_url, runtime_url, supabase_url):
    """Read only flags/privileges/policy classification, never business rows."""
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    try:
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
        async with owner.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            tables = (
                (
                    await connection.execute(
                        text(
                            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,"
                            "has_table_privilege('lms_app',c.oid,'SELECT') AS can_select,"
                            "has_table_privilege('lms_app',c.oid,'INSERT') AS can_insert,"
                            "has_table_privilege('lms_app',c.oid,'UPDATE') AS can_update "
                            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname='public' AND c.relname=ANY(:tables) ORDER BY c.relname"
                        ),
                        {"tables": list(TABLES)},
                    )
                )
                .mappings()
                .all()
            )
            policies = (
                (
                    await connection.execute(
                        text(
                            "SELECT c.relname,p.polname,p.polcmd::text AS polcmd,p.polpermissive,"
                            "(0=ANY(p.polroles) OR EXISTS(SELECT 1 FROM pg_roles r "
                            "WHERE r.oid=ANY(p.polroles) AND pg_has_role('lms_app',r.oid,'MEMBER'))) AS app_applies,"
                            "pg_get_expr(p.polqual,p.polrelid) AS expression "
                            "FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname='public' AND c.relname=ANY(:tables) ORDER BY c.relname,p.polname"
                        ),
                        {"tables": list(TABLES)},
                    )
                )
                .mappings()
                .all()
            )
        if {row["relname"] for row in tables} != set(TABLES):
            raise GateBlocked("neighbor_metadata_table_missing")
        safe_policies = []
        for row in policies:
            if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", row["polname"]):
                raise GateBlocked("neighbor_policy_name_unexpected")
            safe_policies.append(
                {
                    "table": row["relname"],
                    "policy": row["polname"],
                    "app_applies": row["app_applies"],
                    "predicate_mentions_tenant_context": "app.tenant_id"
                    in (row["expression"] or ""),
                    "classification": classify_pending_policy(
                        row["polcmd"],
                        row["polpermissive"],
                        row["app_applies"],
                        row["expression"],
                    ),
                }
            )
        unscoped = any(
            row["table"] == "user_invitations"
            and row["classification"] == "unscoped_pending_select"
            for row in safe_policies
        )
        return {
            "status": "BLOCKED" if unscoped else "PASS",
            "scope": "read_only_dev_neighbor_metadata",
            "runtime_non_bypass": True,
            "tables": [dict(row) for row in tables],
            "policies": safe_policies,
            "unscoped_pending_invitation_policy": unscoped,
            "neighbor_equivalence": "NOT_VERIFIED",
            "business_rows_read": False,
            "mutations": False,
        }
    finally:
        await runtime.dispose()
        await owner.dispose()


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


async def migration(
    connection, schema: str, operation: str = "upgrade", *, path=MIGRATION
) -> None:
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_action")
    if path not in {MIGRATION, RETENTION_MIGRATION}:
        raise GateBlocked("invalid_migration_path")
    spec = importlib.util.spec_from_file_location("workbench_owned_migration", path)
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
        text(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog")
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


async def verify_isolated_resolution(connection, schema: str) -> None:
    """Fail before application mutation if any required table is missing/foreign."""
    safe_schema(schema)
    for table in (*TABLES, "workbench_assignment_plans"):
        resolved = await connection.scalar(
            text(
                "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.oid=to_regclass(:table)"
            ),
            {"table": table},
        )
        if resolved != schema:
            raise GateBlocked("isolated_table_resolution_mismatch")


async def verify_invitation_preparation(
    owner_engine, runtime_engine, schema, actor, now
):
    """Exercise existing invitation preparation without accepting/delivering it."""
    from app.models.department import Department
    from app.models.tenant_settings import TenantSettings
    from app.models.users import User
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from app.modules.methodologist_workbench.assignment_schemas import (
        AssignmentPreviewRequest,
    )
    from app.modules.methodologist_workbench.assignment_service import (
        confirm_assignment_plan,
        create_assignment_preview,
        get_assignment_plan,
    )
    from app.modules.methodologist_workbench.plan_contract import ConfirmationRequest

    departments, learners, courses = (
        [uuid4(), uuid4()],
        [uuid4(), uuid4()],
        [uuid4(), uuid4(), uuid4()],
    )
    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        db.add(TenantSettings(tenant_id=actor.tenant_id, invite_expiry_days=7))
        for index in range(2):
            db.add(
                Department(
                    id=departments[index],
                    tenant_id=actor.tenant_id,
                    name=f"Activation department {index}",
                    normalized_name=f"activation department {index}",
                    slug=f"activation-{index}",
                )
            )
            db.add(
                User(
                    id=learners[index],
                    tenant_id=actor.tenant_id,
                    role="student",
                    first_name="Synthetic",
                    last_name=f"Unactivated{index}",
                    organization_unit_id=departments[index],
                    is_active=True,
                    status="active",
                    password_hash=None,
                    telegram_id=None,
                    email_verified_at=None,
                    email=f"activation-{index}@example.invalid",
                )
            )
        for index, course_id in enumerate(courses):
            course = Course(
                id=course_id,
                tenant_id=actor.tenant_id,
                title=f"Activation course {index}",
                status="published",
            )
            db.add(course)
            await db.flush()
            release_id = uuid4()
            db.add(
                ContentRelease(
                    id=release_id,
                    tenant_id=actor.tenant_id,
                    course_id=course_id,
                    version=1,
                    snapshot={},
                    snapshot_sha256="b" * 64,
                )
            )
            await db.flush()
            course.current_release_id = release_id
        await db.commit()
        await context(db, schema, actor.tenant_id, actor.actor_id)
        initial_users = await db.scalar(
            text("SELECT count(*) FROM users WHERE tenant_id=:t"),
            {"t": actor.tenant_id},
        )

    async def preview(index, *, silent=False):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            result = await create_assignment_preview(
                db,
                actor,
                AssignmentPreviewRequest(
                    instruction=f'Назначь курс "Activation course {index}" отделу "Activation department {int(silent)}" до {(now + timedelta(days=3)).date()}',
                    timezone_name="UTC",
                    notify=not silent,
                ),
                now=now,
            )
            if (
                result.state != "preview_ready"
                or result.new_count != 1
                or not result.recipients[0].access_warning
            ):
                raise GateBlocked("activation_preview_warning_missing")
            await db.commit()
            return ConfirmationRequest(
                plan_id=result.plan_id,
                revision=result.revision,
                fingerprint=result.fingerprint,
            )

    async def confirm(request, *, rollback=False):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            outcome = await confirm_assignment_plan(db, actor, request, now=now)
            if rollback:
                await db.rollback()
            else:
                await db.commit()
            return outcome

    async def invitation_rows():
        async with AsyncSession(owner_engine) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            # Never select token/email/activation URL, even for sanitized evidence.
            return (
                await db.execute(
                    text(
                        "SELECT id,status,user_id,invited_by,expires_at,superseded_by,"
                        "delivery_attempt_count,delivery_message_id,accepted_at "
                        "FROM user_invitations WHERE user_id=:id ORDER BY created_at,id"
                    ),
                    {"id": learners[0]},
                )
            ).all()

    first = await preview(0)
    if await invitation_rows():
        raise GateBlocked("preview_prepared_activation")
    rolled_back = await confirm(first, rollback=True)
    if len(rolled_back.dispatch_ids) != 1 or await invitation_rows():
        raise GateBlocked("invitation_rollback_not_atomic")
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        remaining = await db.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM enrollments WHERE user_id=:u) "
                "OR EXISTS(SELECT 1 FROM enrollment_access_policies WHERE user_id=:u) "
                "OR EXISTS(SELECT 1 FROM course_assignment_notification_outbox WHERE id=:oid) "
                "OR NOT EXISTS(SELECT 1 FROM workbench_assignment_plans WHERE id=:p "
                "AND status='ready' AND receipt IS NULL)"
            ),
            {"u": learners[0], "p": first.plan_id, "oid": rolled_back.dispatch_ids[0]},
        )
        if remaining is not False:
            raise GateBlocked("activation_rollback_left_domain_state")

    first_outcome = await confirm(first)
    rows = await invitation_rows()
    if (
        len(rows) != 1
        or rows[0].status != "pending"
        or rows[0].user_id != learners[0]
        or rows[0].invited_by != actor.actor_id
        or rows[0].superseded_by is not None
        or not now + timedelta(days=6) < rows[0].expires_at < now + timedelta(days=8)
    ):
        raise GateBlocked("activation_identity_or_expiry_mismatch")
    invitation_id, original_expiry = rows[0].id, rows[0].expires_at
    second = await preview(1)
    second_outcome = await confirm(second)
    reused = await invitation_rows()
    if (
        len(reused) != 1
        or reused[0].id != invitation_id
        or reused[0].expires_at != original_expiry
    ):
        raise GateBlocked("valid_invitation_not_reused")
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        await db.execute(
            text("UPDATE user_invitations SET expires_at=:expiry WHERE id=:id"),
            {"expiry": now - timedelta(days=1), "id": invitation_id},
        )
        await db.commit()
    third = await preview(2)
    third_outcome = await confirm(third)
    replaced = await invitation_rows()
    pending = [row for row in replaced if row.status == "pending"]
    old = next((row for row in replaced if row.id == invitation_id), None)
    if (
        len(replaced) != 2
        or len(pending) != 1
        or old is None
        or old.status != "superseded"
        or old.superseded_by != pending[0].id
    ):
        raise GateBlocked("expired_activation_not_superseded")

    outcomes = (first_outcome, second_outcome, third_outcome)
    for request, outcome in zip((first, second, third), outcomes, strict=True):
        replay = await confirm(request)
        if (
            replay.receipt != outcome.receipt
            or replay.dispatch_ids
            or len(outcome.dispatch_ids) != 1
        ):
            raise GateBlocked("activation_replay_mutated")
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            if await get_assignment_plan(db, actor, request.plan_id) != outcome.receipt:
                raise GateBlocked("activation_receipt_reload_mismatch")
    if await invitation_rows() != replaced:
        raise GateBlocked("activation_replay_changed_invitation")

    silent = await confirm(await preview(0, silent=True))
    if silent.dispatch_ids or silent.receipt.notification_state != "not_requested":
        raise GateBlocked("silent_activation_queued")
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        silent_invites = await db.scalar(
            text("SELECT count(*) FROM user_invitations WHERE user_id=:u"),
            {"u": learners[1]},
        )
        all_users = await db.scalar(
            text("SELECT count(*) FROM users WHERE tenant_id=:t"),
            {"t": actor.tenant_id},
        )
        unchanged = await db.scalar(
            text(
                "SELECT bool_and(password_hash IS NULL AND telegram_id IS NULL AND email_verified_at IS NULL "
                "AND role='student' AND status='active' AND is_active) FROM users WHERE id IN (:a,:b)"
            ),
            {"a": learners[0], "b": learners[1]},
        )
        queued = (
            await db.execute(
                text(
                    "SELECT o.id,o.enrollment_id,o.status,o.attempt_count FROM course_assignment_notification_outbox o "
                    "JOIN enrollments e ON e.id=o.enrollment_id WHERE e.user_id IN (:a,:b)"
                ),
                {"a": learners[0], "b": learners[1]},
            )
        ).all()
        expected_ids = {item.dispatch_ids[0] for item in outcomes}
        expected_enrollments = {
            item.receipt.created[0].enrollment_id for item in outcomes
        }
        if (
            silent_invites != 0
            or all_users != initial_users
            or unchanged is not True
            or {row.id for row in queued} != expected_ids
            or {row.enrollment_id for row in queued} != expected_enrollments
            or any(row.status != "pending" or row.attempt_count != 0 for row in queued)
            or any(
                row.delivery_attempt_count != 0
                or row.delivery_message_id is not None
                or row.accepted_at is not None
                for row in replaced
            )
        ):
            raise GateBlocked("activation_delivered_duplicated_or_identity_changed")
    return [
        "activation_preview_warning_no_invitation",
        "activation_rollback_atomic",
        "activation_same_user_tenant_expiry",
        "valid_activation_reused",
        "expired_activation_superseded",
        "activation_receipt_replay_no_mutation",
        "notify_false_no_activation",
        "activation_no_login_or_delivery",
    ]


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


async def verify_organization_changes(owner_engine, runtime_engine, schema, actor, now):
    """Bounded audience contract, not neighbor policy/FK/trigger equivalence."""
    from app.models.department import Department
    from app.models.users import User
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from app.modules.methodologist_workbench.assignment_schemas import (
        AssignmentPreviewRequest,
    )
    from app.modules.methodologist_workbench.assignment_service import (
        WorkbenchConflict,
        WorkbenchNotFound,
        confirm_assignment_plan,
        create_assignment_preview,
        get_assignment_plan,
    )
    from app.modules.methodologist_workbench.plan_contract import (
        ActorContext,
        ConfirmationRequest,
    )
    from app.modules.positions.models import Position

    root, child, outside, position, direct, fallback, excluded, course_id, hire = (
        uuid4() for _ in range(9)
    )
    async with AsyncSession(owner_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        for unit_id, name, parent in (
            (root, "Organization root", None),
            (child, "Organization child", root),
            (outside, "Organization outside", None),
        ):
            db.add(
                Department(
                    id=unit_id,
                    tenant_id=actor.tenant_id,
                    name=name,
                    normalized_name=name.lower(),
                    slug=unit_id.hex,
                    parent_id=parent,
                )
            )
        db.add(
            Position(
                id=position,
                tenant_id=actor.tenant_id,
                name="Synthetic position",
                normalized_name="synthetic position",
                department_id=child,
            )
        )
        for user_id, unit, user_position in (
            (direct, root, position),
            (fallback, None, position),
            (excluded, outside, position),
        ):
            db.add(
                User(
                    id=user_id,
                    tenant_id=actor.tenant_id,
                    role="student",
                    first_name="Synthetic",
                    last_name="Organization",
                    is_active=True,
                    status="active",
                    organization_unit_id=unit,
                    position_id=user_position,
                    password_hash="synthetic-non-credential",
                )
            )
        course = Course(
            id=course_id,
            tenant_id=actor.tenant_id,
            title="Organization course",
            status="published",
        )
        db.add(course)
        await db.flush()
        release_id = uuid4()
        db.add(
            ContentRelease(
                id=release_id,
                tenant_id=actor.tenant_id,
                course_id=course_id,
                version=1,
                snapshot={},
                snapshot_sha256="c" * 64,
            )
        )
        await db.flush()
        course.current_release_id = release_id
        await db.commit()

    async def preview(descendants=True):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            result = await create_assignment_preview(
                db,
                actor,
                AssignmentPreviewRequest(
                    instruction=f'Назначь курс "Organization course" отделу "Organization root" до {(now + timedelta(days=3)).date()}',
                    timezone_name="UTC",
                    include_descendants=descendants,
                    notify=False,
                ),
                now=now,
            )
            if result.state != "preview_ready":
                raise GateBlocked("organization_preview_not_ready")
            expected = {direct, fallback} if descendants else {direct}
            if {row.user_id for row in result.recipients} != expected:
                raise GateBlocked("explicit_placement_or_descendants_mismatch")
            await db.commit()
            return ConfirmationRequest(
                plan_id=result.plan_id,
                revision=result.revision,
                fingerprint=result.fingerprint,
            )

    async def rejected(request, caller=actor, missing=False, backend=None):
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, caller.tenant_id, caller.actor_id)
            if backend is not None:
                backend.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            try:
                await confirm_assignment_plan(db, caller, request, now=now)
            except (WorkbenchNotFound, WorkbenchConflict) as exc:
                expected_type = WorkbenchNotFound if missing else WorkbenchConflict
                expected_code = "plan_not_found" if missing else "stale"
                if not isinstance(exc, expected_type) or str(exc) != expected_code:
                    raise GateBlocked("organization_unexpected_rejection") from None
                await db.rollback()
            else:
                raise GateBlocked("changed_or_foreign_plan_was_accepted")

    async def assert_no_effects(request):
        async with AsyncSession(owner_engine) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            untouched = await db.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM workbench_assignment_plans WHERE id=:p "
                    "AND status='ready' AND receipt IS NULL) "
                    "AND NOT EXISTS(SELECT 1 FROM enrollments WHERE course_id=:c) "
                    "AND NOT EXISTS(SELECT 1 FROM enrollment_access_policies WHERE user_id IN (:a,:b,:d,:h)) "
                    "AND NOT EXISTS(SELECT 1 FROM user_invitations WHERE user_id IN (:a,:b,:d,:h)) "
                    "AND NOT EXISTS(SELECT 1 FROM course_assignment_notification_outbox o "
                    "JOIN enrollments e ON e.id=o.enrollment_id WHERE e.course_id=:c)"
                ),
                {
                    "p": request.plan_id,
                    "c": course_id,
                    "a": direct,
                    "b": fallback,
                    "d": excluded,
                    "h": hire,
                },
            )
            if untouched is not True:
                raise GateBlocked("rejected_organization_plan_left_effects")

    await preview(False)
    request = await preview()
    for caller in (
        ActorContext(
            tenant_id=actor.tenant_id, actor_id=uuid4(), active_role="methodologist"
        ),
        ActorContext(
            tenant_id=uuid4(), actor_id=actor.actor_id, active_role="methodologist"
        ),
    ):
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, caller.tenant_id, caller.actor_id)
            try:
                await get_assignment_plan(db, caller, request.plan_id)
            except WorkbenchNotFound as exc:
                if str(exc) != "plan_not_found":
                    raise
            else:
                raise GateBlocked("foreign_plan_get_allowed")
        await rejected(request, caller, missing=True)
        await assert_no_effects(request)

    for mutation, restore, parameters in (
        (
            "UPDATE users SET organization_unit_id=:outside WHERE id=:id",
            "UPDATE users SET organization_unit_id=:root WHERE id=:id",
            {"id": direct},
        ),
        (
            "UPDATE positions SET department_id=:outside WHERE id=:id",
            "UPDATE positions SET department_id=:child WHERE id=:id",
            {"id": position},
        ),
        (
            "UPDATE departments SET parent_id=:outside WHERE id=:id",
            "UPDATE departments SET parent_id=:root WHERE id=:id",
            {"id": child},
        ),
    ):
        request = await preview()
        values = {**parameters, "outside": outside, "root": root, "child": child}
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            await db.execute(text(mutation), values)
            await db.commit()
        await rejected(request)
        await assert_no_effects(request)
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, actor.tenant_id, actor.actor_id)
            await db.execute(text(restore), values)
            await db.commit()

    # A hire committed after preview but BEFORE guarded selection invalidates it.
    # This is distinct from a future hire after one-time selection (not a rule).
    request = await preview()
    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        db.add(
            User(
                id=hire,
                tenant_id=actor.tenant_id,
                role="student",
                first_name="Synthetic",
                last_name="New hire",
                is_active=True,
                status="active",
                organization_unit_id=root,
                password_hash="synthetic-non-credential",
            )
        )
        await db.commit()
    await rejected(request)
    await assert_no_effects(request)
    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, actor.tenant_id, actor.actor_id)
        await db.execute(
            text("UPDATE users SET status='inactive',is_active=false WHERE id=:id"),
            {"id": hire},
        )
        await db.commit()

    # Distinct runtime transactions: UPDATE holds the actual learner row lock.
    # Observe the confirm backend blocked by this exact mutator before commit.
    request = await preview()
    backend = asyncio.get_running_loop().create_future()
    task = None
    async with AsyncSession(runtime_engine) as mutator:
        await context(mutator, schema, actor.tenant_id, actor.actor_id)
        mutator_pid = await mutator.scalar(text("SELECT pg_backend_pid()"))
        await mutator.execute(
            text("UPDATE users SET organization_unit_id=:outside WHERE id=:id"),
            {"outside": outside, "id": direct},
        )
        try:
            task = asyncio.create_task(rejected(request, backend=backend))
            confirm_pid = await asyncio.wait_for(backend, timeout=10)
            deadline = asyncio.get_running_loop().time() + 10
            observed = False
            async with owner_engine.connect() as inspector:
                await inspector.execute(text("SET TRANSACTION READ ONLY"))
                while asyncio.get_running_loop().time() < deadline:
                    observed = await inspector.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=:pid "
                            "AND wait_event_type='Lock' AND :blocker=ANY(pg_blocking_pids(pid)))"
                        ),
                        {"pid": confirm_pid, "blocker": mutator_pid},
                    )
                    if observed:
                        break
                    if task.done():
                        await task
                        raise GateBlocked("organization_confirm_did_not_wait_for_edit")
                    # Polling only: the lock observation, not elapsed time, is the oracle.
                    await asyncio.sleep(0.05)
            if not observed:
                raise GateBlocked("organization_lock_not_observed")
            await mutator.commit()
            await asyncio.wait_for(task, timeout=15)
        finally:
            await mutator.rollback()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    await assert_no_effects(request)
    return [
        "organization_explicit_placement_wins",
        "organization_descendants_opt_in_position_fallback",
        "foreign_actor_plan_get_confirm_denied",
        "foreign_tenant_plan_get_confirm_denied",
        "committed_user_move_rejected_no_effects",
        "committed_position_move_rejected_no_effects",
        "committed_child_reparent_rejected_no_effects",
        "committed_post_preview_hire_rejected_no_effects",
        "observed_concurrent_user_move_rejected_no_effects",
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
            from workbench_retention_dev_checks import verify_retention_upgrade

            checks += await verify_retention_upgrade(
                connection, schema, migration, RETENTION_MIGRATION
            )
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
            "retention_migration_upgrade",
            "enable_force_rls",
            "accepted_enqueue_body_isolated",
        ]
        async with runtime_engine.begin() as connection:
            await connection.execute(
                text(f"SET LOCAL search_path TO {qualified}, pg_catalog")
            )
            await verify_isolated_resolution(connection, schema)
        checks.append("all_required_tables_resolve_owned")
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
                or row.executed_at is not None
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
        stage = "invitation_preparation"
        checks += await verify_invitation_preparation(
            owner_engine, runtime_engine, schema, actor, now
        )
        stage = "organization_changes"
        checks += await verify_organization_changes(
            owner_engine, runtime_engine, schema, actor, now
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
        stage = "retention"
        from workbench_retention_dev_checks import verify_retention

        checks += await verify_retention(
            owner_engine, runtime_engine, schema, actor, other_tenant, request
        )
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
    parser.add_argument("--metadata-only", action="store_true")
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
        operation = inspect_neighbor_metadata if args.metadata_only else run_gate
        result = asyncio.run(operation(*urls, config.get("SUPABASE_URL") or ""))
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
