"""Atomic validated operator edits; rollback is another audited revision."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .catalog import BY_KEY, CATALOG, InvalidSettings, effective_values
from .models import RuntimeSettings, RuntimeSettingsHistory


class SettingsConflict(RuntimeError):  # noqa: N818 - module-local policy error
    pass


class SettingsMissing(RuntimeError):  # noqa: N818 - module-local policy error
    pass


class RuntimeSettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _row(self, *, lock: bool = False) -> RuntimeSettings:
        statement = select(RuntimeSettings).where(RuntimeSettings.id == 1).execution_options(populate_existing=True)
        if lock:
            statement = statement.with_for_update()
        row = await self.db.scalar(statement)
        if row is None:
            raise SettingsMissing("runtime_settings_missing")
        return row

    @staticmethod
    def response(row: RuntimeSettings) -> dict[str, Any]:
        values, defaults = effective_values(row.overrides), effective_values({})
        return {"revision": row.revision, "updated_at": row.updated_at, "settings": [
            {"key": spec.key, "label": spec.label, "kind": spec.kind, "value": values[spec.key],
             "default": defaults[spec.key], "overridden": spec.key in row.overrides,
             "minimum": spec.minimum, "maximum": spec.maximum, "choices": spec.choices}
            for spec in CATALOG], "propagation": "next_operation", "cache_seconds": 0}

    async def get(self) -> dict[str, Any]:
        return self.response(await self._row())

    async def history(self) -> list[dict[str, Any]]:
        rows = (await self.db.scalars(select(RuntimeSettingsHistory)
            .order_by(RuntimeSettingsHistory.revision.desc()).limit(100))).all()
        for row in rows:
            effective_values(row.before)
            effective_values(row.after)
        return [{"revision": row.revision, "before": row.before, "after": row.after,
                 "reason": row.reason, "created_at": row.created_at, "actor_id": row.actor_id} for row in rows]

    async def update(self, *, revision: int, changes: dict[str, Any], reason: str, actor_id: UUID) -> dict[str, Any]:
        if set(changes) - BY_KEY.keys():
            raise InvalidSettings("runtime_settings_unknown_key")
        row = await self._row(lock=True)
        overrides = dict(row.overrides)
        for key, value in changes.items():
            if value is None:  # Explicit reset to declared deployment default.
                overrides.pop(key, None)
            else:
                overrides[key] = value
        return await self._write(row, revision, overrides, reason, actor_id)

    async def revert(self, *, revision: int, target_revision: int, reason: str, actor_id: UUID) -> dict[str, Any]:
        row = await self._row(lock=True)
        if target_revision == 1:
            overrides: dict[str, Any] = {}
        else:
            target = await self.db.scalar(select(RuntimeSettingsHistory).where(RuntimeSettingsHistory.revision == target_revision))
            if target is None:
                raise SettingsMissing("runtime_settings_history_missing")
            effective_values(target.after)
            overrides = dict(target.after)
        return await self._write(row, revision, overrides, reason, actor_id)

    async def _write(self, row: RuntimeSettings, expected: int, overrides: dict[str, Any], reason: str, actor_id: UUID) -> dict[str, Any]:
        if row.revision != expected:
            raise SettingsConflict("runtime_settings_revision_conflict")
        if len(reason.strip()) < 3 or len(reason) > 240:
            raise InvalidSettings("runtime_settings_reason_required")
        effective_values(overrides)
        if row.overrides == overrides:
            return self.response(row)
        self.db.add(RuntimeSettingsHistory(revision=row.revision + 1, before=dict(row.overrides),
            after=dict(overrides), reason=reason.strip(), actor_id=actor_id))
        row.overrides = dict(overrides)
        row.revision += 1
        row.updated_by, row.updated_at = actor_id, datetime.now(UTC)
        # Persist state and audit in the SAME transaction; no deferred logging.
        await self.db.flush()
        response = self.response(row)
        await self.db.commit()
        return response
