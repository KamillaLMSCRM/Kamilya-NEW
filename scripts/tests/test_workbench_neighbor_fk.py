"""Database-free contract tests for the source-bound FK builder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
from workbench_neighbor_fk import EXPECTED_FK_SIGNATURES, foreign_key_sql


FIELDS = (
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
)


def fixture_rows() -> list[dict]:
    """Independent 27-row contract fixture; deliberately not implementation-derived."""
    specs = [
        ("content_releases", "content_releases_course_id_fkey", "course_id", "courses", "a", "r"),
        ("content_releases", "content_releases_published_by_fkey", "published_by", "users", "a", "n"),
        ("content_releases", "content_releases_tenant_id_fkey", "tenant_id", "tenants", "a", "c"),
        ("course_assignment_notification_outbox", "course_assignment_notification_outbox_assigned_by_fkey", "assigned_by", "users", "a", "n"),
        ("course_assignment_notification_outbox", "course_assignment_notification_outbox_enrollment_id_fkey", "enrollment_id", "enrollments", "a", "r"),
        ("course_assignment_notification_outbox", "course_assignment_notification_outbox_tenant_id_fkey", "tenant_id", "tenants", "a", "c"),
        ("courses", "courses_reviewed_by_fkey", "reviewed_by", "users", "a", "n"),
        ("courses", "fk_courses_current_release_id", "current_release_id", "content_releases", "a", "r"),
        ("courses", "fk_courses_source_instruction", "source_instruction_id", "documents", "a", "n"),
        ("departments", "departments_head_user_id_fkey", "head_user_id", "users", "a", "n"),
        ("departments", "departments_parent_id_fkey", "parent_id", "departments", "a", "n"),
        ("departments", "departments_tenant_id_fkey", "tenant_id", "tenants", "a", "c"),
        ("enrollment_access_policies", "enrollment_access_policies_enrollment_id_fkey", "enrollment_id", "enrollments", "a", "r"),
        ("enrollments", "enrollments_course_id_fkey", "course_id", "courses", "a", "c"),
        ("enrollments", "enrollments_recurring_assignment_id_fkey", "recurring_assignment_id", "recurring_learning_assignments", "a", "r"),
        ("enrollments", "fk_enrollments_content_release_id", "content_release_id", "content_releases", "a", "r"),
        ("enrollments", "fk_enrollments_learning_path_assignment", "learning_path_assignment_id", "learning_path_assignments", "a", "r"),
        ("enrollments", "fk_enrollments_previous_enrollment", "previous_enrollment_id", "enrollments", "a", "r"),
        ("enrollments", "fk_enrollments_reassigned_by", "reassigned_by", "users", "a", "r"),
        ("positions", "fk_positions_instruction_document", "instruction_document_id", "documents", "a", "n"),
        ("positions", "positions_department_id_fkey", "department_id", "departments", "a", "n"),
        ("tenant_settings", "tenant_settings_tenant_id_fkey", "tenant_id", "tenants", "a", "c"),
        ("user_roles", "user_roles_tenant_id_fkey", "tenant_id", "tenants", "a", "c"),
        ("user_roles", "user_roles_user_id_fkey", "user_id", "users", "a", "c"),
        ("users", "fk_users_organization_unit_id", "organization_unit_id", "departments", "a", "n"),
        ("users", "fk_users_tenant", "tenant_id", "tenants", "a", "c"),
        ("users", "users_position_id_fkey", "position_id", "positions", "a", "a"),
    ]
    return [
        {
            "table": table,
            "name": name,
            "columns": [column],
            "target_schema": "public",
            "target_table": target,
            "target_columns": ["id"],
            "on_update": on_update,
            "on_delete": on_delete,
            "deferrable": False,
            "initially_deferred": False,
            "validated": True,
        }
        for table, name, column, target, on_update, on_delete in specs
    ]


def test_catalog27_success_is_owned_and_quoted() -> None:
    rows = fixture_rows()
    statements = foreign_key_sql("workbench_0123456789ab", rows)

    assert len(rows) == 27 == len(EXPECTED_FK_SIGNATURES)
    assert len(statements) == 27
    assert all(statement.startswith('ALTER TABLE "workbench_0123456789ab".') for statement in statements)
    assert all('REFERENCES "workbench_0123456789ab".' in statement for statement in statements)
    assert all('REFERENCES "public".' not in statement for statement in statements)


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda rows: rows.pop(), "complete_set"),
        (lambda rows: rows[1].update(name=rows[0]["name"]), "duplicate"),
        (lambda rows: rows[0].update(target_table="users"), "signature"),
        (lambda rows: rows[0].update(on_delete="c"), "signature"),
        (lambda rows: rows[0].update(columns=["name"]), "signature"),
        (lambda rows: rows[0].update(deferrable=True), "signature"),
        (lambda rows: rows[0].update(target_schema="public;DROP TABLE x"), "invalid"),
        (lambda rows: rows[0].update(name='x"; DROP TABLE y; --'), "invalid"),
    ],
)
def test_catalog_drift_is_rejected(mutator, error: str) -> None:
    rows = fixture_rows()
    mutator(rows)
    with pytest.raises(ValueError, match=error):
        foreign_key_sql("workbench_0123456789ab", rows)


def test_schema_and_row_shape_are_strict() -> None:
    with pytest.raises(ValueError, match="owned_schema"):
        foreign_key_sql("workbench_0123456789abc", fixture_rows())
    rows = fixture_rows()
    rows[0]["unexpected"] = True
    with pytest.raises(ValueError, match="row_keys"):
        foreign_key_sql("workbench_0123456789ab", rows)
