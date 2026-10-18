from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.models.department import Department
from app.modules.positions import router
from app.modules.positions.models import Position
from app.modules.positions.router import (
    _resolve_or_create_department,
    create_position,
    update_position,
)
from app.modules.positions.schemas import PositionCreate, PositionUpdate


class _ScalarRows:
    def __init__(self, rows: list[Department]) -> None:
        self._rows = rows

    def all(self) -> list[Department]:
        return self._rows


def _db_with_name_matches(rows: list[Department]) -> SimpleNamespace:
    return SimpleNamespace(
        scalars=AsyncMock(return_value=_ScalarRows(rows)),
        scalar=AsyncMock(),
        add=MagicMock(),
        flush=AsyncMock(),
    )


def _unit(tenant_id, *, name: str = "Учебный отдел", active: bool = True) -> Department:
    return Department(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        slug=f"branch--training--{str(uuid4())[:8]}",
        normalized_name=name.casefold(),
        is_active=active,
        archived_at=None if active else object(),
        legacy_root=False,
        description="",
    )


def _position(tenant_id, department: Department) -> Position:
    return Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Учебный специалист",
        department_id=department.id,
        department=department.name,
        level="junior",
        responsibilities="",
        requirements="",
        employee_count=0,
    )


def _route_db(*, scalar_result=None) -> SimpleNamespace:
    return SimpleNamespace(
        scalar=AsyncMock(return_value=scalar_result),
        scalars=AsyncMock(),
        add=MagicMock(),
        flush=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_legacy_name_reuses_one_nested_canonical_unit() -> None:
    tenant_id = uuid4()
    nested = _unit(tenant_id)
    db = _db_with_name_matches([nested])

    resolved = await _resolve_or_create_department(db, tenant_id, "  Учебный отдел  ")

    assert resolved is nested
    statement = db.scalars.await_args.args[0].compile(dialect=postgresql.dialect())
    assert "FOR UPDATE OF departments" in str(statement)
    assert "ORDER BY departments.id" in str(statement)
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_legacy_name_creates_nothing() -> None:
    tenant_id = uuid4()
    db = _db_with_name_matches([_unit(tenant_id), _unit(tenant_id)])

    with pytest.raises(HTTPException) as error:
        await _resolve_or_create_department(db, tenant_id, "Учебный отдел")

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "department_selection_required"
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_unit_id_selects_exact_tenant_owned_unit() -> None:
    tenant_id = uuid4()
    nested = _unit(tenant_id)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=nested),
        scalars=AsyncMock(),
        add=MagicMock(),
        flush=AsyncMock(),
    )

    resolved = await _resolve_or_create_department(
        db,
        tenant_id,
        "ignored legacy name",
        department_id=nested.id,
    )

    assert resolved is nested
    statement = db.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "departments.id" in sql
    assert "departments.tenant_id" in sql
    assert nested.id in statement.params.values()
    assert tenant_id in statement.params.values()
    assert "FOR UPDATE OF departments" in sql
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_unit_id_rejects_cross_tenant_or_missing_unit() -> None:
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        scalars=AsyncMock(),
        add=MagicMock(),
        flush=AsyncMock(),
    )

    with pytest.raises(HTTPException) as error:
        await _resolve_or_create_department(
            db,
            uuid4(),
            department_id=uuid4(),
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "organization_unit_not_found"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_unit_id_rejects_archived_unit() -> None:
    tenant_id = uuid4()
    archived = _unit(tenant_id, active=False)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=archived),
        scalars=AsyncMock(),
        add=MagicMock(),
        flush=AsyncMock(),
    )

    with pytest.raises(HTTPException) as error:
        await _resolve_or_create_department(
            db,
            tenant_id,
            department_id=archived.id,
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "organization_unit_inactive"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_unique_new_legacy_name_still_creates_compatibility_unit() -> None:
    tenant_id = uuid4()
    db = _db_with_name_matches([])

    resolved = await _resolve_or_create_department(db, tenant_id, "  New Legacy Unit  ")

    assert resolved is db.add.call_args.args[0]
    assert resolved.tenant_id == tenant_id
    assert resolved.name == "New Legacy Unit"
    assert resolved.normalized_name == "new legacy unit"
    db.flush.assert_awaited_once()


def test_position_write_contract_accepts_department_uuid() -> None:
    department_id = uuid4()

    assert PositionCreate(name="Role", department_id=department_id).department_id == department_id
    assert PositionUpdate(department_id=department_id).model_dump(exclude_unset=True) == {
        "department_id": department_id,
    }


@pytest.mark.asyncio
async def test_create_explicit_null_department_id_ignores_stale_legacy_name(monkeypatch) -> None:
    tenant_id = uuid4()
    db = _route_db()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    response = AsyncMock(side_effect=lambda _db, position, **_kwargs: position)
    monkeypatch.setattr(router, "_position_response", response)

    created = await create_position(
        PositionCreate(
            name="Учебный специалист",
            department_id=None,
            department="Устаревший отдел",
        ),
        db=db,
        user=user,
    )

    assert created.department_id is None
    assert created.department == ""
    db.scalar.assert_not_awaited()
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_explicit_department_id_overrides_stale_legacy_name(monkeypatch) -> None:
    tenant_id = uuid4()
    selected_department = _unit(tenant_id, name="Выбранный отдел")
    db = _route_db(scalar_result=selected_department)
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    monkeypatch.setattr(
        router,
        "_position_response",
        AsyncMock(side_effect=lambda _db, position, **_kwargs: position),
    )

    created = await create_position(
        PositionCreate(
            name="Учебный специалист",
            department_id=selected_department.id,
            department="Устаревший отдел",
        ),
        db=db,
        user=user,
    )

    assert created.department_id == selected_department.id
    assert created.department == selected_department.name
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_explicit_department_id_rejects_cross_tenant_unit(monkeypatch) -> None:
    db = _route_db(scalar_result=None)
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    monkeypatch.setattr(router, "_position_response", AsyncMock())

    with pytest.raises(HTTPException) as error:
        await create_position(
            PositionCreate(name="Учебный специалист", department_id=uuid4()),
            db=db,
            user=user,
        )

    assert error.value.status_code == 422
    assert error.value.detail == {"code": "organization_unit_not_found"}
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_update_explicit_null_department_id_clears_stale_legacy_name(monkeypatch) -> None:
    tenant_id = uuid4()
    old_department = _unit(tenant_id, name="Старый отдел")
    position = _position(tenant_id, old_department)
    db = _route_db()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    monkeypatch.setattr(
        router.qualification_service,
        "prepare_external_change",
        AsyncMock(return_value=position),
    )
    monkeypatch.setattr(
        router.qualification_service,
        "record_external_change",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router,
        "_position_response",
        AsyncMock(side_effect=lambda _db, row, **_kwargs: row),
    )

    updated = await update_position(
        position.id,
        PositionUpdate(department_id=None, department="Устаревший отдел"),
        db=db,
        user=user,
    )

    assert updated.department_id is None
    assert updated.department == ""
    db.scalar.assert_not_awaited()
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_explicit_department_id_overrides_stale_legacy_name(monkeypatch) -> None:
    tenant_id = uuid4()
    old_department = _unit(tenant_id, name="Старый отдел")
    selected_department = _unit(tenant_id, name="Выбранный отдел")
    position = _position(tenant_id, old_department)
    db = _route_db(scalar_result=selected_department)
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    monkeypatch.setattr(
        router.qualification_service,
        "prepare_external_change",
        AsyncMock(return_value=position),
    )
    monkeypatch.setattr(
        router.qualification_service,
        "record_external_change",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router,
        "_position_response",
        AsyncMock(side_effect=lambda _db, row, **_kwargs: row),
    )

    updated = await update_position(
        position.id,
        PositionUpdate(
            department_id=selected_department.id,
            department="Устаревший отдел",
        ),
        db=db,
        user=user,
    )

    assert updated.department_id == selected_department.id
    assert updated.department == selected_department.name
    db.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_explicit_department_id_rejects_archived_unit(monkeypatch) -> None:
    tenant_id = uuid4()
    old_department = _unit(tenant_id, name="Старый отдел")
    archived_department = _unit(tenant_id, name="Архивный отдел", active=False)
    position = _position(tenant_id, old_department)
    db = _route_db(scalar_result=archived_department)
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    monkeypatch.setattr(
        router.qualification_service,
        "prepare_external_change",
        AsyncMock(return_value=position),
    )
    monkeypatch.setattr(
        router.qualification_service,
        "record_external_change",
        AsyncMock(),
    )
    monkeypatch.setattr(router, "_position_response", AsyncMock())

    with pytest.raises(HTTPException) as error:
        await update_position(
            position.id,
            PositionUpdate(department_id=archived_department.id),
            db=db,
            user=user,
        )

    assert error.value.status_code == 422
    assert error.value.detail == {"code": "organization_unit_inactive"}
    assert position.department_id == old_department.id
    assert position.department == old_department.name
    router.qualification_service.record_external_change.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_omitted_department_fields_preserves_existing_unit(monkeypatch) -> None:
    tenant_id = uuid4()
    department = _unit(tenant_id)
    position = _position(tenant_id, department)
    db = _route_db()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    monkeypatch.setattr(
        router.qualification_service,
        "prepare_external_change",
        AsyncMock(return_value=position),
    )
    monkeypatch.setattr(
        router.qualification_service,
        "record_external_change",
        AsyncMock(),
    )
    monkeypatch.setattr(
        router,
        "_position_response",
        AsyncMock(side_effect=lambda _db, row, **_kwargs: row),
    )

    updated = await update_position(
        position.id,
        PositionUpdate(level="middle"),
        db=db,
        user=user,
    )

    assert updated.department_id == department.id
    assert updated.department == department.name
    assert updated.level == "middle"
    db.scalar.assert_not_awaited()
    db.scalars.assert_not_awaited()
