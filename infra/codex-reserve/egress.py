"""Fixed-destination ingress and TLS CONNECT egress for the isolated CLI.

No authentication files, request bodies, TLS decryption, arbitrary destinations,
arbitrary HTTP forwarding, host mounts or logs. Publish only ingress port18999,
never CONNECT port18888. Ingress cannot choose its upstream or inspect payloads.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

ALLOWED_HOSTS = frozenset({"chatgpt.com", "auth.openai.com"})
MAX_TUNNEL_BYTES = 20 * 1024 * 1024
# The runner supports up to120s, then up to5s process cleanup plus bounded
# header/body and response delivery. Do not race its classified failure reply.
INGRESS_IDLE_SECONDS = 135
INGRESS_TOTAL_SECONDS = 150


def destination(line: str) -> str:
    method, authority, version = line.split(" ")
    if method != "CONNECT" or version != "HTTP/1.1":
        raise ValueError("destination_denied")
    host, port = authority.split(":")
    if host not in ALLOWED_HOSTS or port != "443":
        raise ValueError("destination_denied")
    return host


async def resolve_public(host: str) -> str:
    if host not in ALLOWED_HOSTS:
        raise ValueError("destination_denied")
    rows = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = [str(row[4][0]) for row in rows]
    if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in addresses):
        raise ValueError("destination_denied")
    # Connect to the already-validated literal, not the name: no second DNS lookup.
    return sorted(addresses, key=lambda address: ipaddress.ip_address(address).version)[0]


class Egress:
    def __init__(self) -> None:
        self.active = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream = None
        pumps = []
        established = False
        self.active += 1
        try:
            if self.active > 8:
                raise ValueError("busy")
            async with asyncio.timeout(5):
                header = await reader.readuntil(b"\r\n\r\n")
                if len(header) > 8192:
                    raise ValueError("header_limit")
                host = destination(header.decode("ascii").split("\r\n")[0])
                address = await resolve_public(host)
                upstream_reader, upstream = await asyncio.open_connection(address, 443)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            established = True
            transferred = 0

            async def pump(source: asyncio.StreamReader, target: asyncio.StreamWriter) -> None:
                nonlocal transferred
                while True:
                    block = await asyncio.wait_for(source.read(65536), timeout=30)
                    if not block:
                        return
                    transferred += len(block)
                    if transferred > MAX_TUNNEL_BYTES:
                        raise ValueError("transfer_limit")
                    target.write(block)
                    await asyncio.wait_for(target.drain(), timeout=5)

            async with asyncio.timeout(120):
                pumps = [asyncio.create_task(pump(reader, upstream)), asyncio.create_task(pump(upstream_reader, writer))]
                done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            if not established:
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                try:
                    await asyncio.wait_for(writer.drain(), timeout=1)
                except (OSError, TimeoutError):
                    pass
        finally:
            for task in pumps:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (upstream, writer):
                if stream is not None:
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except OSError:
                        pass
            self.active -= 1


class Ingress:
    """Blind, bounded private ingress to one fixed authenticated connector.

    Docker cannot publish a port on an internal-only service on all supported
    engines. The mount-free edge owns publication; CLI stays internal-only.
    This listener is not a CONNECT/HTTP proxy and accepts no upstream argument.
    """

    def __init__(self) -> None:
        self.active = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream = None
        tasks = []
        self.active += 1
        try:
            if self.active > 8:
                return
            upstream_reader, upstream = await asyncio.wait_for(
                asyncio.open_connection("connector", 18999), timeout=3,
            )
            transferred = 0

            async def pump(source: asyncio.StreamReader, target: asyncio.StreamWriter) -> None:
                nonlocal transferred
                while block := await asyncio.wait_for(source.read(65536), timeout=INGRESS_IDLE_SECONDS):
                    transferred += len(block)
                    if transferred > MAX_TUNNEL_BYTES:
                        raise ValueError("transfer_limit")
                    target.write(block)
                    await asyncio.wait_for(target.drain(), timeout=5)

            async with asyncio.timeout(INGRESS_TOTAL_SECONDS):
                tasks = [asyncio.create_task(pump(reader, upstream)), asyncio.create_task(pump(upstream_reader, writer))]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (OSError, ValueError, TimeoutError):
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for stream in (upstream, writer):
                if stream is not None:
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except OSError:
                        pass
            self.active -= 1


async def main() -> None:
    proxy = Egress()
    ingress = Ingress()
    server = await asyncio.start_server(proxy.handle, "0.0.0.0", 18888, limit=8192)
    entry = await asyncio.start_server(ingress.handle, "0.0.0.0", 18999, limit=8192)
    async with server, entry:
        await asyncio.gather(server.serve_forever(), entry.serve_forever())


if __name__ == "__main__":
    asyncio.run(main())
