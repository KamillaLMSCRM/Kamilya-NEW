"""Fail-closed VM126 receiver for one DEV worker environment file."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import tempfile
import json
from pathlib import Path
from urllib.parse import urlsplit

MAX_PAYLOAD_BYTES = 64 * 1024
DATABASE_PROJECT_FINGERPRINT = (
    "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"
)
REDIS_HOST = "173.249.51.164"
REDIS_PORT = 6380
REDIS_DB = "/1"
ISOLATED_MANAGED_CONNECTOR_URL = "http://172.17.0.1:19000/v1"
VERSION = "v6"
ENV_DIRECTORY = "env-v6"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
VALUE_RE = re.compile(r"^[^\x00\r\n]+$")
RELEASE_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_KEYS = frozenset(
    {
        "AI_DIRECT_LUNA_QA_API_KEY",
        "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION",
        "AI_DIRECT_LUNA_QA_DEV_ENABLED",
        "AI_MANAGED_LUNA_QA_DEV_ENABLED",
        "AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION",
        "CHATGPT_RESERVE_URL",
        "CHATGPT_RESERVE_TOKEN",
        "CHATGPT_RESERVE_MODEL",
        "CHATGPT_RESERVE_AUTH_MODE",
        "AI_LESSON_CYCLE_DEV_ENABLED",
        "AI_LESSON_CYCLE_DEV_TENANTS",
        "AI_QA_LUNA_DEV_ENABLED",
        "AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED",
        "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED",
        "APP_ENV",
        "DATABASE_URL",
        "DB_MAX_OVERFLOW",
        "DB_POOL_SIZE",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE_SECONDS",
        "DEPLOYMENT_ENVIRONMENT",
        "DEV_MODEL_SSH_ENABLED",
        "DEV_MODEL_SSH_KEY_B64",
        "DEV_MODEL_SSH_KNOWN_HOST",
        "DEV_MODEL_SSH_ROLE",
        "DEV_OCR_SSH_ENABLED",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DOCLING_API_KEY",
        "DOCLING_TIMEOUT_SECONDS",
        "JWT_ALGORITHM",
        "JWT_SECRET",
        "MASTER_ENCRYPTION_KEY",
        "METHODOLOGIST_DOCUMENT_DRAFT_ENABLED",
        "METHODOLOGIST_LESSON_CORRECTION_ENABLED",
        "METHODOLOGIST_WORKBENCH_ENABLED",
        "PROVIDER_KEY_ENCRYPTION_KEY",
        "REDIS_TLS_VERIFY",
        "REDIS_URL",
        "RELEASE_SHA",
        "STAFF_STRUCTURE_V3_ENABLED",
        "STORAGE_BACKEND",
        "SUPABASE_BUCKET",
        "SUPABASE_KEY",
        "SUPABASE_URL",
        "CELERY_QUEUES",
        "CELERY_CONCURRENCY",
    }
)
REQUIRED_KEYS = frozenset(
    {
        "AI_DIRECT_LUNA_QA_DEV_ENABLED",
        "AI_MANAGED_LUNA_QA_DEV_ENABLED",
        "AI_LESSON_CYCLE_DEV_ENABLED",
        "AI_LESSON_CYCLE_DEV_TENANTS",
        "AI_QA_LUNA_DEV_ENABLED",
        "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED",
        "APP_ENV",
        "DATABASE_URL",
        "DB_MAX_OVERFLOW",
        "DB_POOL_SIZE",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE_SECONDS",
        "DEPLOYMENT_ENVIRONMENT",
        "JWT_ALGORITHM",
        "JWT_SECRET",
        "MASTER_ENCRYPTION_KEY",
        "PROVIDER_KEY_ENCRYPTION_KEY",
        "REDIS_TLS_VERIFY",
        "REDIS_URL",
        "RELEASE_SHA",
        "SUPABASE_BUCKET",
        "SUPABASE_KEY",
        "SUPABASE_URL",
        "CELERY_QUEUES",
        "CELERY_CONCURRENCY",
    }
)


def _supabase_project_ref(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.supabase\.co", host):
        raise ValueError("database_scope_invalid")
    return host.split(".", 1)[0]


def _database_project_ref(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    username = parsed.username or ""
    if (
        parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}
        or not host
    ):
        raise ValueError("database_scope_invalid")
    if (
        host.startswith("db.")
        and host.endswith(".supabase.co")
        and username == "lms_app"
    ):
        return host.split(".", 2)[1]
    if host.endswith(".pooler.supabase.com") and username.startswith("lms_app."):
        ref = username.split(".", 1)[1]
        if re.fullmatch(r"[a-z0-9-]{8,}", ref):
            return ref
    raise ValueError("database_scope_invalid")


def _validate_luna_mode(values: dict[str, str]) -> None:
    direct = values.get("AI_DIRECT_LUNA_QA_DEV_ENABLED")
    managed = values.get("AI_MANAGED_LUNA_QA_DEV_ENABLED", "false")
    qa = values.get("AI_QA_LUNA_DEV_ENABLED")
    pending = values.get("AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED")
    if (
        direct == "false"
        and managed == "false"
        and qa == "false"
        and pending == "false"
    ):
        if any(
            key in values
            for key in (
                "AI_DIRECT_LUNA_QA_API_KEY",
                "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION",
            )
        ):
            raise ValueError("luna_mode_invalid")
        reserve_keys = {
            "CHATGPT_RESERVE_URL",
            "CHATGPT_RESERVE_TOKEN",
            "CHATGPT_RESERVE_MODEL",
            "CHATGPT_RESERVE_AUTH_MODE",
            "AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION",
        }
        present = {key for key in reserve_keys if values.get(key)}
        if present and (
            present != reserve_keys
            or values.get("CHATGPT_RESERVE_MODEL") != "gpt-5.6-luna"
            or values.get("CHATGPT_RESERVE_AUTH_MODE") != "codex_cli"
            or values.get("CHATGPT_RESERVE_URL")
            not in (
                {ISOLATED_MANAGED_CONNECTOR_URL}
                if values.get("DEPLOYMENT_ENVIRONMENT") == "vm-development-worker"
                else {"http://127.0.0.1:18999/v1"}
            )
        ):
            raise ValueError("luna_mode_invalid")
    elif direct == "true" and managed == "false":
        if not values.get("AI_DIRECT_LUNA_QA_API_KEY") or not values.get(
            "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION"
        ):
            raise ValueError("luna_mode_invalid")
    elif direct == "false" and managed == "true":
        if any(
            key in values
            for key in (
                "AI_DIRECT_LUNA_QA_API_KEY",
                "AI_DIRECT_LUNA_QA_CREDENTIAL_REVISION",
            )
        ):
            raise ValueError("luna_mode_invalid")
        if (
            not values.get("AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION")
            or not values.get("CHATGPT_RESERVE_TOKEN")
            or values.get("CHATGPT_RESERVE_URL")
            not in (
                {"http://127.0.0.1:18999/v1", ISOLATED_MANAGED_CONNECTOR_URL}
                if values.get("DEPLOYMENT_ENVIRONMENT") == "vm-development-worker"
                else {"http://127.0.0.1:18999/v1"}
            )
            or values.get("CHATGPT_RESERVE_MODEL") != "gpt-5.6-luna"
            or values.get("CHATGPT_RESERVE_AUTH_MODE") != "codex_cli"
        ):
            raise ValueError("luna_mode_invalid")
    else:
        raise ValueError("luna_mode_invalid")


def validate_payload(
    payload: bytes, release_sha: str, expected_hash: str
) -> dict[str, str]:
    if not RELEASE_RE.fullmatch(release_sha) or len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload_scope_invalid")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("payload_hash_mismatch")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("payload_encoding_invalid") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            raise ValueError("dotenv_shape_invalid")
        key, value = line.split("=", 1)
        if (
            key not in ALLOWED_KEYS
            or not KEY_RE.fullmatch(key)
            or key in values
            or not VALUE_RE.fullmatch(value)
        ):
            raise ValueError("dotenv_key_or_value_invalid")
        values[key] = value
    if (
        not REQUIRED_KEYS.issubset(values)
        or values["DEPLOYMENT_ENVIRONMENT"] != "vm-development-worker"
        or values["RELEASE_SHA"] != release_sha
    ):
        raise ValueError("worker_identity_invalid")
    if (
        hashlib.sha256(
            _supabase_project_ref(values["SUPABASE_URL"]).encode("ascii")
        ).hexdigest()
        != DATABASE_PROJECT_FINGERPRINT
    ):
        raise ValueError("supabase_project_invalid")
    if _database_project_ref(values["DATABASE_URL"]) != _supabase_project_ref(
        values["SUPABASE_URL"]
    ):
        raise ValueError("database_project_invalid")
    redis = urlsplit(values["REDIS_URL"])
    if (
        redis.scheme != "rediss"
        or redis.hostname != REDIS_HOST
        or redis.port != REDIS_PORT
        or redis.path != REDIS_DB
        or redis.query
        or redis.fragment
    ):
        raise ValueError("redis_scope_invalid")
    _validate_luna_mode(values)
    native = (
        values.get("AI_DIRECT_LUNA_QA_DEV_ENABLED") == "false"
        and values.get("AI_MANAGED_LUNA_QA_DEV_ENABLED") == "false"
        and values.get("AI_QA_LUNA_DEV_ENABLED") == "false"
        and values.get("AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED") == "false"
    )
    if "AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED" in values and (
        values["AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED"] != "true" or not native
    ):
        raise ValueError("local_deepseek_mode_invalid")
    if (
        values.get("CELERY_QUEUES") != "ai,documents,maintenance"
        or values.get("CELERY_CONCURRENCY") != "1"
        or values.get("AI_LESSON_CYCLE_DEV_ENABLED") != "true"
        or (
            not native
            and (
                values.get("AI_QA_LUNA_DEV_ENABLED") != "true"
                or values.get("AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED") != "true"
            )
        )
        or json.loads(values.get("AI_LESSON_CYCLE_DEV_TENANTS", "null"))
        != ["a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"]
    ):
        raise ValueError("worker_queue_scope_invalid")
    if (
        values.get("DB_POOL_SIZE") != "2"
        or values.get("DB_MAX_OVERFLOW") != "0"
        or values.get("REDIS_TLS_VERIFY") != "true"
    ):
        raise ValueError("worker_runtime_scope_invalid")
    return {
        "release_sha": release_sha,
        "payload_sha256": actual_hash,
        "keycount": str(len(values)),
    }


def build_payload_from_render_values(
    source: dict[str, str],
    release_sha: str,
    *,
    isolated_managed_connector: bool = False,
    native_mode: bool = False,
    local_deepseek: bool = False,
) -> bytes:
    """Normalize an authenticated Render worker snapshot without logging values."""
    if (type(native_mode) is not bool or type(isolated_managed_connector) is not bool
            or type(local_deepseek) is not bool):
        raise ValueError("mode_type_invalid")
    if local_deepseek and not native_mode:
        raise ValueError("local_deepseek_mode_invalid")
    if source.get("DEPLOYMENT_ENVIRONMENT") != "render-development-worker":
        raise ValueError("source_environment_invalid")
    if native_mode:
        if (
            source.get("AI_DIRECT_LUNA_QA_DEV_ENABLED") != "false"
            or source.get("AI_MANAGED_LUNA_QA_DEV_ENABLED") != "false"
            or source.get("AI_QA_LUNA_DEV_ENABLED") != "false"
            or source.get("AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED") != "false"
        ):
            raise ValueError("source_native_flags_invalid")
        _validate_luna_mode(source)
    else:
        _validate_luna_mode(source)
    if (
        isolated_managed_connector
        and source.get("AI_MANAGED_LUNA_QA_DEV_ENABLED") != "true"
        and not (native_mode and source.get("CHATGPT_RESERVE_URL"))
    ):
        raise ValueError("isolated_managed_connector_invalid")
    if native_mode and source.get("CHATGPT_RESERVE_URL") and not isolated_managed_connector:
        raise ValueError("native_connector_mapping_required")
    if source.get("AI_LESSON_CYCLE_DEV_ENABLED") != "true" or (
        not native_mode
        and (
            source.get("AI_QA_LUNA_DEV_ENABLED") != "true"
            or source.get("AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED") != "true"
        )
    ):
        raise ValueError("source_flags_invalid")
    tenants = source.get("AI_LESSON_CYCLE_DEV_TENANTS", "")
    try:
        parsed = json.loads(tenants)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in tenants.split(",") if item.strip()]
    if parsed != ["a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"]:
        raise ValueError("source_tenant_scope_invalid")
    if not RELEASE_RE.fullmatch(release_sha):
        raise ValueError("release_sha_invalid")
    values = {
        key: value
        for key, value in source.items()
        if key in ALLOWED_KEYS and value != ""
    }
    values.update(
        {
            "DEPLOYMENT_ENVIRONMENT": "vm-development-worker",
            "RELEASE_SHA": release_sha,
            "AI_LESSON_CYCLE_DEV_TENANTS": json.dumps(
                ["a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"], separators=(",", ":")
            ),
            "CELERY_QUEUES": "ai,documents,maintenance",
            "CELERY_CONCURRENCY": "1",
        }
    )
    if isolated_managed_connector:
        values["CHATGPT_RESERVE_URL"] = ISOLATED_MANAGED_CONNECTOR_URL
    if local_deepseek:
        values["AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED"] = "true"
    body = "".join(f"{key}={values[key]}\n" for key in sorted(values)).encode()
    validate_payload(body, release_sha, hashlib.sha256(body).hexdigest())
    return body


def _assert_directory(path: Path, require_root: bool) -> None:
    if path.is_symlink():
        raise PermissionError("receiver_symlink_path_invalid")
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    if require_root and (mode != 0o700 or os.lstat(path).st_uid != 0):
        raise PermissionError("receiver_directory_owner_or_mode_invalid")


def _reject_symlink_ancestors(path: Path) -> None:
    """Reject symlinked path components before creating or opening anything."""
    cursor = path
    while True:
        if cursor.is_symlink():
            raise PermissionError("receiver_symlink_path_invalid")
        parent = cursor.parent
        if parent == cursor:
            return
        cursor = parent


def _read_existing(path: Path, payload: bytes, require_root: bool) -> bool:
    if path.is_symlink():
        raise FileExistsError("different_environment_already_installed")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if require_root and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600):
            raise PermissionError("receiver_file_owner_or_mode_invalid")
        existing = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            existing += chunk
    finally:
        os.close(fd)
    if existing != payload:
        raise FileExistsError("different_environment_already_installed")
    return True


def install_payload(
    payload: bytes,
    release_sha: str,
    expected_hash: str,
    root_dir: Path,
    *,
    require_root: bool = True,
) -> dict[str, str]:
    result = validate_payload(payload, release_sha, expected_hash)
    _reject_symlink_ancestors(root_dir)
    root_dir = root_dir.absolute()
    root_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_directory(root_dir, require_root)
    target = root_dir / release_sha / "runtime.env"
    if target.parent.exists() and target.parent.is_symlink():
        raise PermissionError("receiver_release_directory_symlink")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _assert_directory(target.parent, require_root)
    if target.exists() or target.is_symlink():
        _read_existing(target, payload, require_root)
        return {**result, "status": "already_present"}
    fd, temporary = tempfile.mkstemp(prefix=".runtime.env.", dir=str(target.parent))
    temporary_path = Path(temporary)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        elif require_root:
            raise PermissionError("receiver_file_mode_unverifiable")
        else:
            os.chmod(temporary_path, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, target)
        temporary_path.unlink()
    except FileExistsError:
        _read_existing(target, payload, require_root)
        if temporary_path.exists():
            temporary_path.unlink()
        return {**result, "status": "already_present"}
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    if require_root:
        _read_existing(target, payload, require_root)
    return {**result, "status": "installed"}


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--expected-payload-sha256", required=True)
    args = parser.parse_args()
    payload = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
    try:
        result = install_payload(
            payload,
            args.release_sha,
            args.expected_payload_sha256,
            Path("/opt/kamilya-dev-worker/releases") / ENV_DIRECTORY,
        )
        print(
            "STATUS|status={status}|release_sha={release_sha}|payload_sha256={payload_sha256}|keycount={keycount}".format(
                **result
            ),
            flush=True,
        )
        return 0
    except Exception:
        print(
            "STATUS|status=blocked|release_sha=unknown|payload_sha256=unknown|keycount=0",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
