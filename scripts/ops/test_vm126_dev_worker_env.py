from __future__ import annotations

import hashlib
import io
import os
import sys
from pathlib import Path

import pytest

from scripts.ops import vm126_dev_worker_env_receiver as receiver
from scripts.ops import vm126_dev_worker_stage as stage
from scripts.ops.kz_remote_exec import StageResult

PROJECT_FINGERPRINT = hashlib.sha256(b"devproject").hexdigest()
RELEASE = "a" * 40


@pytest.fixture(autouse=True)
def pin_fixture_project(monkeypatch):
    monkeypatch.setattr(receiver, "DATABASE_PROJECT_FINGERPRINT", PROJECT_FINGERPRINT)


def payload(release: str = RELEASE, *, database: str = "postgresql+asyncpg://lms_app.devproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres", redis: str = "rediss://:secret@173.249.51.164:6380/1") -> bytes:
    return ("\n".join([
        "DEPLOYMENT_ENVIRONMENT=vm-development-worker",
        f"DATABASE_URL={database}",
        f"REDIS_URL={redis}",
        f"RELEASE_SHA={release}",
        "DEV_MODEL_SSH_ROLE=worker",
        "AI_DIRECT_LUNA_QA_API_KEY=secret",
        "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION=fixture",
        "AI_DIRECT_LUNA_QA_DEV_ENABLED=true",
        "AI_LESSON_CYCLE_DEV_ENABLED=true",
        "AI_LESSON_CYCLE_DEV_TENANTS=a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0",
        "AI_QA_LUNA_DEV_ENABLED=true",
        "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=true",
        "APP_ENV=development",
        "DB_MAX_OVERFLOW=0",
        "DB_POOL_SIZE=2",
        "DB_POOL_TIMEOUT=30",
        "DB_POOL_RECYCLE_SECONDS=300",
        "JWT_ALGORITHM=HS256",
        "JWT_SECRET=secret",
        "MASTER_ENCRYPTION_KEY=secret",
        "PROVIDER_KEY_ENCRYPTION_KEY=secret",
        "REDIS_TLS_VERIFY=true",
        "SUPABASE_BUCKET=documents",
        "SUPABASE_KEY=secret",
        "SUPABASE_URL=https://devproject.supabase.co",
        "CELERY_QUEUES=ai,documents,maintenance",
        "CELERY_CONCURRENCY=1",
    ]) + "\n").encode()


def test_receiver_validates_dev_identity_and_idempotent_install(tmp_path: Path) -> None:
    body = payload()
    digest = hashlib.sha256(body).hexdigest()
    first = receiver.install_payload(body, RELEASE, digest, tmp_path, require_root=False)
    second = receiver.install_payload(body, RELEASE, digest, tmp_path, require_root=False)
    assert first["status"] == "installed"
    assert second["status"] == "already_present"
    assert (tmp_path / RELEASE / "runtime.env").read_bytes() == body


@pytest.mark.parametrize(
    "body",
    (
        payload(database="postgresql://lms_app:x@other.supabase.co:5432/postgres"),
        payload(redis="redis://173.249.51.164:6379/0"),
        payload().replace(f"RELEASE_SHA={RELEASE}".encode(), f"RELEASE_SHA={'b' * 40}".encode()),
        payload() + b"UNKNOWN=value\n",
        payload() + b"AI_GENERATION_V2_ENABLED=true\n",
        payload() + b"BAD=value\n",
    ),
)
def test_receiver_rejects_foreign_scope_or_malformed_env(body: bytes, tmp_path: Path) -> None:
    with pytest.raises((ValueError, FileExistsError)):
        receiver.install_payload(body, RELEASE, hashlib.sha256(body).hexdigest(), tmp_path, require_root=False)


def test_receiver_requires_runtime_keys_even_when_unrelated_key_is_present() -> None:
    body = payload().replace(b"JWT_SECRET=secret\n", b"") + b"UNRELATED_RUNTIME=value\n"
    with pytest.raises(ValueError, match="dotenv_key_or_value_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())

    body = payload().replace(b"JWT_SECRET=secret\n", b"")
    with pytest.raises(ValueError, match="worker_identity_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())


def test_receiver_uses_pinned_project_fingerprint_not_caller_value(monkeypatch) -> None:
    body = payload()
    monkeypatch.setattr(receiver, "DATABASE_PROJECT_FINGERPRINT", "0" * 64)
    with pytest.raises(ValueError, match="supabase_project_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())


def test_build_payload_normalizes_render_tenant_json_without_printing_values() -> None:
    source = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in payload().decode().splitlines()
    }
    source["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    source["AI_LESSON_CYCLE_DEV_TENANTS"] = '["a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"]'
    body = receiver.build_payload_from_render_values(source, RELEASE)
    assert b"DEPLOYMENT_ENVIRONMENT=vm-development-worker\n" in body
    assert b"AI_LESSON_CYCLE_DEV_TENANTS=a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0\n" in body

    source["AI_LESSON_CYCLE_DEV_TENANTS"] = '["other-tenant"]'
    with pytest.raises(ValueError, match="source_tenant_scope_invalid"):
        receiver.build_payload_from_render_values(source, RELEASE)


@pytest.mark.parametrize(
    "database",
    (
        "postgresql+asyncpg://lms_app:secret@db.devproject.supabase.co:5432/postgres",
        "postgresql+asyncpg://lms_app.devproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    ),
)
def test_receiver_accepts_runtime_lms_app_direct_and_pooler_identities(database: str) -> None:
    body = payload(database=database)
    result = receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())
    assert result["release_sha"] == RELEASE


@pytest.mark.parametrize(
    "database",
    (
        "postgresql+asyncpg://postgres.devproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
        "postgresql+asyncpg://postgres:secret@db.devproject.supabase.co:5432/postgres",
    ),
)
def test_receiver_rejects_privileged_database_identity(database: str) -> None:
    body = payload(database=database)
    with pytest.raises(ValueError, match="database_scope_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())


@pytest.mark.skipif(os.name == "nt", reason="symlink permission requires Linux receiver integration")
def test_receiver_rejects_symlinked_parent_before_creation(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(PermissionError, match="receiver_symlink_path_invalid"):
        receiver.install_payload(payload(), RELEASE, hashlib.sha256(payload()).hexdigest(), linked / "releases", require_root=False)


def test_receiver_never_overwrites_different_existing_release_file(tmp_path: Path) -> None:
    body = payload()
    target = tmp_path / RELEASE / "runtime.env"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different\n")
    with pytest.raises(FileExistsError, match="different_environment_already_installed"):
        receiver.install_payload(body, RELEASE, hashlib.sha256(body).hexdigest(), tmp_path, require_root=False)


def test_receiver_rejects_symlink_target_and_newline_injection(tmp_path: Path) -> None:
    body = payload() + b"DEV_MODEL_SSH_ROLE=worker\n"
    target = tmp_path / RELEASE / "runtime.env"
    target.parent.mkdir(parents=True)
    if os.name == "nt":
        pytest.skip("symlink permission requires Linux receiver integration")
    target.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())
    with pytest.raises(FileExistsError):
        receiver.install_payload(payload(), RELEASE, hashlib.sha256(payload()).hexdigest(), tmp_path, require_root=False)


def test_stage_verifies_hostname_receiver_hash_and_does_not_put_payload_in_command() -> None:
    body = payload()
    receiver_sha = "c" * 64
    commands: list[tuple[str, bytes]] = []

    def runner(command: str, sent: bytes) -> StageResult:
        commands.append((command, sent))
        if command.endswith("hostname"):
            return StageResult(0, b"kml\n", b"")
        if "sha256sum" in command:
            return StageResult(0, f"{receiver_sha}  {stage.RECEIVER_PATH}\n".encode(), b"")
        keycount = str(len(body.decode().splitlines()))
        return StageResult(0, b"STATUS|status=installed|release_sha=" + RELEASE.encode() + b"|payload_sha256=" + hashlib.sha256(body).hexdigest().encode() + b"|keycount=" + keycount.encode() + b"\n", b"")

    result = stage.stage_payload(body, RELEASE, receiver_sha, runner)
    assert result["status"] == "installed"
    assert commands[-1][1] == body
    assert all("secret" not in command for command, _ in commands)
    assert "--release-sha" in commands[-1][0]
    assert stage.RECEIVER_PATH in commands[-1][0]
    assert "/opt/kamilya-dev-worker/" in commands[-1][0]
    assert "kz-production" not in commands[-1][0]


def test_stage_rejects_foreign_receiver_hash_or_target_identity() -> None:
    body = payload()

    def bad_runner(command: str, _sent: bytes) -> StageResult:
        if command.endswith("hostname"):
            return StageResult(0, b"other-host\n", b"")
        return StageResult(0, b"", b"")

    with pytest.raises(RuntimeError, match="target_identity_mismatch"):
        stage.stage_payload(body, RELEASE, "c" * 64, bad_runner)


@pytest.mark.parametrize("timeout", (0, 121, True, False))
def test_stage_rejects_unbounded_timeout(timeout) -> None:
    with pytest.raises(ValueError, match="timeout_invalid"):
        stage.stage_payload(payload(), RELEASE, "c" * 64, lambda *_: StageResult(0, b"", b""), timeout=timeout)


def test_stage_rejects_output_noise_or_stderr() -> None:
    body = payload()
    receiver_sha = "c" * 64
    keycount = str(len(body.decode().splitlines()))
    digest = hashlib.sha256(body).hexdigest()

    def noisy_runner(command: str, _sent: bytes) -> StageResult:
        if command.endswith("hostname"):
            return StageResult(0, b"kml\n", b"")
        if "sha256sum" in command:
            return StageResult(0, f"{receiver_sha}  {stage.RECEIVER_PATH}\n".encode(), b"")
        return StageResult(0, f"STATUS|status=installed|release_sha={RELEASE}|payload_sha256={digest}|keycount={keycount}\nnoise\n".encode(), b"")

    with pytest.raises(RuntimeError, match="receiver_output_invalid"):
        stage.stage_payload(body, RELEASE, receiver_sha, noisy_runner)

    def stderr_runner(command: str, sent: bytes) -> StageResult:
        result = noisy_runner(command, sent)
        if not command.endswith("hostname") and "sha256sum" not in command:
            return StageResult(result.exit_code, result.stdout.replace(b"\nnoise\n", b"\n"), b"warning")
        return result

    with pytest.raises(RuntimeError, match="receiver_install_failed"):
        stage.stage_payload(body, RELEASE, receiver_sha, stderr_runner)


def test_receiver_main_suppresses_payload_and_exception_details(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["receiver", "--release-sha", RELEASE, "--expected-payload-sha256", "d" * 64])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"DATABASE_URL=postgresql://secret@example\n")))
    assert receiver.main() == 1
    output = capsys.readouterr().out
    assert output.startswith("STATUS|status=blocked|")
    assert "secret" not in output
    assert "postgres" not in output
