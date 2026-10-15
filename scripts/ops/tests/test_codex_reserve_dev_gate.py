from __future__ import annotations
import ast
import importlib.util
import sys
from pathlib import Path
import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
spec = importlib.util.spec_from_file_location("reserve_gate", OPS / "codex_reserve_dev_gate.py")
gate = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(gate)

def test_schema_is_owned_and_lowercase() -> None:
    assert gate.safe_schema_name("reserve_012345abcdef")
    for value in ("public", "reserve_short", "reserve_012345ABCDEf", "tenant_012345abcdef", "reserve_012345abcdef;DROP SCHEMA public"):
        with pytest.raises(gate.GateBlocked, match="unsafe_schema_name"):
            gate.safe_schema_name(value)

def test_contract_constants_and_sources() -> None:
    assert gate.OFF == ["deepseek", "qwen38_flash_next", "glm53_flash"]
    assert gate.RESERVE[-1] == "chatgpt_reserve"
    assert "version_table_schema" in gate.M0156.read_text(encoding="utf-8")
    assert "version_table_schema" in gate.M0180.read_text(encoding="utf-8")
    assert "REFERENCES {schema}.users" in gate.M0156.read_text(encoding="utf-8")

def test_source_parse_and_cleanup_bound() -> None:
    source = (OPS / "codex_reserve_dev_gate.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'DROP SCHEMA IF EXISTS "{schema}" CASCADE' in source
    assert "DROP SCHEMA public" not in source

def test_no_execute_is_inert(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["gate", "--env-file", "never-read.env"])
    assert gate.main() == 2
    assert capsys.readouterr().out == '{"status": "BLOCKED", "error_class": "execute_flag_required"}\n'

def test_execute_rejects_noncanonical_env_path(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["gate", "--env-file", str(tmp_path / "dev.env"), "--execute"])
    assert gate.main() == 2
    assert "noncanonical_env_path" in capsys.readouterr().out

def test_cleanup_failure_is_false_not_exception() -> None:
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("dsn=must-not-escape")
    import asyncio
    assert asyncio.run(gate.cleanup(BrokenEngine(), "reserve_012345abcdef")) is False

def test_provenance_rejects_missing_sha_before_git() -> None:
    with pytest.raises(gate.GateBlocked, match="invalid_expected_release_sha"):
        gate.source_provenance("", "https://synthetic.example")

def test_provenance_requires_exact_committed_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *a, **kw: b"different")
    with pytest.raises(gate.GateBlocked, match="release_source_bytes_mismatch"):
        gate.source_provenance("a" * 40, "https://synthetic.example")
