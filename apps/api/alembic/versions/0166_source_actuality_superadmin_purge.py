"""Allow exact-tenant superadmin purge of source-actuality records.

Revision ID: 0166
Revises: 0165
Create Date: 2026-09-28
"""

import re

from alembic import op

revision = "0166"
down_revision = "0165"
branch_labels = None
depends_on = None

TENANT_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
)


def _schema() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe source-actuality purge schema")
    return f'"{schema}"'


def _policy_ownership(schema: str) -> str:
    return f"""EXISTS (SELECT 1 FROM {schema}.documents d
            WHERE d.tenant_id=document_source_policies.tenant_id
              AND d.source_family_id=document_source_policies.source_family_id)
        AND (document_source_policies.owner_id IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_source_policies.owner_id
              AND u.tenant_id=document_source_policies.tenant_id
              AND u.role='methodologist' AND u.is_active IS TRUE AND u.status='active'))
        AND (document_source_policies.created_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_source_policies.created_by
              AND u.tenant_id=document_source_policies.tenant_id))
        AND (document_source_policies.updated_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_source_policies.updated_by
              AND u.tenant_id=document_source_policies.tenant_id))"""


def _review_ownership(schema: str) -> str:
    return f"""EXISTS (SELECT 1 FROM {schema}.documents old_d
            WHERE old_d.id=document_change_reviews.previous_document_id
              AND old_d.tenant_id=document_change_reviews.tenant_id
              AND old_d.source_family_id=document_change_reviews.source_family_id)
        AND EXISTS (SELECT 1 FROM {schema}.documents new_d
            WHERE new_d.id=document_change_reviews.new_document_id
              AND new_d.tenant_id=document_change_reviews.tenant_id
              AND new_d.source_family_id=document_change_reviews.source_family_id)
        AND (document_change_reviews.decided_by IS NULL OR EXISTS (
            SELECT 1 FROM {schema}.users u WHERE u.id=document_change_reviews.decided_by
              AND u.tenant_id=document_change_reviews.tenant_id
              AND u.role='methodologist' AND u.is_active IS TRUE AND u.status='active'))"""


def _table_ownership(schema: str) -> dict[str, str]:
    return {
        "document_change_reviews": _review_ownership(schema),
        "document_source_policies": _policy_ownership(schema),
    }


def _replace_all_policy_with_command_policies(
    schema: str,
    table: str,
    ownership: str,
) -> None:
    qualified = f"{schema}.{table}"
    op.execute(f"DROP POLICY {table}_tenant ON {qualified}")
    op.execute(
        f"CREATE POLICY {table}_tenant_select ON {qualified} "
        f"FOR SELECT TO lms_app USING ({TENANT_PREDICATE})"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_insert ON {qualified} "
        f"FOR INSERT TO lms_app WITH CHECK ({TENANT_PREDICATE} AND {ownership})"
    )
    op.execute(
        f"CREATE POLICY {table}_tenant_update ON {qualified} "
        f"FOR UPDATE TO lms_app USING ({TENANT_PREDICATE}) "
        f"WITH CHECK ({TENANT_PREDICATE} AND {ownership})"
    )


def upgrade() -> None:
    schema = _schema()
    for table, ownership in _table_ownership(schema).items():
        qualified = f"{schema}.{table}"
        _replace_all_policy_with_command_policies(schema, table, ownership)
        op.execute(f"GRANT DELETE ON {qualified} TO lms_app")
        op.execute(
            f"""
            CREATE POLICY {table}_superadmin_delete
            ON {qualified}
            FOR DELETE TO lms_app
            USING (
                {TENANT_PREDICATE}
                AND COALESCE(current_setting('app.is_superadmin', true), '') = 'true'
            )
            """
        )


def downgrade() -> None:
    schema = _schema()
    for table, ownership in reversed(tuple(_table_ownership(schema).items())):
        qualified = f"{schema}.{table}"
        op.execute(f"DROP POLICY IF EXISTS {table}_superadmin_delete ON {qualified}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_update ON {qualified}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_insert ON {qualified}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_select ON {qualified}")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {qualified}")
        op.execute(f"REVOKE DELETE ON {qualified} FROM lms_app")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {qualified} "
            f"USING ({TENANT_PREDICATE}) "
            f"WITH CHECK ({TENANT_PREDICATE} AND {ownership})"
        )
