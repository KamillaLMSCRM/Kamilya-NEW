"""Pytest configuration for the API.

Provides:
  - `db_session` (function-scoped): async SQLAlchemy session wrapped in a
    transaction that is rolled back at test teardown. Each test sees a clean
    DB without paying the cost of TRUNCATE between tests.
  - `client` (function-scoped): FastAPI TestClient bound to the same session.
  - `make_tenant`, `make_user`, `make_course`, `make_module`, `make_lesson`,
    `make_quiz`, `make_document`: factory functions that build and persist
    ORM objects with sensible defaults, returning the instance.

These fixtures are intentionally minimal — they build rows in code (not via
HTTP) so cross-tenant tests can assert that an *unauthenticated* or
*wrong-tenant* user never reaches a tenant's data. HTTP-driven factories can
be added later if integration flows need them.
"""

from __future__ import annotations

import os
from typing import AsyncIterator, Callable
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Settings override — must run BEFORE app imports so Pydantic Settings
# load the test DATABASE_URL / JWT_SECRET at import time.
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://lms:lms_test_password@localhost:5432/kamilya_lms_test")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_for_ci_only_min_length_32")
os.environ.setdefault("JWT_AUDIENCE", "kamilya-lms")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-telegram-webhook-secret")
os.environ.setdefault("PROVIDER_KEY_ENCRYPTION_KEY", "ZGV2X2tleV9tdXN0X2JlXzMyX2J5dGVzX2xvbmc=")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", "ZGV2X2tleV9tdXN0X2JlXzMyX2J5dGVzX2xvbmc=")


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncIterator[AsyncSession]:
    """Function-scoped async session, isolated by outer-transaction rollback.

    Pattern from SQLAlchemy docs: open a connection, begin a transaction,
    bind the session to that connection, yield, then rollback/close.
    Any commit() inside the test becomes a savepoint — visible to the test
    but discarded at teardown so other tests never see it.
    """
    from app.core.db import async_session_factory, engine

    async with engine.connect() as connection:
        await connection.begin()
        async with async_session_factory(
            bind=connection,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session
        await connection.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """FastAPI AsyncClient wired to the same transactional session.

    Overrides the `get_db` dependency so endpoints see the rolled-back-on-
    teardown session rather than spinning up a new one.
    """
    from app.core.db import get_db
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# Factories
# ===========================================================================
# Each factory takes an explicit `db` session and optional overrides.
# Returns the persisted ORM instance with `id` populated.


@pytest_asyncio.fixture
def make_tenant(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_tenant(name=..., slug=..., is_demo=False) -> Tenant."""
    from app.models.tenants import Tenant

    async def _factory(name: str = "Test Tenant", slug: str | None = None, **overrides) -> Tenant:
        tenant = Tenant(
            id=overrides.get("id", uuid4()),
            name=name,
            slug=slug or f"t-{uuid4().hex[:8]}",
            status=overrides.get("status", "active"),
            plan=overrides.get("plan", "free"),
            is_demo=overrides.get("is_demo", False),
            settings=overrides.get("settings", {}),
        )
        db_session.add(tenant)
        await db_session.flush()
        return tenant

    return _factory


@pytest_asyncio.fixture
def make_user(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_user(tenant, role='student', email=...) -> User.

    Default password is 'Password123!'. Use `password_hash=` to override.
    """
    from argon2 import PasswordHasher
    from app.models.users import User

    ph = PasswordHasher()

    async def _factory(
        tenant: "any",
        role: str = "student",
        email: str | None = None,
        first_name: str = "Test",
        last_name: str = "User",
        password: str | None = None,
        **overrides,
    ) -> User:
        user = User(
            id=overrides.get("id", uuid4()),
            tenant_id=tenant.id,
            email=email or f"{role}-{uuid4().hex[:8]}@{tenant.slug}.example",
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=overrides.get("is_active", True),
            password_hash=ph.hash(password) if password else ph.hash("Password123!"),
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _factory


@pytest_asyncio.fixture
def make_superadmin(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory for platform superadmin (tenant_id=None)."""
    from argon2 import PasswordHasher
    from app.models.users import User

    ph = PasswordHasher()

    async def _factory(email: str | None = None, **overrides) -> User:
        user = User(
            id=overrides.get("id", uuid4()),
            tenant_id=None,  # superadmin does NOT belong to any tenant
            email=email or f"superadmin-{uuid4().hex[:8]}@kml.kz",
            first_name="Super",
            last_name="Admin",
            role="superadmin",
            is_active=True,
            password_hash=ph.hash("SuperPass123!"),
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _factory


@pytest_asyncio.fixture
def make_course(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_course(tenant, creator, title=...) -> Course."""
    from app.models.courses import Course

    async def _factory(
        tenant: "any",
        creator: "any",
        title: str = "Test Course",
        **overrides,
    ) -> Course:
        course = Course(
            id=overrides.get("id", uuid4()),
            tenant_id=tenant.id,
            title=title,
            description=overrides.get("description", ""),
            status=overrides.get("status", "draft"),
            created_by=creator.id,
            delivery_type=overrides.get("delivery_type", "native"),
            ai_generated=overrides.get("ai_generated", False),
            review_status=overrides.get("review_status", "pending"),
        )
        db_session.add(course)
        await db_session.flush()
        return course

    return _factory


@pytest_asyncio.fixture
def make_module(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_module(course, title=...) -> Module.

    Module lives in app.modules.lessons.models (not app.models.courses).
    """
    from app.modules.lessons.models import Module

    async def _factory(course: "any", title: str = "Test Module", **overrides) -> "Module":
        mod = Module(
            id=overrides.get("id", uuid4()),
            tenant_id=course.tenant_id,
            course_id=course.id,
            title=title,
            description=overrides.get("description", ""),
            order_index=overrides.get("order_index", 0),
        )
        db_session.add(mod)
        await db_session.flush()
        return mod

    return _factory


@pytest_asyncio.fixture
def make_lesson(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_lesson(module, title=...) -> Lesson."""
    from app.modules.lessons.models import Lesson

    async def _factory(module: "any", title: str = "Test Lesson", **overrides) -> "Lesson":
        lesson = Lesson(
            id=overrides.get("id", uuid4()),
            tenant_id=module.tenant_id,
            module_id=module.id,
            title=title,
            content_type=overrides.get("content_type", "text"),
            content=overrides.get("content", "Lesson body."),
            order_index=overrides.get("order_index", 0),
        )
        db_session.add(lesson)
        await db_session.flush()
        return lesson

    return _factory


@pytest_asyncio.fixture
def make_quiz(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_quiz(lesson, title=...) -> Quiz.

    Uses pass_score (the real column name) — Quiz has lesson_id directly,
    not module_id, so the lesson reference is sufficient.
    """
    from app.modules.quizzes.models import Quiz

    async def _factory(lesson: "any", title: str = "Test Quiz", **overrides) -> "Quiz":
        quiz = Quiz(
            id=overrides.get("id", uuid4()),
            tenant_id=lesson.tenant_id,
            lesson_id=lesson.id,
            title=title,
            pass_score=overrides.get("pass_score", 80),
            time_limit=overrides.get("time_limit", None),
            attempt_limit=overrides.get("attempt_limit", 3),
            deferral_days=overrides.get("deferral_days", 7),
        )
        db_session.add(quiz)
        await db_session.flush()
        return quiz

    return _factory


@pytest_asyncio.fixture
def make_document(db_session: AsyncSession) -> Callable[..., "any"]:
    """Return an async factory: make_document(tenant, uploader, name=...) -> Document.

    Document lives in app.models.document. Real columns: title, filename,
    content_type, size (column name `file_size`), s3_key (not storage_key).
    """
    from app.models.document import Document

    async def _factory(
        tenant: "any",
        uploader: "any",
        name: str = "test.md",
        title: str | None = None,
        **overrides,
    ) -> "Document":
        doc = Document(
            id=overrides.get("id", uuid4()),
            tenant_id=tenant.id,
            uploaded_by=uploader.id,
            title=title or name,
            filename=name,
            content_type=overrides.get("content_type", "text/markdown"),
            size=overrides.get("size_bytes", overrides.get("size", 1024)),
            s3_key=overrides.get("s3_key", f"tenants/{tenant.id}/{uuid4()}"),
            embedding_status=overrides.get("embedding_status", "pending"),
        )
        db_session.add(doc)
        await db_session.flush()
        return doc

    return _factory


# ===========================================================================
# Auth helpers — issue real tokens so tests hit authenticated paths.
# ===========================================================================


def make_access_token(
    user_id: UUID | str,
    tenant_id: UUID | str | None,
    role: str = "student",
    audience: str = "kamilya-lms",
    expires_minutes: int = 60,
) -> str:
    """Issue a real HS256 access token signed with the test JWT_SECRET.

    Uses the same `create_access_token` helper the app uses in production so
    signature, audience, and algorithm are identical to real flows.
    """
    from app.core.auth import create_access_token
    from datetime import timedelta

    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "roles": [role],
        "aud": audience,
    }
    return create_access_token(payload, expires_delta=timedelta(minutes=expires_minutes))


@pytest_asyncio.fixture
def auth_headers():
    """Return a function auth_headers(user) -> dict that produces a Bearer header.

    Usage:
        async def test_x(client, auth_headers, make_user, make_tenant):
            tenant = await make_tenant()
            user = await make_user(tenant, role="admin")
            r = await client.get("/api/v1/admin/...", headers=auth_headers(user))
    """

    def _make(user: "any") -> dict[str, str]:
        token = make_access_token(user.id, user.tenant_id, role=user.role)
        return {"Authorization": f"Bearer {token}"}

    return _make
