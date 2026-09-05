from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.pool import NullPool

from app.modules.learning_reminders import tasks
from app.modules.learning_reminders.tasks import deliver

TENANT_ID = UUID("00000000-0000-0000-0000-000000000201")
REMINDER_ID = UUID("00000000-0000-0000-0000-000000000202")


def reminder_settings(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        LEARNING_REMINDERS_ENABLED=enabled,
        DATABASE_URL="postgresql+asyncpg://synthetic.invalid/db",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="synthetic-key",
        PUBLIC_URL="https://app.example.test",
    )


class FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


class FakeSession:
    def __init__(self, *, enter_error: Exception | None = None) -> None:
        self.db = FakeDb()
        self.enter_error = enter_error

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self.db

    async def __aexit__(self, *_args) -> None:
        return None


class FakeDb:
    async def execute(self, *_args, **_kwargs) -> None:
        return None


class FakeStore:
    def __init__(self, db) -> None:
        self.db = db

    async def claim(self, **_kwargs):
        return None


def _install_engine_mocks(monkeypatch, *, session: FakeSession):
    engines: list[FakeEngine] = []
    session_maker_calls: list[tuple[FakeEngine, dict[str, object]]] = []

    def fake_create_async_engine(url: str, **kwargs):
        engine = FakeEngine()
        engines.append(engine)
        assert url == reminder_settings().DATABASE_URL
        assert kwargs == {"poolclass": NullPool}
        return engine

    def fake_async_sessionmaker(engine, **kwargs):
        session_maker_calls.append((engine, kwargs))
        return lambda: session

    monkeypatch.setattr(tasks, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(tasks, "async_sessionmaker", fake_async_sessionmaker)
    return engines, session_maker_calls


def _run_default_delivery(settings_factory, *, store_factory=None):
    return asyncio.run(
        deliver(
            TENANT_ID,
            REMINDER_ID,
            settings_factory=settings_factory,
            store_factory=store_factory or (lambda db: FakeStore(db)),
        )
    )


def test_default_delivery_uses_a_new_nullpool_engine_and_disposes_each_call(monkeypatch):
    engines, session_maker_calls = _install_engine_mocks(monkeypatch, session=FakeSession())

    assert _run_default_delivery(reminder_settings) == {"status": "skipped"}
    assert _run_default_delivery(reminder_settings) == {"status": "skipped"}

    assert len(engines) == 2
    assert engines[0] is not engines[1]
    assert [engine.dispose_calls for engine in engines] == [1, 1]
    assert [kwargs for _engine, kwargs in session_maker_calls] == [{"expire_on_commit": False}] * 2


def test_default_delivery_disposes_engine_when_session_fails(monkeypatch):
    engines, _session_maker_calls = _install_engine_mocks(
        monkeypatch, session=FakeSession(enter_error=RuntimeError("synthetic session failure"))
    )

    with pytest.raises(RuntimeError, match="synthetic session failure"):
        _run_default_delivery(reminder_settings)

    assert len(engines) == 1
    assert engines[0].dispose_calls == 1


def test_disabled_delivery_does_not_construct_or_dispose_an_engine(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled delivery must not construct an engine")

    monkeypatch.setattr(tasks, "create_async_engine", forbidden)

    assert _run_default_delivery(lambda: reminder_settings(enabled=False)) == {"status": "disabled"}


def test_injected_session_factory_is_caller_owned(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("injected delivery must not construct an engine")

    monkeypatch.setattr(tasks, "create_async_engine", forbidden)
    session = FakeSession()

    result = asyncio.run(
        deliver(
            TENANT_ID,
            REMINDER_ID,
            session_factory=lambda: session,
            settings_factory=reminder_settings,
            store_factory=lambda db: FakeStore(db),
        )
    )

    assert result == {"status": "skipped"}
