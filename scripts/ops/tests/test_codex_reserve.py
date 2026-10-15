"""Database/provider-free subprocess and private connector contract tests."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import io
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "synthetic-connector-credential-00000000000"


@pytest.fixture
def modules(monkeypatch):
    def load(name, filename):
        spec = importlib.util.spec_from_file_location(name, ROOT / "infra/codex-reserve" / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    runner = load("kamilya_codex_runner", "runner.py")
    monkeypatch.setitem(sys.modules, "runner", runner)
    return runner, load("kamilya_codex_server", "server.py"), load("kamilya_codex_egress", "egress.py"), load("kamilya_codex_install", "install_cli.py")


@pytest.fixture
def worker(modules, tmp_path):
    binary = Path(sys.executable)
    return modules[0].CodexRunner(binary, tmp_path, hashlib.sha256(binary.read_bytes()).hexdigest())


def output(content="synthetic", **changes):
    events = [
        {"type": "thread.started", "thread_id": "synthetic"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"content": content})}},
        {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 10}},
    ]
    if changes:
        events[-1].update(changes)
    return b"\n".join(json.dumps(event).encode() for event in events)


def payload(**changes):
    return {"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "synthetic"}], "max_tokens": 100, **changes}


def test_binary_pin_and_configuration_must_match(modules, tmp_path):
    with pytest.raises(modules[0].RunnerError, match="not_configured"):
        modules[0].CodexRunner(Path(sys.executable), tmp_path, "0" * 64)


def test_environment_excludes_application_and_provider_secrets(worker, monkeypatch):
    for key in ("DATABASE_URL", "JWT_SECRET", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CHATGPT_RESERVE_TOKEN", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.setenv(key, "synthetic-not-for-child")
    env = worker.environment()
    assert all(value != "synthetic-not-for-child" for value in env.values())
    assert env["CODEX_HOME"] == str(worker.cli_home)


def test_command_is_fixed_ephemeral_stdin_restricted_without_tool_bypass(worker, tmp_path):
    args = worker.command(tmp_path / "schema.json")
    assert args[0] == "exec" and args[-1] == "-"
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert 'default_permissions="kamilya_text_only"' in args
    assert 'permissions.kamilya_text_only.network.enabled=false' in args
    assert 'permissions.kamilya_text_only.filesystem' in " ".join(args)
    assert args[args.index("--model") + 1] == "gpt-5.6-luna"
    assert "features.shell_tool=false" in args and "features.apps=false" in args
    assert not any("bypass" in value for value in args)


@pytest.mark.parametrize("changes", [
    {"model": "other"}, {"command": "synthetic"}, {"max_tokens": True}, {"max_tokens": -1},
    {"messages": [{"role": "tool", "content": "synthetic"}]},
    {"messages": [{"role": "user", "content": "synthetic", "extra": "not allowed"}]},
    {"messages": [{"role": "user", "content": "x" * 524289}]},
])
async def test_invalid_input_rejected_before_process(worker, modules, monkeypatch, changes):
    run = AsyncMock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(modules[0].RunnerError, match="invalid_input"):
        await worker.complete(payload(**changes))
    run.assert_not_awaited()


async def test_one_execution_returns_compatible_reply_and_usage(worker, monkeypatch):
    run = AsyncMock(return_value=(0, output(), b"not returned"))
    monkeypatch.setattr(worker, "_run", run)
    result = await worker.complete(payload())
    assert result["choices"][0]["message"]["content"] == "synthetic"
    assert result["usage"]["completion_tokens"] == 10
    assert run.await_count == 1
    assert not Path(run.call_args.kwargs["cwd"]).exists()


async def test_observed_token_limit_violation_rejects_without_rerun(worker, modules, monkeypatch):
    run = AsyncMock(return_value=(0, output(usage={"input_tokens": 50, "output_tokens": 101}), b""))
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(modules[0].RunnerError, match="output_limit"):
        await worker.complete(payload())
    assert run.await_count == 1


@pytest.mark.parametrize("data,reason", [
    (b"not-json", "protocol_mismatch"),
    (b'{"type":"turn.failed"}', "unavailable"),
    (b'{"type":"item.started","item":{"type":"command_execution"}}', "tool_use_rejected"),
    (b'{"type":"turn.completed"}', "protocol_mismatch"),
])
def test_malformed_failed_and_tool_results_are_never_accepted(modules, data, reason):
    with pytest.raises(modules[0].RunnerError, match=reason):
        modules[0].CodexRunner.parse_result(data)


async def test_managed_login_readiness_runs_no_generation(worker, modules, monkeypatch):
    run = AsyncMock(side_effect=[(0, modules[0].CLI_VERSION.encode(), b""), (0, b"", b"Logged in using ChatGPT")])
    monkeypatch.setattr(worker, "_run", run)
    result = await worker.readiness()
    assert result["authorization"] == "codex_cli" and result["ready"] is True
    assert run.await_count == 2 and all("exec" not in call.args[0] for call in run.call_args_list)


async def test_non_chatgpt_login_is_not_ready(worker, modules, monkeypatch):
    run = AsyncMock(side_effect=[(0, modules[0].CLI_VERSION.encode(), b""), (0, b"Logged in using an API key", b"synthetic")])
    monkeypatch.setattr(worker, "_run", run)
    with pytest.raises(modules[0].RunnerError, match="authorization_required"):
        await worker.readiness()


async def test_busy_does_not_queue_or_start_second_process(worker, modules):
    async with worker._operation:
        with pytest.raises(modules[0].RunnerError, match="busy"):
            await worker.complete(payload())


async def test_real_subprocess_timeout_is_bounded_and_reaped(worker, modules, tmp_path, monkeypatch):
    stopped = []
    stop = worker._stop
    async def record(process):
        await stop(process)
        stopped.append(process.returncode)
    monkeypatch.setattr(worker, "_stop", record)
    with pytest.raises(modules[0].RunnerError, match="timeout"):
        await worker._run(["-c", "import time; time.sleep(60)"], b"", cwd=tmp_path, timeout=0.05)
    assert len(stopped) == 1 and stopped[0] is not None


async def test_real_subprocess_external_cancellation_reaps_child(worker, tmp_path, monkeypatch):
    stopped = []
    stop = worker._stop
    async def record(process):
        await stop(process)
        stopped.append(process.returncode)
    monkeypatch.setattr(worker, "_stop", record)
    task = asyncio.create_task(worker._run(["-c", "import time; time.sleep(60)"], b"", cwd=tmp_path, timeout=60))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(stopped) == 1 and stopped[0] is not None


async def test_real_subprocess_output_limit_is_bounded(worker, modules, tmp_path, monkeypatch):
    monkeypatch.setattr(modules[0], "MAX_OUTPUT_BYTES", 32)
    with pytest.raises(modules[0].RunnerError, match="output_limit"):
        await worker._run(["-c", "print('x' * 1024)"], b"", cwd=tmp_path, timeout=5)


async def test_private_http_auth_and_readiness_without_model(modules):
    runner = SimpleNamespace(readiness=AsyncMock(return_value={"ready": True}), complete=AsyncMock())
    connector = modules[1].Connector(runner, TOKEN)
    server = await asyncio.start_server(connector.handle, "127.0.0.1", 0, limit=8192)
    async with server:
        port = server.sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            assert (await client.get("/v1/readiness")).status_code == 403
            result = await client.get("/v1/readiness", headers={"Authorization": f"Bearer {TOKEN}"})
            assert result.status_code == 200 and result.json() == {"ready": True}
    runner.readiness.assert_awaited_once()
    runner.complete.assert_not_awaited()


async def test_http_client_disconnect_cancels_model(modules):
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def complete(data):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    connector = modules[1].Connector(SimpleNamespace(complete=complete), TOKEN)
    server = await asyncio.start_server(connector.handle, "127.0.0.1", 0, limit=8192)
    async with server:
        port = server.sockets[0].getsockname()[1]
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        data = json.dumps(payload()).encode()
        writer.write(f"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n".encode() + data)
        await writer.drain()
        await asyncio.wait_for(started.wait(), timeout=1)
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_successful_http_returns_only_runner_envelope(modules):
    result = {"choices": [{"message": {"content": "synthetic answer"}}]}
    worker = SimpleNamespace(complete=AsyncMock(return_value=result))
    connector = modules[1].Connector(worker, TOKEN)
    server = await asyncio.start_server(connector.handle, "127.0.0.1", 0, limit=8192)
    async with server:
        port = server.sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            response = await client.post("/v1/chat/completions", json=payload(), headers={"Authorization": f"Bearer {TOKEN}"})
            assert response.status_code == 200 and response.json() == result
    worker.complete.assert_awaited_once()


@pytest.mark.parametrize("line", [
    "GET https://chatgpt.com HTTP/1.1", "CONNECT 127.0.0.1:443 HTTP/1.1",
    "CONNECT auth.openai.com:80 HTTP/1.1", "CONNECT api.openai.com:443 HTTP/1.1",
    "CONNECT chatgpt.com.evil.test:443 HTTP/1.1", "CONNECT user@chatgpt.com:443 HTTP/1.1",
    "CONNECT 169.254.169.254:443 HTTP/1.1", "CONNECT 192.168.1.225:5432 HTTP/1.1",
])
def test_egress_denies_arbitrary_internal_and_metadata_destinations(modules, line):
    with pytest.raises(ValueError):
        modules[2].destination(line)


@pytest.mark.parametrize("host", ["chatgpt.com", "auth.openai.com"])
def test_egress_only_permits_fixed_tls_destinations(modules, host):
    assert modules[2].destination(f"CONNECT {host}:443 HTTP/1.1") == host


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["1.1.1.1", "10.0.0.1"], ["169.254.169.254"], ["224.0.0.1"], []])
async def test_egress_dns_private_mixed_or_multicast_fails_closed(modules, monkeypatch, addresses):
    resolver = AsyncMock(return_value=[(None, None, None, None, (address, 443)) for address in addresses])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(ValueError, match="destination_denied"):
        await modules[2].resolve_public("chatgpt.com")


async def test_egress_dns_returns_validated_literal_without_connecting_by_hostname(modules, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[(None, None, None, None, ("1.1.1.1", 443))]))
    assert await modules[2].resolve_public("chatgpt.com") == "1.1.1.1"


async def test_absent_measured_usage_is_rejected_not_claimed_capped(worker, modules, monkeypatch):
    monkeypatch.setattr(worker, "_run", AsyncMock(return_value=(0, output(usage={}), b"")))
    with pytest.raises(modules[0].RunnerError, match="output_limit"):
        await worker.complete(payload())


def test_isolated_child_only_uses_fixed_internal_proxy(worker, monkeypatch):
    monkeypatch.setenv("CODEX_CONNECTOR_ISOLATED", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-untrusted-proxy.test")
    env = worker.environment()
    assert env["HTTPS_PROXY"] == "http://egress:18888"
    assert env["HTTP_PROXY"] == "http://egress:18888" and env["NO_PROXY"] == ""


def test_published_ingress_is_on_edge_not_internal_only_connector():
    import yaml
    config = yaml.safe_load((ROOT / "infra/codex-reserve/compose.yml").read_text())
    assert not config["services"]["connector"].get("ports")
    assert config["services"]["egress"]["ports"] == ["${CODEX_BIND_IP:-127.0.0.1}:18999:18999"]


def test_compose_has_internal_network_no_app_mounts_no_public_egress_port():
    import yaml
    config = yaml.safe_load((ROOT / "infra/codex-reserve/compose.yml").read_text())
    connector, egress = config["services"]["connector"], config["services"]["egress"]
    assert connector["networks"] == ["codex-private"]
    assert config["networks"]["codex-private"]["internal"] is True
    assert len(connector["volumes"]) == 2
    assert {mount["target"] for mount in connector["volumes"]} == {"/codex-home", "/run/secrets/connector-token"}
    for component in (connector, egress):
        assert component["user"] == "10001:10001" and component["read_only"] is True
        assert component["cap_drop"] == ["ALL"] and component["security_opt"] == ["no-new-privileges:true"]
        assert component["pids_limit"] <= 64
        assert "env_file" not in component
    assert egress["ports"] == ["${CODEX_BIND_IP:-127.0.0.1}:18999:18999"]
    assert not egress.get("volumes") and not egress.get("environment")
    assert egress["entrypoint"] == ["python", "/opt/codex-reserve/egress.py"]


async def test_ingress_routes_only_to_fixed_connector_and_cleans_up(modules, monkeypatch):
    connections = []
    received = []
    closed = asyncio.Event()

    async def endpoint(reader, writer):
        try:
            received.append(await reader.readexactly(9))
            writer.write(b"synthetic-reply")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()

    server = await asyncio.start_server(endpoint, "127.0.0.1", 0)
    original_open = asyncio.open_connection

    async def fixed_open(host, port):
        connections.append((host, port))
        return await original_open("127.0.0.1", server.sockets[0].getsockname()[1])

    proxy = modules[2].Ingress()
    gateway = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    async with server, gateway:
        monkeypatch.setattr(asyncio, "open_connection", fixed_open)
        reader, writer = await original_open("127.0.0.1", gateway.sockets[0].getsockname()[1])
        writer.write(b"synthetic")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), timeout=2) == b"synthetic-reply"
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(closed.wait(), timeout=2)
        await asyncio.sleep(0)
    assert connections == [("connector", 18999)] and received == [b"synthetic"]
    assert proxy.active == 0


def test_ingress_deadlines_leave_maximum_runner_cleanup_and_response_margin(modules):
    assert modules[2].INGRESS_IDLE_SECONDS >= 120 + 5 + 5
    assert modules[2].INGRESS_TOTAL_SECONDS > modules[2].INGRESS_IDLE_SECONDS
    assert modules[2].INGRESS_TOTAL_SECONDS <= 150


@pytest.mark.parametrize("disconnect", [True, False])
async def test_ingress_preserves_connector_cancellation_and_timeout_response(modules, monkeypatch, disconnect):
    started, cancelled, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def complete(request):
        started.set()
        try:
            if disconnect:
                await asyncio.Event().wait()
            await asyncio.sleep(0.02)
            raise modules[0].RunnerError("timeout")
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            finished.set()

    connector = modules[1].Connector(SimpleNamespace(complete=complete), TOKEN)
    backend = await asyncio.start_server(connector.handle, "127.0.0.1", 0)
    ingress = modules[2].Ingress()
    entry = await asyncio.start_server(ingress.handle, "127.0.0.1", 0)
    original_open = asyncio.open_connection

    async def fixed_open(host, port):
        assert (host, port) == ("connector", 18999)
        return await original_open("127.0.0.1", backend.sockets[0].getsockname()[1])

    async with backend, entry:
        monkeypatch.setattr(asyncio, "open_connection", fixed_open)
        reader, writer = await original_open("127.0.0.1", entry.sockets[0].getsockname()[1])
        writer.write((f"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}").encode())
        await writer.drain()
        await asyncio.wait_for(started.wait(), timeout=2)
        if disconnect:
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(cancelled.wait(), timeout=2)
        else:
            reply = await asyncio.wait_for(reader.read(), timeout=2)
            assert reply.startswith(b"HTTP/1.1 503") and b'"error": "timeout"' in reply
            assert not cancelled.is_set()
            writer.close()
            await writer.wait_closed()
        await asyncio.wait_for(finished.wait(), timeout=2)
        # Observe termination at the composed transport seam, not only a fake
        # runner return: both live handlers must release their connections.
        async with asyncio.timeout(2):
            while connector.connections or ingress.active:
                await asyncio.sleep(0)
    assert connector.connections == 0 and ingress.active == 0


def test_installer_rejects_redirects_and_tampered_archive(modules, monkeypatch):
    from urllib.error import URLError
    with pytest.raises(URLError):
        modules[3].NoRedirect().redirect_request(None, None, 302, None, None, "https://elsewhere.test")
    monkeypatch.setattr(modules[3], "build_opener", lambda *args: SimpleNamespace(open=lambda *a, **k: io.BytesIO(b"tampered")))
    with pytest.raises(RuntimeError, match="SHA-512"):
        modules[3].download()


@pytest.mark.parametrize("symlink,duplicate", [(True, False), (False, True)])
def test_installer_never_extracts_symlink_or_duplicate_binary(modules, symlink, duplicate):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        member = tarfile.TarInfo(modules[3].MEMBER)
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = "/sensitive"
            archive.addfile(member)
        else:
            member.size = 3
            archive.addfile(member, io.BytesIO(b"one"))
            archive.addfile(member, io.BytesIO(b"two"))
    with pytest.raises(RuntimeError, match="unique regular"):
        modules[3].extract_binary(stream.getvalue())


def test_installer_reads_only_pinned_member_no_extractall(modules):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name in (modules[3].MEMBER, "../not-extracted"):
            member = tarfile.TarInfo(name)
            member.size = 6
            archive.addfile(member, io.BytesIO(b"binary"))
    assert modules[3].extract_binary(stream.getvalue()) == b"binary"


@pytest.mark.skipif(os.name != "nt", reason="Windows process-job descendant regression")
async def test_parent_exited_descendant_cannot_survive_windows_job_close(worker, modules, tmp_path):
    canary = tmp_path / "descendant-must-not-write.txt"
    child_code = f"import time; from pathlib import Path; time.sleep(1.5); Path({str(canary)!r}).write_text('failed')"
    parent_code = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child_code!r}]); sys.exit(0)"
    with pytest.raises(modules[0].RunnerError, match="timeout"):
        await worker._run(["-c", parent_code], b"", cwd=tmp_path, timeout=0.3)
    await asyncio.sleep(1.6)
    assert not canary.exists()
