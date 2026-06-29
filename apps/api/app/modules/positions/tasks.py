"""Celery tasks for course-assignment recompute (B1b).

apply_rules_for_users_task — runs apply_rules_for_users for a list of
user_ids. Used after staff import (auto) and via the explicit
/admin/staff/apply-rules endpoint (manual / retroactive).

Each user is processed in its own try/except so a single failure does
not poison the whole batch. The summary is logged for Celery
inspection and returned as the task result.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Sequence
from uuid import UUID

logger = logging.getLogger(__name__)

try:
    from app.core.celery_app import celery_app
    from app.core.db import async_session_factory
    from app.modules.positions.batch_service import apply_rules_for_users

    @celery_app.task(
        bind=True,
        name="positions.apply_course_rules",
        max_retries=1,
    )
    def apply_rules_for_users_task(
        self,
        user_ids: list[str],
    ) -> dict:
        """Run recompute for the given users in a fresh event loop.

        Each user is processed in its own try/except so a single
        bad row does not fail the whole batch. Failures are
        recorded in the result dict for inspection.

        Event-loop strategy:
          Celery prefork + SQLAlchemy async + asyncio is a known
          pitfall — asyncpg connections get bound to whichever loop
          was current when the engine was imported, and that loop
          is shared across forked child processes. Result:
          "got Future attached to a different loop" when the inner
          async body accesses an ORM relationship (`Position.department`)
          and SQLAlchemy's lazy loader schedules a fetch on the
          engine's loop, NOT on the loop `loop.run_until_complete` is
          driving.

          `asyncio.run()` solves this in 3.7+ — it creates a fresh
          loop, runs the coroutine to completion, then closes the
          loop and binds a fresh one on the next call. Any
          wait_on_future from the runner executes on the same loop
          as the coroutine, so no future-mismatch.

          See docs/LESSONS.md 2026-06-29 "tasks.py async event-loop
          bug" for the full writeup.
        """
        logger.info(
            "apply_rules_for_users_task: starting for %d users", len(user_ids)
        )
        return asyncio.run(_run_apply_rules(user_ids))

    async def _run_apply_rules(user_ids: Sequence[str]) -> dict:
        """Inner async body — kept separate so the Celery task wrapper
        stays a plain sync function. Failures per user are captured
        and returned in the result.
        """
        from app.core.db import async_session_factory

        result: dict = {
            "users_processed": 0,
            "added": 0,
            "removed": 0,
            "skipped_manual": 0,
            "protected_completed": 0,
            "failed_user_ids": [],
            "errors": [],
        }
        async with async_session_factory() as db:
            for raw_id in user_ids:
                try:
                    user_uuid = UUID(raw_id)
                except (TypeError, ValueError):
                    result["errors"].append(f"bad user_id: {raw_id}")
                    continue
                try:
                    outcome = await apply_rules_for_users(db, [user_uuid])
                    result["users_processed"] += outcome.users_processed
                    result["added"] += outcome.added
                    result["removed"] += outcome.removed
                    result["skipped_manual"] += outcome.skipped_manual
                    result["protected_completed"] += outcome.protected_completed
                except Exception as e:
                    logger.exception("apply_rules failed for user %s", raw_id)
                    result["failed_user_ids"].append(raw_id)
                    result["errors"].append(f"{raw_id}: {type(e).__name__}: {e}")
            await db.commit()
        logger.info(
            "apply_rules_for_users_task: users=%d added=%d removed=%d failed=%d",
            result["users_processed"],
            result["added"],
            result["removed"],
            len(result["failed_user_ids"]),
        )
        return result

except ImportError as e:
    # Celery / app imports not available (e.g. running unit tests
    # without the full app context). Define a no-op so the module
    # is importable. The real task is registered when this module
    # is loaded by the worker.
    logger.warning("Celery task registration skipped: %s", e)

    def apply_rules_for_users_task(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError(
            "apply_rules_for_users_task is not registered; "
            "ensure app.core.celery_app is importable"
        )
