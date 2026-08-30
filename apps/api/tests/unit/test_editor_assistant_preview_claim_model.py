"""Public contract tests for the durable editor-assistant preview claim."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.modules.editor_assistant.models import AIEditorRequestPreview

API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    API_ROOT
    / "alembic"
    / "versions"
    / "0136_add_editor_assistant_preview_claims.py"
)


def _normalized_sql(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0136", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _captured_sql(module: ModuleType, function_name: str) -> str:
    statements: list[str] = []
    with patch.object(module.op, "execute", side_effect=lambda value: statements.append(str(value))):
        getattr(module, function_name)()
    return _normalized_sql("\n".join(statements))


def test_preview_claim_public_table_contract() -> None:
    table = AIEditorRequestPreview.__table__
    columns = table.c

    assert table.name == "ai_editor_request_previews"
    assert isinstance(columns.id.type, UUID)
    assert columns.id.primary_key
    assert columns.id.default is not None
    assert columns.id.server_default is not None

    expected_columns = {
        "id",
        "tenant_id",
        "request_id",
        "preview_key",
        "payload_fingerprint",
        "state",
        "claim_token_sha256",
        "completed_result_json",
        "failure_code",
        "completed_at",
        "failed_at",
        "created_at",
        "updated_at",
    }
    assert set(columns.keys()) == expected_columns
    assert isinstance(columns.completed_result_json.type, JSONB)
    assert columns.claim_token_sha256.nullable
    assert columns.completed_result_json.nullable
    assert columns.failure_code.nullable

    forbidden_fragments = (
        "prompt",
        "provider_response",
        "instruction",
        "evidence",
        "excerpt",
        "exception",
        "raw_",
    )
    assert not any(
        fragment in column_name
        for column_name in columns.keys()
        for fragment in forbidden_fragments
    )


def test_preview_claim_has_same_tenant_fk_and_unique_preview_key() -> None:
    table = AIEditorRequestPreview.__table__
    foreign_keys = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    same_tenant_fk = next(
        constraint
        for constraint in foreign_keys
        if constraint.name == "fk_ai_editor_previews_same_tenant_request"
    )
    assert [element.parent.name for element in same_tenant_fk.elements] == [
        "tenant_id",
        "request_id",
    ]
    assert [element.target_fullname for element in same_tenant_fk.elements] == [
        "ai_editor_requests.tenant_id",
        "ai_editor_requests.id",
    ]

    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_constraints["uq_ai_editor_preview_tenant_key"] == (
        "tenant_id",
        "preview_key",
    )


def test_preview_claim_checks_and_indexes_are_db_enforced() -> None:
    table = AIEditorRequestPreview.__table__
    checks = {
        constraint.name: _normalized_sql(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "between 1 and 120" in checks["ck_ai_editor_previews_key_length"]
    assert "^[0-9a-f]{64}$" in checks["ck_ai_editor_previews_payload_fingerprint"]
    assert "state in ('pending', 'completed', 'failed')" in checks[
        "ck_ai_editor_previews_state"
    ]
    assert "^[0-9a-f]{64}$" in checks["ck_ai_editor_previews_claim_digest"]
    assert "octet_length(completed_result_json::text) <= 65536" in checks[
        "ck_ai_editor_previews_result_size"
    ]
    assert "jsonb_typeof(completed_result_json) = 'object'" in checks[
        "ck_ai_editor_previews_result_object"
    ]

    failure_check = checks["ck_ai_editor_previews_failure_code"]
    expected_failure_codes = {
        "provider_timeout",
        "provider_unavailable",
        "provider_output_unparseable",
        "contract_violation",
        "validation_blocked",
        "stale_base_version",
        "rejected_out_of_scope",
        "source_evidence_unavailable",
        "requires_new_draft_revision",
        "internal_error",
    }
    assert all(f"'{code}'" in failure_check for code in expected_failure_codes)

    state_shape = checks["ck_ai_editor_previews_state_shape"]
    for required_fragment in (
        "state = 'pending'",
        "claim_token_sha256 is not null",
        "state = 'completed'",
        "completed_result_json is not null",
        "completed_at is not null",
        "state = 'failed'",
        "failure_code is not null",
        "failed_at is not null",
    ):
        assert required_fragment in state_shape

    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    assert indexes["ix_ai_editor_previews_tenant_request"] == (
        "tenant_id",
        "request_id",
    )
    assert indexes["ix_ai_editor_previews_tenant_state_updated"] == (
        "tenant_id",
        "state",
        "updated_at",
    )


def test_migration_contract_has_linear_chain_rls_policies_and_safe_grants() -> None:
    migration = _load_migration()
    assert migration.revision == "0136"
    assert migration.down_revision == "0135"
    assert migration.branch_labels is None
    assert migration.depends_on is None

    upgrade_sql = _captured_sql(migration, "upgrade")
    table_name = "ai_editor_request_previews"
    assert (
        "create unique index if not exists uq_ai_editor_requests_tenant_id "
        "on ai_editor_requests (tenant_id, id)"
    ) in upgrade_sql
    assert f"create table {table_name}" in upgrade_sql
    assert (
        "foreign key (tenant_id, request_id) references "
        "ai_editor_requests (tenant_id, id)"
    ) in upgrade_sql
    assert f"alter table {table_name} enable row level security" in upgrade_sql
    assert f"alter table {table_name} force row level security" in upgrade_sql

    assert (
        f"create policy {table_name}_tenant_select on {table_name} for select"
        in upgrade_sql
    )
    assert (
        f"create policy {table_name}_tenant_insert on {table_name} for insert"
        in upgrade_sql
    )
    assert (
        f"create policy {table_name}_tenant_update on {table_name} for update"
        in upgrade_sql
    )
    assert (
        "using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        in upgrade_sql
    )
    assert (
        "with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        in upgrade_sql
    )
    assert f"grant select on {table_name} to lms_app" in upgrade_sql
    assert (
        "grant insert (tenant_id, request_id, preview_key, payload_fingerprint, "
        f"state, claim_token_sha256) on {table_name} to lms_app"
        in upgrade_sql
    )
    assert f"grant select, insert on {table_name} to lms_app" not in upgrade_sql
    assert f"grant insert on {table_name} to lms_app" not in upgrade_sql
    assert (
        "grant update (state, claim_token_sha256, completed_result_json, "
        "failure_code, completed_at, failed_at, updated_at) "
        f"on {table_name} to lms_app"
        in upgrade_sql
    )
    assert f"grant select, insert, update on {table_name}" not in upgrade_sql
    assert f"grant update on {table_name}" not in upgrade_sql
    assert "jsonb_typeof(completed_result_json) = 'object'" in upgrade_sql
    for immutable_column in (
        "id",
        "tenant_id",
        "request_id",
        "preview_key",
        "payload_fingerprint",
        "created_at",
    ):
        assert not re.search(
            rf"grant update \([^)]*\b{immutable_column}\b[^)]*\)",
            upgrade_sql,
        )
    assert not re.search(r"grant\s+[^;]*\bdelete\b", upgrade_sql)
    assert "for delete" not in upgrade_sql

    downgrade_sql = _captured_sql(migration, "downgrade")
    for operation in ("select", "insert", "update"):
        assert (
            f"drop policy if exists {table_name}_tenant_{operation} on {table_name}"
            in downgrade_sql
        )
    assert f"drop table if exists {table_name}" in downgrade_sql
