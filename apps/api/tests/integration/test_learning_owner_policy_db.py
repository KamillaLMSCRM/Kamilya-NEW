"""CI-only integration wrapper for the non-bypass reminder-owner contract."""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text


def _ci_enabled() -> bool:
    return os.getenv("CI", "").strip().lower() == "true"


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _ci_enabled(), reason="owner-policy database contract is CI-only"),
]


async def test_learning_owner_policy_db(db_session, monkeypatch) -> None:
    """Exercise the root helper only against rollback-scoped synthetic SQL."""
    repo_root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(repo_root / "scripts" / "ops"))

    from learning_owner_policy_check import check_owner_policy
    from learning_reminder_dev_check import ROOT, TABLES, SqlCollector

    schema = f"r2_reminder_{uuid4().hex}"
    assert re.fullmatch(r"r2_reminder_[0-9a-f]{32}", schema)

    async def execute(statement: str, params: dict | None = None):
        return await db_session.execute(text(statement), params or {})

    await execute(f'CREATE SCHEMA "{schema}"')
    for table, columns in TABLES.items():
        await execute(f'CREATE TABLE "{schema}"."{table}" ({columns})')

    migration_path = ROOT / "apps/api/alembic/versions/0152_learning_reminders.py"
    spec = importlib.util.spec_from_file_location("learning_reminders_0152", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    collector = SqlCollector(schema)
    migration.op = collector
    migration.upgrade()
    for statement in collector.statements:
        assert "public." not in statement
        assert "__KML_SCHEMA__" not in statement
        await execute(statement)

    await execute(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app')
    checks = await check_owner_policy(await db_session.connection(), schema, apply_fix=True)

    required_checks = {
        "production_non_bypass_owner_failure_reproduced",
        "bounded_discovery_with_non_bypass_owner",
        "course_ledger_end_to_end_no_provider",
        "tenant_and_direct_access_negatives",
        "downgrade_preserves_delivery_history",
        "baseline_course_enqueue_42501",
        "owner_policy_restores_no_context_due_discovery",
        "course_nullable_and_nonnull_actor_dedup",
        "path_enqueue_due_claim_wrong_token_and_finalize",
        "reupgrade_restores_nullable_actor_and_due_discovery",
    }
    assert required_checks <= set(checks)
