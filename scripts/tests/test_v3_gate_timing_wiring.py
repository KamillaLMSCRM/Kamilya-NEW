"""Offline gate wiring: no database, provider or model access."""
import json
import sys
from types import SimpleNamespace

import pytest

from scripts.ops import v3_extraction_checkpoint_dev_check as gate


@pytest.mark.parametrize("pooled", [False, True])
def test_engine_instrumentation_preserves_source_and_pool_contract(monkeypatch, tmp_path, capsys, pooled):
    evidence = tmp_path / ".release-evidence"
    evidence.mkdir()
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "POOLED", False)
    monkeypatch.setattr(gate.base, "canonical_env_file", lambda: tmp_path / "unused.env")
    import ai_generation_checkpoint_dev_check as canonical
    calls = []
    def original_factory(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace()
    monkeypatch.setattr(canonical, "create_async_engine", original_factory)
    monkeypatch.setattr(gate, "instrument_engine", lambda engine, timing, event: engine)
    async def fake_execute(**_kwargs):
        canonical.create_async_engine("fake", poolclass="original")
        return {"passed": False, "cleanup": True, "shared_migration_head_unchanged": True,
                "source_unchanged": True, "checks": [], "source_sha256": "source"}
    monkeypatch.setattr(gate.base, "execute", fake_execute)
    arguments = ["gate", "--execute", "--custody", str(evidence / "intent.json")]
    if pooled:
        arguments.append("--pooled")
    monkeypatch.setattr(sys, "argv", arguments)
    assert gate.main() == 1
    assert canonical.create_async_engine is original_factory
    if pooled:
        assert calls == [{"pool_size": 2, "max_overflow": 0, "pool_timeout": 20, "pool_pre_ping": True}]
    else:
        assert calls == [{"poolclass": "original"}]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    timing = next(line for line in lines if line.get("checkpoint") == "gate_finished")
    assert "journal_operations_partial" in timing
    assert "db_events_owner_and_runtime_aggregate" in timing
    assert timing["pool_reset_scope_if_enabled"] == "one_reused_backend_only"
