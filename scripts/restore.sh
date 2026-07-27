#!/usr/bin/env bash
# Kamilya LMS encrypted database restore.
#
# A target database and passphrase file are mandatory. The script never drops
# or recreates a database; pg_restore cleans objects inside the explicitly
# named target in a single transaction. Production restore is denied unless
# explicit approval gates are passed.

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
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-}"
BACKUP_PBKDF2_ITERATIONS="${BACKUP_PBKDF2_ITERATIONS:-600000}"
LOG_DIR="${LOG_DIR:-}"
TEMP_FILES=()
EXCLUDED_EXTENSIONS=()
EXCLUDED_SCHEMA_DATA=()
REQUIRED_ROLES=()

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --backup-file <file> --target-db <db> [options]

Required environment:
  BACKUP_PASSPHRASE_FILE  Root-only passphrase file (mode no wider than 600)
  DB_HOST, DB_PORT, DB_USER, PRODUCTION_DB_NAME

Options:
  --backup-file <file>       Encrypted .dump.enc backup to restore
  --target-db <db>           Explicit target database; never inferred
  --log-dir <dir>            Log directory (required unless LOG_DIR is set)
  --dry-run                  Validate arguments and encrypted archive only
  --yes                      Skip non-production confirmation prompt
  --exclude-extension <name> Exclude a platform-owned extension and its
                             comment from a portable restore (repeatable)
  --portable-supabase        Restore LMS data outside Supabase while excluding
                             Supabase Vault objects/data and ensuring the
                             schema-only lms_app role exists as NOLOGIN
  --ensure-role <name>       Create a missing schema dependency as a NOLOGIN
                             PostgreSQL role (repeatable)
  --allow-production         Enable the production target gate; still requires
                             --yes and RESTORE_PRODUCTION_CONFIRMATION=I_UNDERSTAND
  --help

Authentication is delegated to libpq. No password or passphrase is accepted
on the command line.
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
  make_temp_file "${LOG_DIR}/.kamilya-restore-verify.XXXXXX.dump"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter "${BACKUP_PBKDF2_ITERATIONS}" -md sha256 \
    -pass "file:${BACKUP_PASSPHRASE_FILE}" \
    -in "${BACKUP_FILE}" -out "${TEMP_FILE}" >/dev/null 2>&1 || return 1
  pg_restore --list "${TEMP_FILE}" >/dev/null 2>&1
}

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
    --exclude-extension)
      (($# >= 2)) || die "--exclude-extension requires a value"
      EXCLUDED_EXTENSIONS+=("$2")
      shift 2
      ;;
    --portable-supabase)
      EXCLUDED_EXTENSIONS+=("supabase_vault")
      EXCLUDED_SCHEMA_DATA+=("vault")
      REQUIRED_ROLES+=("lms_app")
      shift
      ;;
    --ensure-role)
      (($# >= 2)) || die "--ensure-role requires a value"
      REQUIRED_ROLES+=("$2")
      shift
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
: "${BACKUP_PASSPHRASE_FILE:?BACKUP_PASSPHRASE_FILE is required}"
: "${LOG_DIR:?--log-dir or LOG_DIR is required}"

[[ -f "${BACKUP_FILE}" ]] || die "backup file not found: ${BACKUP_FILE}"
[[ ! -L "${BACKUP_FILE}" ]] || die "backup file must not be a symlink"
[[ "${BACKUP_FILE}" == *.dump.enc ]] || die "restore accepts only encrypted .dump.enc backups"
[[ "${TARGET_DB}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "target database must be a simple PostgreSQL identifier"
[[ "${PRODUCTION_DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "PRODUCTION_DB_NAME must be a simple PostgreSQL identifier"
[[ "${DB_PORT}" =~ ^[0-9]+$ ]] || die "DB_PORT must be numeric"
[[ "${DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || die "DB_USER contains unsupported characters"
[[ "${BACKUP_PBKDF2_ITERATIONS}" =~ ^[1-9][0-9]+$ ]] || die "BACKUP_PBKDF2_ITERATIONS must be numeric"
(( BACKUP_PBKDF2_ITERATIONS >= 100000 )) || die "BACKUP_PBKDF2_ITERATIONS must be at least 100000"
for extension in "${EXCLUDED_EXTENSIONS[@]}"; do
  [[ "${extension}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || die "excluded extension contains unsupported characters"
done
for schema in "${EXCLUDED_SCHEMA_DATA[@]}"; do
  [[ "${schema}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "excluded schema contains unsupported characters"
done
for role in "${REQUIRED_ROLES[@]}"; do
  [[ "${role}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "required role contains unsupported characters"
done
validate_passphrase_file

if [[ "${TARGET_DB}" == "${PRODUCTION_DB_NAME}" ]]; then
  (( ALLOW_PRODUCTION == 1 )) || die "production target is blocked; pass --allow-production only for an approved restore"
  (( ASSUME_YES == 1 )) || die "production restore requires --yes"
  [[ "${RESTORE_PRODUCTION_CONFIRMATION:-}" == 'I_UNDERSTAND' ]] || die "production restore requires RESTORE_PRODUCTION_CONFIRMATION=I_UNDERSTAND"
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

require_command mkdir
require_command mktemp
require_command openssl
require_command pg_restore
mkdir -p -- "${LOG_DIR}"
validate_encrypted_backup || die "encrypted backup failed decrypt/pg_restore validation"

if (( DRY_RUN == 1 )); then
  printf 'DRY-RUN: encrypted archive, passphrase file, and target validation passed for %s; no database operation performed.\n' "${TARGET_DB}"
  exit 0
fi

require_command date
require_command psql
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_ID
readonly LOG_FILE="${LOG_DIR}/restore_${RUN_ID}_${TARGET_DB}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

if (( ASSUME_YES == 0 )); then
  printf 'This will overwrite objects in target database %s on %s. Type RESTORE %s to continue: ' "${TARGET_DB}" "${DB_HOST}" "${TARGET_DB}"
  read -r confirmation
  [[ "${confirmation}" == "RESTORE ${TARGET_DB}" ]] || die "restore cancelled"
fi

printf 'Restoring verified encrypted archive %s into explicitly selected target %s on %s:%s\n' "${BACKUP_FILE}" "${TARGET_DB}" "${DB_HOST}" "${DB_PORT}"
for role in "${REQUIRED_ROLES[@]}"; do
  role_exists="$(psql \
    --host="${DB_HOST}" \
    --port="${DB_PORT}" \
    --username="${DB_USER}" \
    --dbname="${TARGET_DB}" \
    --tuples-only \
    --no-align \
    --command "SELECT 1 FROM pg_roles WHERE rolname = '${role}';")"
  if [[ "${role_exists//[[:space:]]/}" != "1" ]]; then
    psql \
      --host="${DB_HOST}" \
      --port="${DB_PORT}" \
      --username="${DB_USER}" \
      --dbname="${TARGET_DB}" \
      --command "CREATE ROLE \"${role}\" NOLOGIN;"
    printf 'Created missing schema dependency role as NOLOGIN: %s\n' "${role}"
  fi
done
make_temp_file "${LOG_DIR}/.kamilya-restore.XXXXXX.dump"
openssl enc -d -aes-256-cbc -pbkdf2 -iter "${BACKUP_PBKDF2_ITERATIONS}" -md sha256 \
  -pass "file:${BACKUP_PASSPHRASE_FILE}" \
  -in "${BACKUP_FILE}" -out "${TEMP_FILE}"
readonly DECRYPTED_DUMP="${TEMP_FILE}"
TOC_FILE=''
if ((${#EXCLUDED_EXTENSIONS[@]} > 0 || ${#EXCLUDED_SCHEMA_DATA[@]} > 0)); then
  make_temp_file "${LOG_DIR}/.kamilya-restore-toc.XXXXXX.list"
  TOC_FILE="${TEMP_FILE}"
  pg_restore --list "${DECRYPTED_DUMP}" >"${TOC_FILE}"
  for extension in "${EXCLUDED_EXTENSIONS[@]}"; do
    make_temp_file "${LOG_DIR}/.kamilya-restore-toc.XXXXXX.list"
    awk -v ext="${extension}" \
      'index($0, " EXTENSION - " ext " ") == 0 && index($0, " COMMENT - EXTENSION " ext " ") == 0' \
      "${TOC_FILE}" >"${TEMP_FILE}"
    TOC_FILE="${TEMP_FILE}"
    printf 'Portable restore excludes platform extension: %s\n' "${extension}"
  done
  for schema in "${EXCLUDED_SCHEMA_DATA[@]}"; do
    make_temp_file "${LOG_DIR}/.kamilya-restore-toc.XXXXXX.list"
    awk -v schema="${schema}" \
      'index($0, " TABLE DATA " schema " ") == 0' \
      "${TOC_FILE}" >"${TEMP_FILE}"
    TOC_FILE="${TEMP_FILE}"
    printf 'Portable restore excludes platform-owned data schema: %s\n' "${schema}"
  done
fi

RESTORE_ARGS=()
if [[ -n "${TOC_FILE}" ]]; then
  RESTORE_ARGS+=("--use-list=${TOC_FILE}")
fi
pg_restore \
  --host="${DB_HOST}" \
  --port="${DB_PORT}" \
  --username="${DB_USER}" \
  --dbname="${TARGET_DB}" \
  --no-owner \
  --no-acl \
  --clean \
  --if-exists \
  --exit-on-error \
  --single-transaction \
  "${RESTORE_ARGS[@]}" \
  "${DECRYPTED_DUMP}"

table_count="$(psql --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" --dbname="${TARGET_DB}" --tuples-only --no-align --command "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")"
table_count="${table_count//[[:space:]]/}"
[[ "${table_count}" =~ ^[1-9][0-9]*$ ]] || die "restore verification found no public tables"
printf 'Restore completed and verified. Public tables: %s. Log: %s\n' "${table_count}" "${LOG_FILE}"
