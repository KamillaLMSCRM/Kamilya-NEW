from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys

import pytest


MODULE_ROOT = Path(__file__).parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "glm_relay", MODULE_ROOT / "infra" / "dev-private-models" / "glm_relay.py"
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["glm_relay"] = _MODULE
_SPEC.loader.exec_module(_MODULE)
GLMRelay = _MODULE.GLMRelay
PRODUCTION_ALLOWED_SOURCE = _MODULE.PRODUCTION_ALLOWED_SOURCE
PRODUCTION_BIND_HOST = _MODULE.PRODUCTION_BIND_HOST
PRODUCTION_BIND_PORT = _MODULE.PRODUCTION_BIND_PORT
PRODUCTION_UPSTREAM_HOST = _MODULE.PRODUCTION_UPSTREAM_HOST
PRODUCTION_UPSTREAM_PORT = _MODULE.PRODUCTION_UPSTREAM_PORT
RelayConfig = _MODULE.RelayConfig


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    await writer.wait_closed()


@pytest.mark.asyncio
async def test_duplex_forwards_and_closes() -> None:
    async def upstream(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await reader.readexactly(5)
            writer.write(data[::-1])
            await writer.drain()
        finally:
            await _close(writer)

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    relay = GLMRelay(
        RelayConfig(
            bind_host="127.0.0.1",
            bind_port=0,
            allowed_source="127.0.0.1",
            upstream_host="127.0.0.1",
            upstream_port=upstream_port,
        )
    )
    try:
        await relay.start()
        port = relay.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"hello")
        await writer.drain()
        writer.write_eof()
        assert await reader.readexactly(5) == b"olleh"
        await _close(writer)
    finally:
        await relay.close()
        upstream_server.close()
        await upstream_server.wait_closed()


@pytest.mark.asyncio
async def test_rejects_source_when_allowlist_does_not_match() -> None:
    relay = GLMRelay(
        RelayConfig(
            bind_host="127.0.0.1",
            bind_port=0,
            allowed_source="192.0.2.1",
            upstream_host="127.0.0.1",
            upstream_port=1,
        )
    )
    await relay.start()
    try:
        port = relay.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write_eof()
        assert await asyncio.wait_for(reader.read(), timeout=1) == b""
        await asyncio.wait_for(
            asyncio.gather(*tuple(relay._tasks), return_exceptions=True), timeout=1
        )
        assert not relay._tasks
        await _close(writer)
    finally:
        await relay.close()


@pytest.mark.asyncio
async def test_direction_limit_closes_both_sides() -> None:
    async def upstream(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.read()
            writer.write(b"x" * 8)
            await writer.drain()
            await asyncio.sleep(1)
        finally:
            await _close(writer)

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    relay = GLMRelay(
        RelayConfig(
            bind_host="127.0.0.1",
            bind_port=0,
            allowed_source="127.0.0.1",
            upstream_host="127.0.0.1",
            upstream_port=upstream_port,
            max_direction_bytes=4,
            buffer_size=4,
        )
    )
    await relay.start()
    try:
        port = relay.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"go")
        await writer.drain()
        writer.write_eof()
        assert await asyncio.wait_for(reader.read(4), timeout=1) == b"xxxx"
        assert await asyncio.wait_for(reader.read(), timeout=1) == b""
        await asyncio.wait_for(
            asyncio.gather(*tuple(relay._tasks), return_exceptions=True), timeout=1
        )
        await _close(writer)
    finally:
        await relay.close()
        upstream_server.close()
        await upstream_server.wait_closed()


@pytest.mark.asyncio
async def test_request_overflow_closes_connection_and_releases_capacity() -> None:
    release = asyncio.Event()

    async def upstream(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.read()
            release.set()
        finally:
            await _close(writer)

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    relay = GLMRelay(
        RelayConfig(
            bind_host="127.0.0.1", bind_port=0, allowed_source="127.0.0.1",
            upstream_host="127.0.0.1", upstream_port=upstream_port,
            max_direction_bytes=4, buffer_size=4, max_connections=1,
        )
    )
    await relay.start()
    try:
        port = relay.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"12345")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), timeout=1) == b""
        await asyncio.wait_for(release.wait(), timeout=1)
        assert not relay._tasks
    finally:
        await relay.close()
        upstream_server.close()
        await upstream_server.wait_closed()


@pytest.mark.asyncio
async def test_max_connections_rejects_fifth_and_timeout_reaps() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def upstream(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        entered.set()
        try:
            await release.wait()
        finally:
            await _close(writer)

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    relay = GLMRelay(
        RelayConfig(
            bind_host="127.0.0.1", bind_port=0, allowed_source="127.0.0.1",
            upstream_host="127.0.0.1", upstream_port=upstream_port,
            max_connections=4, total_timeout=0.1,
        )
    )
    await relay.start()
    writers: list[asyncio.StreamWriter] = []
    try:
        port = relay.sockets[0].getsockname()[1]
        clients = [await asyncio.open_connection("127.0.0.1", port) for _ in range(5)]
        writers = [writer for _, writer in clients]
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert await asyncio.wait_for(clients[4][0].read(), timeout=1) == b""
        await asyncio.sleep(0.2)
        assert not relay._tasks
    finally:
        release.set()
        for writer in writers:
            await _close(writer)
        await relay.close()
        upstream_server.close()
        await upstream_server.wait_closed()


def test_production_defaults_are_fixed() -> None:
    config = RelayConfig()
    assert (config.bind_host, config.bind_port) == (
        PRODUCTION_BIND_HOST,
        PRODUCTION_BIND_PORT,
    )
    assert (config.allowed_source,) == (PRODUCTION_ALLOWED_SOURCE,)
    assert (config.upstream_host, config.upstream_port) == (
        PRODUCTION_UPSTREAM_HOST,
        PRODUCTION_UPSTREAM_PORT,
    )
    assert config.max_connections == 4
    assert config.connect_timeout == 5.0
    assert config.total_timeout == 120.0
    assert config.max_direction_bytes == 4 * 1024 * 1024
