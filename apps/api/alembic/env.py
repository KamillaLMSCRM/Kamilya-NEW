"""Alembic env — async SQLAlchemy 2.0.

Sets DATABASE_URL from app settings, runs migrations against the configured
target (Base.metadata). Uses the canonical async pattern:
async_engine_from_config -> async connect -> run_sync(do_run_migrations).

Without run_sync(), alembic's sync API cannot drive an AsyncConnection
(and naive `with connectable.connect()` raises 'AsyncConnection does not
support the context manager protocol').

Offline mode (`alembic upgrade --sql`) still works as before — produces
SQL only, no DB connection.
"""
import asyncio
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.db import Base
from app.core.config import get_settings

config = context.config
if config.config_file_name is not None:
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout/file without connecting to the DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Sync migration runner, invoked via run_sync() inside the async context."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect to the DB asynchronously and drive the sync migration API."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entrypoint for online mode — bridge to the async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
