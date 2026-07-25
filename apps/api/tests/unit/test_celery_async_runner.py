"""Celery async runner lifecycle contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_async_runner_disposes_database_engine_between_event_loops(monkeypatch):
    from app.core import db
    from app.modules.ai import tasks

    dispose = AsyncMock()
    monkeypatch.setattr(db, "engine", SimpleNamespace(dispose=dispose))
    observed_loops: list[asyncio.AbstractEventLoop] = []

    async def probe(value: int) -> int:
        observed_loops.append(asyncio.get_running_loop())
        return value

    assert tasks._run_async(probe(1)) == 1
    assert tasks._run_async(probe(2)) == 2
    assert observed_loops[0] is not observed_loops[1]
    assert dispose.await_count == 2
