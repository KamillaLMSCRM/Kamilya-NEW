from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "upgrade-kz-release-plane.yml"
SUDOERS = ROOT / "infra" / "deploy" / "kamilya-release-plane-upgrader.sudoers"


def test_upgrade_workflow_requires_exact_ci_and_protected_environment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '[[ "${workflow_name}" == "CI" ]]' in text
    assert '[[ "${conclusion}" == "success" ]]' in text
    assert "environment: kz-production" in text
    assert "runs-on: [self-hosted, linux, x64, kamilya-production-release]" in text
    assert "if: ${{ inputs.execute_upgrade }}" in text


def test_production_upgrade_job_has_no_checkout_or_arbitrary_sudo() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    production = text[text.index("  upgrade-production:") :]
    assert "actions/checkout" not in production
    commands = [line.strip() for line in production.splitlines() if "sudo -n" in line]
    assert commands == [
        "run: sudo -n /usr/local/sbin/kamilya-release-plane-upgrader validate",
        "run: sudo -n /usr/local/sbin/kamilya-release-plane-upgrader execute",
        "run: sudo -n /usr/local/sbin/kamilya-release-plane-upgrader readback",
    ]


def test_sudoers_allows_only_fixed_release_commands() -> None:
    lines = [line for line in SUDOERS.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 5
    assert all(line.startswith("kamilya-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/") for line in lines)
    assert all("*" not in line and "bash" not in line and "python" not in line for line in lines)
