from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-kz-production.yml"
COMPOSE = ROOT / "infra" / "compose" / "kamilya-release-slot.yml"


def _job(text: str, name: str) -> str:
    start = text.index(f"  {name}:")
    rest = text[start + 1 :]
    positions = [rest.find(f"\n  {candidate}:") for candidate in ("build-image", "deploy-production")]
    positions = [value for value in positions if value >= 0]
    end = start + 1 + min(positions) if positions else len(text)
    return text[start:end]


def test_workflow_builds_exact_sha_digest_and_requires_matching_ci() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    build = _job(text, "build-image")
    assert "actual_sha" in build and 'workflow_name' in build and 'conclusion' in build
    assert '[[ "${workflow_name}" == "CI" ]]' in build
    assert '[[ "${conclusion}" == "success" ]]' in build
    assert "apps/api/Dockerfile" in build
    assert "@${{ steps.build.outputs.digest }}" in build
    assert "actions/attest-build-provenance@v2" in build


def test_production_job_is_protected_fixed_runner_without_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    deploy = _job(text, "deploy-production")
    assert "runs-on: [self-hosted, linux, x64, kamilya-production-release]" in deploy
    assert "environment: kz-production" in deploy
    assert "actions/checkout" not in deploy
    assert "/opt/kamilya-release-plane/release_plane.py execute" in deploy
    assert "--confirm-release-id" in deploy
    assert "sudo -n" in deploy


def test_slot_compose_never_runs_migrations_on_api_start() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "alembic upgrade" not in text
    assert "KAMILYA_API_IMAGE" in text
    assert "KAMILYA_SLOT_PORT" in text
    assert "external: true" in text
    assert text.count("<<: *app-runtime") == 4
