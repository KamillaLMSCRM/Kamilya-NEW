from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.modules.organization_units.service import build_tree, normalize_unit_name


def _unit(*, name: str, kind: str, parent_id=None, legacy_root=False):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        slug=name.casefold().replace(" ", "-"),
        unit_type=kind,
        parent_id=parent_id,
        external_key=None,
        is_active=True,
        legacy_root=legacy_root,
        description="",
        code=None,
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
    )


def test_normalization_handles_unicode_case_and_spaces() -> None:
    assert normalize_unit_name("  БӨЛІМ   А  ") == "бөлім а"


def test_tree_distinguishes_branches_departments_and_legacy_roots() -> None:
    branch = _unit(name="Филиал Павлодар", kind="branch")
    department = _unit(name="Бухгалтерия", kind="department", parent_id=branch.id)
    legacy = _unit(name="Старое подразделение", kind="department", legacy_root=True)
    branches, legacy_roots = build_tree([department, legacy, branch])

    assert [node["name"] for node in branches] == ["Филиал Павлодар"]
    assert [node["name"] for node in branches[0]["children"]] == ["Бухгалтерия"]
    assert [node["name"] for node in legacy_roots] == ["Старое подразделение"]


def test_tree_exposes_position_employee_projections_and_rollups() -> None:
    branch = _unit(name="Филиал Павлодар", kind="branch")
    department = _unit(name="Бухгалтерия", kind="department", parent_id=branch.id)
    legacy = _unit(name="Старое подразделение", kind="department", legacy_root=True)
    projections = {
        department.id: [
            {
                "id": uuid4(),
                "name": "Кассир",
                "department": department.name,
                "department_slug": department.slug,
                "employee_count": 2,
                "ready_percent": 50,
                "employees": [
                    {
                        "id": uuid4(),
                        "full_name": "Иванова Алия",
                        "personnel_number": "001",
                        "is_active": True,
                    },
                    {
                        "id": uuid4(),
                        "full_name": "Петров Ерлан",
                        "personnel_number": "002",
                        "is_active": False,
                    },
                ],
            }
        ]
    }

    branches, legacy_roots = build_tree([department, legacy, branch], positions_by_unit=projections)

    assert branches[0]["department_count"] == 1
    assert branches[0]["position_count"] == 1
    assert branches[0]["employee_count"] == 2
    assert branches[0]["children"][0]["positions"][0]["employees"][0]["full_name"] == "Иванова Алия"
    assert legacy_roots[0]["department_count"] == 0
