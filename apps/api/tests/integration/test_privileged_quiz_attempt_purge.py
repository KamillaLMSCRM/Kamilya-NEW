"""Migration contract for owner-authorized evidentiary-attempt deletion."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "0125_privileged_quiz_attempt_purge.py"
)


def test_migration_keeps_evidence_immutable_outside_owner_delete() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0125"' in source
    assert 'down_revision = "0124"' in source
    assert "OLD.evidence_sha256 IS NOT NULL" in source
    assert "TG_OP = 'DELETE'" in source
    assert "privileged_tenant_purge_authorized(OLD.tenant_id)" in source
    assert "Evidentiary quiz attempts are immutable" in source
    assert "SECURITY DEFINER" not in source
    assert "GRANT " not in source
    assert "session_replication_role" not in source


@pytest.mark.asyncio
async def test_catalog_retains_trigger_and_exact_owner_delete_guard(db_session) -> None:
    function_definition = await db_session.scalar(
        text(
            "SELECT pg_catalog.pg_get_functiondef("
            "'public.prevent_quiz_attempt_evidence_mutation()'::regprocedure)"
        )
    )
    assert "TG_OP = 'DELETE'" in function_definition
    assert "privileged_tenant_purge_authorized(OLD.tenant_id)" in function_definition
    assert "Evidentiary quiz attempts are immutable" in function_definition

    trigger_enabled = await db_session.scalar(
        text(
            "SELECT t.tgenabled "
            "FROM pg_catalog.pg_trigger AS t "
            "WHERE t.tgrelid = 'public.quiz_attempts'::regclass "
            "AND t.tgname = 'quiz_attempts_prevent_evidence_mutation' "
            "AND NOT t.tgisinternal"
        )
    )
    assert trigger_enabled in ("O", b"O")
