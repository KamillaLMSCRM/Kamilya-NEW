from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[4]


def test_application_settings_do_not_embed_unused_minio_credentials() -> None:
    source = (REPO_ROOT / "apps" / "api" / "app" / "core" / "config.py").read_text(
        encoding="utf-8"
    )

    assert "MINIO_ACCESS_KEY" not in source
    assert "MINIO_SECRET_KEY" not in source


def test_local_minio_requires_operator_supplied_root_credentials() -> None:
    source = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "minioadmin" not in source.lower()
    assert "MINIO_ROOT_USER: ${MINIO_ROOT_USER:?set MINIO_ROOT_USER}" in source
    assert "MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:?set MINIO_ROOT_PASSWORD}" in source
