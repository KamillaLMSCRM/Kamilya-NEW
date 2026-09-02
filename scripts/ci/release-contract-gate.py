#!/usr/bin/env python3
"""Validate release-critical source contracts without settings, secrets, or network access."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "apps" / "api" / "alembic" / "versions"
CELERY_APP = REPO_ROOT / "apps" / "api" / "app" / "core" / "celery_app.py"
ERRORS_JOURNAL = REPO_ROOT / "ERRORS.md"
AGENT_RULES = REPO_ROOT / "AGENTS.md"
LEGACY_LESSONS = REPO_ROOT / "docs" / "LESSONS.md"
EXPECTED_TASK_MODULES = {
    "app.modules.ai.tasks",
    "app.modules.positions.tasks",
    "app.modules.users.tasks",
    "app.modules.enrollments.notification_tasks",
    "app.modules.learning_cycles.tasks",
    "app.modules.candidate_assessments.retention_tasks",
    "app.modules.tenants.tasks",
}
EXPECTED_TASK_NAMES = {
    "ai.generate_course",
    "ai.ingest_document",
    "ai.regenerate_lesson",
    "ai.regenerate_module",
    "positions.apply_course_rules",
    "users.deliver_invitation",
    "enrollments.deliver_assignment_notification",
    "enrollments.recover_assignment_notifications",
    "learning_cycles.materialize",
    "learning_cycles.recover_due",
    "candidate_assessments.enforce_retention",
    "crm.deliver_lead_outbox",
    "crm.recover_lead_outbox",
}

ERROR_ENTRY = re.compile(r"^## ([A-Z][A-Z0-9_-]*-\d{3}) (?:—|-) .+$", re.MULTILINE)
ERROR_FIELD_NAMES = (
    ("Date", "Дата"),
    ("Symptom", "Симптом"),
    ("Cause", "Причина"),
    ("Fix", "Исправление"),
    ("Verification", "Проверка"),
    ("Prevention", "Профилактика"),
)
ERROR_SECRET_PATTERNS = {
    "private key marker": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "credential URL": re.compile(r"(?:postgres(?:ql)?|redis|https?)://[^\s/:]+:[^\s/@]+@", re.IGNORECASE),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "JWT value": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
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
            "Alembic metadata error: expected exactly one head and one root " f"(heads={heads}, roots={roots})"
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
                    if (
                        keyword.arg == "name"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ):
                        registered.add(keyword.value.value)

    missing_tasks = sorted(EXPECTED_TASK_NAMES - registered)
    if missing_tasks:
        raise ValueError(f"Celery contract error: missing task registrations: {', '.join(missing_tasks)}")
    return f"Celery contract OK ({', '.join(sorted(EXPECTED_TASK_NAMES))})"


def check_migration_owner() -> str:
    render_blueprint = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    app_main = (REPO_ROOT / "apps" / "api" / "app" / "main.py").read_text(encoding="utf-8")

    if "preDeployCommand: PYTHONPATH=. alembic upgrade head" not in render_blueprint:
        raise ValueError("Migration owner error: Render pre-deploy migration is missing")
    if "alembic upgrade head &&" not in dockerfile:
        raise ValueError("Migration owner error: Docker startup is not fail-closed")
    if "_run_migrations" in app_main or "alembic upgrade" in app_main:
        raise ValueError("Migration owner error: HTTP application startup must not run migrations")
    return "migration ownership OK (Render pre-deploy and fail-closed Docker startup)"


def check_errors_journal() -> str:
    try:
        journal = ERRORS_JOURNAL.read_text(encoding="utf-8")
        agent_rules = AGENT_RULES.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"Errors journal contract error: {error}") from error

    if LEGACY_LESSONS.exists():
        raise ValueError("Errors journal contract error: competing docs/LESSONS.md still exists")
    if "[`ERRORS.md`](ERRORS.md)" not in agent_rules:
        raise ValueError("Errors journal contract error: AGENTS.md does not link the root journal")
    if "обязан полностью прочитать `ERRORS.md`" not in agent_rules:
        raise ValueError("Errors journal contract error: AGENTS.md does not require a full preflight read")

    ids = ERROR_ENTRY.findall(journal)
    if not ids:
        raise ValueError("Errors journal contract error: no CATEGORY-NNN entries found")
    duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicates:
        raise ValueError(f"Errors journal contract error: duplicate ids: {', '.join(duplicates)}")

    matches = list(ERROR_ENTRY.finditer(journal))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(journal)
        section = journal[match.start() : end]
        missing = [
            names[0]
            for names in ERROR_FIELD_NAMES
            if not any(f"- {name}:" in section for name in names)
        ]
        if missing:
            raise ValueError(f"Errors journal contract error: {match.group(1)} missing fields: {', '.join(missing)}")

    for rule_name, pattern in ERROR_SECRET_PATTERNS.items():
        match = pattern.search(journal)
        if match:
            line = journal.count("\n", 0, match.start()) + 1
            raise ValueError(f"Errors journal contract error: possible {rule_name} at ERRORS.md:{line}")

    header_date = re.search(
        r"^(?:Current as of|Актуально на): (\d{4}-\d{2}-\d{2})\.$",
        journal,
        re.MULTILINE,
    )
    entry_dates = re.findall(r"^- (?:Date|Дата): (\d{4}-\d{2}-\d{2})", journal, re.MULTILINE)
    if not header_date or not entry_dates or header_date.group(1) != max(entry_dates):
        raise ValueError("Errors journal contract error: header date must equal the latest entry date")

    return f"errors journal OK ({len(ids)} unique entries, secret-safe structure)"


def main() -> int:
    try:
        print(f"release-contract-gate: {check_alembic_chain()}")
        print(f"release-contract-gate: {check_celery_contract()}")
        print(f"release-contract-gate: {check_migration_owner()}")
        print(f"release-contract-gate: {check_errors_journal()}")
    except ValueError as error:
        print(f"release-contract-gate: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
