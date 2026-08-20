#!/usr/bin/env bash
# Portable contract tests for backup, historical restore, and KZ restore drill.

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_SCRIPT="${ROOT_DIR}/scripts/backup.sh"
RESTORE_SCRIPT="${ROOT_DIR}/scripts/restore.sh"
KZ_DRILL_SCRIPT="${ROOT_DIR}/scripts/kz-restore-drill.sh"
TMP_DIR="$(mktemp -d)"
PASSFILE="${TMP_DIR}/backup.pass"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

printf 'local-test-passphrase\n' >"${PASSFILE}"
chmod 600 -- "${PASSFILE}"

assert_failure() {
  if "$@" >/dev/null 2>&1; then
    printf 'FAIL: expected command to fail: %s\n' "$*" >&2
    exit 1
  fi
}

assert_contains() {
  local file=$1 expected=$2
  grep -F -- "${expected}" "${file}" >/dev/null || {
    printf 'FAIL: %s does not contain %s\n' "${file}" "${expected}" >&2
    exit 1
  }
}

env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms \
  "${BACKUP_SCRIPT}" --dry-run >"${TMP_DIR}/backup.out"
grep -F 'passphrase-file validation passed' "${TMP_DIR}/backup.out" >/dev/null

# Unset inherited values explicitly: a developer shell must not make this pass.
assert_failure env -u BACKUP_PASSPHRASE_FILE BACKUP_DIR="${TMP_DIR}/backups" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms "${BACKUP_SCRIPT}" --dry-run
assert_failure env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME='bad name' DB_USER=lms "${BACKUP_SCRIPT}" --dry-run
assert_failure env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms MC_ALIAS=kz MC_TARGET=bucket \
  "${BACKUP_SCRIPT}" --dry-run
chmod 644 -- "${PASSFILE}"
if [[ "$(uname -s)" != MINGW* && "$(stat -c '%a' -- "${PASSFILE}")" == "644" ]]; then
  assert_failure env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
    DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms "${BACKUP_SCRIPT}" --dry-run
fi
chmod 600 -- "${PASSFILE}"

# The selected GPG mode detects ciphertext modification rather than producing
# unauthenticated plaintext as the retired CBC construction could.
printf 'authenticated-test-payload\n' >"${TMP_DIR}/plain.dump"
gpg --batch --yes --quiet --pinentry-mode loopback --symmetric --cipher-algo AES256 \
  --passphrase-file "${PASSFILE}" --output "${TMP_DIR}/valid.dump.gpg" "${TMP_DIR}/plain.dump"
cp -- "${TMP_DIR}/valid.dump.gpg" "${TMP_DIR}/tampered.dump.gpg"
printf '\000' | dd of="${TMP_DIR}/tampered.dump.gpg" bs=1 seek=20 count=1 conv=notrunc status=none
assert_failure gpg --batch --yes --quiet --pinentry-mode loopback \
  --passphrase-file "${PASSFILE}" --output "${TMP_DIR}/tampered.out" \
  --decrypt "${TMP_DIR}/tampered.dump.gpg"

# Historical restore remains explicitly scoped to historical Supabase archives.
assert_contains "${RESTORE_SCRIPT}" '--portable-supabase'
assert_contains "${RESTORE_SCRIPT}" 'RESTORE_PRODUCTION_CONFIRMATION'

# KZ production restore has a separate fail-closed drill contract.
assert_contains "${BACKUP_SCRIPT}" '.dump.gpg'
assert_contains "${BACKUP_SCRIPT}" 'gpg --batch'
assert_contains "${BACKUP_SCRIPT}" 'sha256sum'
assert_contains "${BACKUP_SCRIPT}" 'mc retention set'
assert_contains "${BACKUP_SCRIPT}" 'offsite round-trip verification failed'
assert_contains "${BACKUP_SCRIPT}" 'offsite checksum round-trip verification failed'
assert_contains "${KZ_DRILL_SCRIPT}" 'production target is always blocked for a restore drill'
assert_contains "${KZ_DRILL_SCRIPT}" 'target database is not empty; restore drill refused'
assert_contains "${KZ_DRILL_SCRIPT}" 'EXPECTED_ALEMBIC_HEAD'
assert_contains "${KZ_DRILL_SCRIPT}" "extname='vector'"
assert_contains "${KZ_DRILL_SCRIPT}" 'relforcerowsecurity'
assert_contains "${KZ_DRILL_SCRIPT}" '--detach-sign'
assert_contains "${KZ_DRILL_SCRIPT}" 'trap cleanup EXIT'

assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya \
  BACKUP_PASSPHRASE_FILE="${PASSFILE}" EXPECTED_ALEMBIC_HEAD=0120 \
  DRILL_REPORT_DIR="${TMP_DIR}/reports" DRILL_REPORT_SIGNING_KEY=test \
  "${KZ_DRILL_SCRIPT}" --backup-file "${TMP_DIR}/missing.dump.gpg" --target-db drill --dry-run

printf 'backup/restore security contract tests passed\n'
