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


def test_populated_purge_uses_bounded_outbox_readback_without_runtime_table_select():
    path = Path(__file__).parents[1] / "integration/test_superadmin_populated_enrollment_purge.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(module) if isinstance(node, ast.Call)]
    direct_selects = [node for node in calls if isinstance(node.func, ast.Name)
                      and node.func.id == "select" and any(
                          isinstance(child, ast.Name) and child.id == "CourseAssignmentNotificationOutbox"
                          for argument in node.args for child in ast.walk(argument))]
    assert not direct_selects, "lms_app must not SELECT the protected outbox table"
    status_calls = [node for node in calls if isinstance(node.func, ast.Attribute)
                    and node.func.attr == "statuses"]
    assert len(status_calls) == 2, "prove populated status before purge and absence after purge"
    assert all({keyword.arg for keyword in node.keywords} == {"tenant_id", "course_id"}
               for node in status_calls), "outbox readback must remain tenant/course bounded"
