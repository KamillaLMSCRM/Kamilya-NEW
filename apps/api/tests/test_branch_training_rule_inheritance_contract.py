from pathlib import Path

ASSIGNMENT = Path(__file__).parents[1] / "app" / "modules" / "positions" / "assignment_service.py"
BATCH = Path(__file__).parents[1] / "app" / "modules" / "positions" / "batch_service.py"


def test_effective_department_rules_include_parent_branch() -> None:
    source = ASSIGNMENT.read_text(encoding="utf-8")
    assert "resolve_ancestor_path" in source
    assert "DepartmentCourse.department_id.in_(department_scope_ids)" in source


def test_branch_recompute_and_preview_use_recursive_employee_scope() -> None:
    assignment = ASSIGNMENT.read_text(encoding="utf-8")
    batch = BATCH.read_text(encoding="utf-8")
    assert "resolve_employee_scope" in assignment
    assert "resolve_employee_scope" in batch
    assert "Department.parent_id == department_id" not in assignment
    assert "Department.parent_id == department_id" not in batch
