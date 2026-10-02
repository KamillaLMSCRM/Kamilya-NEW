"""The shared-session API fixture must not serve cached pre-purge ORM rows."""
import ast
from pathlib import Path


def test_populated_purge_expires_shared_identity_map_before_api_absence_readback():
    path = Path(__file__).parents[1] / "integration/test_superadmin_populated_enrollment_purge.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    test = next(node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_superadmin_delete_populated"))
    deleted = next(index for index, node in enumerate(test.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "response" for target in node.targets))
    readback = next(index for index, node in enumerate(test.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "readback" for target in node.targets))
    between = test.body[deleted + 1:readback]
    assert any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
               and isinstance(node.value.func, ast.Attribute)
               and isinstance(node.value.func.value, ast.Name)
               and node.value.func.value.id == "db_session"
               and node.value.func.attr == "expire_all" for node in between), "fresh GET must not reuse cached tenant after raw DELETE"
