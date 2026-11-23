"""Run the DEV caption relay on the workstation via the existing VPS loopback."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

import paramiko

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.deploy.dev_release_controller import LiveProviderAdapter, _read_env_file
from scripts.ops.kz_remote_exec import DEFAULT_ENV_FILE

VPS = "173.249.51.164"
CAPTION_HOST = "caption-dev.173-249-51-164.sslip.io"
RENDER_DEV = "srv-d8rp8ej7uimc73fglid0"
LOOPBACK = "127.0.0.1"
LOCAL_PORT = 18082
REMOTE_PORT = 18081


def dev_caption_token() -> str:
    adapter = LiveProviderAdapter(repo_root=REPO, env_file=DEFAULT_ENV_FILE, timeout_seconds=30)
    config = adapter.render_service(RENDER_DEV)
    if config.get("branch") != "dev" or config.get("plan") != "free":
        raise RuntimeError("Unexpected DEV service identity")
    entries = adapter._http_json(
        f"https://api.render.com/v1/services/{RENDER_DEV}/env-vars?limit=100", adapter.render_token,
    )
    values = {row["envVar"]["key"]: row["envVar"].get("value") for row in entries}
    route = urlsplit(values["YOUTUBE_CAPTION_SERVICE_URL"])
    if route.scheme != "https" or route.netloc != CAPTION_HOST or route.path not in {"", "/"}:
        raise RuntimeError("Unexpected caption relay host")
    token = values["YOUTUBE_CAPTION_SERVICE_TOKEN"]
    if not token or len(token) < 32:
        raise RuntimeError("DEV caption token missing")
    return token


def pump(source: socket.socket | paramiko.Channel, destination: socket.socket | paramiko.Channel) -> None:
    try:
        while incoming := source.recv(65536):
            destination.sendall(incoming)
        destination.shutdown(socket.SHUT_WR)
    except (OSError, EOFError, paramiko.SSHException):
        pass


def forward(channel: paramiko.Channel) -> None:
    with channel, socket.create_connection((LOOPBACK, LOCAL_PORT), timeout=3) as local:
        channel.settimeout(28)
        local.settimeout(28)
        outgoing = threading.Thread(target=pump, args=(channel, local), daemon=True)
        outgoing.start()
        pump(local, channel)
        outgoing.join(timeout=3)


def forward_connection(password: str, server: subprocess.Popen) -> None:
    with paramiko.SSHClient() as ssh:
        ssh.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        ssh.connect(VPS, username="root", password=password, allow_agent=False, look_for_keys=False,
                    timeout=8, banner_timeout=8, auth_timeout=8)
        transport = ssh.get_transport()
        if transport is None:
            raise paramiko.SSHException("No transport")
        transport.set_keepalive(15)
        transport.request_port_forward(LOOPBACK, REMOTE_PORT)
        print("READY: DEV relay forwarded on the VPS loopback", flush=True)
        slots = threading.BoundedSemaphore(4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            while server.poll() is None and transport.is_active():
                channel = transport.accept(3)
                if channel is None:
                    continue
                if not slots.acquire(blocking=False):
                    channel.close()
                    continue
                future = pool.submit(forward, channel)
                future.add_done_callback(lambda _: slots.release())
        if server.poll() is not None:
            raise RuntimeError("Caption process exited")


def wait_for_local(server: subprocess.Popen) -> None:
    for _ in range(30):
        if server.poll() is not None:
            raise RuntimeError("Caption process exited before readiness")
        try:
            with urlopen(f"http://{LOOPBACK}:{LOCAL_PORT}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("Caption process failed readiness")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay-python", required=True, type=Path)
    parser.add_argument("--legacy-env", required=True, type=Path)
    args = parser.parse_args()
    password = _read_env_file(args.legacy_env)["vps_root_password"]
    with socket.socket() as probe:
        probe.bind((LOOPBACK, LOCAL_PORT))
    env = {**os.environ, "CAPTION_SERVICE_TOKEN": dev_caption_token()}
    command = [str(args.relay_python), "-m", "uvicorn", "app:app", "--host", LOOPBACK,
               "--port", str(LOCAL_PORT), "--no-access-log", "--log-level", "error"]
    with subprocess.Popen(command, cwd=REPO / "infra/youtube-caption-service", env=env) as server:
        try:
            wait_for_local(server)
            while server.poll() is None:
                try:
                    forward_connection(password, server)
                except (paramiko.AuthenticationException, paramiko.BadHostKeyException):
                    raise
                except (OSError, EOFError, paramiko.SSHException) as error:
                    print(f"RECONNECT: {type(error).__name__}", flush=True)
                time.sleep(5)
        finally:
            server.terminate()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as failure:
        print(f"STOP: {type(failure).__name__}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
