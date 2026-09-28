from __future__ import annotations

import ast
import asyncio
import importlib
import sys
import re
import types
from pathlib import Path

import pytest

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

# These safety-contract tests deliberately need no database or project
# dependency installation. Import stubs keep collection offline and inert.
dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.dotenv_values = lambda *_args, **_kwargs: {}
dotenv_stub.load_dotenv = lambda *_args, **_kwargs: False
sys.modules.setdefault("dotenv", dotenv_stub)

helper_stub = types.ModuleType("kb_rag_isolated_dev_gate")
helper_stub.API_ROOT = OPS_DIR.parents[1] / "apps" / "api"


class _GateBlocked(RuntimeError):
    pass


helper_stub.GateBlocked = _GateBlocked
helper_stub.assert_sanitized_evidence = lambda _value: None
helper_stub.file_sha256 = lambda _path: "0" * 64
helper_stub.normalize_database_url = lambda value: value
helper_stub.public_revision = lambda _connection: "0164"
helper_stub.same_supabase_project = lambda *_args: True
helper_stub.scalar = lambda *_args, **_kwargs: None
helper_stub.supabase_project_ref = lambda _value: "synthetic-project"
sys.modules.setdefault("kb_rag_isolated_dev_gate", helper_stub)

sqlalchemy_stub = types.ModuleType("sqlalchemy")
sqlalchemy_stub.text = lambda value: value
engine_stub = types.ModuleType("sqlalchemy.engine")
engine_stub.make_url = lambda value: types.SimpleNamespace(username="lms_app", database="postgres")
asyncio_stub = types.ModuleType("sqlalchemy.ext.asyncio")
asyncio_stub.AsyncConnection = object
asyncio_stub.create_async_engine = lambda *_args, **_kwargs: None
pool_stub = types.ModuleType("sqlalchemy.pool")
pool_stub.NullPool = object
ext_stub = types.ModuleType("sqlalchemy.ext")
sys.modules.setdefault("sqlalchemy", sqlalchemy_stub)
sys.modules.setdefault("sqlalchemy.engine", engine_stub)
sys.modules.setdefault("sqlalchemy.ext", ext_stub)
sys.modules.setdefault("sqlalchemy.ext.asyncio", asyncio_stub)
sys.modules.setdefault("sqlalchemy.pool", pool_stub)

gate = importlib.import_module("source_actuality_dev_gate")

for _module_name, _stub in (
    ("dotenv", dotenv_stub),
    ("kb_rag_isolated_dev_gate", helper_stub),
    ("sqlalchemy", sqlalchemy_stub),
    ("sqlalchemy.engine", engine_stub),
    ("sqlalchemy.ext", ext_stub),
    ("sqlalchemy.ext.asyncio", asyncio_stub),
    ("sqlalchemy.pool", pool_stub),
):
    if sys.modules.get(_module_name) is _stub:
        del sys.modules[_module_name]


def test_schema_name_is_random_scope_only() -> None:
    assert gate.safe_schema_name("source_actuality_012345abcdef")
    for unsafe in (
        "public",
        "source_actuality_0123456789ab;DROP SCHEMA public",
        "source_actuality_0123456789AB",
        "source_actuality_short",
        "other_012345abcdef",
    ):
        with pytest.raises(gate.GateBlocked, match="unsafe_schema_name"):
            gate.safe_schema_name(unsafe)


def test_exact_migration_contract_and_no_public_ddl() -> None:
    gate.assert_migration_contract()
    migration = gate.MIGRATION_0165_PATH.read_text(encoding="utf-8")
    assert 'revision = "0165"' in migration
    assert 'down_revision = "0164"' in migration
    assert 'version_table_schema' in migration
    assert "DROP TABLE" in migration
    assert not re.search(r"(?:CREATE|ALTER|DROP|GRANT|REVOKE)\s+[^\n;]*\bpublic\.", migration, re.I)
    purge_migration = gate.MIGRATION_0166_PATH.read_text(encoding="utf-8")
    assert 'revision = "0166"' in purge_migration
    assert 'down_revision = "0165"' in purge_migration
    assert "version_table_schema" in purge_migration
    assert "FOR DELETE TO lms_app" in purge_migration
    assert not re.search(
        r"(?:CREATE|ALTER|DROP|GRANT|REVOKE)\s+[^\n;]*\bpublic\.",
        purge_migration,
        re.I,
    )


def test_cleanup_is_in_finally_and_reads_schema_existence() -> None:
    tree = ast.parse(gate.__file__ and Path(gate.__file__).read_text(encoding="utf-8"))
    run_gate = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_gate")
    final_nodes = [node for node in run_gate.body if isinstance(node, ast.Try)]
    assert len(final_nodes) == 1
    final = final_nodes[0].finalbody
    assert any(
        isinstance(node, ast.If)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "cleanup_isolated_schema"
            for call in ast.walk(node)
        )
        for node in final
    )
    cleanup_source = ast.get_source_segment(Path(gate.__file__).read_text(encoding="utf-8"),
        next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "cleanup_isolated_schema"))
    assert "DROP SCHEMA IF EXISTS" in cleanup_source
    assert "SELECT EXISTS" in cleanup_source


def test_cleanup_reads_back_schema_even_when_drop_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"readback": False, "rollback": False}

    class Connection:
        async def __aenter__(self) -> "Connection":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def execute(self, statement: str) -> None:
            assert statement.startswith("DROP SCHEMA IF EXISTS")
            raise RuntimeError("synthetic_drop_failure")

        async def rollback(self) -> None:
            state["rollback"] = True

    class Engine:
        def connect(self) -> Connection:
            return Connection()

    async def readback(_connection: object, _statement: str, **_params: object) -> bool:
        state["readback"] = True
        return False

    monkeypatch.setattr(gate, "scalar", readback)
    result = asyncio.run(gate.cleanup_isolated_schema(Engine(), "source_actuality_012345abcdef"))
    assert result is False
    assert state == {"readback": True, "rollback": True}


def test_no_database_mutation_without_execute_flag(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["source_actuality_dev_gate.py", "--env-file", "must-not-be-read.env"])

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("preflight or mutation ran without --execute")

    monkeypatch.setattr(gate, "load_dotenv", forbidden)
    monkeypatch.setattr(gate, "dotenv_values", forbidden)
    monkeypatch.setattr(gate, "run_gate", forbidden)
    assert gate.main() == 2
    assert capsys.readouterr().out == '{"error_class": "execute_flag_required", "status": "BLOCKED"}\n'


def test_baseline_and_gate_never_issue_public_ddl() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "CREATE SCHEMA \"{schema}\"" in source
    assert "create schema public" not in source.lower()
    assert "drop schema public" not in source.lower()
    assert "version_table_schema" in source


def test_expected_migration_tables_are_exact() -> None:
    assert gate.EXPECTED_TABLES == {"document_source_policies", "document_change_reviews"}


def test_gate_and_test_sources_parse() -> None:
    ast.parse(Path(gate.__file__).read_text(encoding="utf-8"))
    ast.parse(Path(__file__).read_text(encoding="utf-8"))
