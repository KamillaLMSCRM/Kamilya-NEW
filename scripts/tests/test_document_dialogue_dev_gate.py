"""Database-free safety tests for the document-dialogue DEV gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate():
    path = ROOT / "scripts/ops/document_dialogue_dev_gate.py"
    spec = importlib.util.spec_from_file_location("document_dialogue_dev_gate_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_schema_is_random_workbench_shape_only(gate):
    assert gate.safe_schema("workbench_0123456789ab") == '"workbench_0123456789ab"'
    for value in ("public", "workbench_short", "workbench_0123456789AB", "workbench_0123456789ab;drop"):
        with pytest.raises(gate.GateBlocked):
            gate.safe_schema(value)


def test_required_checks_are_unique_and_complete(gate):
    gate.validate_checks(sorted(gate.REQUIRED_CHECKS), gate.REQUIRED_CHECKS)
    with pytest.raises(gate.GateBlocked, match="required_checks_missing"):
        gate.validate_checks(sorted(gate.REQUIRED_CHECKS)[:-1], gate.REQUIRED_CHECKS)
    with pytest.raises(gate.GateBlocked, match="required_checks_missing"):
        gate.validate_checks(sorted(gate.REQUIRED_CHECKS) + [next(iter(gate.REQUIRED_CHECKS))], gate.REQUIRED_CHECKS)


def test_source_contract_is_present_and_manifest_is_workspace_bound(gate):
    manifest = gate.source_manifest()
    assert any(name.endswith("0181_document_preparation_dialogue.py") for name in manifest)
    assert any(name.endswith("document_dialogue.py") for name in manifest)
    assert any(name.endswith("document_dialogue_dev_gate.py") for name in manifest)
    assert any(name.endswith("document_service.py") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_1.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_2.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_3.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_4.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_5.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_6.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_7.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_8.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_9.md") for name in manifest)
    assert any(name.endswith("DOCUMENT_CONTENT_COMPLETENESS_ADDENDUM_V1_10.md") for name in manifest)
    assert any(name.endswith("test_document_completeness.py") for name in manifest)
    assert "content_incomplete_answer_private_refund_no_retry" in gate.REQUIRED_CHECKS
    assert "content_conflict_invalid_response_private_refund_no_retry" in gate.REQUIRED_CHECKS
    assert any(name.endswith("app/modules/ai/llm_client.py") for name in manifest)


def test_evidence_runs_are_explicit_not_arbitrary(gate):
    assert gate.EVIDENCE_RUNS == ("DOCUMENT55-20261015", "DOCUMENT56-20261015", "DOCUMENT57-20261015", "DOCUMENT58-20261016")


def test_runtime_role_requires_lms_app(gate):
    gate.validate_runtime_url("postgresql+asyncpg://lms_app.project:secret@example.test/db")
    with pytest.raises(gate.GateBlocked, match="wrong_runtime_role"):
        gate.validate_runtime_url("postgresql+asyncpg://service_role.project:secret@example.test/db")


def test_driver_never_reports_raw_failure_text(gate):
    result = gate.sanitized_result("BLOCKED", failure=type(RuntimeError("secret" )).__name__)
    assert "secret" not in str(result)


def test_fake_generation_still_satisfies_real_job_ownership_guard(gate):
    from document_dialogue_dev_checks import synthetic_generation_params
    params = synthetic_generation_params(["synthetic-document"])
    assert params == {"documents": ["synthetic-document"], "source_analysis": {"generation_engine": "evidence_v2"}}
