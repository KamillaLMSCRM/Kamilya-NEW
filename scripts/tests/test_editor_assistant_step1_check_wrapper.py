from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "dev" / "run_editor_assistant_step1_checks.ps1"


def test_wrapper_has_fixed_local_pg18_target_and_disposable_database() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert '"kamilya-postgres18-compat"' in source
    assert "kamilya_step1_$PID" in source
    assert "createdb" in source
    assert "dropdb --if-exists --force" in source
    assert "127.0.0.1" in source


def test_wrapper_does_not_accept_or_print_database_credentials() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "DatabaseUrl" not in source.split("param(", 1)[1].split(")", 1)[0]
    assert "POSTGRES_PASSWORD=" not in source
    assert "Write-Output $DatabaseUrl" not in source
    assert "[REDACTED_DATABASE_URL]" in source
    assert "Remove-Item Env:DATABASE_URL" in source


def test_wrapper_runs_exact_step1_migration_and_test_scope() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert '"downgrade", "0135"' in source
    assert '"upgrade", "0136"' in source
    assert source.count('"upgrade", "head"') >= 2
    assert '"downgrade", "0134"' in source
    assert '"upgrade", "0135"' in source
    assert '"tests/unit/test_editor_assistant_telemetry.py"' in source
    assert '"tests/integration/test_editor_assistant_preview_repository.py"' in source
    assert "EDITOR ASSISTANT STEP 1 CHECKS PASSED" in source


def test_wrapper_asserts_preview_rls_policies_and_exact_runtime_grants() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "Assert-PreviewCatalogContract" in source
    assert "relrowsecurity" in source
    assert "relforcerowsecurity" in source
    assert '"INSERT,SELECT,UPDATE"' in source
    assert '-Expected "SELECT"' in source
    assert (
        '"claim_token_sha256,payload_fingerprint,preview_key,request_id,'
        'state,tenant_id"'
    ) in source
    assert (
        '"claim_token_sha256,completed_at,completed_result_json,failed_at,'
        'failure_code,state,updated_at"'
    ) in source
    assert "has_table_privilege" in source
    assert "'DELETE'" in source
    assert '-Expected "false"' in source
    assert "request_fingerprint_sha256" in source
    assert "ck_ai_editor_requests_fingerprint_sha256" in source
