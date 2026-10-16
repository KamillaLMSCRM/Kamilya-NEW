"""Fixed private DEV TCP relay for the ASUS GLM connector.

The production entry point deliberately has no destination configuration: it
always listens on the approved ASUS address and forwards to the approved GLM
address.  Tests may inject loopback addresses through the constructor.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass


LOG = logging.getLogger("dev_glm_relay")

PRODUCTION_BIND_HOST = "10.77.77.4"
PRODUCTION_BIND_PORT = 18005
PRODUCTION_ALLOWED_SOURCE = "10.77.77.1"
PRODUCTION_UPSTREAM_HOST = "10.66.66.28"
PRODUCTION_UPSTREAM_PORT = 8888
MAX_CONNECTIONS = 4
CONNECT_TIMEOUT_SECONDS = 5.0
TOTAL_TIMEOUT_SECONDS = 120.0
MAX_DIRECTION_BYTES = 4 * 1024 * 1024
BUFFER_SIZE = 64 * 1024


@dataclass(frozen=True)
class RelayConfig:
    """Relay limits and endpoints.

    The defaults are the fixed production values.  A caller can supply values
    only to an explicitly constructed in-process test relay; ``main`` never
    reads them from argv or the environment.
    """

    bind_host: str = PRODUCTION_BIND_HOST
    bind_port: int = PRODUCTION_BIND_PORT
    allowed_source: str = PRODUCTION_ALLOWED_SOURCE
    upstream_host: str = PRODUCTION_UPSTREAM_HOST
    upstream_port: int = PRODUCTION_UPSTREAM_PORT
    max_connections: int = MAX_CONNECTIONS
    connect_timeout: float = CONNECT_TIMEOUT_SECONDS
    total_timeout: float = TOTAL_TIMEOUT_SECONDS
    max_direction_bytes: int = MAX_DIRECTION_BYTES
    buffer_size: int = BUFFER_SIZE


class GLMRelay:
    """Bounded, source-restricted TCP relay."""

    def __init__(self, config: RelayConfig | None = None) -> None:
        self.config = config or RelayConfig()
        if self.config.max_connections < 1 or self.config.buffer_size < 1:
            raise ValueError("relay limits must be positive")
        if self.config.max_direction_bytes < 1:
            raise ValueError("direction limit must be positive")
        self._capacity = asyncio.BoundedSemaphore(self.config.max_connections)
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def server(self) -> asyncio.AbstractServer | None:
        return self._server

    @property
    def sockets(self) -> tuple[asyncio.BaseTransport, ...]:
        if self._server is None:
            return ()
        return tuple(self._server.sockets or ())

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._accept,
            host=self.config.bind_host,
            port=self.config.bind_port,
            limit=self.config.buffer_size,
        )
        LOG.info("relay_started")

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        LOG.info("relay_stopped")

    def _track(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _accept(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        peer = client_writer.get_extra_info("peername")
        source = peer[0] if isinstance(peer, tuple) and peer else None
        if source != self.config.allowed_source:
            LOG.info("connection_rejected_source")
            await self._close_writer(client_writer)
            return
        if not self._capacity.locked():
            await self._capacity.acquire()
            task = asyncio.create_task(self._handle(client_reader, client_writer))
            self._track(task)
            return
        LOG.info("connection_rejected_capacity")
        await self._close_writer(client_writer)

    async def _handle(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        deadline = asyncio.get_running_loop().time() + self.config.total_timeout
        try:
            try:
                connect_timeout = min(
                    self.config.connect_timeout,
                    max(0.0, deadline - asyncio.get_running_loop().time()),
                )
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self.config.upstream_host, self.config.upstream_port
                    ),
                    timeout=connect_timeout,
                )
            except (OSError, asyncio.TimeoutError):
                LOG.info("upstream_connect_failed")
                return
            proxy_timeout = max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.wait_for(
                self._proxy(
                    client_reader, client_writer, upstream_reader, upstream_writer
                ),
                timeout=proxy_timeout,
            )
        except asyncio.CancelledError:
            raise
        except (OSError, asyncio.TimeoutError, ValueError):
            LOG.info("connection_closed")
        finally:
            await self._close_writer(upstream_writer)
            await self._close_writer(client_writer)
            self._capacity.release()

    async def _proxy(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        upstream_reader: asyncio.StreamReader,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        pumps = {
            asyncio.create_task(self._pump(client_reader, upstream_writer)),
            asyncio.create_task(self._pump(upstream_reader, client_writer)),
        }
        try:
            await asyncio.gather(*pumps)
        except BaseException:
            for task in pumps:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            raise

    async def _pump(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        transferred = 0
        while True:
            remaining = self.config.max_direction_bytes - transferred
            chunk = await reader.read(min(self.config.buffer_size, remaining + 1))
            if not chunk:
                with contextlib.suppress(Exception):
                    writer.write_eof()
                    await writer.drain()
                return
            transferred += len(chunk)
            if transferred > self.config.max_direction_bytes:
                raise ValueError("direction_limit")
            writer.write(chunk)
            await writer.drain()

    @staticmethod
    async def _close_writer(writer: asyncio.StreamWriter | None) -> None:
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(OSError, asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), timeout=1.0)


async def run() -> None:
    relay = GLMRelay()
    await relay.start()
    try:
        await asyncio.Event().wait()
    finally:
        await relay.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
