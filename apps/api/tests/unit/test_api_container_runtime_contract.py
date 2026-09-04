from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[4]
API_DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"
RELEASE_COMPOSE_FILES = (
    REPO_ROOT / "infra" / "compose" / "kamilya-release-slot.yml",
    REPO_ROOT / "infra" / "compose" / "kamilya-app-worker.yml",
)


def test_api_image_runs_as_a_fixed_unprivileged_identity() -> None:
    source = API_DOCKERFILE.read_text(encoding="utf-8")

    assert "groupadd --system --gid 10001 kamilya" in source
    assert "useradd --system --uid 10001 --gid kamilya" in source
    assert "--shell /usr/sbin/nologin" in source
    assert "ENV HOME=/home/kamilya" in source
    assert "ENV PYTHONDONTWRITEBYTECODE=1" in source
    assert 'ENV PATH="/app/.venv/bin:$PATH"' in source
    assert "USER 10001:10001" in source
    assert source.index("USER 10001:10001") < source.index("CMD [")


def test_api_image_keeps_application_and_virtualenv_root_owned() -> None:
    source = API_DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY --chown" not in source
    assert source.index("COPY apps/api/ .") < source.index("USER 10001:10001")
    assert source.index("poetry install") < source.index("USER 10001:10001")


def test_release_services_drop_privilege_and_make_rootfs_read_only() -> None:
    for compose_file in RELEASE_COMPOSE_FILES:
        source = compose_file.read_text(encoding="utf-8")

        assert 'user: "10001:10001"' in source
        assert "read_only: true" in source
        assert "cap_drop:" in source and "- ALL" in source
        assert "security_opt:" in source and "- no-new-privileges:true" in source
        assert "tmpfs:" in source and "/tmp:rw,noexec,nosuid,nodev" in source
        assert '["poetry", "run"' not in source
