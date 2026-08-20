from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[4]


def test_docling_runtime_is_non_root_fail_closed_and_hardened():
    dockerfile = (REPO_ROOT / "infra" / "docling-service" / "Dockerfile").read_text(encoding="utf-8")
    unit = (REPO_ROOT / "infra" / "docling-service" / "docling.service").read_text(encoding="utf-8")
    source = (REPO_ROOT / "infra" / "docling-service" / "main.py").read_text(encoding="utf-8")

    assert "USER docling" in dockerfile
    assert "DOCLING_ENV=production" in dockerfile
    assert "User=docling" in unit
    assert "Environment=DOCLING_ENV=production" in unit
    assert "EnvironmentFile=/opt/docling-service/.env" in unit
    assert "StateDirectory=docling" in unit
    assert "UMask=0077" in unit
    assert "MemoryMax=8G" in unit
    assert "CPUQuota=400%" in unit
    assert "TasksMax=256" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "if DOCLING_API_KEY and" not in source
    assert "validate_runtime_config" in source
    assert "preflight_ooxml" in source


def test_api_upload_uses_spooled_stream_and_archive_preflight():
    router = (REPO_ROOT / "apps" / "api" / "app" / "modules" / "documents" / "router.py").read_text(
        encoding="utf-8"
    )
    storage = (REPO_ROOT / "apps" / "api" / "app" / "core" / "storage" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert "await file.read()" not in router
    assert "while chunk := await file.read(UPLOAD_CHUNK_BYTES)" in router
    assert "preflight_ooxml" in router
    assert "put_file" in storage
