"""Exact permanent-QA revision assertions, no network or business mutations."""

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext import asyncio as sqlalchemy_asyncio

from scripts.ops import kb_rag_isolated_dev_gate as canonical


@pytest.fixture
def stand():
    path = Path(__file__).resolve().parents[2] / "scripts/ops/dev_qa_stand.py"
    spec = importlib.util.spec_from_file_location("qa_staged_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("expected,actual,passes", [("0168", "0168", True), ("0169", "0169", True), ("0172", "0172", True), ("0172", "0169", False)])
async def test_only_exact_packet_revision_is_verified(stand, monkeypatch, expected, actual, passes):
    role = SimpleNamespace(one=lambda: SimpleNamespace(rolsuper=False, rolbypassrls=False))
    revision = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [actual]))
    conn = SimpleNamespace(execute=AsyncMock(side_effect=[None, role, revision]))
    @asynccontextmanager
    async def connection():
        yield conn
    @asynccontextmanager
    async def begin():
        yield None
    conn.begin = begin
    engine = SimpleNamespace(connect=connection, dispose=AsyncMock())
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(canonical, "normalize_database_url", lambda _: "postgresql+asyncpg://lms_app@synthetic.invalid/postgres")
    monkeypatch.setattr(canonical, "same_supabase_project", lambda *args: True)
    if passes:
        await stand.database_readback({}, expected_revision=expected)
    else:
        with pytest.raises(stand.StandError, match="dev_schema_revision_mismatch"):
            await stand.database_readback({}, expected_revision=expected)
    engine.dispose.assert_awaited_once()
    assert str(conn.execute.await_args_list[0].args[0]) == "SET TRANSACTION READ ONLY"
    assert conn.execute.await_count == 3


@pytest.mark.asyncio
async def test_unknown_revision_rejected_before_engine(stand, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("engine created for unknown revision")
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", forbidden)
    with pytest.raises(stand.StandError, match="unsupported_qa_schema_revision"):
        await stand.database_readback({}, expected_revision="0171")
