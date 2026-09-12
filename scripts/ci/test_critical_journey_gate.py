import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.critical_journey_gate import (  # noqa: E402
    ContractError,
    impacted_journeys,
    load_contract,
    pytest_selectors,
    run,
)


def test_ai_paths_resolve_the_complete_critical_journey() -> None:
    journeys = load_contract()
    impacted = impacted_journeys(
        journeys,
        [
            "apps/api/app/modules/documents/operations.py",
            "apps/api/app/modules/ai/context_expansion.py",
            "apps/api/app/modules/quizzes/service.py",
            "apps/api/alembic/versions/0133_grant_embedding_lifecycle_runtime.py",
        ],
    )
    assert [journey.journey_id for journey in impacted] == ["AI-COURSE-01"]
    assert len(impacted[0].required_tests) == 5
    assert len(impacted[0].database_tests) == 1
    assert "scripts/ci/kb_rag_schema_contract.py" in impacted[0].runtime_gates


def test_unrelated_path_does_not_trigger_ai_journey() -> None:
    assert impacted_journeys(load_contract(), ["apps/web/app/login/page.tsx"]) == ()


def test_pytest_selectors_are_relative_to_backend_working_directory() -> None:
    selectors = pytest_selectors(load_contract(), REPO_ROOT / "apps" / "api", execution_profile="local")
    assert "tests/unit/test_context_expansion.py::test_expansion_deduplicates_overlapping_context_windows" in selectors
    assert "../../scripts/ci/test_kb_rag_schema_contract.py::test_valid_snapshot_returns_sanitized_ci_contract" in selectors


def test_local_mode_emits_database_free_tests_and_defers_database_gate(tmp_path: Path) -> None:
    output = tmp_path / "tests.txt"
    result = run(
        all_journeys=True,
        changed_files=(),
        contract_path=REPO_ROOT / "docs" / "critical-journeys" / "ai-course-generation.json",
        pytest_root=REPO_ROOT / "apps" / "api",
        emit_pytest_args=output,
        execution_profile="local",
    )
    assert result["status"] == "READY"
    assert result["journeys"] == ["AI-COURSE-01"]
    assert result["required_tests"] == 5
    assert result["deferred_database_tests"] == 1
    assert len(output.read_text(encoding="utf-8").splitlines()) == 5
    assert "test_document_reindex_worker_completes_and_is_idempotent" not in output.read_text(encoding="utf-8")


def test_ci_mode_emits_database_tests_for_ephemeral_ci_postgres(tmp_path: Path) -> None:
    output = tmp_path / "tests.txt"
    result = run(
        all_journeys=True,
        changed_files=(),
        contract_path=REPO_ROOT / "docs" / "critical-journeys" / "ai-course-generation.json",
        pytest_root=REPO_ROOT / "apps" / "api",
        emit_pytest_args=output,
        execution_profile="ci",
    )

    assert result["required_tests"] == 6
    assert result["deferred_database_tests"] == 0
    assert "test_document_reindex_worker_completes_and_is_idempotent" in output.read_text(encoding="utf-8")


def test_missing_required_test_fails_closed(tmp_path: Path) -> None:
    contract = json.loads(
        (REPO_ROOT / "docs" / "critical-journeys" / "ai-course-generation.json").read_text(encoding="utf-8")
    )
    contract["journeys"][0]["required_tests"][0] = "apps/api/tests/missing.py::test_missing"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ContractError, match="required_test_selector_missing"):
        load_contract(path)
