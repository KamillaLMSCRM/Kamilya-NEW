#!/usr/bin/env python3
"""Exact-token isolation on synthetic Supabase DEV rows; public remains untouched."""

from __future__ import annotations

import argparse
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
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from workbench_assignment_dev_gate import safe_failure

ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    "tenants",
    "users",
    "departments",
    "positions",
    "courses",
    "enrollments",
    "user_invitations",
)


def safe_schema(schema):
    if not re.fullmatch(r"invitation_[0-9a-f]{12}", schema):
        raise GateBlocked("unsafe_invitation_schema")
    return f'"{schema}"'


async def context(db, schema, tenant="", token=""):
    await db.execute(
        text(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog")
    )
    await db.execute(
        text(
            "SELECT set_config('app.tenant_id',:tenant,true), "
            "set_config('app.invitation_token',:token,true), "
            "set_config('app.is_superadmin','false',true)"
        ),
        {"tenant": str(tenant), "token": token},
    )


async def apply_migration(connection, schema):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location(
        "invitation_migration0170",
        ROOT / "apps/api/alembic/versions/0170_invitation_exact_token_rls.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def upgrade(sync):
        with Operations.context(
            MigrationContext.configure(sync, opts={"version_table_schema": schema})
        ):
            module.upgrade()

    await connection.run_sync(upgrade)


async def run_gate(owner_url, runtime_url, supabase_url):
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")
    schema = f"invitation_{uuid4().hex[:12]}"
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    created = cleanup = neutral = False
    before = failure = None
    checks = []
    stage = "preflight"
    tenants = [uuid4(), uuid4()]
    statuses = ("pending", "accepted", "expired", "revoked", "superseded")
    invitation_ids = [uuid4() for _ in range(6)]
    # Synthetic capability strings never emitted, even in evidence/failure output.
    tokens = [uuid4().hex for _ in range(6)]
    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        checks.append("runtime_non_bypass")
        stage = "owned_schema"
        async with owner.begin() as db:
            before = await public_snapshot(db)
            await db.execute(text(f"CREATE SCHEMA {qualified}"))
            created = True
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
            for table in TABLES:
                await db.execute(
                    text(
                        f"CREATE TABLE {qualified}.{table} (LIKE public.{table} INCLUDING ALL)"
                    )
                )
                await db.execute(
                    text(
                        f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qualified}.{table} TO lms_app"
                    )
                )
            await db.execute(
                text(
                    f"ALTER TABLE {qualified}.user_invitations ENABLE ROW LEVEL SECURITY"
                )
            )
            await db.execute(
                text(
                    f"ALTER TABLE {qualified}.user_invitations FORCE ROW LEVEL SECURITY"
                )
            )
            # Exact source0042 tenant expression; not a copy of arbitrary live DDL.
            expression = (
                "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
            )
            await db.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON {qualified}.user_invitations USING ({expression}) WITH CHECK ({expression})"
                )
            )
            await db.execute(
                text(
                    f"CREATE POLICY user_invitations_public_pending_lookup ON {qualified}.user_invitations FOR SELECT USING (status='pending')"
                )
            )
            # Source0019 invoker helper, isolated fixed path; no public function call.
            await db.execute(
                text(
                    f"CREATE FUNCTION {qualified}.set_current_tenant(tenant_uuid uuid) RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN PERFORM set_config('app.tenant_id',tenant_uuid::text,true); END; $$"
                )
            )
            await db.execute(
                text(
                    f"REVOKE ALL ON FUNCTION {qualified}.set_current_tenant(uuid) FROM PUBLIC"
                )
            )
            await db.execute(
                text(
                    f"GRANT EXECUTE ON FUNCTION {qualified}.set_current_tenant(uuid) TO lms_app"
                )
            )
            for index, tenant in enumerate(tenants):
                await db.execute(
                    text(
                        f"INSERT INTO {qualified}.tenants(id,name,slug) VALUES(:id,:name,:slug)"
                    ),
                    {
                        "id": tenant,
                        "name": f"Synthetic invitation {index}",
                        "slug": tenant.hex,
                    },
                )
            for index, invite_id in enumerate(invitation_ids):
                await db.execute(
                    text(
                        f"INSERT INTO {qualified}.user_invitations(id,tenant_id,email,invited_by,token,status,expires_at,user_id) VALUES(:id,:tenant,:email,:actor,:token,:status,:expiry,:user)"
                    ),
                    {
                        "id": invite_id,
                        "tenant": tenants[int(index == 5)],
                        "email": f"synthetic-{index}@example.invalid",
                        "actor": uuid4(),
                        "token": tokens[index],
                        "status": statuses[index % 5],
                        "expiry": datetime.now(UTC) + timedelta(days=1),
                        "user": uuid4(),
                    },
                )

        async def visible(tenant="", token=""):
            async with runtime.begin() as db:
                await context(db, schema, tenant, token)
                resolved = await db.scalar(
                    text(
                        "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass('user_invitations')"
                    )
                )
                if resolved != schema:
                    raise GateBlocked("public_invitation_resolution")
                return set(
                    (await db.scalars(text("SELECT id FROM user_invitations"))).all()
                )

        stage = "legacy_reproduction"
        if await visible(tenants[0]) != set(invitation_ids):
            raise GateBlocked("legacy_control_not_reproduced")
        if await visible() != {invitation_ids[0], invitation_ids[5]}:
            raise GateBlocked("legacy_anonymous_control_not_reproduced")
        checks.append("legacy_foreign_pending_and_anonymous_enumeration_reproduced")
        stage = "migration0170"
        async with owner.begin() as db:
            await apply_migration(db, schema)
            flags = (
                await db.execute(
                    text(
                        "SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname='user_invitations'"
                    ),
                    {"s": schema},
                )
            ).one()
            if flags != (True, True):
                raise GateBlocked("force_rls_missing")
            policies = set(
                (
                    await db.scalars(
                        text(
                            "SELECT p.polname FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname='user_invitations'"
                        ),
                        {"s": schema},
                    )
                ).all()
            )
            if policies != {"tenant_isolation", "user_invitations_public_token_lookup"}:
                raise GateBlocked("unexpected_policy_set")
        checks.append("migration0170_force_rls_exact_policy_set")
        stage = "token_tenant_negatives"
        for token in (
            "",
            "unrelated-synthetic",
            tokens[0].upper(),
            tokens[0] + " ",
            "' OR true --",
        ):
            if await visible(token=token):
                raise GateBlocked("absent_wrong_or_alternate_token_visible")
        checks.append("absent_wrong_empty_case_space_injection_tokens_hidden")
        for index, token in enumerate(tokens):
            if await visible(token=token) != {invitation_ids[index]}:
                raise GateBlocked("exact_token_not_single_row")
        checks.append("exact_token_single_row_all_five_statuses_two_tenants")
        if await visible(tenants[0], tokens[5]) != set(invitation_ids[:5]):
            raise GateBlocked("foreign_token_overrode_authenticated_tenant")
        if await visible(tenants[1], tokens[0]) != {invitation_ids[5]}:
            raise GateBlocked("reverse_tenant_isolation_failed")
        checks.append("both_tenants_hide_foreign_even_with_foreign_token")
        async with runtime.begin() as db:
            await context(db, schema, token=tokens[0])
            changed = await db.execute(
                text("UPDATE user_invitations SET first_name='Forbidden' WHERE id=:id"),
                {"id": invitation_ids[0]},
            )
            deleted = await db.execute(
                text("DELETE FROM user_invitations WHERE id=:id"),
                {"id": invitation_ids[0]},
            )
            if changed.rowcount != 0 or deleted.rowcount != 0:
                raise GateBlocked("anonymous_token_allowed_write")
            try:
                async with db.begin_nested():
                    await db.execute(
                        text(
                            "INSERT INTO user_invitations(id,tenant_id,email,invited_by,token,expires_at) VALUES(:id,:tenant,'denied@example.invalid',:actor,:token,:expiry)"
                        ),
                        {
                            "id": uuid4(),
                            "tenant": tenants[0],
                            "actor": uuid4(),
                            "token": uuid4().hex,
                            "expiry": datetime.now(UTC),
                        },
                    )
            except DBAPIError as exc:
                if "42501" not in safe_failure(exc):
                    raise
            else:
                raise GateBlocked("anonymous_token_allowed_insert")
        checks.append("anonymous_exact_token_insert_update_delete_denied")
        async with runtime.begin() as db:
            await context(db, schema, tenants[0])
            changed = await db.execute(
                text("UPDATE user_invitations SET first_name='Synthetic' WHERE id=:id"),
                {"id": invitation_ids[0]},
            )
            if changed.rowcount != 1:
                raise GateBlocked("normal_tenant_mutation_broken")
        checks.append("normal_own_tenant_update_preserved")
        # Same physical connection: LOCAL token must disappear after commit/rollback.
        async with runtime.connect() as db:
            for commit in (True, False):
                await context(db, schema, token=tokens[0])
                if await db.scalar(text("SELECT count(*) FROM user_invitations")) != 1:
                    raise GateBlocked("transaction_scope_control_failed")
                if commit:
                    await db.commit()
                else:
                    await db.rollback()
                await db.execute(
                    text(f"SET LOCAL search_path TO {qualified},pg_catalog")
                )
                if await db.scalar(text("SELECT count(*) FROM user_invitations")) != 0:
                    raise GateBlocked("token_context_leaked_after_transaction")
                await db.rollback()
        checks.append("same_connection_commit_rollback_token_scope_cleared")
        stage = "application_lookup_and_view"
        sys.path.insert(0, str(ROOT / "apps/api"))
        from app.models.registry import load_all_models

        load_all_models()
        from app.modules.users.invitations_service import (
            _get_pending_invitation,
            _lookup_public_invitation,
            get_public_invitation,
        )
        from fastapi import HTTPException

        for index, token in enumerate(tokens):
            async with AsyncSession(runtime, expire_on_commit=False) as db:
                await context(db, schema)
                for table in TABLES:
                    resolved = await db.scalar(
                        text(
                            "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:t)"
                        ),
                        {"t": table},
                    )
                    if resolved != schema:
                        raise GateBlocked("application_table_resolution_not_owned")
                outcome = await get_public_invitation(db, token)
                expected = (
                    None,
                    "already_accepted",
                    "expired",
                    "revoked",
                    "superseded",
                )[index % 5]
                if outcome["reason_if_invalid"] != expected or outcome["valid"] != (
                    expected is None
                ):
                    raise GateBlocked("public_terminal_state_compatibility_failed")
                scope = await db.scalar(
                    text("SELECT current_setting('app.invitation_token',true)")
                )
                if scope != "":
                    raise GateBlocked("helper_token_scope_not_cleared")
                await db.rollback()
            async with AsyncSession(runtime, expire_on_commit=False) as db:
                await context(db, schema)
                try:
                    invitation = await _get_pending_invitation(db, token)
                except HTTPException as exc:
                    if index % 5 == 0 or exc.status_code != 410:
                        raise GateBlocked(
                            "activation_terminal_state_not_rejected"
                        ) from None
                else:
                    if index % 5 != 0 or invitation.id != invitation_ids[index]:
                        raise GateBlocked("activation_pending_identity_mismatch")
                await db.rollback()
        checks += [
            "shared_public_lookup_masked_view_and_terminal_reasons",
            "pending_activation_bootstrap_nonpending410_no_otp_or_accept",
        ]
        async with AsyncSession(runtime) as db:
            await context(db, schema)
            if await _lookup_public_invitation(db, "unrelated-synthetic") is not None:
                raise GateBlocked("unknown_application_token_matched")
            if (
                await db.scalar(
                    text("SELECT current_setting('app.invitation_token',true)")
                )
                != ""
            ):
                raise GateBlocked("missing_token_lookup_scope_not_cleared")
        checks.append("missing_application_token_scope_cleared")
    except Exception as exc:
        failure = safe_failure(exc)
    finally:
        if created:
            try:
                async with owner.begin() as db:
                    await db.execute(text(f"DROP SCHEMA IF EXISTS {qualified} CASCADE"))
                async with owner.connect() as db:
                    cleanup = not await db.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"
                        ),
                        {"s": schema},
                    )
                    neutral = before == await public_snapshot(db)
            except Exception:
                cleanup = False
        await runtime.dispose()
        await owner.dispose()
    outcome = {
        "status": "PASS" if failure is None and cleanup and neutral else "BLOCKED",
        "scope": "synthetic_invitation_token_rls_supabase_dev",
        "stage": stage,
        "failure": failure,
        "checks": checks,
        "cleanup": cleanup,
        "public_schema_neutral": neutral,
        "other_neighbor_equivalence": "NOT_VERIFIED",
        "public_policy_applied": False,
        "otp_mail_activation": "NOT_RUN",
    }
    assert_sanitized_evidence(outcome)
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    config = dotenv_values(args.env_file)
    load_dotenv(args.env_file, override=True)
    try:
        result = asyncio.run(
            run_gate(
                *(
                    normalize_database_url(config.get(key) or "")
                    for key in ("MIGRATION_DATABASE_URL", "DATABASE_URL")
                ),
                config.get("SUPABASE_URL") or "",
            )
        )
    except Exception as exc:
        result = {"status": "BLOCKED", "reason": safe_failure(exc)}
    assert_sanitized_evidence(result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
