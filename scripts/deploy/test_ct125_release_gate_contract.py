from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "infra" / "deploy" / "kamilya-ct125-release-gate.sh"


def test_ct125_gate_binds_to_current_verified_guest_identity() -> None:
    text = GATE.read_text(encoding="utf-8")

    assert "[[ \"$(hostname)\" == 'KML-1-77' ]]" in text
    assert "kml-db" not in text


def test_ct125_gate_keeps_strict_ssh_and_backup_contract() -> None:
    text = GATE.read_text(encoding="utf-8")

    for contract in (
        "BatchMode=yes",
        "IdentitiesOnly=yes",
        "StrictHostKeyChecking=yes",
        'UserKnownHostsFile="${CT125_KNOWN_HOSTS}"',
        "SELECT version_num FROM alembic_version",
        "kamilya-pg-backup.timer",
        "sha256sum --check",
        "backup=encrypted_verified_fresh",
    ):
        assert contract in text

