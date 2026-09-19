"""Run a local command against the production-equivalent VM126 Docling service.

The wrapper opens a local-only TCP forward through the canonical KZ proxy and
does not expose Docling publicly or copy document content to an extra service.
Run this wrapper with the system Python (which owns the approved Paramiko tool),
then pass the application command after ``--``.
"""
from __future__ import annotations

import argparse
import base64
import json
import select
import socketserver
from pathlib import Path
import shlex
import subprocess
import sys
import threading

import paramiko


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ops import kz_remote_exec as transport  # noqa: E402


LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 18600

RELAY_CODE = r"""
import os
import select
import socket

upstream = socket.create_connection(("docling", 8600), timeout=30)
stdin_open = True
while True:
    readers = [upstream]
    if stdin_open:
        readers.append(0)
    ready, _, _ = select.select(readers, [], [])
    if 0 in ready:
        data = os.read(0, 65536)
        if data:
            upstream.sendall(data)
        else:
            stdin_open = False
            upstream.shutdown(socket.SHUT_WR)
    if upstream in ready:
        data = upstream.recv(65536)
        if not data:
            break
        os.write(1, data)
upstream.close()
"""


class _ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _handler_for(proxy_transport: paramiko.Transport, container: str):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            channel = proxy_transport.open_session(timeout=30)
            encoded = base64.b64encode(RELAY_CODE.encode("utf-8")).decode("ascii")
            bootstrap = f"import base64;exec(base64.b64decode('{encoded}'))"
            nested = (
                *transport.VM126.remote_prefix,
                "sudo",
                "-n",
                "docker",
                "exec",
                "-i",
                container,
                "python",
                "-u",
                "-c",
                shlex.quote(bootstrap),
            )
            channel.exec_command(shlex.join(nested))
            try:
                while True:
                    readable, _, _ = select.select([self.request, channel], [], [])
                    if self.request in readable:
                        data = self.request.recv(65536)
                        if not data:
                            break
                        channel.sendall(data)
                    if channel in readable:
                        data = channel.recv(65536)
                        if not data:
                            break
                        self.request.sendall(data)
            finally:
                channel.close()

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    transport.assert_canonical_trust_paths(
        transport.DEFAULT_ENV_FILE, transport.DEFAULT_KNOWN_HOSTS
    )
    host, username, password = transport.proxy_credentials(transport.DEFAULT_ENV_FILE)
    client = paramiko.SSHClient()
    client.load_host_keys(str(transport.DEFAULT_KNOWN_HOSTS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    server: _ForwardServer | None = None
    thread: threading.Thread | None = None
    try:
        client.connect(
            host,
            username=username,
            password=password,
            allow_agent=False,
            look_for_keys=False,
            timeout=30,
            auth_timeout=30,
            banner_timeout=30,
            disabled_algorithms=transport.DISABLED_ALGORITHMS,
        )
        proxy_transport = client.get_transport()
        if proxy_transport is None or not proxy_transport.is_active():
            raise RuntimeError("proxy_transport_inactive")
        state_result = transport.run_channel(
            client,
            transport.VM126.command(
                30,
                "sudo",
                "-n",
                "cat",
                "/var/lib/kamilya-release-plane/state.json",
            ),
            b"",
            40,
        )
        if state_result.exit_code != 0:
            raise RuntimeError("release_state_unavailable")
        slot = json.loads(state_result.stdout.decode("utf-8")).get("active_slot")
        if slot not in {"blue", "green"}:
            raise RuntimeError("active_slot_invalid")
        container = f"kamilya-{slot}-api-1"
        server = _ForwardServer(
            (LOCAL_HOST, LOCAL_PORT), _handler_for(proxy_transport, container)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            "DOC_TUNNEL|status=ready|local=127.0.0.1:18600|"
            f"remote=vm126:{container}:docling:8600"
        )
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
