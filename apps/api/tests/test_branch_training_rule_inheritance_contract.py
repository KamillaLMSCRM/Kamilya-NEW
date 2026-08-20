from pathlib import Path

ASSIGNMENT = Path(__file__).parents[1] / "app" / "modules" / "positions" / "assignment_service.py"
BATCH = Path(__file__).parents[1] / "app" / "modules" / "positions" / "batch_service.py"


def test_effective_department_rules_include_parent_branch() -> None:
    source = ASSIGNMENT.read_text(encoding="utf-8")
    assert "department_scope_ids.append(unit.parent_id)" in source
    assert "DepartmentCourse.department_id.in_(department_scope_ids)" in source


def test_branch_recompute_and_preview_include_direct_child_departments() -> None:
    assignment = ASSIGNMENT.read_text(encoding="utf-8")
    batch = BATCH.read_text(encoding="utf-8")
    assert "Department.parent_id == department_id" in assignment
    assert "Department.parent_id == department_id" in batch
    assert "union_all(select(literal(department_id)))" in assignment
    assert "union_all(select(literal(department_id)))" in batch
