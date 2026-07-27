#!/usr/bin/env bash
# Kamilya LMS database backup.
#
# Required environment: BACKUP_DIR, DB_HOST, DB_PORT, DB_NAME, DB_USER.
# Authentication is delegated to libpq (.pgpass, PGPASSFILE, or another
# standard libpq mechanism). The script never accepts or prints a password.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
readonly BACKUP_PREFIX="kamilya_"
readonly BACKUP_SUFFIX=".dump.gz"
DRY_RUN=0

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [--dry-run]

Required environment:
  BACKUP_DIR       Local directory for backups and logs
  DB_HOST          PostgreSQL host
  DB_PORT          PostgreSQL port
  DB_NAME          PostgreSQL database name
  DB_USER          PostgreSQL user

Optional environment:
  RETENTION_DAYS       Delete older valid backups after this many days (30)
  MIN_VALID_BACKUPS    Never retain fewer valid local backups than this (1)
  LOG_DIR              Log directory (BACKUP_DIR/logs)
  MC_ALIAS             MinIO/mc alias; requires MC_TARGET when set
  MC_TARGET            MinIO destination when MC_ALIAS is set
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local exit_code=$?
  printf 'ERROR: backup failed at line %s (exit %s)\n' "${BASH_LINENO[0]}" "${exit_code}" >&2
  exit "${exit_code}"
}
trap on_error ERR

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: ${arg}" ;;
  esac
done

: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
MIN_VALID_BACKUPS="${MIN_VALID_BACKUPS:-1}"
LOG_DIR="${LOG_DIR:-${BACKUP_DIR}/logs}"

[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS must be a non-negative integer"
[[ "${MIN_VALID_BACKUPS}" =~ ^[1-9][0-9]*$ ]] || die "MIN_VALID_BACKUPS must be a positive integer"
[[ "${DB_PORT}" =~ ^[0-9]+$ ]] || die "DB_PORT must be numeric"
[[ "${DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "DB_NAME must be a simple PostgreSQL identifier"
[[ "${DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "DB_USER must be a simple PostgreSQL identifier"
[[ -z "${MC_ALIAS:-}" || -n "${MC_TARGET:-}" ]] || die "MC_TARGET is required when MC_ALIAS is set"

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

if (( DRY_RUN == 1 )); then
  printf 'DRY-RUN: configuration is valid; no database or filesystem operation performed.\n'
  exit 0
fi

require_command date
require_command find
require_command gzip
require_command mkdir
require_command mv
require_command pg_dump
require_command pg_restore
mkdir -p -- "${BACKUP_DIR}" "${LOG_DIR}"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_ID
readonly LOG_FILE="${LOG_DIR}/backup_${RUN_ID}.log"
readonly FINAL_FILE="${BACKUP_DIR}/${BACKUP_PREFIX}${RUN_ID}${BACKUP_SUFFIX}"
readonly DUMP_PART="${FINAL_FILE}.dump.part"
readonly GZIP_PART="${FINAL_FILE}.part"

cleanup() {
  rm -f -- "${DUMP_PART}" "${GZIP_PART}"
}
trap cleanup EXIT
exec > >(tee -a "${LOG_FILE}") 2>&1

printf 'Starting backup for database %s on %s:%s\n' "${DB_NAME}" "${DB_HOST}" "${DB_PORT}"
pg_dump \
  --host="${DB_HOST}" \
  --port="${DB_PORT}" \
  --username="${DB_USER}" \
  --dbname="${DB_NAME}" \
  --format=custom \
  --compress=9 \
  --file="${DUMP_PART}"

[[ -s "${DUMP_PART}" ]] || die "pg_dump produced an empty archive"
pg_restore --list "${DUMP_PART}" >/dev/null || die "pg_restore could not read the dump archive"
gzip -9 -c -- "${DUMP_PART}" > "${GZIP_PART}"
gzip -t -- "${GZIP_PART}"
mv -- "${GZIP_PART}" "${FINAL_FILE}"
rm -f -- "${DUMP_PART}"
printf 'Published verified backup: %s\n' "${FINAL_FILE}"

if [[ -n "${MC_ALIAS:-}" ]]; then
  require_command mc
  printf 'Uploading verified backup to %s\n' "${MC_TARGET}"
  mc cp -- "${FINAL_FILE}" "${MC_TARGET}/"
fi

valid_count=0
while IFS= read -r -d '' candidate; do
  if gzip -t -- "${candidate}" && gzip -dc -- "${candidate}" | pg_restore --list >/dev/null 2>&1; then
    valid_count=$((valid_count + 1))
  fi
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*${BACKUP_SUFFIX}" -print0)

printf 'Valid local backups before retention: %s\n' "${valid_count}"
while IFS= read -r -d '' candidate; do
  if (( valid_count <= MIN_VALID_BACKUPS )); then
    break
  fi
  if [[ "${candidate}" != "${FINAL_FILE}" ]] && ! gzip -t -- "${candidate}"; then
    rm -f -- "${candidate}"
    continue
  fi
  if [[ "${candidate}" != "${FINAL_FILE}" ]] && gzip -t -- "${candidate}" && gzip -dc -- "${candidate}" | pg_restore --list >/dev/null 2>&1; then
    rm -f -- "${candidate}"
    valid_count=$((valid_count - 1))
  fi
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*${BACKUP_SUFFIX}" -mtime "+${RETENTION_DAYS}" -print0)

printf 'Backup completed successfully. Valid local backups retained: %s\n' "${valid_count}"
