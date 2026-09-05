"""Catch fixture-invented user columns before the real DEV migration gate."""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.users import User


def test_reminder_migration_references_only_physical_user_columns():
    root = Path(__file__).resolve().parents[4]
    path = root / "apps/api/alembic/versions/0152_learning_reminders.py"
    spec = importlib.util.spec_from_file_location("reminder_schema_regression", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    migration.op = SimpleNamespace(
        execute=lambda sql: statements.append(str(sql)),
        get_context=lambda: SimpleNamespace(opts={}),
    )
    migration.upgrade()
    source = "\n".join(statements)
    referenced = set(re.findall(r"\bu\.([a-z_]+)\b", source))
    assert referenced
    assert referenced <= set(User.__table__.columns.keys())
    assert {"password_hash", "telegram_id", "email_verified_at"} <= referenced
    assert "has_login_access" not in referenced


@pytest.mark.asyncio
async def test_dev_gate_failure_is_sanitized_and_nonzero_without_database(monkeypatch, capsys):
    root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(root / "scripts/ops"))
    spec = importlib.util.spec_from_file_location(
        "reminder_failure_regression", root / "scripts/ops/learning_reminder_dev_check.py"
    )
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    monkeypatch.setattr(sys, "argv", ["gate", "--execute", "--application"])
    monkeypatch.setattr(
        gate,
        "dotenv_values",
        lambda _path: {
            "DATABASE_URL": "postgresql+asyncpg://lms_app:synthetic@invalid.invalid/postgres",
            "MIGRATION_DATABASE_URL": "postgresql+asyncpg://postgres:synthetic@invalid.invalid/postgres",
            "SUPABASE_URL": "https://synthetic.example",
        },
    )
    monkeypatch.setattr(gate, "same_supabase_project", lambda *_args: True)

    class DeniedConnection:
        async def __aenter__(self):
            raise RuntimeError("sensitive_exception_payload_must_not_appear")

        async def __aexit__(self, *_args):
            return False

    engines = []

    def fake_engine(*_args, **_kwargs):
        engine = SimpleNamespace(begin=DeniedConnection, dispose=AsyncMock())
        engines.append(engine)
        return engine

    monkeypatch.setattr(gate, "create_async_engine", fake_engine)
    assert await gate.run() == 1
    output = capsys.readouterr().out
    assert "sensitive_exception_payload" not in output
    report = json.loads(output)
    assert (report["status"], report["stage"], report["error_type"]) == ("BLOCKED", "preflight", "RuntimeError")
    assert report["gate_locations"]
    for engine in engines:
        engine.dispose.assert_awaited_once()
