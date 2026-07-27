#!/usr/bin/env bash
# Static and dry-run contract tests for backup.sh and restore.sh.

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_SCRIPT="${ROOT_DIR}/scripts/backup.sh"
RESTORE_SCRIPT="${ROOT_DIR}/scripts/restore.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

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

env BACKUP_DIR="${TMP_DIR}/backups" DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms \
  "${BACKUP_SCRIPT}" --dry-run >"${TMP_DIR}/backup.out"
grep -F 'configuration is valid' "${TMP_DIR}/backup.out" >/dev/null

assert_failure env DB_HOST=db DB_PORT=5432 DB_NAME=kamilya DB_USER=lms \
  "${BACKUP_SCRIPT}" --dry-run
assert_failure env BACKUP_DIR="${TMP_DIR}" DB_HOST=db DB_PORT=5432 DB_NAME='bad name' DB_USER=lms \
  "${BACKUP_SCRIPT}" --dry-run

assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya LOG_DIR="${TMP_DIR}" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/missing.dump.gz" --target-db staging --dry-run
printf 'not-a-gzip' >"${TMP_DIR}/invalid.dump.gz"
assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya LOG_DIR="${TMP_DIR}" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/invalid.dump.gz" --target-db staging --dry-run
assert_failure env DB_HOST=db DB_PORT=5432 DB_USER=lms PRODUCTION_DB_NAME=kamilya LOG_DIR="${TMP_DIR}" \
  "${RESTORE_SCRIPT}" --backup-file "${TMP_DIR}/invalid.dump.gz" --target-db kamilya --dry-run

assert_contains "${BACKUP_SCRIPT}" 'pg_restore --list'
assert_contains "${BACKUP_SCRIPT}" 'MIN_VALID_BACKUPS'
assert_contains "${RESTORE_SCRIPT}" '--target-db'
assert_contains "${RESTORE_SCRIPT}" 'RESTORE_PRODUCTION_CONFIRMATION'

printf 'backup/restore validation tests passed\n'
