"""Read-only Supabase reproduction of delivery across distinct Celery event loops."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))


class EmptyStore:
    def __init__(self, db):
        self.db = db

    async def claim(self, **kwargs):
        return None


def main():
    if "--execute" not in sys.argv:
        print('{"status":"READY","database_writes":0,"provider_calls":0}')
        return 0
    values = dotenv_values(ROOT / ".env")
    url = normalize_database_url(values.get("DATABASE_URL") or "")
    if not same_supabase_project(url, values.get("SUPABASE_URL") or "") or (make_url(url).username or "").split(".")[0] != "lms_app":
        raise RuntimeError("canonical_dev_identity")
    # Do not load production/provider secrets into this read-only fixture.
    from app.modules.learning_reminders.tasks import deliver

    settings = SimpleNamespace(LEARNING_REMINDERS_ENABLED=True, DATABASE_URL=url)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.CRITICAL)
    engine = create_async_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=False, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    loops = [asyncio.new_event_loop() for _ in range(3)]
    first_loop = loops[0]
    statuses = []
    failure = None
    try:
        for loop in loops:
            kwargs = {"settings_factory": lambda: settings, "store_factory": EmptyStore}
            if "--baseline" in sys.argv:
                kwargs["session_factory"] = factory
            try:
                result = loop.run_until_complete(deliver(UUID(int=101), UUID(int=102), **kwargs))
                assert result == {"status": "skipped"}
                statuses.append("skipped")
            except Exception as exc:
                message = str(exc)
                failure = "cross_loop" if "different loop" in message or "another loop" in message or "Event loop is closed" in message else type(exc).__name__
                break
    finally:
        first_loop.run_until_complete(engine.dispose())
        for loop in loops:
            loop.close()
    baseline = "--baseline" in sys.argv
    passed = (failure == "cross_loop" and len(statuses) == 1) if baseline else (failure is None and len(statuses) == 3)
    print(json.dumps({"status": "PASS" if passed else "FAIL", "baseline": baseline, "successful_distinct_loops": len(statuses), "failure": failure, "database_writes": 0, "provider_calls": 0}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
