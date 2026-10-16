"""One fresh immutable DB snapshot per operation, with no mutable process cache."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from .catalog import RuntimeSnapshot, default_snapshot, effective_values

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_scope: ContextVar[RuntimeSnapshot | None] = ContextVar("runtime_settings_snapshot", default=None)


@contextmanager
def runtime_settings_scope(snapshot: RuntimeSnapshot) -> Iterator[RuntimeSnapshot]:
    """Bind one operation's immutable policy; reset even on cancellation/error."""
    token = _scope.set(snapshot)
    try:
        yield snapshot
    finally:
        _scope.reset(token)


class RuntimeSettingsUnavailable(RuntimeError):  # noqa: N818 - module interface name
    pass


async def resolve_runtime_settings(db: AsyncSession | None = None) -> RuntimeSnapshot:
    scoped = _scope.get()
    if scoped is not None:
        return scoped
    from .models import RuntimeSettings

    try:
        statement = select(RuntimeSettings).where(RuntimeSettings.id == 1).execution_options(autoflush=False, populate_existing=True)
        if db is not None:
            # Do not acquire a second pool slot while auth/tenant work holds one.
            # Savepoint contains only this SELECT, never caller commit/rollback.
            connection = await db.connection()
            async with connection.begin_nested():
                row = await db.scalar(statement)
        else:
            from app.core.db import async_session_factory

            async with async_session_factory() as session:
                row = await session.scalar(statement)
        if row is None:
            raise LookupError("runtime_settings_missing")
        snapshot = RuntimeSnapshot(row.revision, effective_values(row.overrides))
        logger.info("runtime_settings.snapshot revision=%s", snapshot.revision)
        return snapshot
    except ProgrammingError as exc:
        # Additive rollout: older schema alone may use declared defaults.
        # Never treat a denied read, invalid row or outage as permission to reset.
        if getattr(exc.orig, "sqlstate", None) == "42P01":
            return default_snapshot()
        logger.error("runtime_settings.read_failed error_type=%s", type(exc).__name__)
    except Exception as exc:
        logger.error("runtime_settings.read_failed error_type=%s", type(exc).__name__)
    raise RuntimeSettingsUnavailable("runtime_settings_unavailable") from None
