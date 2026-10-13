"""The isolation gate cannot read credentials or connect without exact execution."""
import importlib
import sys
from pathlib import Path


def test_approval_gate_requires_execute_before_reading_credentials(monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "ops"))
    gate = importlib.import_module("course_approval_audit_dev_gate")
    monkeypatch.setattr(sys, "argv", ["gate", "--env-file", "missing-never-read.env"])
    def forbidden(*args, **kwargs):
        raise AssertionError("credential read before execute approval")
    monkeypatch.setattr(gate, "dotenv_values", forbidden)
    monkeypatch.setattr(gate, "load_dotenv", forbidden)
    assert gate.main() == 2
    assert '"execute_required"' in capsys.readouterr().out
