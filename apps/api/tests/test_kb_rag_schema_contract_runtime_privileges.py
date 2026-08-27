"""Focused runtime-privilege checks for the PostgreSQL 17 KB/RAG gate."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ci"
    / "kb_rag_schema_contract.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("kb_rag_schema_contract", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _valid_privileges() -> tuple[tuple[str, bool, bool, bool, bool], ...]:
    return (
        ("embedding_active_revisions", True, True, True, False),
        ("embedding_reindex_runs", True, True, True, False),
        ("embedding_reindex_events", True, True, True, False),
    )


def test_runtime_privilege_contract_accepts_minimal_required_grants() -> None:
    _module()._require_runtime_privileges(_valid_privileges())


def test_runtime_privilege_contract_rejects_missing_select() -> None:
    module = _module()
    invalid = list(_valid_privileges())
    invalid[0] = ("embedding_active_revisions", False, True, True, False)

    with pytest.raises(module.ContractError, match="lifecycle_runtime_privileges_invalid"):
        module._require_runtime_privileges(tuple(invalid))


def test_runtime_privilege_contract_rejects_delete_capability() -> None:
    module = _module()
    invalid = list(_valid_privileges())
    invalid[1] = ("embedding_reindex_runs", True, True, True, True)

    with pytest.raises(module.ContractError, match="lifecycle_runtime_privileges_invalid"):
        module._require_runtime_privileges(tuple(invalid))
