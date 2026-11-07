"""Offline checks for the isolated preparation gate; never opens a database."""

import sys
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

import source_preparation_review_dev_gate as gate


def test_schema_guard_refuses_non_owned_targets():
    assert gate.safe_schema("preparation_review_dev_0123456789ab") == '"preparation_review_dev_0123456789ab"'
    for value in ("public", "preparation_review_dev_123", "preparation_review_dev_0123456789ab;DROP SCHEMA public"):
        with pytest.raises(ValueError, match="invalid_owned_schema"):
            gate.safe_schema(value)


def test_synthetic_manifest_selection_and_scoped_asset_identity():
    tenant, doc = uuid4(), uuid4()
    package = gate.synthetic_manifest(tenant, doc)
    text, selected, blocks = package.selected([package.parts[0].id])
    assert selected == [package.parts[0].id] and len(blocks) == 1
    assert "Learning:" in text and "Administrative:" not in text
    assert package.parts[1].role == "administrative"
    assert package.assets[0].storage_key.startswith(f"source-assets/{tenant}/{doc}/")
    assert package.assets[0].id in blocks[0].asset_ids


def test_documents_have_distinct_stable_source_identities_and_valid_bindings():
    tenant = uuid4()
    ids = [uuid4() for _ in range(4)]
    packages = [gate.synthetic_manifest(tenant, doc) for doc in ids]
    assert len({package.original_blob_sha256 for package in packages}) == len(ids)
    assert gate.synthetic_manifest(tenant, ids[0]).original_blob_sha256 == packages[0].original_blob_sha256
    for package in packages:
        binding = package.binding([package.parts[0].id])
        assert gate.selected_binding_text(binding, package.original_blob_sha256) == package.blocks[0].text
        with pytest.raises(ValueError):
            gate.selected_binding_text(binding, packages[(packages.index(package) + 1) % len(packages)].original_blob_sha256)


def test_db_diagnostic_discloses_only_reviewed_fixed_identifiers():
    class Original(Exception):
        sqlstate = "23505"
        constraint_name = "uq_documents_active_tenant_content_sha256"

    known = DBAPIError(None, None, Original("sensitive payload"))
    assert gate.safe_db_diagnostic(known) == {"sqlstate": "23505", "constraint": "uq_documents_active_tenant_content_sha256"}
    known.orig.constraint_name = "sensitive constraint value"
    known.orig.sqlstate = "sensitive sql value"
    assert gate.safe_db_diagnostic(known) == {"sqlstate": None, "constraint": None}


def test_entrypoint_is_blocked_without_explicit_execute(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["source_preparation_review_dev_gate.py"])
    monkeypatch.setattr(gate, "run", lambda: pytest.fail("gate attempted execution"))
    assert gate.main() == 2
    assert '"reason": "execute_required"' in capsys.readouterr().out


def test_recovery_coverage_requires_each_locked_transaction_check():
    checks = sorted(gate.RECOVERY_CHECKS)
    assert gate.recovery_coverage(checks)
    for check in checks:
        assert not gate.recovery_coverage([item for item in checks if item != check])
