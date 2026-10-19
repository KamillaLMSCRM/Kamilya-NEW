"""Platform superadmin only; never expose a generic environment editor."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User

from .catalog import InvalidSettings
from .schemas import SettingsRevert, SettingsUpdate
from .service import RuntimeSettingsService, SettingsConflict, SettingsMissing

router = APIRouter(prefix="/admin/runtime-settings", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]
Superadmin = Annotated[User, Depends(require_role("superadmin"))]


@router.get("")
async def get_settings(user: Superadmin, db: Db) -> dict[str, Any]:
    try:
        return await RuntimeSettingsService(db).get()
    except SettingsMissing as exc:
        raise HTTPException(503, str(exc)) from None
    except InvalidSettings:
        raise HTTPException(503, "runtime_settings_invalid_stored_values") from None
    except SQLAlchemyError:
        raise HTTPException(503, "runtime_settings_unavailable") from None


@router.get("/history")
async def get_history(user: Superadmin, db: Db) -> list[dict[str, Any]]:
    try:
        return await RuntimeSettingsService(db).history()
    except (InvalidSettings, SQLAlchemyError):
        raise HTTPException(503, "runtime_settings_history_unavailable") from None


@router.put("")
async def update_settings(payload: SettingsUpdate, user: Superadmin, db: Db) -> dict[str, Any]:
    try:
        return await RuntimeSettingsService(db).update(**payload.model_dump(), actor_id=cast(UUID, user.id))
    except SettingsConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except SettingsMissing as exc:
        raise HTTPException(503, str(exc)) from None
    except InvalidSettings as exc:
        raise HTTPException(422, str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(503, "runtime_settings_unavailable") from None


@router.post("/revert")
async def revert_settings(payload: SettingsRevert, user: Superadmin, db: Db) -> dict[str, Any]:
    try:
        return await RuntimeSettingsService(db).revert(**payload.model_dump(), actor_id=cast(UUID, user.id))
    except SettingsConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except SettingsMissing as exc:
        raise HTTPException(404, str(exc)) from None
    except InvalidSettings as exc:
        raise HTTPException(422, str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(503, "runtime_settings_unavailable") from None
