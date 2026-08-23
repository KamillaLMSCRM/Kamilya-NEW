from pathlib import Path
import importlib.util

import pytest


SCRIPT = Path(__file__).with_name("kb_rag_isolated_dev_gate.py")
SPEC = importlib.util.spec_from_file_location("kb_rag_isolated_dev_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_schema_guard_accepts_only_generated_prefix() -> None:
    assert MODULE.safe_schema_name("hbr_kb_012345abcdef") == "hbr_kb_012345abcdef"
    for unsafe in ("public", "hbr_kb_bad", "hbr_kb_012345abcdef;drop schema public"):
        with pytest.raises(MODULE.GateBlocked):
            MODULE.safe_schema_name(unsafe)


def test_migration_sources_are_schema_neutral() -> None:
    MODULE.assert_migration_sources_are_schema_neutral()


def test_supabase_project_identity_match_is_fail_closed() -> None:
    assert MODULE.same_supabase_project(
        "postgresql+asyncpg://postgres.abcdefgh:secret@pooler.supabase.com:6543/postgres",
        "https://abcdefgh.supabase.co",
    )
    assert not MODULE.same_supabase_project(
        "postgresql+asyncpg://postgres.otherref:secret@pooler.supabase.com:6543/postgres",
        "https://abcdefgh.supabase.co",
    )
    assert not MODULE.same_supabase_project(
        "postgresql+asyncpg://user:secret@db.example.com:5432/postgres",
        "https://abcdefgh.supabase.co",
    )


def test_database_url_normalization_matches_application_driver() -> None:
    assert MODULE.normalize_database_url("postgres://u:p@h/db").startswith(
        "postgresql+asyncpg://"
    )
    assert MODULE.normalize_database_url("postgresql://u:p@h/db").startswith(
        "postgresql+asyncpg://"
    )
    value = "postgresql+asyncpg://u:p@h/db"
    assert MODULE.normalize_database_url(value) == value


def test_plan_summary_exposes_only_shape_and_index_names() -> None:
    node_types, indexes = MODULE.summarize_plan(
        [{"Plan": {"Node Type": "Bitmap Heap Scan", "Plans": [
            {"Node Type": "Bitmap Index Scan", "Index Name": "safe_idx"}
        ]}}]
    )
    assert node_types == ["Bitmap Heap Scan", "Bitmap Index Scan"]
    assert indexes == ["safe_idx"]


def test_source_and_target_helpers_return_only_sha256_digests() -> None:
    assert MODULE.supabase_project_ref("https://abcdefgh.supabase.co") == "abcdefgh"
    with pytest.raises(MODULE.GateBlocked):
        MODULE.supabase_project_ref("https://example.com")
    digest = MODULE.digest_json({"target": "synthetic", "database": "postgres"})
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_evidence_sanitizer_rejects_credentials_and_contact_material() -> None:
    MODULE.assert_sanitized_evidence({"status": "PASSED", "digest": "a" * 64})
    for unsafe in (
        {"url": "postgresql://user:value@host/db"},
        {"password": "value"},
        {"contact": "person@example.test"},
    ):
        with pytest.raises(MODULE.GateBlocked):
            MODULE.assert_sanitized_evidence(unsafe)
