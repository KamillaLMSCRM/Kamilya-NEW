import re
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


def test_build_only_creates_image_evidence_without_release_manifest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    build = _job(text, "build-image")
    assert 'name: release-image-${{ env.RELEASE_SHA }}' in build
    assert 'path: release-image.json' in build
    assert '"ci_run_id": os.environ["CI_RUN_ID"]' in build
    assert "Create strict release manifest\n        if: ${{ inputs.deploy_to_production }}" in build
    assert "name: release-manifest-${{ inputs.release_sha }}\n          path: release-manifest.json" in build
    assert build.count("if: ${{ inputs.deploy_to_production }}") == 2


def test_successful_master_ci_automatically_builds_but_never_deploys() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    build = _job(text, "build-image")
    deploy = _job(text, "deploy-production")
    assert 'workflow_run:\n    workflows: ["CI"]\n    types: [completed]' in text
    assert "github.event.workflow_run.conclusion == 'success'" in build
    assert "github.event.workflow_run.head_branch == 'master'" in build
    assert "github.event.workflow_run.id || inputs.ci_run_id" in build
    assert "github.event.workflow_run.head_sha || inputs.release_sha" in build
    assert "ref: ${{ env.RELEASE_SHA }}" in build
    assert "tags: ${{ steps.image.outputs.name }}:${{ env.RELEASE_SHA }}" in build
    assert "github.event_name == 'workflow_dispatch' && inputs.deploy_to_production" in deploy


def test_previous_runtime_identity_is_optional_until_production_deploy() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    inputs = text[: text.index("\npermissions:")]
    assert "previous_release_sha:" in inputs
    assert "previous_image:" in inputs
    for name in ("previous_release_sha", "previous_image"):
        match = re.search(rf"(?ms)^      {name}:\n(?P<body>(?:        .*\n)+)", inputs)
        assert match is not None
        assert "required: false" in match.group("body")
    deploy = _job(text, "deploy-production")
    assert "github.event_name == 'workflow_dispatch' && inputs.deploy_to_production" in deploy


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
