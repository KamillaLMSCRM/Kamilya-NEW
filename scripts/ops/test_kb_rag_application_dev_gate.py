import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ops import kb_rag_application_dev_gate as gate


def test_application_schema_name_is_strictly_bounded() -> None:
    valid = "hbr_kb_app_0123456789ab"
    assert gate.safe_schema_name(valid) == valid
    for invalid in (
        "public",
        "hbr_kb_0123456789ab",
        "hbr_kb_app_short",
        "hbr_kb_app_0123456789AB",
        "hbr_kb_app_0123456789ab;drop",
    ):
        with pytest.raises(gate.GateBlocked, match="unsafe_application_schema_name"):
            gate.safe_schema_name(invalid)


def test_expected_public_revision_is_required_and_strictly_formatted() -> None:
    assert gate.validate_expected_public_revision("0156") == "0156"
    for invalid in ("", "156", "015", "01567", "01a6", " 0156", "0156 "):
        with pytest.raises(gate.GateBlocked, match="expected_public_revision_invalid"):
            gate.validate_expected_public_revision(invalid)


def test_public_revision_guards_compare_expected_revision_at_each_phase() -> None:
    for phase in ("preflight", "postflight", "cleanup"):
        gate.assert_expected_public_revision("0156", "0156", phase)
        with pytest.raises(gate.GateBlocked, match=f"public_revision_mismatch:{phase}"):
            gate.assert_expected_public_revision("0127", "0156", phase)


def test_success_path_fails_closed_when_public_cleanup_readback_is_not_unchanged() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "assert_cleanup_readback_ready(public_cleanup_readback)" in source
    with pytest.raises(gate.GateBlocked, match="cleanup_public_readback_failed"):
        gate.assert_cleanup_readback_ready("changed")
    gate.assert_cleanup_readback_ready("unchanged")


@pytest.mark.asyncio
async def test_seed_binds_text_document_ids_as_strings() -> None:
    document_a, document_b = uuid.uuid4(), uuid.uuid4()
    bound = []

    class Connection:
        async def execute(self, statement, params=None):
            if params and "doc" in params:
                assert isinstance(params["doc"], str)
                bound.append(params["doc"])

        async def commit(self):
            pass

    await gate._seed_synthetic_active(
        Connection(), "hbr_kb_app_0123456789ab", tenant_a=uuid.uuid4(),
        tenant_b=uuid.uuid4(), doc_a=document_a, doc_b=document_b,
    )
    assert bound == [str(document_a), str(document_a), str(document_b)]
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "doc=doc_b," not in source
    assert "doc=str(doc_b)," in source


def test_runner_covers_exact_migration_chain_and_is_schema_neutral() -> None:
    assert [path.name for path in gate.MIGRATIONS] == [
        "0128_add_embedding_provenance.py",
        "0129_add_embedding_chunk_index.py",
        "0130_add_document_embedding_fts.py",
        "0131_add_embedding_reindex_lifecycle.py",
    ]
    gate.assert_migration_sources_are_schema_neutral()


def test_gate_reference_shape_matches_current_writer_projection() -> None:
    from app.modules.ai.writer import RetrievedChunk, _public_source_reference
    chunk = RetrievedChunk(chunk_id="internal", doc_id="owned-doc", tenant_id="tenant",
                           doc_name="synthetic.md", headings=[], text="source",
                           query="q", distance=0.1)
    reference = _public_source_reference(chunk)
    assert set(reference) == {"document", "doc_id", "doc_name", "headings", "context_sections"}
    assert reference["doc_id"] == "owned-doc"
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert 'reference["doc_id"] != document_id' in source
    assert 'reference["doc_name"] != anchor_meta["doc_name"]' in source


def test_candidate_helpers_are_synthetic_and_deterministic() -> None:
    chunks = gate._candidate_chunks(
        "22222222-2222-2222-2222-222222222222",
        "document:" + "a" * 64,
    )
    manifest = gate._manifest(chunks)
    assert len(chunks) == len(manifest) == 3
    assert [item.chunk_index for item in manifest] == [0, 1, 2]
    assert all(len(item.content_sha256) == 64 for item in manifest)
    assert all("synthetic" in chunk["metadata"]["doc_name"] for chunk in chunks)


def test_main_refuses_before_loading_env_without_execute(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["gate", "--env-file", "missing.env", "--approval-id", gate.APPROVAL_ID],
    )
    monkeypatch.setattr(
        gate,
        "load_dotenv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("env must not be read")
        ),
    )
    assert gate.main() == 2
    assert json.loads(capsys.readouterr().out)["error_class"] == "execute_flag_required"


def test_main_refuses_before_loading_env_without_exact_approval(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["gate", "--env-file", "missing.env", "--execute", "--approval-id", "wrong"],
    )
    monkeypatch.setattr(
        gate,
        "load_dotenv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("env must not be read")
        ),
    )
    assert gate.main() == 2
    assert json.loads(capsys.readouterr().out)["error_class"] == "approval_id_required"


def test_main_requires_expected_public_revision_before_loading_env(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["gate", "--env-file", "missing.env", "--execute", "--approval-id", gate.APPROVAL_ID],
    )
    monkeypatch.setattr(
        gate,
        "load_dotenv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("env must not be read")
        ),
    )
    assert gate.main() == 2
    assert json.loads(capsys.readouterr().out)["error_class"] == (
        "expected_public_revision_required"
    )


def test_evidence_path_must_remain_inside_repository() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "REPO_ROOT.resolve() not in output_path.parents" in source
    assert '"disposable_schema_removed"' in source
    assert '"shared_public_revision_and_metadata_unchanged"' in source
    assert '"RUNTIME-DERIVED"' in source


def test_runner_source_contains_required_application_and_cleanup_gates() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    required = (
        "transaction_rollback_injection",
        "duplicate_open_run",
        "partial_candidate_invisible_and_cannot_activate",
        "concurrent_event_generation_cas",
        "atomic_activation_cas",
        "semantic_fts_corpus_context_active_only",
        "writer_context_budget_and_safe_citations",
        "lifecycle_force_rls_read_write_and_no_tenant_negatives",
        "rollback_restored_old_active",
        "exact_nonactive_revision_cleanup",
        "upgrade_downgrade_reupgrade_0127_0131",
        "cleanup_ok = await cleanup(engine, schema)",
    )
    for marker in required:
        assert marker in source


def test_sanitized_evidence_contract_rejects_secret_material() -> None:
    with pytest.raises(gate.GateBlocked, match="evidence_contains_forbidden_material"):
        gate.assert_sanitized_evidence({"status": "READY", "value": "postgresql://hidden"})


def test_target_fingerprint_binds_project_without_exposing_reference() -> None:
    first = gate._target_fingerprint(
        project_ref="abcdefghijklmno",
        database="postgres",
        postgresql_major=17,
        pgvector_version="0.8.0",
    )
    second = gate._target_fingerprint(
        project_ref="differentproject",
        database="postgres",
        postgresql_major=17,
        pgvector_version="0.8.0",
    )
    assert first != second
    assert "abcdefghijklmno" not in first
    assert len(first) == 64


@pytest.mark.asyncio
async def test_cleanup_drops_only_exact_validated_schema(monkeypatch) -> None:
    calls = []

    class Result:
        def scalar_one(self):
            return False

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, statement, params=None):
            calls.append((str(statement), params))
            return Result()

        async def commit(self):
            calls.append(("COMMIT", None))

    class Engine:
        def connect(self):
            return Connection()

    schema = "hbr_kb_app_0123456789ab"
    assert await gate.cleanup(Engine(), schema) is True
    assert calls[0][0] == f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'
    assert not any("public" in sql.lower() for sql, _ in calls)


@pytest.mark.asyncio
async def test_application_session_factory_uses_transaction_local_state(
    monkeypatch,
) -> None:
    calls = []

    class Session:
        def __init__(self):
            self.transaction = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, statement, params=None):
            calls.append(str(statement))

        def in_transaction(self):
            return self.transaction

        async def rollback(self):
            calls.append("ROLLBACK")
            self.transaction = False

        async def commit(self):
            calls.append("COMMIT")

    session = Session()
    monkeypatch.setattr(
        gate,
        "async_sessionmaker",
        lambda *_args, **_kwargs: lambda: session,
    )
    factory = gate._make_application_session_factory(
        object(), "hbr_kb_app_0123456789ab"
    )
    async with factory() as observed:
        assert observed is session

    assert "ROLLBACK" in calls
    assert any(call.startswith("SET LOCAL search_path TO") for call in calls)
    assert "SET LOCAL ROLE authenticated" in calls
    assert not any(call.startswith("RESET") for call in calls)
    assert calls[-1] == "ROLLBACK"


def test_application_overrides_are_restored_exactly() -> None:
    original_factory = object()
    original_settings = object()
    db_module = SimpleNamespace(async_session_factory=object())
    config_module = SimpleNamespace(get_settings=object())

    gate._restore_application_overrides(
        db_module,
        config_module,
        original_factory,
        original_settings,
    )

    assert db_module.async_session_factory is original_factory
    assert config_module.get_settings is original_settings
