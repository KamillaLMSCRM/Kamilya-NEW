from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

# Pool sizing per AGENTS.md §DB:
#   pool_size = (CPU × 2) + spindle_count
#   Start with 20 (Render starter plan = 0.5 CPU, 2 GB RAM).
#   max_overflow = 10 (allows bursts above pool_size up to 30 connections).
#   pool_pre_ping = True (defends against stale connections after PgBouncer
#     or Supabase connection recycling).
#   pool_recycle = 1800 (recycle connections every 30 min — defensive
#     against firewalls dropping idle TCP, and matches Supabase's
#     pooler-side timeout for free-tier projects).
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)
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
