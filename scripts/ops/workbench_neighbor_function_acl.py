"""Source-bound function ACL readback for the neighbor workbench.

This module is deliberately read-only.  It builds one parameterized catalog
query and returns only sanitized metadata; function definitions and SQL are
used internally for source binding and are never returned or printed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from kb_rag_isolated_dev_gate import GateBlocked
from workbench_neighbor_catalog import TRIGGER_SOURCES

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "apps/api/alembic/versions"
_SCHEMA = re.compile(r"(?:public|workbench_[0-9a-f]{12})\Z")
_ROLE = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    identity_arguments: str
    source_file: str
    source_function: str = "upgrade"
    # PostgreSQL's default function ACL grants EXECUTE to PUBLIC.  A source
    # migration that explicitly revokes/grants overrides those defaults.
    public_execute: bool = True
    # Effective access includes PUBLIC; direct ACL access is separate.
    app_execute: bool = True
    app_execute_acl: bool = False
    security_definer: bool | None = None
    language: str | None = None


def _specs() -> tuple[FunctionSpec, ...]:
    trigger_specs = tuple(
        FunctionSpec(name, "", filename, function)
        for name, (filename, function) in sorted(TRIGGER_SOURCES.items())
    )
    return trigger_specs + (
        FunctionSpec(
            "privileged_tenant_purge_authorized",
            "uuid",
            "0141_superadmin_content_release_purge.py",
            security_definer=False,
            language="plpgsql",
        ),
        FunctionSpec(
            "lookup_login_user_by_email",
            "text",
            "0111_email_login_lookup_function_owner_policy.py",
            public_execute=False,
            app_execute=True,
            app_execute_acl=True,
            security_definer=True,
            language="sql",
        ),
    )


EXPECTED_FUNCTIONS = _specs()
EXPECTED_FUNCTION_NAMES = frozenset(item.name for item in EXPECTED_FUNCTIONS)

# No caller should interpolate a schema or function name into this statement.
# :schema is used for both the namespace and regprocedure lookup.  The
# aclexplode branch is intentionally explicit: effective privileges alone do
# not distinguish an explicit PUBLIC ACL from owner/default privileges.
FUNCTION_ACL_QUERY = """
SELECT
    p.oid,
    n.nspname AS function_schema,
    p.proname AS function_name,
    pg_catalog.oidvectortypes(p.proargtypes) AS identity_arguments,
    owner_role.rolname AS function_owner,
    owner_role.rolsuper AS owner_superuser,
    owner_role.rolbypassrls AS owner_bypassrls,
    p.prosecdef AS security_definer,
    language.lanname AS language,
    p.proconfig,
    has_function_privilege('lms_app', p.oid, 'EXECUTE') AS app_execute,
    COALESCE(bool_or(acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'), false)
        AS public_execute_acl,
    COALESCE(bool_or(acl.grantee = lms_role.oid
                     AND acl.privilege_type = 'EXECUTE'), false)
        AS app_execute_acl,
    COALESCE(bool_or(acl.grantee = owner_role.oid
                     AND acl.privilege_type = 'EXECUTE'), false)
        AS owner_execute_acl,
    pg_get_functiondef(p.oid) AS definition
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
JOIN pg_language AS language ON language.oid = p.prolang
JOIN pg_roles AS owner_role ON owner_role.oid = p.proowner
JOIN pg_roles AS lms_role ON lms_role.rolname = 'lms_app'
LEFT JOIN LATERAL aclexplode(
    COALESCE(p.proacl, acldefault('f', p.proowner))
) AS acl ON true
WHERE n.nspname = :schema
  AND p.proname = ANY(:function_names)
GROUP BY p.oid, n.nspname, p.proname, owner_role.rolname,
         owner_role.rolsuper, owner_role.rolbypassrls, p.prosecdef,
         language.lanname, p.proconfig, lms_role.oid
ORDER BY p.proname, identity_arguments
"""


def validate_schema(schema: str) -> str:
    if not isinstance(schema, str) or not _SCHEMA.fullmatch(schema):
        raise GateBlocked("neighbor_function_acl_schema_invalid")
    return schema


def _source_acl(spec: FunctionSpec) -> tuple[bool, bool]:
    """Bind expected ACLs to reviewed source, failing closed on source drift."""
    source = VERSIONS / spec.source_file
    try:
        content = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateBlocked("neighbor_function_acl_source_missing") from exc
    # Some reviewed migrations bind the owned schema through a local
    # ``schema`` variable, so the function header is not always a literal
    # ``public.<name>`` string.  Require a callable declaration/reference in
    # the selected source instead of guessing an arbitrary ACL baseline.
    marker = re.search(rf"\b{re.escape(spec.name)}\s*\(", content, re.IGNORECASE)
    if marker is None:
        raise GateBlocked("neighbor_function_acl_source_unknown")
    # Only exact, reviewed ACL statements are accepted.  Absence means the
    # PostgreSQL default ACL, not an invented least-privilege substitute.
    relevant = content[marker.start() :]
    revoked = bool(
        re.search(
            rf"REVOKE\s+ALL\s+ON\s+FUNCTION\s+(?:public\.)?{re.escape(spec.name)}\({re.escape(spec.identity_arguments)}\)\s+FROM\s+PUBLIC",
            relevant,
            re.IGNORECASE,
        )
    )
    granted = bool(
        re.search(
            rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+(?:public\.)?{re.escape(spec.name)}\({re.escape(spec.identity_arguments)}\)\s+TO\s+lms_app",
            relevant,
            re.IGNORECASE,
        )
    )
    if revoked and not granted:
        raise GateBlocked("neighbor_function_acl_source_incomplete")
    if revoked:
        return False, True
    if granted:
        raise GateBlocked("neighbor_function_acl_source_ambiguous")
    return spec.public_execute, spec.app_execute_acl


def _normalize_controlled(value: str, schema: str) -> str:
    """Normalize only schema tokens, preserving all other definition text."""
    token = "__WORKBENCH_SCHEMA__"
    value = re.sub(
        rf'(?<![a-zA-Z0-9_])"?{re.escape(schema)}"?(?![a-zA-Z0-9_])', token, value
    )
    return value


def _safe_hash(value: str | None, schema: str) -> str | None:
    return (
        None
        if value is None
        else hashlib.sha256(_normalize_controlled(value, schema).encode()).hexdigest()
    )


def _public_project_callee(definition: str) -> bool:
    # pg_catalog is safe; any other public-qualified project callee is an
    # owned-schema rebasing failure.  The body itself is never returned.
    return bool(re.search(r'(?<![a-zA-Z0-9_])"?public"?\.', definition, re.I))


def _row_metadata(
    row: dict[str, Any], schema: str, spec: FunctionSpec, owner: str | None
) -> dict[str, Any]:
    if row.get("function_schema") != schema:
        raise GateBlocked("neighbor_function_acl_namespace_drift")
    if (
        row.get("function_name") != spec.name
        or row.get("identity_arguments") != spec.identity_arguments
    ):
        raise GateBlocked("neighbor_function_acl_signature_drift")
    row_owner = row.get("function_owner")
    if not isinstance(row_owner, str) or not _ROLE.fullmatch(row_owner):
        raise GateBlocked("neighbor_function_acl_owner_invalid")
    expected_public, expected_app_acl = _source_acl(spec)
    expected_app = expected_public or expected_app_acl
    if bool(row.get("public_execute_acl")) != expected_public:
        raise GateBlocked("neighbor_function_acl_public_drift")
    if bool(row.get("app_execute")) != expected_app:
        raise GateBlocked("neighbor_function_acl_effective_app_drift")
    if bool(row.get("app_execute_acl")) != expected_app_acl:
        raise GateBlocked("neighbor_function_acl_explicit_app_drift")
    if not bool(row.get("owner_execute_acl")):
        raise GateBlocked("neighbor_function_acl_owner_drift")
    if owner is not None and row_owner != owner:
        raise GateBlocked("neighbor_function_acl_owner_identity_drift")
    if (
        spec.security_definer is not None
        and bool(row.get("security_definer")) != spec.security_definer
    ):
        raise GateBlocked("neighbor_function_acl_security_definer_drift")
    if spec.language is not None and row.get("language") != spec.language:
        raise GateBlocked("neighbor_function_acl_language_drift")
    definition = row.get("definition")
    if not isinstance(definition, str) or (
        schema != "public" and _public_project_callee(definition)
    ):
        raise GateBlocked("neighbor_function_acl_public_callee_drift")
    return {
        "schema": schema,
        "name": spec.name,
        "identity_arguments": spec.identity_arguments,
        "owner": row_owner,
        "owner_superuser": bool(row.get("owner_superuser")),
        "owner_bypassrls": bool(row.get("owner_bypassrls")),
        "security_definer": bool(row.get("security_definer")),
        "language": row.get("language"),
        "config": tuple(
            _normalize_controlled(item, schema) for item in (row.get("proconfig") or ())
        ),
        "public_execute_acl": bool(row.get("public_execute_acl")),
        "app_execute": bool(row.get("app_execute")),
        "app_execute_acl": bool(row.get("app_execute_acl")),
        "owner_execute_acl": bool(row.get("owner_execute_acl")),
        "definition_sha256": _safe_hash(definition, schema),
        "source": f"apps/api/alembic/versions/{spec.source_file}",
    }


async def inspect_function_acl(
    db: Any, schema: str, *, owner: str | None = None
) -> dict[str, Any]:
    """Read and validate the exact 11-function ACL set in one namespace."""
    schema = validate_schema(schema)
    for spec in EXPECTED_FUNCTIONS:
        _source_acl(spec)
    result = await db.execute(
        text(FUNCTION_ACL_QUERY),
        {
            "schema": schema,
            "function_names": [spec.name for spec in EXPECTED_FUNCTIONS],
            "identity_arguments": [
                spec.identity_arguments for spec in EXPECTED_FUNCTIONS
            ],
        },
    )
    rows = [dict(row) for row in result.mappings()]
    by_name = {
        (row.get("function_name"), row.get("identity_arguments")): row for row in rows
    }
    if len(rows) != len(EXPECTED_FUNCTIONS) or len(by_name) != len(EXPECTED_FUNCTIONS):
        raise GateBlocked("neighbor_function_acl_set_drift")
    metadata = [
        _row_metadata(
            by_name[(spec.name, spec.identity_arguments)], schema, spec, owner
        )
        for spec in EXPECTED_FUNCTIONS
    ]
    return {
        "status": "PASS",
        "scope": "owned" if schema != "public" else "public_baseline",
        "function_count": len(metadata),
        "functions": metadata,
    }


# Proposed root integration signature: await inspect_function_acl(connection, schema)
