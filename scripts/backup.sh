#!/usr/bin/env bash
# Kamilya LMS encrypted database backup.
#
# Required environment: BACKUP_DIR, BACKUP_PASSPHRASE_FILE, DB_HOST, DB_PORT,
# DB_NAME, DB_USER. Authentication is delegated to libpq. The passphrase is
# never accepted on the command line or written to logs.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
readonly BACKUP_PREFIX="kamilya_"
readonly BACKUP_SUFFIX=".dump.enc"
DRY_RUN=0
TEMP_FILES=()

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [--dry-run]

Required environment:
  BACKUP_DIR              Local directory for encrypted backups and logs
  BACKUP_PASSPHRASE_FILE  Root-only passphrase file (mode no wider than 600)
  DB_HOST, DB_PORT, DB_NAME, DB_USER

Optional environment:
  BACKUP_PBKDF2_ITERATIONS  OpenSSL PBKDF2 work factor (600000)
  RETENTION_DAYS            Delete older valid backups after this many days (30)
  MIN_VALID_BACKUPS         Never retain fewer valid local backups than this (1)
  LOG_DIR                   Log directory (BACKUP_DIR/logs)
  MC_ALIAS                  MinIO/mc alias; requires MC_TARGET when set
  MC_TARGET                 MinIO destination when MC_ALIAS is set
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

cleanup() {
  local temp_file
  for temp_file in "${TEMP_FILES[@]}"; do
    rm -f -- "${temp_file}"
  done
}
trap on_error ERR
trap cleanup EXIT

validate_passphrase_file() {
  local mode mode_value
  [[ -f "${BACKUP_PASSPHRASE_FILE}" ]] || die "BACKUP_PASSPHRASE_FILE must point to a regular file"
  [[ ! -L "${BACKUP_PASSPHRASE_FILE}" ]] || die "BACKUP_PASSPHRASE_FILE must not be a symlink"
  [[ -s "${BACKUP_PASSPHRASE_FILE}" ]] || die "BACKUP_PASSPHRASE_FILE must not be empty"
  mode="$(stat -c '%a' -- "${BACKUP_PASSPHRASE_FILE}" 2>/dev/null)" || die "cannot inspect passphrase file mode"
  [[ "${mode}" =~ ^[0-7]{3,4}$ ]] || die "cannot parse passphrase file mode"
  mode_value=$((8#${mode}))
  (( (mode_value & 077) == 0 )) || die "passphrase file must not be readable or writable by group/others"
  (( (mode_value & 400) != 0 )) || die "passphrase file must be readable by its owner"
}

make_temp_file() {
  local pattern=$1
  TEMP_FILE="$(mktemp -- "${pattern}")"
  TEMP_FILES+=("${TEMP_FILE}")
  chmod 600 -- "${TEMP_FILE}"
}

validate_encrypted_backup() {
  local candidate=$1
  make_temp_file "${BACKUP_DIR}/.kamilya-verify.XXXXXX.dump"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter "${BACKUP_PBKDF2_ITERATIONS}" -md sha256 \
    -pass "file:${BACKUP_PASSPHRASE_FILE}" \
    -in "${candidate}" -out "${TEMP_FILE}" >/dev/null 2>&1 || return 1
  pg_restore --list "${TEMP_FILE}" >/dev/null 2>&1
}

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: ${arg}" ;;
  esac
done

: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${BACKUP_PASSPHRASE_FILE:?BACKUP_PASSPHRASE_FILE is required}"
: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
BACKUP_PBKDF2_ITERATIONS="${BACKUP_PBKDF2_ITERATIONS:-600000}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
MIN_VALID_BACKUPS="${MIN_VALID_BACKUPS:-1}"
LOG_DIR="${LOG_DIR:-${BACKUP_DIR}/logs}"

validate_passphrase_file
[[ "${BACKUP_PBKDF2_ITERATIONS}" =~ ^[1-9][0-9]+$ ]] || die "BACKUP_PBKDF2_ITERATIONS must be numeric"
(( BACKUP_PBKDF2_ITERATIONS >= 100000 )) || die "BACKUP_PBKDF2_ITERATIONS must be at least 100000"
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS must be a non-negative integer"
[[ "${MIN_VALID_BACKUPS}" =~ ^[1-9][0-9]*$ ]] || die "MIN_VALID_BACKUPS must be a positive integer"
[[ "${DB_PORT}" =~ ^[0-9]+$ ]] || die "DB_PORT must be numeric"
[[ "${DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "DB_NAME must be a simple PostgreSQL identifier"
[[ "${DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || die "DB_USER contains unsupported characters"
[[ -z "${MC_ALIAS:-}" || -n "${MC_TARGET:-}" ]] || die "MC_TARGET is required when MC_ALIAS is set"

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

if (( DRY_RUN == 1 )); then
  printf 'DRY-RUN: configuration and passphrase-file validation passed; no database operation performed.\n'
  exit 0
fi

require_command date
require_command find
require_command mkdir
require_command mv
require_command openssl
require_command pg_dump
require_command pg_restore
mkdir -p -- "${BACKUP_DIR}" "${LOG_DIR}"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_ID
readonly LOG_FILE="${LOG_DIR}/backup_${RUN_ID}.log"
readonly FINAL_FILE="${BACKUP_DIR}/${BACKUP_PREFIX}${RUN_ID}${BACKUP_SUFFIX}"
readonly DUMP_PART="${FINAL_FILE}.dump.part"
readonly ENCRYPTED_PART="${FINAL_FILE}.part"
TEMP_FILES+=("${DUMP_PART}" "${ENCRYPTED_PART}")
exec > >(tee -a "${LOG_FILE}") 2>&1

printf 'Starting encrypted backup for database %s on %s:%s\n' "${DB_NAME}" "${DB_HOST}" "${DB_PORT}"
pg_dump \
  --host="${DB_HOST}" \
  --port="${DB_PORT}" \
  --username="${DB_USER}" \
  --dbname="${DB_NAME}" \
  --format=custom \
  --compress=9 \
  --file="${DUMP_PART}"

[[ -s "${DUMP_PART}" ]] || die "pg_dump produced an empty archive"
pg_restore --list "${DUMP_PART}" >/dev/null || die "pg_restore could not read the custom dump"
openssl enc -aes-256-cbc -pbkdf2 -iter "${BACKUP_PBKDF2_ITERATIONS}" -md sha256 \
  -salt -pass "file:${BACKUP_PASSPHRASE_FILE}" \
  -in "${DUMP_PART}" -out "${ENCRYPTED_PART}"
validate_encrypted_backup "${ENCRYPTED_PART}" || die "encrypted backup failed decrypt/pg_restore validation"
mv -- "${ENCRYPTED_PART}" "${FINAL_FILE}"
rm -f -- "${DUMP_PART}"
printf 'Published encrypted and verified backup: %s\n' "${FINAL_FILE}"

if [[ -n "${MC_ALIAS:-}" ]]; then
  require_command mc
  printf 'Uploading encrypted backup to %s\n' "${MC_TARGET}"
  mc cp -- "${FINAL_FILE}" "${MC_TARGET}/"
fi

valid_count=0
while IFS= read -r -d '' candidate; do
  if validate_encrypted_backup "${candidate}"; then
    valid_count=$((valid_count + 1))
  fi
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*${BACKUP_SUFFIX}" -print0)

printf 'Valid encrypted local backups before retention: %s\n' "${valid_count}"
while IFS= read -r -d '' candidate; do
  if (( valid_count <= MIN_VALID_BACKUPS )); then
    break
  fi
  if [[ "${candidate}" != "${FINAL_FILE}" ]] && ! validate_encrypted_backup "${candidate}"; then
    rm -f -- "${candidate}"
    continue
  fi
  if [[ "${candidate}" != "${FINAL_FILE}" ]] && validate_encrypted_backup "${candidate}"; then
    rm -f -- "${candidate}"
    valid_count=$((valid_count - 1))
  fi
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*${BACKUP_SUFFIX}" -mtime "+${RETENTION_DAYS}" -print0)

printf 'Backup completed successfully. Valid encrypted backups retained: %s\n' "${valid_count}"
