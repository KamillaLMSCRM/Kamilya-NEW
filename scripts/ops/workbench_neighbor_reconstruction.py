"""Source-bound owned assignment controls; never copy or execute runtime DDL."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sqlalchemy import text

from kb_rag_isolated_dev_gate import GateBlocked
from workbench_neighbor_catalog import TRIGGER_SOURCES, identifier

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "apps/api/alembic/versions"
REFERENCED_TABLES = (
    "documents",
    "learning_path_assignments",
    "recurring_learning_assignments",
    "learning_path_courses",
    "learning_paths",
)
TRIGGER_DEFINITIONS = {
    "content_releases_prevent_mutation": (
        "0081_course_release_and_attempt_evidence.py",
        "upgrade",
    ),
    "courses_validate_current_release": (
        "0081_course_release_and_attempt_evidence.py",
        "upgrade",
    ),
    "enrollments_bind_content_release": (
        "0081_course_release_and_attempt_evidence.py",
        "upgrade",
    ),
    "enrollment_access_policy_ownership": (
        "0106_enrollment_access_policies.py",
        "upgrade",
    ),
    "trg_validate_position_import_identity": (
        "0114_position_import_identity.py",
        "upgrade",
    ),
    "trg_validate_recurring_enrollment_identity": (
        "0103_recurring_enrollment_instances.py",
        "upgrade",
    ),
    "trg_validate_manual_reassignment_identity": (
        "0162_manual_reassignment_occurrences.py",
        "upgrade",
    ),
    "trg_validate_organization_unit_v2": (
        "0161_organization_hierarchy_v2.py",
        "_unit_trigger_sql",
    ),
    "trg_validate_user_organization_unit_ownership": (
        "0161_organization_hierarchy_v2.py",
        "_user_trigger_sql",
    ),
}


def owned_schema(schema):
    if not re.fullmatch(r"workbench_[0-9a-f]{12}", schema):
        raise GateBlocked("neighbor_schema_invalid")
    return f'"{schema}"'


def literal(node, bindings):
    """Deliberately not eval/import: only reviewed declarative source syntax."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in bindings:
        return bindings[node.id]
    if isinstance(node, ast.Tuple | ast.List):
        return tuple(literal(item, bindings) for item in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return literal(node.left, bindings) + literal(node.right, bindings)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(literal(item.value, bindings))
            if isinstance(item, ast.FormattedValue)
            else literal(item, bindings)
            for item in node.values
        )
    raise ValueError("unsupported_source_expression")


def source_strings(filename, function="upgrade", **extra):
    tree = ast.parse((VERSIONS / filename).read_text(encoding="utf-8"))
    bindings = {
        "schema": "public",
        **{
            name: f'"public".{name}' for name in ("departments", "users", "enrollments")
        },
    }
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                bindings[node.targets[0].id] = literal(node.value, bindings)
            except (ValueError, KeyError, TypeError):
                pass
    if "ALLOWED_UNIT_TYPES" in bindings:
        bindings["allowed"] = ", ".join(
            f"'{item}'" for item in bindings["ALLOWED_UNIT_TYPES"]
        )
    bindings.update(extra)
    selected = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function
        ),
        None,
    )
    if selected is None:
        raise GateBlocked("neighbor_source_function_missing")
    values = []
    # Capture op.execute inputs and local declarative strings, not fragment constants.
    for node in ast.walk(selected):
        candidates = []
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and node.args
        ):
            candidates.append(node.args[0])
        elif isinstance(node, ast.Assign):
            candidates.append(node.value)
        for value in candidates:
            try:
                resolved = literal(value, bindings)
            except (ValueError, KeyError, TypeError):
                continue
            strings = resolved if isinstance(resolved, tuple) else (resolved,)
            for item in strings:
                if isinstance(item, str) and item not in values:
                    values.append(item)
    return values, bindings


def select_source(filename, function, kind, name, *, on_table=None, **bindings):
    values, _ = source_strings(filename, function, **bindings)
    pattern = rf'^\s*CREATE\s+(?:OR\s+REPLACE\s+)?{kind}\s+(?:"?public"?\.)?{re.escape(name)}\b'
    found = [value for value in values if re.search(pattern, value, re.I)]
    if on_table is not None:
        table_pattern = (
            rf'\bON\s+(?:"?public"?\.)?"?{re.escape(identifier(on_table))}"?\b'
        )
        found = [value for value in found if re.search(table_pattern, value, re.I)]
    if len(found) != 1:
        raise GateBlocked("neighbor_source_definition_ambiguous")
    return found[0]


def rebase(sql, schema, *, kind=None):
    qualified = owned_schema(schema)
    result = re.sub(r'"?public"?\.', qualified + ".", sql)
    # Only schema entries in a SET search_path clause; never string inputs.
    result = re.sub(
        r'(SET\s+search_path\s*=\s*)"?public"?(?=[\s,;]|$)',
        lambda m: m[1] + qualified,
        result,
        flags=re.I,
    )
    if kind == "FUNCTION":
        result = re.sub(
            r"(CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+)([a-z_][a-z0-9_]*)\s*\(",
            lambda m: m[1] + qualified + "." + m[2] + "(",
            result,
            count=1,
            flags=re.I,
        )
    return result


async def catalog(db, schema, tables):
    """Reuse exact reviewed local catalog SELECTs, not runtime SQL definitions."""
    if schema != "public":
        owned_schema(schema)
    for table in tables:
        identifier(table)
    path = ROOT / "scripts/ops/workbench_neighbor_catalog.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "inspect_neighbor_catalog"
    )
    queries = [
        node.args[0].value
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "rows"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    if len(queries) != 5:
        raise GateBlocked("neighbor_catalog_source_drift")
    # pg_get_* definitions qualify names relative to search_path. Bind it to
    # the compared namespace so identical constraints deparse identically.
    await db.execute(text(f'SET LOCAL search_path TO "{identifier(schema)}", pg_catalog'))
    result = []
    for sql in queries:
        if sql.count("n.nspname='public'") != 1 or not sql.lstrip().startswith(
            "SELECT"
        ):
            raise GateBlocked("neighbor_catalog_query_invalid")
        rows = await db.execute(
            text(sql.replace("n.nspname='public'", "n.nspname=:schema")),
            {"schema": schema, "tables": list(tables)},
        )
        result.append([dict(row) for row in rows.mappings()])
    return result


def normalize(value, schema):
    if value is None:
        return None
    return re.sub(
        rf'(?<![a-zA-Z0-9_])"?{re.escape(schema)}"?(?![a-zA-Z0-9_])', "public", value
    )


def normalized_catalog(snapshot, schema):
    """Private comparison only: never emit expressions, column names or bodies."""
    groups = []
    for index, rows in enumerate(snapshot):
        group = []
        for row in rows:
            row = dict(row)
            if index == 1:
                for key in ("using_expr", "check_expr"):
                    row[key] = normalize(row[key], schema)
            elif index == 2:
                if row["target_schema"] == schema:
                    row["target_schema"] = "public"
                row["definition"] = normalize(row["definition"], schema)
            elif index == 3:
                if row["function_schema"] == schema:
                    row["function_schema"] = "public"
                for key in ("definition", "function_definition", "function_body"):
                    row[key] = normalize(row[key], schema)
                row["proconfig"] = (
                    [normalize(item, schema) for item in row["proconfig"]]
                    if row["proconfig"] is not None
                    else None
                )
            group.append(row)
        groups.append(group)
    return groups


def policy_sql(row, owner):
    table, name = identifier(row["relname"]), identifier(row["polname"])
    standard = {
        "tenant_isolation": (
            {
                "content_releases": "0081_course_release_and_attempt_evidence.py",
                "learning_paths": "0056_add_learning_paths.py",
                "learning_path_courses": "0056_add_learning_paths.py",
                "learning_path_assignments": "0075_learning_program_versions_and_assignments.py",
                "recurring_learning_assignments": "0098_recurring_learning_cycles.py",
            }.get(table, "0042_rls_empty_tenant_context_safe.py"),
            "upgrade",
        ),
        "tenant_organization_units_isolation": (
            "0161_organization_hierarchy_v2.py",
            "upgrade",
        ),
        "enrollment_access_policies_tenant": (
            "0106_enrollment_access_policies.py",
            "upgrade",
        ),
        "users_platform_superadmin_login": ("0044_rls_superadmin_login.py", "upgrade"),
        "users_auth_email_lookup": ("0061_rls_auth_email_lookup.py", "upgrade"),
        "user_invitations_public_pending_lookup": (
            "0046_rls_public_pending_invitations.py",
            "upgrade",
        ),
        "privileged_tenant_purge_delete": (
            "0124_privileged_tenant_purge_rls.py",
            "upgrade",
        ),
        "privileged_tenant_purge_select": (
            "0126_privileged_tenant_purge_visibility.py",
            "upgrade",
        ),
    }
    if name in standard:
        filename, function = standard[name]
        return select_source(
            filename,
            function,
            "POLICY",
            name,
            table=table,
            table_name=table,
            on_table=table,
        )
    if name == f"{table}_superadmin_session":
        return select_source(
            "0045_rls_superadmin_session_scope.py",
            "upgrade",
            "POLICY",
            name,
            table=table,
        )
    if table == "tenants" and name == "service_access":
        legacy = (VERSIONS / "0013e_rls_correct.sql").read_text(encoding="utf-8")
        if "CREATE POLICY service_access ON %I USING (true)" not in legacy:
            raise GateBlocked("neighbor_legacy_source_drift")
        return "CREATE POLICY service_access ON tenants USING (true)"
    if table == "users" and name == "users_auth_email_lookup_function_owner":
        source = (
            VERSIONS / "0111_email_login_lookup_function_owner_policy.py"
        ).read_text(encoding="utf-8")
        if "FOR SELECT TO %I USING (true)" not in source or row["roles"] != [owner]:
            raise GateBlocked("neighbor_lookup_owner_drift")
        return f'CREATE POLICY {name} ON users FOR SELECT TO "{identifier(owner)}" USING (true)'
    if table == "course_assignment_notification_outbox":
        _, bindings = source_strings("0154_assignment_notification_owner_policies.py")
        matches = [
            item
            for item in bindings["POLICIES"]
            if item[0] == table and item[1] == name
        ]
        if len(matches) != 1 or row["roles"] != [owner]:
            raise GateBlocked("neighbor_enqueue_policy_drift")
        _, _, command, predicate = matches[0]
        using = "" if command == "INSERT" else f"USING ({predicate})"
        check = f"WITH CHECK ({bindings['TENANT']})" if command != "SELECT" else ""
        return f'CREATE POLICY {name} ON {table} FOR {command} TO "{identifier(owner)}" {using} {check}'
    raise GateBlocked("neighbor_policy_source_unknown")


async def install_referenced_reads(db, schema, owner):
    """Reproduce SELECT only for trigger/policy dependencies; no target writes."""
    qualified = owned_schema(schema)
    baseline = normalized_catalog(
        await catalog(db, "public", REFERENCED_TABLES), "public"
    )
    if {row["relname"] for row in baseline[0]} != set(REFERENCED_TABLES):
        raise GateBlocked("neighbor_read_target_missing")
    selected = [
        row
        for row in baseline[1]
        if row["command"] in ("*", "r") and row["app_applies"]
    ]
    for row in baseline[0]:
        table = identifier(row["relname"])
        if (
            not row["can_select"]
            or not row["relrowsecurity"]
            or not row["relforcerowsecurity"]
        ):
            raise GateBlocked("neighbor_read_target_source_rights_drift")
        await db.execute(text(f"REVOKE ALL ON {qualified}.{table} FROM PUBLIC,lms_app"))
        await db.execute(text(f"GRANT SELECT ON {qualified}.{table} TO lms_app"))
        await db.execute(
            text(f"ALTER TABLE {qualified}.{table} ENABLE ROW LEVEL SECURITY")
        )
        await db.execute(
            text(f"ALTER TABLE {qualified}.{table} FORCE ROW LEVEL SECURITY")
        )
    await db.execute(text(f"SET LOCAL search_path TO {qualified},pg_catalog"))
    for row in selected:
        await db.execute(text(rebase(policy_sql(row, owner), schema)))
    actual = normalized_catalog(await catalog(db, schema, REFERENCED_TABLES), schema)
    if actual[1] != selected:
        raise GateBlocked("neighbor_read_target_policy_mismatch")
    for expected, observed in zip(baseline[0], actual[0], strict=True):
        keys = ("relname", "can_select", "relrowsecurity", "relforcerowsecurity")
        if any(expected[key] != observed[key] for key in keys):
            raise GateBlocked("neighbor_read_target_acl_flags_mismatch")
        if any(
            observed[f"can_{right}"]
            for right in (
                "insert",
                "update",
                "delete",
                "truncate",
                "references",
                "trigger",
            )
        ):
            raise GateBlocked("neighbor_read_target_write_not_revoked")
    expected_columns = [
        (row["relname"], row["attname"], row["can_select"]) for row in baseline[4]
    ]
    observed_columns = [
        (row["relname"], row["attname"], row["can_select"]) for row in actual[4]
    ]
    if expected_columns != observed_columns or any(
        row["can_insert"] or row["can_update"] or row["can_references"]
        for row in actual[4]
    ):
        raise GateBlocked("neighbor_read_target_column_acl_mismatch")


async def install_neighbors(db, schema, tables, *, apply_isolation=True):
    """Called within one owned setup transaction; fidelity BEFORE app fixtures."""
    qualified = owned_schema(schema)
    baseline = await catalog(db, "public", tables)
    if [len(group) for group in baseline[:4]] != [12, 26, 27, 9]:
        raise GateBlocked("neighbor_control_count_drift")
    owner = await db.scalar(text("SELECT current_user"))
    memberships = (
        await db.execute(
            text(
                "SELECT rolsuper,rolbypassrls,pg_has_role('lms_app',oid,'MEMBER') FROM pg_roles WHERE rolname=:owner"
            ),
            {"owner": owner},
        )
    ).one()
    if (
        owner in ("lms_app", "lms_recovery", "anon", "authenticated", "service_role")
        or memberships[2]
    ):
        raise GateBlocked("neighbor_function_owner_unsafe")
    from workbench_neighbor_function_acl import inspect_function_acl

    baseline_functions = await inspect_function_acl(db, "public", owner=owner)
    # Exact trusted source dependencies; never delivery/claim/finalize functions.
    for name, filename, function in [
        (
            "privileged_tenant_purge_authorized",
            "0141_superadmin_content_release_purge.py",
            "upgrade",
        ),
        (
            "lookup_login_user_by_email",
            "0111_email_login_lookup_function_owner_policy.py",
            "upgrade",
        ),
        *[(name, *source) for name, source in TRIGGER_SOURCES.items()],
    ]:
        ddl = select_source(filename, function, "FUNCTION", name)
        await db.execute(text(rebase(ddl, schema, kind="FUNCTION")))
    signature = f"{qualified}.lookup_login_user_by_email(text)"
    await db.execute(text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC"))
    await db.execute(text(f"GRANT EXECUTE ON FUNCTION {signature} TO lms_app"))
    await install_referenced_reads(db, schema, owner)
    # Existing harness used a stricter substitute; replace ONLY this owned policy.
    await db.execute(
        text(
            f"DROP POLICY gate_enqueue_owner ON {qualified}.course_assignment_notification_outbox"
        )
    )
    for row in baseline[0]:
        table = identifier(row["relname"])
        rights = [
            privilege
            for privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
            )
            if row[f"can_{privilege.lower()}"]
        ]
        expected = (
            []
            if table == "course_assignment_notification_outbox"
            else ["SELECT", "INSERT", "UPDATE"]
            + ([] if table == "enrollment_access_policies" else ["DELETE"])
        )
        if rights != expected:
            raise GateBlocked("neighbor_source_grant_drift")
        await db.execute(text(f"REVOKE ALL ON {qualified}.{table} FROM PUBLIC,lms_app"))
        if rights:
            await db.execute(
                text(f"GRANT {','.join(rights)} ON {qualified}.{table} TO lms_app")
            )
        enabled = "ENABLE" if row["relrowsecurity"] else "DISABLE"
        force = "FORCE" if row["relforcerowsecurity"] else "NO FORCE"
        await db.execute(
            text(f"ALTER TABLE {qualified}.{table} {enabled} ROW LEVEL SECURITY")
        )
        await db.execute(
            text(f"ALTER TABLE {qualified}.{table} {force} ROW LEVEL SECURITY")
        )
    for row in baseline[1]:
        ddl = rebase(policy_sql(row, owner), schema)
        # Unqualified source ON tables resolve ONLY the owned schema.
        await db.execute(text(f"SET LOCAL search_path TO {qualified}, pg_catalog"))
        await db.execute(text(ddl))
    from workbench_neighbor_fk import foreign_key_sql

    fks = [
        dict(
            table=row["relname"],
            name=row["conname"],
            target_schema=row["target_schema"],
            target_table=row["target_table"],
            columns=row["columns"],
            target_columns=row["target_columns"],
            on_update=row["on_update"],
            on_delete=row["on_delete"],
            deferrable=row["condeferrable"],
            initially_deferred=row["condeferred"],
            validated=row["convalidated"],
        )
        for row in baseline[2]
    ]
    for ddl in foreign_key_sql(schema, fks):
        await db.execute(text(ddl))
    for row in baseline[3]:
        name = row["tgname"]
        if name not in TRIGGER_DEFINITIONS or row["enabled"] != "O":
            raise GateBlocked("neighbor_trigger_source_unknown")
        ddl = select_source(*TRIGGER_DEFINITIONS[name], "TRIGGER", name)
        await db.execute(text(rebase(ddl, schema)))
    actual = await catalog(db, schema, tables)
    owned_functions = await inspect_function_acl(db, schema, owner=owner)
    baseline_acl = [
        {key: value for key, value in row.items() if key != "schema"}
        for row in baseline_functions["functions"]
    ]
    owned_acl = [
        {key: value for key, value in row.items() if key != "schema"}
        for row in owned_functions["functions"]
    ]
    if baseline_acl != owned_acl:
        for expected, observed in zip(baseline_acl, owned_acl, strict=True):
            if expected != observed:
                keys = "_".join(
                    key for key in expected if expected[key] != observed[key]
                )
                raise GateBlocked(
                    f"neighbor_function_mismatch_{expected['name']}_{keys}"
                )
        raise GateBlocked("neighbor_readback_mismatch_function_acl_definition")
    left, right = (
        normalized_catalog(baseline, "public"),
        normalized_catalog(actual, schema),
    )
    for kind, expected, observed in zip(
        ("tables_acl_flags", "policies", "foreign_keys", "triggers", "column_acl"),
        left,
        right,
        strict=True,
    ):
        if observed != expected:
            # Retain only category and object names, never SQL/expression data.
            raise GateBlocked(f"neighbor_readback_mismatch_{kind}")
    checks = [
        "neighbor_baseline26_policy27_fk9_trigger_acl_equivalence",
        "neighbor11_function_definition_effective_acl_equivalence",
    ]
    if apply_isolation:
        checks += await apply_neighbor_isolation(db, schema, tables)
    return checks


async def apply_neighbor_isolation(db, schema, tables, *, invitation_applied=False):
    """Deliberate expansion/restriction deltas are never baseline equivalence."""
    from workbench_assignment_dev_gate import migration

    baseline = normalized_catalog(await catalog(db, "public", tables), "public")
    owner = await db.scalar(text("SELECT current_user"))
    if not invitation_applied:
        await migration(db, schema, path=VERSIONS / "0170_invitation_exact_token_rls.py")
    await migration(db, schema, path=VERSIONS / "0172_tenants_scoped_bootstrap_rls.py")
    await verify_deliberate_deltas(db, schema, tables, baseline, owner)
    return ["neighbor_owned0170_0172_upgrade"]


async def verify_compatibility_expansion(db, schema, tables):
    baseline = normalized_catalog(await catalog(db, "public", tables), "public")
    actual = normalized_catalog(await catalog(db, schema, tables), schema)
    extra = [row for row in actual[1] if row["polname"] == "tenants_bootstrap_function_owner"]
    remaining = [row for row in actual[1] if row["polname"] != "tenants_bootstrap_function_owner"]
    if len(extra) != 1 or remaining != baseline[1] or any(
        actual[index] != baseline[index] for index in (0, 2, 3, 4)
    ):
        raise GateBlocked("compatibility_expansion_changed_neighbor_controls")
    owner = await db.scalar(text("SELECT current_user"))
    policy = extra[0]
    if (policy["relname"], policy["command"], policy["roles"], policy["app_applies"],
        policy["using_expr"], policy["check_expr"]) != (
        "tenants", "r", [owner], False, "true", None
    ):
        raise GateBlocked("compatibility_expansion_owner_policy_mismatch")
    return ["compatibility169_expansion_preserves_legacy_neighbor_controls"]


def predicate_tokens(value):
    """Ignore PostgreSQL pretty-print parentheses/text casts, not SQL semantics."""
    return re.sub(r"[\s()]", "", (value or "").replace("::text", ""))


async def verify_deliberate_deltas(db, schema, tables, baseline, owner):
    actual = normalized_catalog(await catalog(db, schema, tables), schema)
    expected_tables = [dict(row) for row in baseline[0]]
    for row in expected_tables:
        if row["relname"] == "tenants":
            row["relrowsecurity"] = row["relforcerowsecurity"] = True
    if actual[0] != expected_tables or actual[2:] != baseline[2:]:
        raise GateBlocked("neighbor_upgrade_unexpected_nonpolicy_delta")
    removed = {
        ("tenants", "service_access"),
        ("user_invitations", "user_invitations_public_pending_lookup"),
    }
    unchanged = [
        row for row in baseline[1] if (row["relname"], row["polname"]) not in removed
    ]
    added_names = {
        ("tenants", "tenants_bootstrap_function_owner"),
        ("tenants", "tenants_own_context"),
        ("user_invitations", "user_invitations_public_token_lookup"),
    }
    retained = [
        row for row in actual[1] if (row["relname"], row["polname"]) not in added_names
    ]
    if retained != unchanged or len(actual[1]) != 27:
        raise GateBlocked("neighbor_upgrade_unexpected_policy_set")
    expected_added = {
        "tenants_bootstrap_function_owner": ("r", [owner], False, "true", None),
        "tenants_own_context": (
            "*",
            ["lms_app"],
            True,
            "id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
            "id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
        ),
        "user_invitations_public_token_lookup": (
            "r",
            ["lms_app"],
            True,
            "NULLIF(current_setting('app.tenant_id', true), '') IS NULL AND "
            "token = NULLIF(current_setting('app.invitation_token', true), '')",
            None,
        ),
    }
    for row in actual[1]:
        if (row["relname"], row["polname"]) not in added_names:
            continue
        command, roles, app, using, check = expected_added[row["polname"]]
        if (row["command"], row["roles"], row["app_applies"], row["polpermissive"]) != (
            command,
            roles,
            app,
            True,
        ):
            raise GateBlocked("neighbor_upgrade_policy_identity_drift")
        if predicate_tokens(row["using_expr"]) != predicate_tokens(
            using
        ) or predicate_tokens(row["check_expr"]) != predicate_tokens(check):
            raise GateBlocked("neighbor_upgrade_policy_expression_drift")


def error_state(exc):
    """Inspect diagnostic codes only; never return a driver message or values."""
    current = exc
    for _ in range(6):
        state = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if state is not None:
            return state
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
        if current is None:
            break
    return None


async def verify_neighbor_negatives(
    owner_engine,
    runtime_engine,
    schema,
    tenant_id,
    other_tenant,
    actor_id,
    learner_id,
    course_id,
    release_id,
):
    """Synthetic, rollback-only control counterexamples as actual lms_app."""
    from uuid import uuid4

    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.department import Department
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from workbench_assignment_dev_gate import context

    owned_schema(schema)
    foreign_dept, foreign_course, foreign_release = (uuid4() for _ in range(3))
    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        await context(db, schema, other_tenant, actor_id)
        db.add(
            Department(
                id=foreign_dept,
                tenant_id=other_tenant,
                name="Foreign control",
                slug="foreign-control",
                normalized_name="foreign control",
            )
        )
        db.add(
            Course(
                id=foreign_course,
                tenant_id=other_tenant,
                title="Foreign control",
                status="published",
            )
        )
        await db.flush()
        db.add(
            ContentRelease(
                id=foreign_release,
                tenant_id=other_tenant,
                course_id=foreign_course,
                version=1,
                snapshot={},
                snapshot_sha256="b" * 64,
            )
        )
        await db.commit()
    probes = (
        (
            "missing_foreign_key_reference_denied",
            "23503",
            "UPDATE courses SET reviewed_by=:bad WHERE id=:own",
            {"bad": uuid4(), "own": course_id},
        ),
        (
            "cross_tenant_organization_trigger_denied",
            "23503",
            "UPDATE users SET organization_unit_id=:bad WHERE id=:own",
            {"bad": foreign_dept, "own": learner_id},
        ),
        (
            "cross_tenant_current_release_trigger_denied",
            "23503",
            "UPDATE courses SET current_release_id=:bad WHERE id=:own",
            {"bad": foreign_release, "own": course_id},
        ),
        (
            "immutable_published_release_update_denied",
            "23514",
            "UPDATE content_releases SET snapshot='{}'::jsonb WHERE id=:own",
            {"own": release_id},
        ),
        (
            "immutable_published_release_delete_denied",
            "23514",
            "DELETE FROM content_releases WHERE id=:own",
            {"own": release_id},
        ),
    )
    checks = []
    for name, expected, sql, params in probes:
        async with AsyncSession(runtime_engine) as db:
            await context(db, schema, tenant_id, actor_id)
            try:
                await db.execute(text(sql), params)
            except DBAPIError as exc:
                if error_state(exc) != expected:
                    raise GateBlocked(f"neighbor_negative_wrong_state_{name}") from None
            else:
                raise GateBlocked(f"neighbor_negative_not_denied_{name}")
            finally:
                await db.rollback()
        checks.append(name)
    async with AsyncSession(runtime_engine) as db:
        await context(db, schema, tenant_id, actor_id)
        row = (
            await db.execute(
                text("SELECT current_release_id,reviewed_by FROM courses WHERE id=:id"),
                {"id": course_id},
            )
        ).one()
        if row.current_release_id != release_id or row.reviewed_by is not None:
            raise GateBlocked("neighbor_negative_rollback_changed_course")
        if (
            await db.scalar(
                text("SELECT count(*) FROM content_releases WHERE id=:id"),
                {"id": release_id},
            )
            != 1
        ):
            raise GateBlocked("neighbor_negative_rollback_changed_release")
        await db.rollback()
    return checks + ["neighbor_negative_rollbacks_preserve_fixture"]
