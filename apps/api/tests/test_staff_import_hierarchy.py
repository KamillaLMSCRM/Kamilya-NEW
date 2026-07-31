"""Unit coverage for the canonical staff import hierarchy."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.department import Department
from app.models.users import User
from app.modules.positions.models import Position
from app.modules.users.staff_import_service import (
    ParsedFile,
    ParsedRow,
    StaffEmailConflictError,
    build_preview,
    commit_import,
    create_manual_staff_member,
)


@pytest.mark.asyncio
async def test_manual_staff_rejects_email_owned_by_another_personnel_record():
    tenant_id = uuid4()
    existing = User(
        id=uuid4(),
        tenant_id=tenant_id,
        personnel_number="EMP-001",
        email="employee@example.kz",
        first_name="Existing",
        last_name="Employee",
        role="student",
        is_active=True,
        status="active",
    )
    db = _MemorySession(users=[existing])

    with pytest.raises(StaffEmailConflictError):
        await create_manual_staff_member(
            db,
            tenant_id,
            personnel_number="EMP-002",
            first_name="New",
            last_name="Employee",
            department="HR",
            position="Specialist",
            email="EMPLOYEE@example.kz",
        )


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _MemorySession:
    """Small session double that returns rows without applying SQL filters."""

    def __init__(self, *, users=None, departments=None, positions=None):
        self.users = list(users or [])
        self.departments = list(departments or [])
        self.positions = list(positions or [])

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is User:
            return _ScalarResult(self.users)
        if entity is Department:
            return _ScalarResult(self.departments)
        if entity is Position:
            return _ScalarResult(self.positions)
        raise AssertionError(f"Unexpected entity: {entity}")

    def add(self, value):
        if isinstance(value, User):
            self.users.append(value)
        elif isinstance(value, Department):
            self.departments.append(value)
        elif isinstance(value, Position):
            self.positions.append(value)
        else:
            raise AssertionError(f"Unexpected object: {value!r}")

    async def flush(self):
        return None

    async def commit(self):
        return None


def _parsed(*rows: ParsedRow) -> ParsedFile:
    return ParsedFile(
        rows=list(rows),
        invalid_rows=[],
        detected_columns={},
        missing_required_columns=[],
        total_rows_in_file=len(rows),
    )


async def _commit(db, tenant_id, parsed):
    fake_apply = AsyncMock(return_value=SimpleNamespace(added=0, removed=0))
    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        fake_apply,
    ), patch(
        "app.core.redis_progress.new_task_id", return_value="staff-task"
    ), patch("app.core.redis_progress.init_task", new=AsyncMock()), patch(
        "app.core.redis_progress.mark_started", new=AsyncMock()
    ), patch("app.core.redis_progress.increment_done", new=AsyncMock()), patch(
        "app.core.redis_progress.mark_success", new=AsyncMock()
    ):
        result = await commit_import(db, tenant_id, parsed)
    return result


async def _manual(db, tenant_id, **kwargs):
    fake_apply = AsyncMock(return_value=SimpleNamespace(added=0, removed=0))
    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        fake_apply,
    ), patch(
        "app.core.redis_progress.new_task_id", return_value="staff-task"
    ), patch("app.core.redis_progress.init_task", new=AsyncMock()), patch(
        "app.core.redis_progress.mark_started", new=AsyncMock()
    ), patch("app.core.redis_progress.increment_done", new=AsyncMock()), patch(
        "app.core.redis_progress.mark_success", new=AsyncMock()
    ):
        return await create_manual_staff_member(db, tenant_id, **kwargs)


@pytest.mark.asyncio
async def test_preview_commit_repeat_and_manual_add_share_normalization():
    tenant_id = uuid4()
    db = _MemorySession()
    first = ParsedRow(
        row_number=2,
        personnel_number=" P-001 ",
        first_name=" Ann ",
        last_name=" Lee ",
        department=" Sales   Operations ",
        position=" Account   Manager ",
        email="ANN@EXAMPLE.COM",
    )

    preview = await build_preview(db, tenant_id, _parsed(first))
    assert preview.summary == {
        "create": 1,
        "update": 0,
        "skip": 0,
        "new_positions": 1,
        "new_departments": 1,
    }

    result = await _commit(db, tenant_id, _parsed(first))
    assert result["created"] == 1
    assert result["positions_created"] == 1
    assert len(db.departments) == 1
    assert len(db.positions) == 1
    assert db.positions[0].department_id == db.departments[0].id
    assert db.positions[0].department == "Sales Operations"

    repeat = ParsedRow(
        row_number=2,
        personnel_number="p-001",
        first_name="Ann",
        last_name="Lee",
        department="sales operations",
        position="account manager",
        email="ann@example.com",
    )
    repeat_preview = await build_preview(db, tenant_id, _parsed(repeat))
    assert repeat_preview.items[0].action == "skip"
    assert repeat_preview.summary["new_positions"] == 0
    assert repeat_preview.summary["new_departments"] == 0

    repeat_result = await _commit(db, tenant_id, _parsed(repeat))
    assert repeat_result["created"] == 0
    assert repeat_result["updated"] == 0
    assert repeat_result["skipped"] == 1
    assert repeat_result["positions_created"] == 0

    manual_result = await _commit(
        db,
        tenant_id,
        _parsed(
            ParsedRow(
                row_number=1,
                personnel_number="  P-001  ",
                first_name="Ann",
                last_name="Lee",
                department=" SALES   OPERATIONS ",
                position=" ACCOUNT MANAGER ",
                email="ann@example.com",
            )
        ),
    )
    assert manual_result["skipped"] == 1

    direct_manual = await create_manual_staff_member(
        db,
        tenant_id,
        personnel_number="P-001",
        first_name="Ann",
        last_name="Lee",
        department="sales operations",
        position="account manager",
        email="ann@example.com",
    )
    assert direct_manual["created"] == 0
    assert len(db.users) == 1
    assert len(db.departments) == 1
    assert len(db.positions) == 1


@pytest.mark.asyncio
async def test_same_position_name_is_separate_per_department_and_tenant():
    tenant_a = uuid4()
    tenant_b = uuid4()
    b_department = Department(
        id=uuid4(), tenant_id=tenant_b, name="Operations", slug="operations"
    )
    b_position = Position(
        id=uuid4(),
        tenant_id=tenant_b,
        name="Manager",
        department="Operations",
        department_id=b_department.id,
        level="",
        responsibilities="",
        requirements="",
        employee_count=0,
    )
    b_user = User(
        id=uuid4(),
        tenant_id=tenant_b,
        personnel_number="P-001",
        first_name="Tenant",
        last_name="B",
        role="student",
        status="active",
        is_active=True,
        position_id=b_position.id,
    )
    db = _MemorySession(
        users=[b_user], departments=[b_department], positions=[b_position]
    )

    result = await _commit(
        db,
        tenant_a,
        _parsed(
            ParsedRow(2, "P-001", "A", "One", "Sales", "Manager"),
            ParsedRow(3, "P-002", "A", "Two", "IT", "Manager"),
        ),
    )

    assert result["created"] == 2
    a_departments = [d for d in db.departments if d.tenant_id == tenant_a]
    a_positions = [p for p in db.positions if p.tenant_id == tenant_a]
    assert len(a_departments) == 2
    assert len(a_positions) == 2
    assert {p.department_id for p in a_positions} == {d.id for d in a_departments}
    assert all(p.name == "Manager" for p in a_positions)
    assert len([u for u in db.users if u.tenant_id == tenant_b]) == 1


@pytest.mark.asyncio
async def test_department_lookup_uses_name_and_slug():
    tenant_id = uuid4()
    department = Department(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Human Resources",
        slug="hr",
    )
    position = Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Recruiter",
        department="Human Resources",
        department_id=department.id,
        level="",
        responsibilities="",
        requirements="",
        employee_count=0,
    )
    db = _MemorySession(departments=[department], positions=[position])
    parsed = _parsed(ParsedRow(2, "P-100", "A", "One", "Human Resources", "Recruiter"))

    preview = await build_preview(db, tenant_id, parsed)
    assert preview.summary["new_departments"] == 0
    assert preview.summary["new_positions"] == 0

    result = await _commit(db, tenant_id, parsed)
    assert result["positions_created"] == 0
    assert len(db.departments) == 1
    assert len(db.positions) == 1
    assert db.users[0].position_id == position.id


@pytest.mark.asyncio
async def test_preview_projects_identical_repeated_personnel_row_as_skip():
    tenant_id = uuid4()
    db = _MemorySession()
    parsed = _parsed(
        ParsedRow(2, "P-200", "A", "One", "Operations", "Manager"),
        ParsedRow(3, " p-200 ", "A", "One", " operations ", " manager "),
    )

    preview = await build_preview(db, tenant_id, parsed)
    assert [item.action for item in preview.items] == ["create", "skip"]
    assert "Повторный ряд" in preview.items[1].notes[0]

    result = await _commit(db, tenant_id, parsed)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert len(db.users) == 1


@pytest.mark.asyncio
async def test_preview_projects_changed_repeated_personnel_row_as_update():
    tenant_id = uuid4()
    db = _MemorySession()
    parsed = _parsed(
        ParsedRow(2, "P-300", "A", "One", "Operations", "Manager"),
        ParsedRow(3, "p-300", "B", "Two", "Operations", "Manager"),
    )

    preview = await build_preview(db, tenant_id, parsed)
    assert [item.action for item in preview.items] == ["create", "update"]
    assert any("имя" in note for note in preview.items[1].notes)
    assert any("фамилия" in note for note in preview.items[1].notes)

    result = await _commit(db, tenant_id, parsed)
    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert db.users[0].first_name == "B"
    assert db.users[0].last_name == "Two"


@pytest.mark.asyncio
async def test_legacy_text_position_is_backfilled_after_department_creation():
    tenant_id = uuid4()
    legacy_position = Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Manager",
        department="  HR  ",
        level="",
        responsibilities="",
        requirements="",
        employee_count=0,
    )
    db = _MemorySession(positions=[legacy_position])
    row = ParsedRow(2, "P-001", "A", "One", "hr", " manager ")

    preview = await build_preview(db, tenant_id, _parsed(row))
    assert preview.summary["new_departments"] == 1
    assert preview.summary["new_positions"] == 0

    result = await _commit(db, tenant_id, _parsed(row))
    assert result["positions_created"] == 0
    assert len(db.departments) == 1
    assert legacy_position.department_id == db.departments[0].id
    assert legacy_position.department == "hr"


@pytest.mark.asyncio
async def test_manual_add_creates_and_reuses_canonical_hierarchy():
    tenant_id = uuid4()
    db = _MemorySession()

    first = await _manual(
        db,
        tenant_id,
        personnel_number=" P-900 ",
        first_name="Manual",
        last_name="User",
        department=" Operations ",
        position=" Shift   Lead ",
    )
    assert first["created"] == 1
    assert db.users[0].position_id == db.positions[0].id
    assert db.positions[0].department_id == db.departments[0].id

    repeat = await _manual(
        db,
        tenant_id,
        personnel_number="p-900",
        first_name="Manual",
        last_name="User",
        department="operations",
        position="shift lead",
    )
    assert repeat["created"] == 0
    assert repeat["skipped"] == 1
    assert len(db.users) == 1
    assert len(db.departments) == 1
    assert len(db.positions) == 1
