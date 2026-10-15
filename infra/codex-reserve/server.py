"""Private one-request-per-connection CLI connector. No prompt/access logs."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from pathlib import Path

from runner import MAX_INPUT_BYTES, CodexRunner, RunnerError


class Connector:
    def __init__(self, runner: CodexRunner, token: str):
        if len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
            raise RunnerError("not_configured")
        self.runner = runner
        self.token = token
        self.connections = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        status, data = 400, {"error": "invalid_input"}
        request_payload = None
        try:
            if self.connections > 8:
                raise RunnerError("busy")
            async with asyncio.timeout(5):
                header = await reader.readuntil(b"\r\n\r\n")
                if len(header) > 8192:
                    raise RunnerError("invalid_input")
                lines = header.decode("ascii").split("\r\n")
                method, path, version = lines[0].split(" ")
                headers: dict[str, str] = {}
                for line in lines[1:-2]:
                    key, value = line.split(":", 1)
                    key = key.lower()
                    if key in headers:
                        raise RunnerError("invalid_input")
                    headers[key] = value.strip()
                if version != "HTTP/1.1" or "transfer-encoding" in headers:
                    raise RunnerError("invalid_input")
                auth = headers.get("authorization", "")
                if not hmac.compare_digest(auth.encode(), f"Bearer {self.token}".encode()):
                    status, data = 403, {"error": "connector_unauthorized"}
                elif method == "GET" and path == "/v1/readiness":
                    data = await self.runner.readiness()
                    status = 200
                elif method == "POST" and path == "/v1/chat/completions":
                    length = int(headers.get("content-length", "0"))
                    if not 1 <= length <= MAX_INPUT_BYTES or headers.get("content-type", "").split(";")[0] != "application/json":
                        raise RunnerError("invalid_input")
                    payload = json.loads(await reader.readexactly(length))
                    if not isinstance(payload, dict):
                        raise RunnerError("invalid_input")
                    # Leave the short header/body deadline before model execution.
                    request_payload = payload
                    status = 202
                else:
                    status, data = 404, {"error": "not_found"}
            if status == 202:
                assert request_payload is not None
                operation = asyncio.create_task(self.runner.complete(request_payload))
                disconnect = asyncio.create_task(reader.read(1))
                try:
                    done, _ = await asyncio.wait({operation, disconnect}, return_when=asyncio.FIRST_COMPLETED)
                    if disconnect in done and operation not in done:
                        operation.cancel()
                        await asyncio.gather(operation, return_exceptions=True)
                        status, data = 499, {"error": "unavailable"}
                        return
                    data = await operation
                    status = 200
                finally:
                    for task in (operation, disconnect):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(operation, disconnect, return_exceptions=True)
        except RunnerError as exc:
            status = 401 if exc.code == "authorization_required" else 400 if exc.code == "invalid_input" else 503
            data = {"error": exc.code}
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            status, data = 400, {"error": "invalid_input"}
        except TimeoutError:
            status, data = 504, {"error": "timeout"}
        except (OSError, RuntimeError):
            status, data = 503, {"error": "unavailable"}
        finally:
            try:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                writer.write(
                    f"HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n".encode() + body
                )
                await asyncio.wait_for(writer.drain(), timeout=2)
            except (OSError, TimeoutError):
                pass
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass
            finally:
                self.connections -= 1


async def main() -> None:
    runner = CodexRunner(
        Path(os.environ["CODEX_CLI_BINARY"]), Path(os.environ["CODEX_CLI_HOME"]),
        os.environ.get("CODEX_CLI_SHA256") or Path(os.environ.get("CODEX_CLI_SHA256_FILE", "/opt/codex-reserve/cli.sha256")).read_text(encoding="utf-8").strip(),
        float(os.environ.get("CODEX_CLI_TIMEOUT", "60")),
    )
    token = Path(os.environ["CODEX_CONNECTOR_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    connector = Connector(runner, token)
    server = await asyncio.start_server(
        connector.handle, os.environ.get("CODEX_CONNECTOR_BIND", "127.0.0.1"),
        int(os.environ.get("CODEX_CONNECTOR_PORT", "18999")), limit=8192,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
