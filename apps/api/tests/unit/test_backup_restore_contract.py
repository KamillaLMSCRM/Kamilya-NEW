from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKUP = (ROOT / "scripts" / "backup.sh").read_text(encoding="utf-8")
KZ_RESTORE = (ROOT / "scripts" / "kz-restore-drill.sh").read_text(encoding="utf-8")


def test_backup_uses_authenticated_gpg_and_portable_checksum() -> None:
    assert ".dump.gpg" in BACKUP
    assert "gpg --batch" in BACKUP
    assert "--cipher-algo AES256" in BACKUP
    assert "sha256sum" in BACKUP
    assert '$(basename "${FINAL_FILE}")' in BACKUP
    assert "openssl enc -aes-256-cbc" not in BACKUP


def test_backup_requires_verified_immutable_offsite_copy() -> None:
    assert "MC_IMMUTABLE_RETENTION" in BACKUP
    assert "offsite round-trip verification failed" in BACKUP
    assert "offsite checksum round-trip verification failed" in BACKUP
    assert "mc retention set --recursive governance" in BACKUP
    assert 'mc retention info "${MC_TARGET}/"' in BACKUP


def test_kz_restore_drill_is_fail_closed_for_production_and_nonempty_db() -> None:
    assert '[[ "${TARGET_DB,,}" != "${PRODUCTION_DB_NAME,,}" ]]' in KZ_RESTORE
    assert "production target is always blocked for a restore drill" in KZ_RESTORE
    assert "target database is not empty; restore drill refused" in KZ_RESTORE
    assert "--allow-production" not in KZ_RESTORE
    assert "--clean" not in KZ_RESTORE


def test_kz_restore_drill_validates_release_data_rls_and_signed_evidence() -> None:
    for contract in (
        "EXPECTED_ALEMBIC_HEAD",
        "extname='vector'",
        "relforcerowsecurity",
        "SELECT count(*) FROM tenants",
        "SELECT count(*) FROM courses",
        "SELECT count(*) FROM enrollments",
        "SELECT count(*) FROM certificates",
        "MAX_RPO_SECONDS",
        "MAX_RTO_SECONDS",
        "--detach-sign",
        "gpg --batch --verify",
    ):
        assert contract in KZ_RESTORE
