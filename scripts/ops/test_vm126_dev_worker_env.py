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


def payload(
    release: str = RELEASE,
    *,
    database: str = "postgresql+asyncpg://lms_app.devproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    redis: str = "rediss://:secret@173.249.51.164:6380/1",
) -> bytes:
    return (
        "\n".join(
            [
                "DEPLOYMENT_ENVIRONMENT=vm-development-worker",
                f"DATABASE_URL={database}",
                f"REDIS_URL={redis}",
                f"RELEASE_SHA={release}",
                "DEV_MODEL_SSH_ROLE=worker",
                "AI_DIRECT_LUNA_QA_API_KEY=secret",
                "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION=fixture",
                "AI_DIRECT_LUNA_QA_DEV_ENABLED=true",
                "AI_MANAGED_LUNA_QA_DEV_ENABLED=false",
                "AI_LESSON_CYCLE_DEV_ENABLED=true",
                'AI_LESSON_CYCLE_DEV_TENANTS=["a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"]',
                "AI_QA_LUNA_DEV_ENABLED=true",
                "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=true",
                "APP_ENV=development",
                "DB_MAX_OVERFLOW=0",
                "DB_POOL_SIZE=2",
                "DB_POOL_TIMEOUT=30",
                "DB_POOL_RECYCLE_SECONDS=300",
                "JWT_ALGORITHM=HS256",
                "JWT_SECRET=" + "x" * 48,
                "MASTER_ENCRYPTION_KEY=secret",
                "PROVIDER_KEY_ENCRYPTION_KEY=secret",
                "REDIS_TLS_VERIFY=true",
                "SUPABASE_BUCKET=documents",
                "SUPABASE_KEY=secret",
                "SUPABASE_URL=https://devproject.supabase.co",
                "CELERY_QUEUES=ai,documents,maintenance",
                "CELERY_CONCURRENCY=1",
            ]
        )
        + "\n"
    ).encode()


def native_payload(release: str = RELEASE) -> bytes:
    values = dict(line.split("=", 1) for line in payload(release).decode().splitlines())
    for key in ("AI_DIRECT_LUNA_QA_API_KEY", "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION"):
        values.pop(key)
    values.update(
        {
            "AI_DIRECT_LUNA_QA_DEV_ENABLED": "false",
            "AI_MANAGED_LUNA_QA_DEV_ENABLED": "false",
            "AI_QA_LUNA_DEV_ENABLED": "false",
            "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED": "false",
        }
    )
    return ("".join(f"{key}={values[key]}\n" for key in sorted(values))).encode()


def test_receiver_validates_dev_identity_and_idempotent_install(tmp_path: Path) -> None:
    body = payload()
    digest = hashlib.sha256(body).hexdigest()
    first = receiver.install_payload(
        body, RELEASE, digest, tmp_path, require_root=False
    )
    second = receiver.install_payload(
        body, RELEASE, digest, tmp_path, require_root=False
    )
    assert first["status"] == "installed"
    assert second["status"] == "already_present"
    assert (tmp_path / RELEASE / "runtime.env").read_bytes() == body


def test_receiver_accepts_explicit_native_provider_mode(tmp_path: Path) -> None:
    body = native_payload()
    digest = hashlib.sha256(body).hexdigest()
    result = receiver.validate_payload(body, RELEASE, digest)
    assert result["release_sha"] == RELEASE
    assert (
        receiver.install_payload(body, RELEASE, digest, tmp_path, require_root=False)[
            "status"
        ]
        == "installed"
    )


def test_receiver_rejects_mixed_native_provider_flags() -> None:
    body = native_payload().replace(
        b"AI_MANAGED_LUNA_QA_DEV_ENABLED=false\n",
        b"AI_MANAGED_LUNA_QA_DEV_ENABLED=true\n",
    )
    with pytest.raises(ValueError, match="luna_mode_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())


@pytest.mark.parametrize(
    "body",
    (
        payload(database="postgresql://lms_app:x@other.supabase.co:5432/postgres"),
        payload(redis="redis://173.249.51.164:6379/0"),
        payload().replace(
            f"RELEASE_SHA={RELEASE}".encode(), f"RELEASE_SHA={'b' * 40}".encode()
        ),
        payload() + b"UNKNOWN=value\n",
        payload() + b"AI_GENERATION_V2_ENABLED=true\n",
        payload() + b"BAD=value\n",
    ),
)
def test_receiver_rejects_foreign_scope_or_malformed_env(
    body: bytes, tmp_path: Path
) -> None:
    with pytest.raises((ValueError, FileExistsError)):
        receiver.install_payload(
            body,
            RELEASE,
            hashlib.sha256(body).hexdigest(),
            tmp_path,
            require_root=False,
        )


def test_receiver_requires_runtime_keys_even_when_unrelated_key_is_present() -> None:
    body = (
        payload().replace(b"JWT_SECRET=" + b"x" * 48 + b"\n", b"")
        + b"UNRELATED_RUNTIME=value\n"
    )
    with pytest.raises(ValueError, match="dotenv_key_or_value_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())

    body = payload().replace(b"JWT_SECRET=" + b"x" * 48 + b"\n", b"")
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
    assert (
        b'AI_LESSON_CYCLE_DEV_TENANTS=["a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"]\n'
        in body
    )

    source["AI_LESSON_CYCLE_DEV_TENANTS"] = '["other-tenant"]'
    with pytest.raises(ValueError, match="source_tenant_scope_invalid"):
        receiver.build_payload_from_render_values(source, RELEASE)


def test_build_payload_native_mode_preserves_approved_reserve_config(capsys) -> None:
    source = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in native_payload().decode().splitlines()
    }
    source["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    source.update(
        {
            "AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION": "reserve-v1",
            "CHATGPT_RESERVE_URL": "http://127.0.0.1:18999/v1",
            "CHATGPT_RESERVE_TOKEN": "private-token",
            "CHATGPT_RESERVE_MODEL": "gpt-5.6-luna",
            "CHATGPT_RESERVE_AUTH_MODE": "codex_cli",
        }
    )
    body = receiver.build_payload_from_render_values(
        source, RELEASE, native_mode=True, isolated_managed_connector=True
    )
    assert b"AI_DIRECT_LUNA_QA_DEV_ENABLED=false\n" in body
    assert b"AI_MANAGED_LUNA_QA_DEV_ENABLED=false\n" in body
    assert b"AI_QA_LUNA_DEV_ENABLED=false\n" in body
    assert b"AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=false\n" in body
    assert b"CHATGPT_RESERVE_URL=http://172.17.0.1:19000/v1\n" in body
    assert source["CHATGPT_RESERVE_URL"] == "http://127.0.0.1:18999/v1"
    assert b"CHATGPT_RESERVE_MODEL=gpt-5.6-luna\n" in body
    from unittest.mock import patch

    from app.core.config import Settings

    runtime_values = dict(line.split("=", 1) for line in body.decode().splitlines())
    with patch.dict(os.environ, runtime_values, clear=True):
        settings = Settings(_env_file=None)
    assert settings.DEPLOYMENT_ENVIRONMENT == "vm-development-worker"
    assert runtime_values["CHATGPT_RESERVE_AUTH_MODE"] == "codex_cli"
    assert runtime_values["CHATGPT_RESERVE_TOKEN"] == "private-token"
    assert capsys.readouterr().out == ""
    with pytest.raises(ValueError, match="native_connector_mapping_required"):
        receiver.build_payload_from_render_values(source, RELEASE, native_mode=True)
    loopback_body = body.replace(
        b"http://172.17.0.1:19000/v1", b"http://127.0.0.1:18999/v1"
    )
    with pytest.raises(ValueError, match="luna_mode_invalid"):
        receiver.validate_payload(
            loopback_body, RELEASE, hashlib.sha256(loopback_body).hexdigest()
        )
    source["AI_QA_LUNA_DEV_ENABLED"] = "true"
    with pytest.raises(ValueError, match="source_native_flags_invalid"):
        receiver.build_payload_from_render_values(source, RELEASE, native_mode=True)


@pytest.mark.parametrize("value", (1, "false", None))
def test_native_mode_requires_strict_boolean(value) -> None:
    source = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in native_payload().decode().splitlines()
    }
    source["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    with pytest.raises(ValueError, match="mode_type_invalid"):
        receiver.build_payload_from_render_values(source, RELEASE, native_mode=value)


@pytest.mark.parametrize(
    "database",
    (
        "postgresql+asyncpg://lms_app:secret@db.devproject.supabase.co:5432/postgres",
        "postgresql+asyncpg://lms_app.devproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    ),
)
def test_receiver_accepts_runtime_lms_app_direct_and_pooler_identities(
    database: str,
) -> None:
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


@pytest.mark.skipif(
    os.name == "nt", reason="symlink permission requires Linux receiver integration"
)
def test_receiver_rejects_symlinked_parent_before_creation(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(PermissionError, match="receiver_symlink_path_invalid"):
        receiver.install_payload(
            payload(),
            RELEASE,
            hashlib.sha256(payload()).hexdigest(),
            linked / "releases",
            require_root=False,
        )


def test_receiver_never_overwrites_different_existing_release_file(
    tmp_path: Path,
) -> None:
    body = payload()
    target = tmp_path / RELEASE / "runtime.env"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different\n")
    with pytest.raises(
        FileExistsError, match="different_environment_already_installed"
    ):
        receiver.install_payload(
            body,
            RELEASE,
            hashlib.sha256(body).hexdigest(),
            tmp_path,
            require_root=False,
        )


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
        receiver.install_payload(
            payload(),
            RELEASE,
            hashlib.sha256(payload()).hexdigest(),
            tmp_path,
            require_root=False,
        )


def test_stage_verifies_hostname_receiver_hash_and_does_not_put_payload_in_command() -> (
    None
):
    body = payload()
    receiver_sha = stage.RECEIVER_SHA
    commands: list[tuple[str, bytes]] = []

    def runner(command: str, sent: bytes) -> StageResult:
        commands.append((command, sent))
        if command.endswith("hostname"):
            return StageResult(0, b"kml\n", b"")
        if "sha256sum" in command:
            return StageResult(
                0, f"{receiver_sha}  {stage.RECEIVER_PATH}\n".encode(), b""
            )
        keycount = str(len(body.decode().splitlines()))
        return StageResult(
            0,
            b"STATUS|status=installed|release_sha="
            + RELEASE.encode()
            + b"|payload_sha256="
            + hashlib.sha256(body).hexdigest().encode()
            + b"|keycount="
            + keycount.encode()
            + b"\n",
            b"",
        )

    result = stage.stage_payload(body, RELEASE, receiver_sha, runner)
    assert result["status"] == "installed"
    assert commands[-1][1] == body
    assert all("secret" not in command for command, _ in commands)
    assert "--release-sha" in commands[-1][0]
    assert stage.RECEIVER_PATH in commands[-1][0]
    assert "/opt/kamilya-dev-worker/" in commands[-1][0]
    assert "kz-production" not in commands[-1][0]


def test_stage_selects_v5_receiver_for_native_mode() -> None:
    body = native_payload()
    commands: list[str] = []

    def runner(command: str, _sent: bytes) -> StageResult:
        commands.append(command)
        if command.endswith("hostname"):
            return StageResult(0, b"kml\n", b"")
        if "sha256sum" in command:
            return StageResult(
                0, f"{stage.RECEIVER_SHA_V5}  {stage.RECEIVER_PATH_V5}\n".encode(), b""
            )
        keycount = str(len(body.decode().splitlines()))
        digest = hashlib.sha256(body).hexdigest()
        return StageResult(
            0,
            f"STATUS|status=installed|release_sha={RELEASE}|payload_sha256={digest}|keycount={keycount}\n".encode(),
            b"",
        )

    result = stage.stage_payload(body, RELEASE, stage.RECEIVER_SHA_V5, runner)
    assert result["status"] == "installed"
    assert stage.RECEIVER_PATH_V5 in commands[-1]


def test_stage_rejects_foreign_receiver_hash_or_target_identity() -> None:
    body = payload()

    def bad_runner(command: str, _sent: bytes) -> StageResult:
        if command.endswith("hostname"):
            return StageResult(0, b"other-host\n", b"")
        return StageResult(0, b"", b"")

    with pytest.raises(RuntimeError, match="target_identity_mismatch"):
        stage.stage_payload(body, RELEASE, stage.RECEIVER_SHA, bad_runner)


@pytest.mark.parametrize("timeout", (0, 121, True, False))
def test_stage_rejects_unbounded_timeout(timeout) -> None:
    with pytest.raises(ValueError, match="timeout_invalid"):
        stage.stage_payload(
            payload(),
            RELEASE,
            "c" * 64,
            lambda *_: StageResult(0, b"", b""),
            timeout=timeout,
        )


def test_stage_rejects_output_noise_or_stderr() -> None:
    body = payload()
    receiver_sha = stage.RECEIVER_SHA
    keycount = str(len(body.decode().splitlines()))
    digest = hashlib.sha256(body).hexdigest()

    def noisy_runner(command: str, _sent: bytes) -> StageResult:
        if command.endswith("hostname"):
            return StageResult(0, b"kml\n", b"")
        if "sha256sum" in command:
            return StageResult(
                0, f"{receiver_sha}  {stage.RECEIVER_PATH}\n".encode(), b""
            )
        return StageResult(
            0,
            f"STATUS|status=installed|release_sha={RELEASE}|payload_sha256={digest}|keycount={keycount}\nnoise\n".encode(),
            b"",
        )

    with pytest.raises(RuntimeError, match="receiver_output_invalid"):
        stage.stage_payload(body, RELEASE, receiver_sha, noisy_runner)

    def stderr_runner(command: str, sent: bytes) -> StageResult:
        result = noisy_runner(command, sent)
        if not command.endswith("hostname") and "sha256sum" not in command:
            return StageResult(
                result.exit_code, result.stdout.replace(b"\nnoise\n", b"\n"), b"warning"
            )
        return result

    with pytest.raises(RuntimeError, match="receiver_install_failed"):
        stage.stage_payload(body, RELEASE, receiver_sha, stderr_runner)


def test_receiver_main_suppresses_payload_and_exception_details(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["receiver", "--release-sha", RELEASE, "--expected-payload-sha256", "d" * 64],
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO(b"DATABASE_URL=postgresql://secret@example\n")),
    )
    assert receiver.main() == 1
    output = capsys.readouterr().out
    assert output.startswith("STATUS|status=blocked|")
    assert "secret" not in output
    assert "postgres" not in output


def test_staged_environment_is_parseable_by_real_worker_settings():
    from unittest.mock import patch
    from app.core.config import Settings

    values = dict(line.split("=", 1) for line in payload().decode().splitlines())
    values["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    body = receiver.build_payload_from_render_values(values, RELEASE)
    runtime_values = dict(line.split("=", 1) for line in body.decode().splitlines())
    with patch.dict(os.environ, runtime_values, clear=True):
        actual = Settings(_env_file=None)
    assert actual.DEPLOYMENT_ENVIRONMENT == "vm-development-worker"


def managed_payload() -> bytes:
    return (
        payload()
        .replace(b"AI_DIRECT_LUNA_QA_API_KEY=secret\n", b"")
        .replace(b"AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION=fixture\n", b"")
        .replace(
            b"AI_DIRECT_LUNA_QA_DEV_ENABLED=true\n",
            b"AI_DIRECT_LUNA_QA_DEV_ENABLED=false\n",
        )
        .replace(
            b"AI_MANAGED_LUNA_QA_DEV_ENABLED=false\n",
            b"AI_MANAGED_LUNA_QA_DEV_ENABLED=true\n",
        )
        + b"AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION=managed-v1\n"
        + b"CHATGPT_RESERVE_URL=http://127.0.0.1:18999/v1\n"
        + b"CHATGPT_RESERVE_TOKEN=synthetic\n"
        + b"CHATGPT_RESERVE_MODEL=gpt-5.6-luna\n"
        + b"CHATGPT_RESERVE_AUTH_MODE=codex_cli\n"
    )


def test_managed_payload_and_render_source_are_scoped_and_omit_direct_secrets() -> None:
    body = managed_payload()
    receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())
    source = dict(line.split("=", 1) for line in body.decode().splitlines())
    source["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    result = receiver.build_payload_from_render_values(source, RELEASE)
    assert b"AI_DIRECT_LUNA_QA_API_KEY=" not in result
    assert b"AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION=" not in result
    assert b"CHATGPT_RESERVE_MODEL=gpt-5.6-luna\n" in result


@pytest.mark.parametrize(
    "body",
    [
        managed_payload().replace(
            b"AI_DIRECT_LUNA_QA_DEV_ENABLED=false",
            b"AI_DIRECT_LUNA_QA_DEV_ENABLED=true",
        ),
        managed_payload().replace(
            b"AI_MANAGED_LUNA_QA_DEV_ENABLED=true",
            b"AI_MANAGED_LUNA_QA_DEV_ENABLED=false",
        ),
        managed_payload().replace(
            b"AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION=managed-v1\n", b""
        ),
        managed_payload().replace(
            b"http://127.0.0.1:18999/v1", b"http://127.0.0.2:18999/v1"
        ),
        managed_payload() + b"AI_DIRECT_LUNA_QA_API_KEY=secret\n",
        managed_payload().replace(b"CHATGPT_RESERVE_TOKEN=synthetic\n", b""),
        managed_payload().replace(
            b"CHATGPT_RESERVE_AUTH_MODE=codex_cli",
            b"CHATGPT_RESERVE_AUTH_MODE=unconfigured",
        ),
    ],
)
def test_managed_mode_rejects_invalid_scope(body: bytes) -> None:
    with pytest.raises(ValueError, match="luna_mode_invalid"):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())
    source = dict(line.split("=", 1) for line in body.decode().splitlines())
    source["DEPLOYMENT_ENVIRONMENT"] = "render-development-worker"
    with pytest.raises(ValueError, match="luna_mode_invalid"):
        receiver.build_payload_from_render_values(source, RELEASE)


def test_managed_stage_selects_v3_and_rejects_wrong_hash_before_remote() -> None:
    body = managed_payload()
    calls = []

    def runner(command, data):
        calls.append((command, data))
        if "hostname" in command:
            return StageResult(0, stage.VM126.expected_hostname.encode(), b"")
        if "sha256sum" in command:
            return StageResult(
                0, f"{stage.RECEIVER_SHA_V3}  {stage.RECEIVER_PATH_V3}\n".encode(), b""
            )
        return StageResult(
            0,
            f"STATUS|status=installed|release_sha={RELEASE}|payload_sha256={hashlib.sha256(body).hexdigest()}|keycount={len(body.splitlines())}\n".encode(),
            b"",
        )

    stage.stage_payload(body, RELEASE, stage.RECEIVER_SHA_V3, runner)
    assert (
        stage.RECEIVER_PATH_V3 in calls[1][0] and stage.RECEIVER_PATH_V3 in calls[2][0]
    )
    calls.clear()
    with pytest.raises(ValueError, match="receiver_identity_invalid"):
        stage.stage_payload(body, RELEASE, "0" * 64, runner)
    assert not calls


def test_direct_stage_rejects_wrong_receiver_hash_before_remote() -> None:
    calls = []

    def runner(command, data):
        calls.append((command, data))
        return StageResult(0, b"", b"")

    with pytest.raises(ValueError, match="receiver_identity_invalid"):
        stage.stage_payload(payload(), RELEASE, "0" * 64, runner)
    assert calls == []
