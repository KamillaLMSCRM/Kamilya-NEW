"""PostgreSQL coverage for canonical staff hierarchy writes."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.models.department import Department
from app.models.users import User
from app.modules.positions.admin_router import get_staff_structure
from app.modules.positions.models import Position
from app.modules.users.staff_import_service import (
    ParsedFile,
    ParsedRow,
    build_preview,
    commit_import,
    parse_upload,
)


def _parsed(
    personnel_number: str,
    department: str,
    position: str,
    *,
    phone: str | None = None,
    hire_date: str | None = None,
) -> ParsedFile:
    return ParsedFile(
        rows=[
            ParsedRow(
                row_number=2,
                personnel_number=personnel_number,
                first_name="Test",
                last_name="Learner",
                department=department,
                position=position,
                phone=phone,
                hire_date=hire_date,
            )
        ],
        invalid_rows=[],
        detected_columns={},
        missing_required_columns=[],
        total_rows_in_file=1,
    )


async def _commit(db_session, tenant_id, parsed):
    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        new=AsyncMock(return_value=SimpleNamespace(added=0, removed=0)),
    ), patch(
        "app.core.redis_progress.new_task_id",
        return_value="staff-hierarchy-integration",
    ), patch(
        "app.core.redis_progress.init_task",
        new=AsyncMock(),
    ), patch(
        "app.core.redis_progress.mark_started",
        new=AsyncMock(),
    ), patch(
        "app.core.redis_progress.increment_done",
        new=AsyncMock(),
    ), patch(
        "app.core.redis_progress.mark_success",
        new=AsyncMock(),
    ):
        return await commit_import(db_session, tenant_id, parsed)


@pytest.mark.asyncio
async def test_import_writes_idempotent_tenant_scoped_department_position_user(
    db_session,
    make_tenant,
):
    tenant_a = await make_tenant(name="Staff hierarchy A")
    tenant_b = await make_tenant(name="Staff hierarchy B")

    first = await _commit(
        db_session,
        tenant_a.id,
        _parsed(
            " P-001 ",
            " Sales   Operations ",
            " Account   Manager ",
            phone="+7 777 000 00 01",
            hire_date="2026-07-01",
        ),
    )
    repeat = await _commit(
        db_session,
        tenant_a.id,
        _parsed("p-001", "sales operations", "account manager"),
    )
    other_tenant = await _commit(
        db_session,
        tenant_b.id,
        _parsed("P-001", "Sales Operations", "Account Manager"),
    )

    assert first["created"] == 1
    assert first["positions_created"] == 1
    assert repeat["created"] == 0
    assert repeat["positions_created"] == 0
    assert repeat["skipped"] == 1
    assert other_tenant["created"] == 1
    assert other_tenant["positions_created"] == 1

    for tenant in (tenant_a, tenant_b):
        department = await db_session.scalar(
            select(Department).where(Department.tenant_id == tenant.id)
        )
        position = await db_session.scalar(
            select(Position).where(Position.tenant_id == tenant.id)
        )
        learner = await db_session.scalar(
            select(User).where(
                User.tenant_id == tenant.id,
                func.lower(User.personnel_number) == "p-001",
            )
        )

        assert department is not None
        assert position is not None
        assert learner is not None
        assert position.department_id == department.id
        assert learner.position_id == position.id
        if tenant.id == tenant_a.id:
            assert learner.phone == "+7 777 000 00 01"
            assert learner.hire_date.isoformat() == "2026-07-01"

        assert await db_session.scalar(
            select(func.count()).select_from(Department).where(
                Department.tenant_id == tenant.id
            )
        ) == 1
        assert await db_session.scalar(
            select(func.count()).select_from(Position).where(
                Position.tenant_id == tenant.id
            )
        ) == 1
        assert await db_session.scalar(
            select(func.count()).select_from(User).where(
                User.tenant_id == tenant.id,
                func.lower(User.personnel_number) == "p-001",
            )
        ) == 1


@pytest.mark.asyncio
async def test_multisheet_preview_commit_matches_staff_structure(
    db_session,
    make_tenant,
    make_user,
):
    tenant = await make_tenant(name="Multi-sheet staff flow")
    methodologist = await make_user(tenant, role="methodologist")

    workbook = Workbook()
    employees = workbook.active
    employees.title = "Сотрудники"
    employees.append(["Штатное расписание"])
    employees.append([])
    employees.append(["Табельный №", "ФИО", "Должность", "Отдел"])
    employees.append(["EMP-001", "Ахметов Айбек", "Инженер", "IT"])
    employees.append(["EMP-002", "Ибрагимова Ольга", "Бухгалтер", "Финансы"])
    departments = workbook.create_sheet("Отделы")
    departments.append(["Код", "Название отдела"])
    departments.append(["DEP-01", "IT"])
    departments.append(["DEP-02", "Финансы"])

    payload = BytesIO()
    workbook.save(payload)
    workbook.close()

    parsed = parse_upload("staff.xlsx", payload.getvalue())
    preview = await build_preview(db_session, tenant.id, parsed)
    result = await _commit(db_session, tenant.id, parsed)
    structure = await get_staff_structure(db=db_session, user=methodologist)

    assert parsed.sheet_name == "Сотрудники"
    assert preview.summary == {
        "create": 2,
        "update": 0,
        "skip": 0,
        "new_positions": 2,
        "new_departments": 2,
    }
    assert result["created"] == 2
    assert result["positions_created"] == 2
    assert structure.summary["total_employees"] == 2
    assert structure.summary["total_departments"] == 2
    assert structure.summary["total_positions"] == 2
    assert sum(
        len(position.employees)
        for department in structure.departments
        for position in department.positions
    ) == 2
