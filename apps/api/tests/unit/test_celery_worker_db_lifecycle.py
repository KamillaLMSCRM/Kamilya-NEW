"""Celery worker database lifecycle contracts."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _pooled_engine() -> AsyncEngine:
    return create_async_engine(
        "postgresql+asyncpg://worker-lifecycle.invalid/kamilya",
        pool_size=1,
        max_overflow=0,
    )


def test_importing_celery_app_does_not_replace_the_api_database_engine():
    from app.core import db

    api_engine = db.engine

    from app.core import celery_app  # noqa: F401

    assert db.engine is api_engine


def test_worker_init_rebinds_the_existing_session_factory_to_nullpool(monkeypatch):
    from app.core import celery_app, db

    api_engine = _pooled_engine()
    api_pool = api_engine.sync_engine.pool
    shared_factory = async_sessionmaker(api_engine, expire_on_commit=False)
    original_base = db.Base
    monkeypatch.setattr(db, "engine", api_engine)
    monkeypatch.setattr(db, "async_session_factory", shared_factory)

    worker_engine = celery_app._configure_worker_database()

    assert worker_engine is db.engine
    assert worker_engine is not api_engine
    assert worker_engine.url == api_engine.url
    assert isinstance(worker_engine.sync_engine.pool, NullPool)
    assert api_engine.sync_engine.pool is not api_pool
    assert db.async_session_factory is shared_factory
    assert shared_factory.kw["bind"] is worker_engine
    assert db.Base is original_base


def test_worker_init_is_idempotent_and_prefork_reset_preserves_model_base(monkeypatch):
    from app.core import celery_app, db

    api_engine = _pooled_engine()
    shared_factory = async_sessionmaker(api_engine, expire_on_commit=False)
    original_base = db.Base
    monkeypatch.setattr(db, "engine", api_engine)
    monkeypatch.setattr(db, "async_session_factory", shared_factory)

    first = celery_app._configure_worker_database()
    second = celery_app._configure_worker_database()
    celery_app._reset_db_engine_after_fork()

    assert second is first
    assert db.engine is first
    assert db.async_session_factory is shared_factory
    assert shared_factory.kw["bind"] is first
    assert isinstance(first.sync_engine.pool, NullPool)
    assert db.Base is original_base
