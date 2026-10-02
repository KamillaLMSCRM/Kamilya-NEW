"""Pure, source-bound FK statement builder for the neighbor workbench.

This module deliberately does not import SQLAlchemy, connect to a database, or
execute DDL.  The catalog is evidence captured from the current public schema;
the caller supplies its sanitized rows and this builder emits statements for a
disposable, owned schema only.
"""

from __future__ import annotations

import re


CATALOG_SOURCE = (
    ".release-evidence/WB-NEIGHBOR-CATALOG-20261001/catalog-complete-acl.json"
)
HISTORICAL_DECLARATION_SOURCE = "docs/product/contract-modules/methodologist-workbench/contracts/NEIGHBOR_RECONSTRUCTION_VALIDATION_ADDENDUM_V1.md"
SOURCE_POINTERS = {
    "content_releases": "apps/api/alembic/versions/0081_course_release_and_attempt_evidence.py",
    "course_assignment_notification_outbox": "apps/api/alembic/versions/0097_course_assignment_notification_outbox.py",
    "courses": "apps/api/alembic/versions/0081_course_release_and_attempt_evidence.py",
    "departments": "apps/api/alembic/versions/0161_organization_hierarchy_v2.py",
    "enrollment_access_policies": "apps/api/alembic/versions/0106_enrollment_access_policies.py",
    "enrollments": "apps/api/alembic/versions/0081_course_release_and_attempt_evidence.py",
    "positions": "apps/api/alembic/versions/0011_bootstrap_positions_and_documents.py",
    "tenant_settings": "apps/api/app/models/tenant_settings.py",
    "tenants": "apps/api/alembic/versions/0001_initial.py",
    "user_invitations": "apps/api/alembic/versions/0024_add_user_invitations.py",
    "user_roles": "apps/api/alembic/versions/0001_initial.py",
    "users": "apps/api/alembic/versions/0001_initial.py",
}
# Every expected constraint is bound to a concrete declaration, not merely to
# the existence of a migration file.  Names are catalog names; ``symbol`` is
# the current model attribute or migration declaration that supplies it.
EXPECTED_FK_SOURCE_BINDINGS = {
    "content_releases_course_id_fkey": (
        "apps/api/app/modules/courses/release_models.py",
        "ContentRelease.course_id",
    ),
    "content_releases_published_by_fkey": (
        "apps/api/app/modules/courses/release_models.py",
        "ContentRelease.published_by",
    ),
    "content_releases_tenant_id_fkey": (
        "apps/api/app/modules/courses/release_models.py",
        "ContentRelease.tenant_id",
    ),
    "course_assignment_notification_outbox_assigned_by_fkey": (
        "apps/api/app/models/course_assignment_notification.py",
        "CourseAssignmentNotificationOutbox.assigned_by",
    ),
    "course_assignment_notification_outbox_enrollment_id_fkey": (
        "apps/api/app/models/course_assignment_notification.py",
        "CourseAssignmentNotificationOutbox.enrollment_id",
    ),
    "course_assignment_notification_outbox_tenant_id_fkey": (
        "apps/api/app/models/course_assignment_notification.py",
        "CourseAssignmentNotificationOutbox.tenant_id",
    ),
    "courses_reviewed_by_fkey": (
        "apps/api/app/modules/courses/models.py",
        "Course.reviewed_by",
    ),
    "fk_courses_current_release_id": (
        "apps/api/alembic/versions/0081_course_release_and_attempt_evidence.py",
        "upgrade:fk_courses_current_release_id",
    ),
    "fk_courses_source_instruction": (
        "apps/api/app/modules/courses/models.py",
        "Course.source_instruction_id",
    ),
    "departments_head_user_id_fkey": (
        "apps/api/app/models/department.py",
        "Department.head_user_id",
    ),
    "departments_parent_id_fkey": (
        "apps/api/app/models/department.py",
        "Department.parent_id",
    ),
    "departments_tenant_id_fkey": (
        HISTORICAL_DECLARATION_SOURCE,
        "root accepted static historical FK declaration; original migration not located",
    ),
    "enrollment_access_policies_enrollment_id_fkey": (
        "apps/api/app/models/enrollment_access_policy.py",
        "EnrollmentAccessPolicy.enrollment_id",
    ),
    "enrollments_course_id_fkey": (
        HISTORICAL_DECLARATION_SOURCE,
        "root accepted static historical FK declaration; original migration not located",
    ),
    "enrollments_recurring_assignment_id_fkey": (
        "apps/api/app/models/enrollment.py",
        "Enrollment.recurring_assignment_id",
    ),
    "fk_enrollments_content_release_id": (
        "apps/api/app/models/enrollment.py",
        "Enrollment.content_release_id",
    ),
    "fk_enrollments_learning_path_assignment": (
        "apps/api/app/models/enrollment.py",
        "Enrollment.learning_path_assignment_id",
    ),
    "fk_enrollments_previous_enrollment": (
        "apps/api/app/models/enrollment.py",
        "Enrollment.previous_enrollment_id",
    ),
    "fk_enrollments_reassigned_by": (
        "apps/api/app/models/enrollment.py",
        "Enrollment.reassigned_by",
    ),
    "fk_positions_instruction_document": (
        "apps/api/app/modules/positions/models.py",
        "Position.instruction_document_id",
    ),
    "positions_department_id_fkey": (
        "apps/api/app/modules/positions/models.py",
        "Position.department_id",
    ),
    "tenant_settings_tenant_id_fkey": (
        "apps/api/app/models/tenant_settings.py",
        "TenantSettings.tenant_id",
    ),
    "user_roles_tenant_id_fkey": (
        "apps/api/app/models/user_roles.py",
        "UserRole.tenant_id",
    ),
    "user_roles_user_id_fkey": (
        "apps/api/app/models/user_roles.py",
        "UserRole.user_id",
    ),
    "fk_users_organization_unit_id": (
        "apps/api/app/models/users.py",
        "User.organization_unit_id",
    ),
    "fk_users_tenant": ("apps/api/app/models/users.py", "User.tenant_id"),
    "users_position_id_fkey": ("apps/api/app/models/users.py", "User.position_id"),
}
# Keep historical provenance explicit; static declarations are accepted in the
# contract, not claimed to originate from a located migration or copied live DDL.
HISTORICAL_CATALOG_ONLY_CONSTRAINTS = frozenset(
    {"departments_tenant_id_fkey", "enrollments_course_id_fkey"}
)

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
_SCHEMA = re.compile(r"workbench_[0-9a-f]{12}\Z")
_ROW_KEYS = frozenset(
    {
        "table",
        "name",
        "columns",
        "target_schema",
        "target_table",
        "target_columns",
        "on_update",
        "on_delete",
        "deferrable",
        "initially_deferred",
        "validated",
    }
)
_CONTROL_TABLES = frozenset(SOURCE_POINTERS)
_TARGET_TABLES = _CONTROL_TABLES | {
    "documents",
    "learning_path_assignments",
    "recurring_learning_assignments",
    "learning_path_courses",
}
_ACTION = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}

# (table, constraint, local columns, baseline namespace, target, target columns,
# update action, delete action, deferrable, initially deferred, validated).
EXPECTED_FK_SIGNATURES = (
    (
        "content_releases",
        "content_releases_course_id_fkey",
        ("course_id",),
        "public",
        "courses",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "content_releases",
        "content_releases_published_by_fkey",
        ("published_by",),
        "public",
        "users",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "content_releases",
        "content_releases_tenant_id_fkey",
        ("tenant_id",),
        "public",
        "tenants",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "course_assignment_notification_outbox",
        "course_assignment_notification_outbox_assigned_by_fkey",
        ("assigned_by",),
        "public",
        "users",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "course_assignment_notification_outbox",
        "course_assignment_notification_outbox_enrollment_id_fkey",
        ("enrollment_id",),
        "public",
        "enrollments",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "course_assignment_notification_outbox",
        "course_assignment_notification_outbox_tenant_id_fkey",
        ("tenant_id",),
        "public",
        "tenants",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "courses",
        "courses_reviewed_by_fkey",
        ("reviewed_by",),
        "public",
        "users",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "courses",
        "fk_courses_current_release_id",
        ("current_release_id",),
        "public",
        "content_releases",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "courses",
        "fk_courses_source_instruction",
        ("source_instruction_id",),
        "public",
        "documents",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "departments",
        "departments_head_user_id_fkey",
        ("head_user_id",),
        "public",
        "users",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "departments",
        "departments_parent_id_fkey",
        ("parent_id",),
        "public",
        "departments",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "departments",
        "departments_tenant_id_fkey",
        ("tenant_id",),
        "public",
        "tenants",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "enrollment_access_policies",
        "enrollment_access_policies_enrollment_id_fkey",
        ("enrollment_id",),
        "public",
        "enrollments",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "enrollments",
        "enrollments_course_id_fkey",
        ("course_id",),
        "public",
        "courses",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "enrollments",
        "enrollments_recurring_assignment_id_fkey",
        ("recurring_assignment_id",),
        "public",
        "recurring_learning_assignments",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "enrollments",
        "fk_enrollments_content_release_id",
        ("content_release_id",),
        "public",
        "content_releases",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "enrollments",
        "fk_enrollments_learning_path_assignment",
        ("learning_path_assignment_id",),
        "public",
        "learning_path_assignments",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "enrollments",
        "fk_enrollments_previous_enrollment",
        ("previous_enrollment_id",),
        "public",
        "enrollments",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "enrollments",
        "fk_enrollments_reassigned_by",
        ("reassigned_by",),
        "public",
        "users",
        ("id",),
        "a",
        "r",
        False,
        False,
        True,
    ),
    (
        "positions",
        "fk_positions_instruction_document",
        ("instruction_document_id",),
        "public",
        "documents",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "positions",
        "positions_department_id_fkey",
        ("department_id",),
        "public",
        "departments",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "tenant_settings",
        "tenant_settings_tenant_id_fkey",
        ("tenant_id",),
        "public",
        "tenants",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "user_roles",
        "user_roles_tenant_id_fkey",
        ("tenant_id",),
        "public",
        "tenants",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "user_roles",
        "user_roles_user_id_fkey",
        ("user_id",),
        "public",
        "users",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "users",
        "fk_users_organization_unit_id",
        ("organization_unit_id",),
        "public",
        "departments",
        ("id",),
        "a",
        "n",
        False,
        False,
        True,
    ),
    (
        "users",
        "fk_users_tenant",
        ("tenant_id",),
        "public",
        "tenants",
        ("id",),
        "a",
        "c",
        False,
        False,
        True,
    ),
    (
        "users",
        "users_position_id_fkey",
        ("position_id",),
        "public",
        "positions",
        ("id",),
        "a",
        "a",
        False,
        False,
        True,
    ),
)

if {signature[1] for signature in EXPECTED_FK_SIGNATURES} != set(
    EXPECTED_FK_SOURCE_BINDINGS
):
    raise RuntimeError("neighbor_fk_source_binding_incomplete")
if not HISTORICAL_CATALOG_ONLY_CONSTRAINTS <= set(EXPECTED_FK_SOURCE_BINDINGS):
    raise RuntimeError("neighbor_fk_catalog_only_classification_incomplete")


def _quote(identifier: str) -> str:
    return f'"{identifier}"'


def _check_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"neighbor_fk_{label}_invalid")
    return value


def _row_signature(row: dict[str, object]) -> tuple[object, ...]:
    return (
        row["table"],
        row["name"],
        tuple(row["columns"]),
        row["target_schema"],
        row["target_table"],
        tuple(row["target_columns"]),
        row["on_update"],
        row["on_delete"],
        row["deferrable"],
        row["initially_deferred"],
        row["validated"],
    )


def foreign_key_sql(schema: str, rows: list[dict]) -> list[str]:
    """Validate the complete catalog and return owned-schema FK ALTER statements."""
    if not isinstance(schema, str) or not _SCHEMA.fullmatch(schema):
        raise ValueError("neighbor_fk_owned_schema_invalid")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_FK_SIGNATURES):
        raise ValueError("neighbor_fk_complete_set_required")

    seen: set[str] = set()
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise ValueError("neighbor_fk_row_keys_invalid")
        for key in ("table", "name", "target_schema", "target_table"):
            _check_identifier(row[key], key)
        for key in ("columns", "target_columns"):
            value = row[key]
            if (
                not isinstance(value, (list, tuple))
                or not value
                or not all(
                    isinstance(item, str) and _IDENTIFIER.fullmatch(item)
                    for item in value
                )
            ):
                raise ValueError(f"neighbor_fk_{key}_invalid")
        for key in ("deferrable", "initially_deferred", "validated"):
            if type(row[key]) is not bool:
                raise ValueError(f"neighbor_fk_{key}_invalid")
        for key in ("on_update", "on_delete"):
            if row[key] not in _ACTION:
                raise ValueError(f"neighbor_fk_{key}_invalid")
        name = row["name"]
        if name in seen:
            raise ValueError("neighbor_fk_duplicate")
        seen.add(name)
        if (
            row["target_schema"] != "public"
            or row["target_table"] not in _TARGET_TABLES
        ):
            raise ValueError("neighbor_fk_target_invalid")
        normalized.append(row)

    by_name = {_row_signature(row): row for row in normalized}
    if len(by_name) != len(normalized) or set(by_name) != set(EXPECTED_FK_SIGNATURES):
        raise ValueError("neighbor_fk_signature_drift")

    statements = []
    for (
        table,
        name,
        columns,
        _baseline_schema,
        target,
        target_columns,
        update,
        delete,
        *_,
    ) in EXPECTED_FK_SIGNATURES:
        statements.append(
            f"ALTER TABLE {_quote(schema)}.{_quote(table)} ADD CONSTRAINT {_quote(name)} "
            f"FOREIGN KEY ({', '.join(_quote(column) for column in columns)}) "
            f"REFERENCES {_quote(schema)}.{_quote(target)} ({', '.join(_quote(column) for column in target_columns)}) "
            f"ON UPDATE {_ACTION[update]} ON DELETE {_ACTION[delete]} NOT DEFERRABLE INITIALLY IMMEDIATE;"
        )
    return statements
