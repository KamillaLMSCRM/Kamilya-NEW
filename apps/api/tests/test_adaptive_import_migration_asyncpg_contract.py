"""Keep adaptive-import DDL executable through SQLAlchemy's asyncpg driver."""

from __future__ import annotations

import ast
import re
from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "alembic" / "versions"
FILES = (
    "0112_organization_units.py",
    "0113_staff_import_sessions.py",
    "0114_position_import_identity.py",
    "0115_staff_import_mapping_profiles.py",
)
TOP_LEVEL_DDL = re.compile(r"(?m)^\s*CREATE\s+(?:FUNCTION|TRIGGER)\b", re.IGNORECASE)


def _literal_execute_payloads(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    payloads: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "execute" or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            payloads.append(value.value)
    return payloads


def test_adaptive_import_migrations_do_not_batch_top_level_ddl_for_asyncpg() -> None:
    """asyncpg rejects multiple SQL commands in one prepared statement.

    PL/pgSQL function bodies legitimately contain semicolons, so this contract
    counts only top-level CREATE FUNCTION/TRIGGER lines inside each individual
    ``op.execute`` payload.
    """

    offenders: list[str] = []
    for filename in FILES:
        for index, payload in enumerate(_literal_execute_payloads(MIGRATIONS / filename), start=1):
            if len(TOP_LEVEL_DDL.findall(payload)) > 1:
                offenders.append(f"{filename}:op.execute[{index}]")

    assert offenders == [], f"asyncpg-incompatible multi-command DDL: {offenders}"
