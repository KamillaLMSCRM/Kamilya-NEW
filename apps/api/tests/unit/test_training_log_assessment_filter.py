"""Synthetic query-policy oracle; no application database or provider access."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql, sqlite

from app.modules.training_log.repository import (
    _assessment_enrollment_ids,
    count_current_attempt_outcomes,
    count_training_log,
    list_training_log,
)
from app.modules.training_log.schemas import TrainingLogFilter


class BoolOr:
    def __init__(self):
        self.value = False

    def step(self, value):
        self.value = self.value or bool(value)

    def finalize(self):
        return self.value


def test_actual_aggregate_policy_resolves_passes_and_exhausts_each_quiz_separately():
    """SQLite is an in-memory unit adapter, not an RLS/integration substitute."""
    tenant, foreign, learner, other = (uuid4() for _ in range(4))
    resolved, split, exhausted, successor = (uuid4() for _ in range(4))
    quiz_a, quiz_b, foreign_quiz = (uuid4() for _ in range(3))
    with sqlite3.connect(":memory:") as connection:
        connection.create_aggregate("bool_or", 1, BoolOr)
        connection.executescript("""
            CREATE TABLE enrollments (id TEXT, tenant_id TEXT, user_id TEXT);
            CREATE TABLE quizzes (id TEXT, tenant_id TEXT, attempt_limit INTEGER);
            CREATE TABLE quiz_attempts (
                id TEXT, tenant_id TEXT, user_id TEXT, enrollment_id TEXT,
                quiz_id TEXT, passed BOOLEAN
            );
        """)
        connection.executemany("INSERT INTO enrollments VALUES (?,?,?)", [
            (value.hex, tenant.hex, learner.hex) for value in (resolved, split, exhausted, successor)
        ])
        connection.executemany("INSERT INTO quizzes VALUES (?,?,?)", [
            (quiz_a.hex, tenant.hex, 3), (quiz_b.hex, tenant.hex, 3),
            (foreign_quiz.hex, foreign.hex, 1),
        ])

        def attempt(enrollment, quiz, passed, *, actual_tenant=tenant, actual_user=learner):
            connection.execute("INSERT INTO quiz_attempts VALUES (?,?,?,?,?,?)", (
                uuid4().hex, actual_tenant.hex, actual_user.hex, enrollment.hex, quiz.hex, passed,
            ))

        attempt(resolved, quiz_a, False)
        attempt(resolved, quiz_a, True)
        for quiz in (quiz_a, quiz_b):
            attempt(split, quiz, False)
            attempt(split, quiz, False)
        for _ in range(3):
            attempt(exhausted, quiz_a, False)
        attempt(successor, quiz_a, False)
        # These must not exhaust a different learner/tenant's occurrence.
        attempt(successor, quiz_a, False, actual_tenant=foreign)
        attempt(successor, quiz_a, False, actual_user=other)
        attempt(successor, foreign_quiz, False)

        def selected(status):
            query = _assessment_enrollment_ids(tenant, status).compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True},
            )
            return {row[0] for row in connection.execute(str(query))}

        assert selected("failed") == {split.hex, exhausted.hex, successor.hex}
        assert selected("exhausted") == {exhausted.hex}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "exhausted"])
async def test_list_and_count_include_the_same_policy_before_pagination(status):
    tenant = uuid4()
    statements = []

    async def execute(statement):
        statements.append(str(statement.compile(dialect=postgresql.dialect())))
        return SimpleNamespace(scalar=lambda: 0, mappings=lambda: SimpleNamespace(all=lambda: []))

    db = SimpleNamespace(execute=execute)
    filters = TrainingLogFilter(assessment_status=status)
    assert await count_training_log(db, tenant, filters) == 0
    assert await list_training_log(db, tenant, filters, limit=1, offset=4) == []
    for sql in statements:
        assert "quiz_attempts.enrollment_id" in sql
        assert "assessment_occurrence.user_id = quiz_attempts.user_id" in sql
        assert "bool_or(quiz_attempts.passed)" in sql
        assert "has_passed IS false" in sql
        assert "NOT (EXISTS" in sql  # current occurrence guard preserved
        assert ("attempt_limit <=" in sql) == (status == "exhausted")
    assert "LIMIT" not in statements[0]
    assert "LIMIT" in statements[1]


@pytest.mark.asyncio
async def test_summary_uses_same_outcome_policy_and_exact_occurrence_guard():
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[2, 1]))
    assert await count_current_attempt_outcomes(db, uuid4(), TrainingLogFilter()) == (2, 1)
    queries = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in db.scalar.call_args_list]
    assert all("has_passed IS false" in sql and "previous_enrollment_id" in sql for sql in queries)
    assert "attempt_limit <=" not in queries[0]
    assert "attempt_limit <=" in queries[1]


def test_filter_rejects_unrecognized_assessment_state():
    with pytest.raises(ValidationError):
        TrainingLogFilter(assessment_status="passed")
