"""Offline contract checks for the credential-free Codex reserve image workflow."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "build-codex-reserve.yml"
PINNED_ACTIONS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "docker/setup-buildx-action": "8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
    "docker/login-action": "c94ce9fb468520275223c153574b00df6fe4bcc9",
    "docker/build-push-action": "10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
    "actions/attest-build-provenance": "e8998f949152b193b063cb0ec769d69d929409be",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}


def _workflow() -> dict:
    # PyYAML parses the YAML 1.1 ``on`` key as True; normalize only that key.
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_workflow_is_manual_and_has_exact_inputs() -> None:
    data = _workflow()
    assert set(data) == {"name", "on", "permissions", "concurrency", "jobs"}
    assert set(data["on"]) == {"workflow_dispatch"}
    assert set(data["on"]["workflow_dispatch"]["inputs"]) == {"release_sha", "ci_run_id"}
    assert set(data["permissions"]) == {"actions", "attestations", "contents", "id-token", "packages"}
    assert data["permissions"] == {
        "actions": "read", "contents": "read", "packages": "write",
        "attestations": "write", "id-token": "write",
    }


def test_workflow_validates_exact_ci_run_before_checkout() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    source = steps[0]
    assert source["id"] == "source"
    script = source["run"]
    assert "^[0-9a-f]{40}$" in script
    assert "actions/runs/${CI_RUN_ID}" in script
    for expression in (
        '[[ "${DISPATCH_REF}" == "refs/heads/master" ]]',
        '[[ "${run_name}" == "CI" ]]', '[[ "${run_status}" == "completed" ]]',
        '[[ "${run_conclusion}" == "success" ]]', '[[ "${run_sha}" == "${RELEASE_SHA}" ]]',
        '[[ "${expected_workflow_path}" == ".github/workflows/ci.yml" ]]',
        '[[ "${expected_workflow_id}" =~ ^[0-9]+$ ]]',
        '[[ "${run_workflow_id}" == "${expected_workflow_id}" ]]',
        '[[ "${run_path}" == "${expected_workflow_path}" ]]',
        '[[ "${run_repository,,}" == "${REPOSITORY,,}" ]]',
        '[[ "${run_event}" == "push" ]]',
        '[[ "${run_branch}" == "master" ]]',
        '[[ "${branch_sha}" == "${RELEASE_SHA}" ]]',
    ):
        assert expression in script
    assert 'actions/workflows/ci.yml' in script
    assert 'branches/${run_branch}' in script
    assert "branch_protected" not in script
    assert steps[1]["uses"] == f"actions/checkout@{PINNED_ACTIONS['actions/checkout']}"
    assert steps[1]["with"]["ref"] == "${{ steps.source.outputs.release_sha }}"


def test_every_action_is_pinned_to_verified_full_commit() -> None:
    uses = [step["uses"] for step in _workflow()["jobs"]["build"]["steps"] if "uses" in step]
    assert set(uses) == {f"{action}@{sha}" for action, sha in PINNED_ACTIONS.items()}
    assert all(re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+@[0-9a-f]{40}", value) for value in uses)


def test_workflow_uses_lowercase_immutable_private_image_and_attestation() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    image_step = next(step for step in steps if step.get("id") == "image")
    assert 'owner="${OWNER,,}"' in image_step["run"]
    assert 'ghcr.io/${owner}/kamilya-codex-reserve' in image_step["run"]
    build = next(step for step in steps if step.get("id") == "build")
    assert build["uses"] == f"docker/build-push-action@{PINNED_ACTIONS['docker/build-push-action']}"
    assert build["with"]["context"] == "infra/codex-reserve"
    assert build["with"]["file"] == "infra/codex-reserve/Dockerfile"
    assert build["with"]["push"] is True
    assert "${{ steps.image.outputs.name }}:${{ steps.image.outputs.tag }}" in build["with"]["tags"]
    attestation = next(step for step in steps if step.get("uses", "").startswith("actions/attest-build-provenance@"))
    assert attestation["with"]["push-to-registry"] is True


def test_hardening_check_has_no_network_auth_cache_or_application_env() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    verify = next(step for step in steps if step.get("name", "").startswith("Verify image identity"))
    script = verify["run"]
    assert "--network none" in script and "--read-only" in script
    assert 'test "$(id -u)" != 0' in script
    assert 'codex-cli 0.146.1' in script
    assert "/root/.codex" in script and "/root/.cache" in script
    assert "DATABASE_URL|JWT_SECRET|OPENAI_API_KEY|CODEX_API_KEY" in script
    assert "credentials" not in script.lower()
    assert "host" not in script.lower()


def test_artifact_is_sanitized_and_has_exact_fields() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    create = next(step for step in steps if step.get("name", "").startswith("Create sanitized"))
    script = create["run"]
    assert "codex-reserve-image.json" in script
    assert "release_sha:$release_sha" in script
    assert "product_version:$product_version" in script
    assert "image:$image" in script
    assert "cli_version:$cli_version" in script
    assert "ci_run_id:$ci_run_id" in script
    assert "token" not in script.lower()
    assert "password" not in script.lower()


def test_no_runtime_activation_or_unpinned_external_image() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "manual-reserve" not in text
    assert "docker compose" not in text
    assert "deploy" not in text.lower()
    assert not re.search(r"image:\s*(?!\$\{)[^\n]*:latest", text)
