#!/usr/bin/env python3
"""Validate release-critical source contracts without settings, secrets, or network access."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "apps" / "api" / "alembic" / "versions"
CELERY_APP = REPO_ROOT / "apps" / "api" / "app" / "core" / "celery_app.py"
EXPECTED_TASK_MODULES = {
    "app.modules.ai.tasks",
    "app.modules.positions.tasks",
}
EXPECTED_TASK_NAMES = {
    "ai.generate_course",
    "ai.ingest_document",
    "positions.apply_course_rules",
}


def _literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and (isinstance(node.value, str) or node.value is None):
        return node.value
    raise ValueError("expected a string literal or None")


def _assignment(tree: ast.Module, name: str, source: Path) -> str | None:
    values: list[str | None] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                try:
                    values.append(_literal(node.value))
                except ValueError as error:
                    raise ValueError(f"{source}: {name} {error}") from error
    if len(values) != 1:
        raise ValueError(f"{source}: expected exactly one {name} assignment, found {len(values)}")
    return values[0]


def check_alembic_chain() -> str:
    migrations: dict[str, str | None] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = _assignment(tree, "revision", path)
            down_revision = _assignment(tree, "down_revision", path)
        except (OSError, SyntaxError, ValueError) as error:
            raise ValueError(f"Alembic metadata error: {error}") from error
        if revision is None:
            raise ValueError(f"Alembic metadata error: {path} has a null revision")
        if revision in migrations:
            raise ValueError(f"Alembic metadata error: duplicate revision {revision}")
        migrations[revision] = down_revision

    if not migrations:
        raise ValueError("Alembic metadata error: no Python revisions found")

    parents = {parent for parent in migrations.values() if parent is not None}
    missing = sorted(parents - migrations.keys())
    if missing:
        raise ValueError(f"Alembic metadata error: missing parent revisions: {', '.join(missing)}")

    heads = sorted(set(migrations) - parents)
    roots = sorted(revision for revision, parent in migrations.items() if parent is None)
    if len(heads) != 1 or len(roots) != 1:
        raise ValueError(
            "Alembic metadata error: expected exactly one head and one root "
            f"(heads={heads}, roots={roots})"
        )

    seen: set[str] = set()
    current: str | None = heads[0]
    while current is not None:
        if current in seen:
            raise ValueError(f"Alembic metadata error: cycle detected at revision {current}")
        seen.add(current)
        current = migrations[current]
    if seen != set(migrations):
        disconnected = sorted(set(migrations) - seen)
        raise ValueError(f"Alembic metadata error: disconnected revisions: {', '.join(disconnected)}")

    return f"Alembic chain OK ({len(migrations)} revisions, head={heads[0]})"


def _string_list(node: ast.AST) -> set[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values: set[str] = set()
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        values.add(element.value)
    return values


def check_celery_contract() -> str:
    try:
        app_tree = ast.parse(CELERY_APP.read_text(encoding="utf-8"), filename=str(CELERY_APP))
    except (OSError, SyntaxError) as error:
        raise ValueError(f"Celery contract error: {error}") from error

    includes: set[str] = set()
    for node in ast.walk(app_tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "include":
                    literals = _string_list(keyword.value)
                    if literals is not None:
                        includes.update(literals)
    missing_modules = sorted(EXPECTED_TASK_MODULES - includes)
    if missing_modules:
        raise ValueError(f"Celery contract error: missing included task modules: {', '.join(missing_modules)}")

    registered: set[str] = set()
    for module in EXPECTED_TASK_MODULES:
        path = REPO_ROOT / "apps" / "api" / Path(*module.split("."))
        path = path.with_suffix(".py")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            raise ValueError(f"Celery contract error: {error}") from error
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                if not isinstance(decorator.func, ast.Attribute) or decorator.func.attr != "task":
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                        registered.add(keyword.value.value)

    missing_tasks = sorted(EXPECTED_TASK_NAMES - registered)
    if missing_tasks:
        raise ValueError(f"Celery contract error: missing task registrations: {', '.join(missing_tasks)}")
    return f"Celery contract OK ({', '.join(sorted(EXPECTED_TASK_NAMES))})"


def main() -> int:
    try:
        print(f"release-contract-gate: {check_alembic_chain()}")
        print(f"release-contract-gate: {check_celery_contract()}")
    except ValueError as error:
        print(f"release-contract-gate: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
