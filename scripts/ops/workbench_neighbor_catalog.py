"""Bounded read-only catalog inventory; never execute or emit live DDL."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")
TRIGGER_SOURCES = {
    "prevent_content_release_mutation": (
        "0127_privileged_immutable_row_purge.py",
        "upgrade",
    ),
    "validate_course_current_release": (
        "0081_course_release_and_attempt_evidence.py",
        "upgrade",
    ),
    "validate_organization_unit_v2": (
        "0161_organization_hierarchy_v2.py",
        "_unit_trigger_sql",
    ),
    "validate_enrollment_access_policy_ownership": (
        "0106_enrollment_access_policies.py",
        "upgrade",
    ),
    "bind_enrollment_content_release": (
        "0081_course_release_and_attempt_evidence.py",
        "upgrade",
    ),
    "validate_manual_reassignment_identity": (
        "0162_manual_reassignment_occurrences.py",
        "upgrade",
    ),
    "validate_recurring_enrollment_identity": (
        "0145_learning_path_recurrence_bridge.py",
        "upgrade",
    ),
    "validate_position_import_identity": (
        "0114_position_import_identity.py",
        "upgrade",
    ),
    "validate_user_organization_unit_ownership": (
        "0161_organization_hierarchy_v2.py",
        "_user_trigger_sql",
    ),
}


def identifier(value):
    from kb_rag_isolated_dev_gate import GateBlocked

    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise GateBlocked("neighbor_catalog_identifier_invalid")
    return value


def digest(value):
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def accepted_trigger_source(name):
    """Extract only reviewed local literal/f-string SQL; never import/execute it."""
    source = TRIGGER_SOURCES.get(name)
    if source is None:
        return None
    filename, function = source
    path = Path(__file__).resolve().parents[2] / "apps/api/alembic/versions" / filename
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == function
    )
    bindings = {
        "schema": "public",
        **{
            item: f'"public".{item}' for item in ("departments", "users", "enrollments")
        },
    }
    if filename == "0161_organization_hierarchy_v2.py":
        allowed = next(
            item.value
            for item in tree.body
            if isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ALLOWED_UNIT_TYPES"
                for target in item.targets
            )
        )
        bindings["allowed"] = ", ".join(
            f"'{value}'" for value in ast.literal_eval(allowed)
        )

    def literal(item):
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            return item.value
        if isinstance(item, ast.JoinedStr):
            pieces = []
            for part in item.values:
                if isinstance(part, ast.Constant):
                    pieces.append(part.value)
                elif (
                    isinstance(part, ast.FormattedValue)
                    and isinstance(part.value, ast.Name)
                    and part.value.id in bindings
                ):
                    pieces.append(bindings[part.value.id])
                else:
                    return None
            return "".join(pieces)
        return None

    bodies = []
    for item in ast.walk(node):
        sql = literal(item)
        if sql and re.search(
            rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:[\"a-z_]+\.)?{re.escape(name)}\s*\(",
            sql,
            re.I,
        ):
            match = re.search(r"\bAS\s+\$\$(.*?)\$\$", sql, re.I | re.S)
            if match:
                bodies.append(match.group(1))
    if len(bodies) != 1:
        from kb_rag_isolated_dev_gate import GateBlocked

        raise GateBlocked("neighbor_trigger_source_ambiguous")
    return {
        "path": f"apps/api/alembic/versions/{filename}",
        "source_sha256": digest(content),
        "body_sha256": digest(bodies[0]),
    }


def classify_policy(command, permissive, applies, expression):
    from workbench_assignment_dev_gate import classify_pending_policy

    normalized = re.sub(r"[\s()]", "", expression or "")
    if command in {"r", "*"} and permissive and applies and normalized == "true":
        return "unscoped_true_policy"
    return classify_pending_policy(command, permissive, applies, expression)


async def inspect_neighbor_catalog(owner_url, runtime_url, supabase_url):
    from kb_rag_isolated_dev_gate import (
        GateBlocked,
        assert_sanitized_evidence,
        same_supabase_project,
    )
    from source_actuality_dev_gate import verify_runtime_role
    from workbench_assignment_dev_gate import TABLES

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
    params = {"tables": list(TABLES)}
    try:
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
        async with owner.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )

            async def rows(sql):
                return (await connection.execute(text(sql), params)).mappings().all()

            tables = await rows("""
                SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,
                    has_table_privilege('lms_app',c.oid,'SELECT') AS can_select,
                    has_table_privilege('lms_app',c.oid,'INSERT') AS can_insert,
                    has_table_privilege('lms_app',c.oid,'UPDATE') AS can_update,
                    has_table_privilege('lms_app',c.oid,'DELETE') AS can_delete,
                    has_table_privilege('lms_app',c.oid,'TRUNCATE') AS can_truncate,
                    has_table_privilege('lms_app',c.oid,'REFERENCES') AS can_references,
                    has_table_privilege('lms_app',c.oid,'TRIGGER') AS can_trigger
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relname=ANY(:tables) AND c.relkind='r'
                ORDER BY c.relname
            """)
            policies = await rows("""
                SELECT c.relname,p.polname,p.polcmd::text AS command,p.polpermissive,
                    ARRAY(SELECT CASE WHEN r=0 THEN 'public' ELSE (SELECT rolname FROM pg_roles WHERE oid=r) END
                        FROM unnest(p.polroles) r ORDER BY r) AS roles,
                    (0=ANY(p.polroles) OR EXISTS(SELECT 1 FROM pg_roles r
                        WHERE r.oid=ANY(p.polroles) AND pg_has_role('lms_app',r.oid,'MEMBER'))) AS app_applies,
                    pg_get_expr(p.polqual,p.polrelid) AS using_expr,
                    pg_get_expr(p.polwithcheck,p.polrelid) AS check_expr
                FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relname=ANY(:tables)
                ORDER BY c.relname,p.polname
            """)
            foreign_keys = await rows("""
                SELECT c.relname,k.conname,nn.nspname AS target_schema,cc.relname AS target_table,
                    ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY key(attnum,i)
                        JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=key.attnum ORDER BY key.i) AS columns,
                    ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY key(attnum,i)
                        JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=key.attnum ORDER BY key.i) AS target_columns,
                    k.condeferrable,k.condeferred,k.convalidated,k.confupdtype::text AS on_update,
                    k.confdeltype::text AS on_delete,pg_get_constraintdef(k.oid,true) AS definition
                FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    JOIN pg_class cc ON cc.oid=k.confrelid JOIN pg_namespace nn ON nn.oid=cc.relnamespace
                WHERE n.nspname='public' AND c.relname=ANY(:tables) AND k.contype='f'
                ORDER BY c.relname,k.conname
            """)
            triggers = await rows("""
                SELECT c.relname,t.tgname,t.tgenabled::text AS enabled,t.tgdeferrable,t.tginitdeferred,
                    fn.nspname AS function_schema,p.proname AS function_name,p.prosecdef,
                    p.proconfig,owner.rolname AS function_owner,owner.rolsuper,owner.rolbypassrls,
                    pg_get_triggerdef(t.oid,true) AS definition,pg_get_functiondef(p.oid) AS function_definition,
                    p.prosrc AS function_body
                FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace fn ON fn.oid=p.pronamespace
                    JOIN pg_roles owner ON owner.oid=p.proowner
                WHERE n.nspname='public' AND c.relname=ANY(:tables) AND NOT t.tgisinternal
                ORDER BY c.relname,t.tgname
            """)
            columns = await rows("""
                SELECT c.relname,a.attname,
                    has_column_privilege('lms_app',c.oid,a.attnum,'SELECT') AS can_select,
                    has_column_privilege('lms_app',c.oid,a.attnum,'INSERT') AS can_insert,
                    has_column_privilege('lms_app',c.oid,a.attnum,'UPDATE') AS can_update,
                    has_column_privilege('lms_app',c.oid,a.attnum,'REFERENCES') AS can_references
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relname=ANY(:tables) AND a.attnum>0 AND NOT a.attisdropped
                ORDER BY c.relname,a.attnum
            """)
        if {row["relname"] for row in tables} != set(TABLES):
            raise GateBlocked("neighbor_metadata_table_missing")
        safe_tables = [dict(row) for row in tables]
        for row in safe_tables:
            identifier(row["relname"])
        safe_policies = [
            {
                "table": identifier(row["relname"]),
                "name": identifier(row["polname"]),
                "command": row["command"],
                "permissive": row["polpermissive"],
                "roles": [identifier(role) for role in row["roles"]],
                "app_applies": row["app_applies"],
                "using_sha256": digest(row["using_expr"]),
                "check_sha256": digest(row["check_expr"]),
                "classification": classify_policy(
                    row["command"],
                    row["polpermissive"],
                    row["app_applies"],
                    row["using_expr"],
                ),
            }
            for row in policies
        ]
        safe_fks = [
            {
                "table": identifier(row["relname"]),
                "name": identifier(row["conname"]),
                "target_schema": identifier(row["target_schema"]),
                "target_table": identifier(row["target_table"]),
                "columns": [identifier(item) for item in row["columns"]],
                "target_columns": [identifier(item) for item in row["target_columns"]],
                "deferrable": row["condeferrable"],
                "initially_deferred": row["condeferred"],
                "validated": row["convalidated"],
                "on_update": row["on_update"],
                "on_delete": row["on_delete"],
                "definition_sha256": digest(row["definition"]),
            }
            for row in foreign_keys
        ]
        safe_triggers = [
            {
                "table": identifier(row["relname"]),
                "name": identifier(row["tgname"]),
                "enabled": row["enabled"],
                "deferrable": row["tgdeferrable"],
                "initially_deferred": row["tginitdeferred"],
                "function_schema": identifier(row["function_schema"]),
                "function": identifier(row["function_name"]),
                "security_definer": row["prosecdef"],
                "owner": identifier(row["function_owner"]),
                "owner_superuser": row["rolsuper"],
                "owner_bypassrls": row["rolbypassrls"],
                "function_config_sha256": digest("\n".join(row["proconfig"] or [])),
                "definition_sha256": digest(row["definition"]),
                "function_definition_sha256": digest(row["function_definition"]),
                "function_body_sha256": digest(row["function_body"]),
            }
            for row in triggers
        ]
        for trigger in safe_triggers:
            source = accepted_trigger_source(trigger["function"])
            trigger["source"] = source
            trigger["source_body_binding"] = (
                "UNKNOWN"
                if source is None
                else (
                    "MATCH"
                    if source["body_sha256"] == trigger["function_body_sha256"]
                    else "DRIFT"
                )
            )
        safe_columns = [
            {
                "table": identifier(row["relname"]),
                "column_sha256": digest(identifier(row["attname"])),
                "can_select": row["can_select"],
                "can_insert": row["can_insert"],
                "can_update": row["can_update"],
                "can_references": row["can_references"],
            }
            for row in columns
        ]
        column_acl = []
        for table in safe_tables:
            entries = [row for row in safe_columns if row["table"] == table["relname"]]
            overrides = [
                row
                for row in entries
                if any(
                    row[key] != table[key]
                    for key in (
                        "can_select",
                        "can_insert",
                        "can_update",
                        "can_references",
                    )
                )
            ]
            column_acl.append(
                {
                    "table": table["relname"],
                    "column_count": len(entries),
                    "effective_acl_sha256": digest(
                        json.dumps(entries, sort_keys=True, separators=(",", ":"))
                    ),
                    "overrides": overrides,
                }
            )
        unscoped = any(
            row["table"] == "user_invitations"
            and row["classification"] == "unscoped_pending_select"
            for row in safe_policies
        )
        result = {
            "status": "BLOCKED",
            "catalog_collection": "PASS",
            "scope": "read_only_dev_neighbor_catalog",
            "runtime_non_bypass": True,
            "snapshot": "repeatable_read_read_only",
            "tables": safe_tables,
            "policies": safe_policies,
            "foreign_keys": safe_fks,
            "triggers": safe_triggers,
            "column_acl": column_acl,
            "unscoped_pending_invitation_policy": unscoped,
            "unscoped_true_policies": [
                {"table": row["table"], "name": row["name"]}
                for row in safe_policies
                if row["classification"] == "unscoped_true_policy"
            ],
            "trigger_source_binding": "BODY_MATCH_ONLY"
            if len(safe_triggers) == len(TRIGGER_SOURCES)
            and {row["function"] for row in safe_triggers} == set(TRIGGER_SOURCES)
            and all(row["source_body_binding"] == "MATCH" for row in safe_triggers)
            else "NOT_VERIFIED",
            "force_rls_missing": [
                row["relname"] for row in safe_tables if not row["relforcerowsecurity"]
            ],
            "external_fk_targets": sorted(
                {
                    f'{row["target_schema"]}.{row["target_table"]}'
                    for row in safe_fks
                    if row["target_schema"] != "public"
                    or row["target_table"] not in TABLES
                }
            ),
            "neighbor_equivalence": "NOT_VERIFIED",
            "business_rows_read": False,
            "mutations": False,
            "functional_gate": "NOT_RUN",
            "public_migration": "NOT_RUN",
        }
        assert_sanitized_evidence(result)
        return result
    finally:
        await runtime.dispose()
        await owner.dispose()
