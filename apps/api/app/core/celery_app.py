"""Celery app configuration"""
import ssl
import os

from celery import Celery
from celery.signals import worker_process_init
from app.core.config import get_settings

settings = get_settings()


def _redis_ssl_options() -> dict[str, object] | None:
    """Build Celery TLS options from the Redis URL and explicit policy.

    Production should keep certificate verification enabled.  The opt-out is
    reserved for a transitional self-signed certificate on a private VPS;
    it still encrypts the connection but must be replaced with a public CA
    certificate before treating the endpoint as a permanent public service.
    """
    if not str(settings.REDIS_URL).startswith("rediss://"):
        return None
    verify = os.getenv("REDIS_TLS_VERIFY", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return {"ssl_cert_reqs": ssl.CERT_REQUIRED if verify else ssl.CERT_NONE}


_redis_ssl_options = _redis_ssl_options()

celery_app = Celery(
    "kamilya_lms",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.modules.ai.tasks",
        "app.modules.positions.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=600,
    # Upstash uses rediss:// — Celery 5.6+ requires explicit ssl options
    # for the redis broker/backend when REDIS_URL starts with rediss://.
    # Pass ssl.CERT_REQUIRED as the int value (don't pass the string
    # "CERT_REQUIRED" — redis-py 5.x rejects it with
    # "Invalid SSL Certificate Requirements Flag: CERT_REQUIRED").
    broker_use_ssl=_redis_ssl_options,
    redis_backend_use_ssl=_redis_ssl_options,
)


@worker_process_init.connect
def _reset_db_engine_after_fork(**kwargs) -> None:
    """Discard the module-level async SQLAlchemy engine after fork().

    The async engine in app.core.db is created at import time on the
    parent process's event loop. After Celery prefork spawns children,
    the inherited pool references a loop that the child does NOT own —
    any await on a connection from that pool raises
    "got Future attached to a different loop" the moment the task
    schedules an async operation on the child's loop.

    Disposing the inherited pool is sufficient: SQLAlchemy recreates
    connections lazily on the child's event loop, while keeping the
    declarative model registry shared by all imported model modules.

    Same treatment for Redis, which Celery itself manages — but
    app-level redis clients (e.g. rate_limit) might cache a connection.
    """
    try:
        from app.core import db as _db

        # dispose() closes any open connections from the parent; the
        # pool will be rebuilt lazily on first acquire.
        if getattr(_db, "engine", None) is not None:
            _db.engine.sync_engine.pool.dispose()  # type: ignore[attr-defined]

        # Keep the existing db module and model registry intact. Reloading
        # app.core.db creates a second declarative Base, which splits model
        # metadata across modules imported before and after the reload. That
        # makes cross-model foreign keys fail during mapper configuration.
    except Exception:
        # If the dispose fails (no DB used, no engine built, etc.),
        # do not crash worker init — the first task may still work
        # if the engine wasn't actually used.
        import logging

        logging.getLogger(__name__).warning(
            "worker_process_init: engine reset failed; continuing", exc_info=True
        )


# When run as `celery ... -P solo` (single-threaded, no fork), the
# engine from app.core.db is reused as-is and the signal above is
# unnecessary. We expose an env flag so `kamilya-worker.service` and
# the same proc with -P prefork both behave correctly.
if os.getenv("CELERY_WORKER_POOL", "solo") == "solo":
    # Solo pool: no fork, no signal work needed. But we still want
    # the engine to be rebuilt on first await because the engine was
    # imported at parent-process startup, before the loop ran.
    pass
