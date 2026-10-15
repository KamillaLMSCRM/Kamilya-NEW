from __future__ import annotations

import ast
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "workbench_unicode_dev_checks.py"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_unicode_gate_has_exact_async_entrypoint_and_owned_inputs() -> None:
    source = _source()
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
    entry = next(node for node in functions if node.name == "verify_unicode_resolution")
    assert [arg.arg for arg in entry.args.args] == [
        "owner_engine",
        "runtime_engine",
        "schema",
        "actor",
        "course_id",
        "department_id",
        "learner_id",
        "now",
    ]
    assert "safe_schema(schema)" in source
    assert "await context(connection, schema, actor.tenant_id, actor.actor_id)" in source
    assert "create_async_engine" not in source
    assert "public." not in source
    assert "ALTER TABLE public" not in source


def test_unicode_gate_proves_icu_and_c_collation_without_global_change() -> None:
    source = _source()
    assert 'collname=\'und-x-icu\'' in source
    assert "collprovider='i'" in source
    assert 'ALTER COLUMN title TYPE text COLLATE "C"' in source
    assert 'ALTER COLUMN name TYPE text COLLATE "C"' in source
    assert "pg_catalog.pg_attribute" in source
    assert "owned_fixture_columns_not_c_collated" in source
    assert "lower(CAST(:value AS text) COLLATE \"C\")" in source
    assert "lower(CAST(:value AS text) COLLATE \"und-x-icu\")" in source
    assert "ALTER DATABASE" not in source
    assert "ALTER SYSTEM" not in source


def test_unicode_gate_calls_real_preview_and_rolls_back_every_preview() -> None:
    source = _source()
    assert "create_assignment_preview" in source
    assert "AssignmentPreviewRequest" in source
    assert "AssignmentCandidate" in source
    assert "before_candidate = candidate.model_dump()" in source
    assert "candidate.model_dump() != before_candidate" in source
    assert "await db.rollback()" in source
    assert "unicode_preview_left_rows" in source
    assert "notify=False" in source
    assert "provider_resolver" not in source
    assert ".ainvoke" not in source
    assert "model_call" not in source


def test_whitespace_is_normalized_before_candidate_immutability_snapshot() -> None:
    from app.modules.methodologist_workbench.natural_assignment_intent import AssignmentCandidate

    candidate = AssignmentCandidate(
        course_query="  ПРОВЕРКА Назначения  ",
        department_query="  әҚҢҒҰҮҺӨІ БӨЛІМІ  ",
        due_date="2026-10-27",
        due_time="17:30:00",
    )
    assert candidate.course_query == "ПРОВЕРКА Назначения"
    assert candidate.department_query == "әҚҢҒҰҮҺӨІ БӨЛІМІ"
