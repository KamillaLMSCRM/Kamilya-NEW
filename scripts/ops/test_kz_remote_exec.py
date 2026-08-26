import hashlib
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ops import kz_remote_exec as remote


def _script(tmp_path: Path, body: str, *, mode: str = "read-only", correlation: str = "none") -> Path:
    path = tmp_path / "quoted payload.sh"
    path.write_text(
        "#!/usr/bin/env bash\n"
        "# kamilya-target: vm126\n"
        f"# kamilya-mode: {mode}\n"
        f"# kamilya-correlation: {correlation}\n"
        "# kamilya-output: sanitized\n"
        "set -Eeuo pipefail\n"
        f"{body}\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _inside_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(remote, "REPO_ROOT", tmp_path.resolve())


def test_quoted_script_is_hashed_as_exact_bytes(monkeypatch, tmp_path) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(
        tmp_path,
        "printf '%s\\n' \"$name\" '`literal`' '{\"json\":\"value\"}' | cat",
        mode="mutation",
        correlation="REL-123",
    )
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = remote.load_script(
        path, target="vm126", mode="mutation", correlation_id="REL-123", expected_sha256=expected
    )
    assert manifest.payload == path.read_bytes()
    assert manifest.sha256 == expected


def test_script_outside_repository_is_rejected(monkeypatch, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(remote, "REPO_ROOT", repo.resolve())
    path = _script(tmp_path, "hostname")
    with pytest.raises(remote.GateBlocked, match="script_path_not_allowed"):
        remote.load_script(path, target="vm126", mode="read-only", correlation_id="", expected_sha256="")


@pytest.mark.parametrize(
    "body",
    (
        "rm -f /tmp/example",
        "systemctl restart kamilya-api",
        "docker compose up -d",
        "psql -c 'DELETE FROM users'",
        "echo value > /tmp/example",
        "chmod 600 /tmp/example",
    ),
)
def test_read_only_mode_rejects_mutations(monkeypatch, tmp_path, body) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, body)
    with pytest.raises(remote.GateBlocked, match="read_only_script_contains_mutation"):
        remote.load_script(path, target="vm126", mode="read-only", correlation_id="", expected_sha256="")


def test_mutation_requires_exact_correlation(monkeypatch, tmp_path) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, "systemctl restart example", mode="mutation", correlation="REL-123")
    with pytest.raises(remote.GateBlocked, match="exact_correlation_id_required"):
        remote.load_script(path, target="vm126", mode="mutation", correlation_id="wrong", expected_sha256="")
    assert remote.load_script(
        path, target="vm126", mode="mutation", correlation_id="REL-123", expected_sha256=""
    ).correlation == "REL-123"


def test_destructive_and_ct125_routes_fail_closed(monkeypatch, tmp_path) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, "hostname", mode="destructive", correlation="DEL-1")
    with pytest.raises(remote.GateBlocked, match="destructive_mode_not_supported"):
        remote.load_script(path, target="vm126", mode="destructive", correlation_id="DEL-1", expected_sha256="")
    with pytest.raises(remote.GateBlocked, match="ct125_route_not_configured"):
        remote.resolve_target("ct125")


def test_target_commands_are_fixed_and_do_not_embed_script() -> None:
    commands = (
        remote.VM126.command(30, "sha256sum"),
        remote.VM126.command(30, "bash", "-n", "-s"),
        remote.VM126.command(30, "bash", "-se"),
    )
    assert all("python -c" not in command and "bash -c" not in command for command in commands)
    assert all("StrictHostKeyChecking=yes" in command for command in commands)
    assert all("10.77.77.2" in command for command in commands)


def test_execute_stages_send_identical_bytes_and_suppress_raw_output() -> None:
    payload = b"#!/usr/bin/env bash\nset -Eeuo pipefail\nprintf secret-noise\n"
    digest = hashlib.sha256(payload).hexdigest()
    calls = []

    def runner(command: str, observed: bytes) -> remote.StageResult:
        calls.append((command, observed))
        if command.endswith("hostname"):
            return remote.StageResult(0, b"kml\n", b"")
        if command.endswith("sha256sum"):
            return remote.StageResult(0, f"{digest}  -\n".encode(), b"")
        if command.endswith("bash -n -s"):
            return remote.StageResult(0, b"", b"")
        return remote.StageResult(
            0,
            b"secret-noise\nEVIDENCE|status=ok|release=abcdef123456\n",
            b"suppressed-stderr",
        )

    result = remote.execute_stages(remote.VM126, payload, digest, 30, runner)
    assert len(calls) == 4
    assert calls[0][1] == b""
    assert all(observed == payload for _, observed in calls[1:])
    assert result["target_identity_verified"] is True
    assert result["evidence"] == ["EVIDENCE|status=ok|release=abcdef123456"]
    assert "secret-noise" not in str(result)
    assert "suppressed-stderr" not in str(result)


def test_remote_hash_and_evidence_contract_fail_closed() -> None:
    payload = b"payload"
    digest = hashlib.sha256(payload).hexdigest()

    def bad_hash(_command: str, _payload: bytes) -> remote.StageResult:
        if _command.endswith("hostname"):
            return remote.StageResult(0, b"kml\n", b"")
        return remote.StageResult(0, b"0" * 64 + b"  -\n", b"")

    with pytest.raises(remote.GateBlocked, match="remote_hash_mismatch"):
        remote.execute_stages(remote.VM126, payload, digest, 30, bad_hash)
    with pytest.raises(remote.GateBlocked, match="remote_evidence_contract_invalid"):
        remote.evidence_lines(b"EVIDENCE|email=person@example.com\n")
    with pytest.raises(remote.GateBlocked, match="remote_evidence_contract_invalid"):
        remote.evidence_lines(b"")
    with pytest.raises(remote.GateBlocked, match="remote_evidence_contract_invalid"):
        remote.evidence_lines(b"\xff\xfe")


def test_dry_run_does_not_read_credentials(monkeypatch, tmp_path, capsys) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, "hostname")
    monkeypatch.setattr(remote, "load_env", lambda _path: (_ for _ in ()).throw(AssertionError("env read")))
    monkeypatch.setattr(
        remote.sys,
        "argv",
        ["kz_remote_exec", "--script", str(path), "--target", "vm126"],
    )
    assert remote.main() == 0
    output = capsys.readouterr().out
    assert '"network_attempted": false' in output
    assert '"status": "READY"' in output


@pytest.mark.parametrize(
    "body",
    (
        "tee /tmp/output",
        "curl -X POST http://10.77.77.2:8000/health",
        "curl -fsS --max-time 5 --output /tmp/health.txt http://10.77.77.2:8000/health",
        "curl -fsS --max-time 5 --cookie-jar /tmp/cookies http://10.77.77.2:8000/health",
        "curl -fsS --max-time 5 --config /tmp/curl.conf http://10.77.77.2:8000/health",
        "source /tmp/other.sh",
        "python3 -c 'print(1)'",
        "redis-cli SET key value",
        "docker exec api touch /tmp/value",
        "value=$(hostname)",
    ),
)
def test_read_only_allowlist_rejects_bypass_commands(monkeypatch, tmp_path, body) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, body)
    with pytest.raises(remote.GateBlocked):
        remote.load_script(path, target="vm126", mode="read-only", correlation_id="", expected_sha256="")


@pytest.mark.parametrize(
    "body",
    (
        "export API_TOKEN=abcdefghijklmnopqrstuvwxyz012345",
        "curl postgresql://user:pass@example/db",
        "printf person@example.com",
        "cat /workspace/.env",
        "cat /proc/self/environ",
    ),
)
def test_sensitive_script_content_is_rejected(monkeypatch, tmp_path, body) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, body, mode="mutation", correlation="REL-123")
    with pytest.raises(remote.GateBlocked, match="script_contains_sensitive_material"):
        remote.load_script(path, target="vm126", mode="mutation", correlation_id="REL-123", expected_sha256="")


def test_proxy_and_target_identity_must_match(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PROXY_VPS_HOST=wrong.example\nPROXY_VPS_LOGIN=user\nPROXY_VPS_PASSWORD=value\n",
        encoding="utf-8",
    )
    with pytest.raises(remote.GateBlocked, match="proxy_identity_mismatch"):
        remote.proxy_credentials(env_file)

    payload = b"payload"
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(remote.GateBlocked, match="target_identity_mismatch"):
        remote.execute_stages(
            remote.VM126,
            payload,
            digest,
            30,
            lambda _command, _payload: remote.StageResult(0, b"wrong-host\n", b""),
        )


def test_only_canonical_trust_paths_are_allowed(tmp_path) -> None:
    with pytest.raises(remote.GateBlocked, match="noncanonical_env_file_not_allowed"):
        remote.assert_canonical_trust_paths(tmp_path / ".env", remote.DEFAULT_KNOWN_HOSTS)
    with pytest.raises(remote.GateBlocked, match="noncanonical_known_hosts_not_allowed"):
        remote.assert_canonical_trust_paths(remote.DEFAULT_ENV_FILE, tmp_path / "known_hosts")


def test_read_only_fixed_health_get_is_allowed(monkeypatch, tmp_path) -> None:
    _inside_repo(monkeypatch, tmp_path)
    path = _script(tmp_path, "curl -fsS --max-time 5 http://10.77.77.2:8000/health")
    manifest = remote.load_script(
        path, target="vm126", mode="read-only", correlation_id="", expected_sha256=""
    )
    assert manifest.mode == "read-only"


def test_output_overflow_is_reported_only_after_channel_termination(monkeypatch) -> None:
    class Channel:
        emitted = False
        closed = False

        def exec_command(self, _command):
            return None

        def sendall(self, _payload):
            return None

        def shutdown_write(self):
            return None

        def recv_ready(self):
            return not self.emitted

        def recv(self, _size):
            self.emitted = True
            return b"x" * (remote.MAX_REMOTE_OUTPUT_BYTES + 1)

        def recv_stderr_ready(self):
            return False

        def exit_status_ready(self):
            return self.emitted

        def recv_exit_status(self):
            return 0

        def close(self):
            self.closed = True

    channel = Channel()

    class Transport:
        def is_active(self):
            return True

        def open_session(self, timeout):
            assert timeout == 30
            return channel

    class Client:
        def get_transport(self):
            return Transport()

    with pytest.raises(remote.GateBlocked, match="remote_output_limit_exceeded_after_termination"):
        remote.run_channel(Client(), "fixed", b"payload", 30)
    assert channel.closed is True


def test_source_has_no_shell_true_or_inline_python_executor() -> None:
    source = Path(remote.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "python -c" not in source
    assert "AutoAddPolicy" not in source
