#!/usr/bin/env bash
# Kamilya LMS database restore.
#
# A target database is mandatory. The script never drops or recreates a
# database; pg_restore cleans objects inside the explicitly named target in a
# single transaction. Production restore is denied unless two explicit gates
# are passed.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
DRY_RUN=0
ASSUME_YES=0
ALLOW_PRODUCTION=0
BACKUP_FILE=''
TARGET_DB=''
DB_HOST="${DB_HOST:-}"
DB_PORT="${DB_PORT:-}"
DB_USER="${DB_USER:-}"
PRODUCTION_DB_NAME="${PRODUCTION_DB_NAME:-}"
LOG_DIR="${LOG_DIR:-}"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --backup-file <file> --target-db <db> [options]

Required environment:
  DB_HOST, DB_PORT, DB_USER, PRODUCTION_DB_NAME

Options:
  --backup-file <file>       Verified .dump.gz backup to restore
  --target-db <db>           Explicit target database; never inferred
  --log-dir <dir>            Log directory (required unless LOG_DIR is set)
  --dry-run                  Validate arguments and archive only
  --yes                      Skip non-production confirmation prompt
  --allow-production         Enable the production target gate; still requires
                             --yes and RESTORE_PRODUCTION_CONFIRMATION=I_UNDERSTAND
  --help

Authentication is delegated to libpq. No password is accepted by this script.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local exit_code=$?
  printf 'ERROR: restore failed at line %s (exit %s)\n' "${BASH_LINENO[0]}" "${exit_code}" >&2
  exit "${exit_code}"
}
trap on_error ERR

while (($# > 0)); do
  case "$1" in
    --backup-file)
      (($# >= 2)) || die "--backup-file requires a value"
      BACKUP_FILE=$2
      shift 2
      ;;
    --target-db)
      (($# >= 2)) || die "--target-db requires a value"
      TARGET_DB=$2
      shift 2
      ;;
    --log-dir)
      (($# >= 2)) || die "--log-dir requires a value"
      LOG_DIR=$2
      shift 2
      ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --allow-production) ALLOW_PRODUCTION=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

: "${BACKUP_FILE:?--backup-file is required}"
: "${TARGET_DB:?--target-db is required}"
: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${PRODUCTION_DB_NAME:?PRODUCTION_DB_NAME is required for overwrite protection}"
: "${LOG_DIR:?--log-dir or LOG_DIR is required}"

[[ -f "${BACKUP_FILE}" ]] || die "backup file not found: ${BACKUP_FILE}"
[[ "${TARGET_DB}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "target database must be a simple PostgreSQL identifier"
[[ "${PRODUCTION_DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "PRODUCTION_DB_NAME must be a simple PostgreSQL identifier"

if [[ "${TARGET_DB}" == "${PRODUCTION_DB_NAME}" ]]; then
  (( ALLOW_PRODUCTION == 1 )) || die "production target is blocked; pass --allow-production only for an approved restore"
  (( ASSUME_YES == 1 )) || die "production restore requires --yes"
  [[ "${RESTORE_PRODUCTION_CONFIRMATION:-}" == 'I_UNDERSTAND' ]] || die "production restore requires RESTORE_PRODUCTION_CONFIRMATION=I_UNDERSTAND"
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

require_command gzip
require_command pg_restore
gzip -t -- "${BACKUP_FILE}" || die "backup is not a valid gzip stream"
gzip -dc -- "${BACKUP_FILE}" | pg_restore --list >/dev/null || die "backup is not a readable PostgreSQL custom archive"

if (( DRY_RUN == 1 )); then
  printf 'DRY-RUN: archive and target validation passed for %s; no database operation performed.\n' "${TARGET_DB}"
  exit 0
fi

require_command date
require_command mkdir
require_command psql
mkdir -p -- "${LOG_DIR}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_ID
readonly LOG_FILE="${LOG_DIR}/restore_${RUN_ID}_${TARGET_DB}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

if (( ASSUME_YES == 0 )); then
  printf 'This will overwrite objects in target database %s on %s. Type RESTORE %s to continue: ' "${TARGET_DB}" "${DB_HOST}" "${TARGET_DB}"
  read -r confirmation
  [[ "${confirmation}" == "RESTORE ${TARGET_DB}" ]] || die "restore cancelled"
fi

printf 'Restoring verified archive %s into explicitly selected target %s on %s:%s\n' "${BACKUP_FILE}" "${TARGET_DB}" "${DB_HOST}" "${DB_PORT}"
gzip -dc -- "${BACKUP_FILE}" | pg_restore \
  --host="${DB_HOST}" \
  --port="${DB_PORT}" \
  --username="${DB_USER}" \
  --dbname="${TARGET_DB}" \
  --no-owner \
  --no-acl \
  --clean \
  --if-exists \
  --exit-on-error \
  --single-transaction

table_count="$(psql --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" --dbname="${TARGET_DB}" --tuples-only --no-align --command "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")"
table_count="${table_count//[[:space:]]/}"
[[ "${table_count}" =~ ^[1-9][0-9]*$ ]] || die "restore verification found no public tables"
printf 'Restore completed and verified. Public tables: %s. Log: %s\n' "${table_count}" "${LOG_FILE}"
