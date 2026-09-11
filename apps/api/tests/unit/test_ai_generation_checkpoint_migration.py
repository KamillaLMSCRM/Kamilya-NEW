"""Static contract tests for migration 0158."""

import importlib.util
from pathlib import Path

MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0158_ai_generation_checkpoints.py"


def _source() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("migration_0158", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_advances_from_0157():
    module = _module()
    assert module.revision == "0158"
    assert module.down_revision == "0157"


def test_migration_adds_durable_run_and_lesson_checkpoint_contracts():
    source = _source()
    assert "CREATE TABLE {runs}" in source
    assert "CREATE TABLE {checkpoints}" in source
    for field in ("tenant_id uuid", "generation_key", "plan_revision", "source_job_id", "plan_payload jsonb", "content_payload jsonb", "review_payload jsonb", "assessment_payload jsonb"):
        assert field in source
    assert "UNIQUE (tenant_id, generation_key)" in source
    assert "UNIQUE (tenant_id, id)" in source
    assert "UNIQUE (tenant_id, generation_run_id, module_key, lesson_key)" in source
    assert "FOREIGN KEY (tenant_id, source_job_id)" in source
    assert "REFERENCES {schema}.ai_jobs(tenant_id, id)" in source
    assert "FOREIGN KEY (tenant_id, generation_run_id)" in source
    assert "REFERENCES {runs}(tenant_id, id)" in source
    assert "module_order integer" in source
    assert "lesson_order integer" in source
    assert "lease_duration_seconds" in source
    assert "attempt_count integer NOT NULL DEFAULT 0" in source
    assert "review_status varchar(16) NOT NULL DEFAULT 'pending'" in source


def test_migration_enforces_tenant_isolation_and_immutable_identity():
    source = _source()
    assert source.count("_restrict_table(") == 3
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "prevent_ai_generation_identity_change" in source
    assert "prevent_ai_generation_checkpoint_identity_change" in source
    assert "ai_generation_run_identity_immutable" in source
    assert "ai_generation_checkpoint_identity_immutable" in source
    assert "CREATE POLICY {policy_name} ON {table}" in source
    assert "CREATE POLICY {table}_tenant" not in source
    assert "GRANT SELECT, INSERT, UPDATE ON {table} TO lms_app" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" not in source


def test_migration_has_required_indexes_and_additive_downgrade():
    source = _source()
    assert "ix_ai_generation_runs_tenant_source_job" in source
    assert "ix_ai_generation_runs_lease_expiry" in source
    assert "ix_ai_generation_checkpoint_pending" in source
    assert "DROP TABLE {schema}.ai_generation_lesson_checkpoints" in source
    assert "DROP TABLE {schema}.ai_generation_runs" in source
    assert "ALTER TABLE" not in source[source.index("def downgrade"):]


def test_checkpoint_leases_are_bounded_and_have_a_safe_claim_contract():
    source = _source()
    for constraint in (
        "ck_ai_generation_checkpoint_lease_pair",
        "ck_ai_generation_checkpoint_lease_duration",
        "ck_ai_generation_checkpoint_attempt_count",
    ):
        assert constraint in source
    assert "lease_owner varchar(160)" in source
    assert "lease_expires_at timestamptz" in source
    assert "lease_duration_seconds BETWEEN 1 AND 900" in source
