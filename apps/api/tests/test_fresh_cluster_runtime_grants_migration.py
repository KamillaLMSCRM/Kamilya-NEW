from __future__ import annotations

from pathlib import Path

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0109_fresh_cluster_runtime_grants.py"
DOCKERFILE = Path(__file__).parents[1] / "Dockerfile"


def test_fresh_cluster_runtime_grants_are_linear_and_least_privilege() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0109"' in source
    assert 'down_revision = "0108"' in source
    assert "NOSUPERUSER NOBYPASSRLS" in source
    for table in ("tenants", "content_blocks", "questions", "quiz_choices"):
        assert f'"{table}"' in source

    assert "course_assignment_notification_outbox" not in source
    assert "crm_lead_outbox" not in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE" in source


def test_fresh_cluster_runtime_grants_have_a_reversible_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE" in source
    assert "DROP TABLE" not in source


def test_api_dockerfile_uses_the_repository_root_build_context() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY apps/api/pyproject.toml apps/api/poetry.lock* ./" in source
    assert "COPY packages /packages" in source
    assert "poetry install --no-interaction --no-ansi --without dev --no-root" in source
    assert "COPY apps/api/ ." in source
    assert "COPY ../../packages" not in source
    assert "ENV PYTHONPATH=/app" in source
