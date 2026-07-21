from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

# Production uses the Supabase session pooler, which currently caps this
# service at 15 DB clients. Keep SQLAlchemy below that cap so load spikes queue
# inside the app instead of crashing with asyncpg EMAXCONNSESSION.
engine_options = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
}
if settings.APP_ENV == "test":
    # pytest-asyncio creates a fresh event loop for function-scoped tests.
    # Reusing asyncpg connections across those loops causes false failures.
    engine_options["poolclass"] = NullPool
else:
    engine_options.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )

engine = create_async_engine(settings.DATABASE_URL, **engine_options)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
