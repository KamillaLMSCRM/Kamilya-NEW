from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
GATE = (ROOT / "scripts" / "ci" / "run_rls_release_gate.sh").read_text(
    encoding="utf-8"
)
WORKER_TEST = (
    ROOT / "apps" / "api" / "tests" / "integration" / "test_ai_generation_execution_claim.py"
).read_text(encoding="utf-8")


def test_ci_and_local_ephemeral_database_match_production_major() -> None:
    assert "pgvector/pgvector:pg17" in CI
    assert "pgvector/pgvector:pg17" in COMPOSE
    assert "pgvector/pgvector:pg16" not in CI
    assert "pgvector/pgvector:pg16" not in COMPOSE


def test_rls_gate_is_blocking_and_limited_to_confirmed_local_test_database() -> None:
    assert "PostgreSQL 17 + pgvector RLS release gate" in CI
    assert "run_rls_release_gate.sh" in CI
    assert "continue-on-error" not in CI[CI.index("PostgreSQL 17 + pgvector RLS release gate") :]
    assert '[[ "${APP_ENV:-}" == "test" ]]' in GATE
    assert "EPHEMERAL_POSTGRES_ONLY" in GATE
    assert "@localhost:" in GATE
    assert "@127.0.0.1:" in GATE


def test_rls_gate_covers_crud_export_worker_and_environment_contracts() -> None:
    for required_path in (
        "test_rls_release_environment.py",
        "test_tenant_isolation.py",
        "test_adaptive_staff_import_rls.py",
        "test_training_evidence_export_api.py",
        "test_training_evidence_shares.py",
        "test_ai_generation_execution_claim.py",
        "test_superadmin_admin_rls.py",
    ):
        assert required_path in GATE
    assert 'SET LOCAL ROLE lms_app' in WORKER_TEST
