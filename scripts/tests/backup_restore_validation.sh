#!/usr/bin/env bash
# Static and dry-run contract tests for the encrypted backup/restore scripts.

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_SCRIPT="${ROOT_DIR}/scripts/backup.sh"
RESTORE_SCRIPT="${ROOT_DIR}/scripts/restore.sh"
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
  local file=$1
  local expected=$2
  grep -F -- "${expected}" "${file}" >/dev/null || {
    printf 'FAIL: %s does not contain %s\n' "${file}" "${expected}" >&2
    exit 1
  }
}

env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms \
  "${BACKUP_SCRIPT}" --dry-run >"${TMP_DIR}/backup.out"
grep -F 'passphrase-file validation passed' "${TMP_DIR}/backup.out" >/dev/null
env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER='postgres.project-ref' \
  "${BACKUP_SCRIPT}" --dry-run >/dev/null

assert_failure env BACKUP_DIR="${TMP_DIR}/backups" DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms \
  "${BACKUP_SCRIPT}" --dry-run
assert_failure env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME='bad name' DB_USER=lms "${BACKUP_SCRIPT}" --dry-run
assert_failure env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER='bad:user' "${BACKUP_SCRIPT}" --dry-run
chmod 644 -- "${PASSFILE}"
assert_failure env BACKUP_DIR="${TMP_DIR}/backups" BACKUP_PASSPHRASE_FILE="${PASSFILE}" \
  DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms "${BACKUP_SCRIPT}" --dry-run
chmod 600 -- "${PASSFILE}"

printf 'not-a-dump' >"${TMP_DIR}/plain.dump"
openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -salt \
  -pass "file:${PASSFILE}" -in "${TMP_DIR}/plain.dump" -out "${TMP_DIR}/invalid.dump.enc" 2>/dev/null

assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya \
  BACKUP_PASSPHRASE_FILE="${PASSFILE}" LOG_DIR="${TMP_DIR}/logs" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/missing.dump.enc" --target-db staging --dry-run
assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya \
  BACKUP_PASSPHRASE_FILE="${PASSFILE}" LOG_DIR="${TMP_DIR}/logs" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/invalid.dump.enc" --target-db staging --dry-run
assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya \
  BACKUP_PASSPHRASE_FILE="${PASSFILE}" LOG_DIR="${TMP_DIR}/logs" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/invalid.dump.enc" --target-db kamilya --dry-run
assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya \
  BACKUP_PASSPHRASE_FILE="${PASSFILE}" LOG_DIR="${TMP_DIR}/logs" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/invalid.dump.gz" --target-db staging --dry-run

if find "${TMP_DIR}/logs" -maxdepth 1 -type f -name '.kamilya-restore-verify.*' -print -quit | grep -q .; then
  printf 'FAIL: temporary plaintext restore file was not removed\n' >&2
  exit 1
fi
assert_contains "${BACKUP_SCRIPT}" 'openssl enc -aes-256-cbc -pbkdf2'
assert_contains "${BACKUP_SCRIPT}" 'BACKUP_PASSPHRASE_FILE'
assert_contains "${BACKUP_SCRIPT}" '.dump.enc'
assert_contains "${RESTORE_SCRIPT}" '--target-db'
assert_contains "${RESTORE_SCRIPT}" 'RESTORE_PRODUCTION_CONFIRMATION'
assert_contains "${RESTORE_SCRIPT}" 'trap cleanup EXIT'

printf 'encrypted backup/restore validation tests passed\n'
