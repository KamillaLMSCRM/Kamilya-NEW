#!/usr/bin/env bash
# Kamilya LMS authenticated encrypted PostgreSQL backup.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly SCRIPT_NAME="$(basename "$0")"
readonly BACKUP_PREFIX="kamilya_"
readonly BACKUP_SUFFIX=".dump.gpg"
DRY_RUN=0
TEMP_FILES=()

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [--dry-run]

Required environment:
  BACKUP_DIR, BACKUP_PASSPHRASE_FILE, DB_HOST, DB_PORT, DB_NAME, DB_USER

Optional environment:
  RETENTION_DAYS             Local retention in days (30)
  MIN_VALID_BACKUPS          Minimum valid local archives (1)
  LOG_DIR                    Log directory (BACKUP_DIR/logs)
  MC_ALIAS, MC_TARGET        Configured MinIO alias and destination
  MC_IMMUTABLE_RETENTION     Governance retention, for example 30d; required
                             whenever MC_ALIAS is set
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

on_error() {
  local exit_code=$?
  printf 'ERROR: backup failed at line %s (exit %s)\n' "${BASH_LINENO[0]}" "${exit_code}" >&2
  exit "${exit_code}"
}

cleanup() {
  local path
  for path in "${TEMP_FILES[@]}"; do rm -f -- "${path}"; done
}
trap on_error ERR
trap cleanup EXIT

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

validate_secret_file() {
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

validate_checksum() {
  local archive=$1 sidecar=$2 expected_name=${3:-} digest expected
  [[ -f "${sidecar}" && ! -L "${sidecar}" ]] || return 1
  [[ -n "${expected_name}" ]] || expected_name="$(basename "${archive}")"
  digest="$(sha256sum -- "${archive}")"
  expected="${digest%% *}  ${expected_name}"
  grep -Fx -- "${expected}" "${sidecar}" >/dev/null 2>&1
}

decrypt_archive() {
  local archive=$1 output=$2
  gpg --batch --yes --quiet --pinentry-mode loopback \
    --passphrase-file "${BACKUP_PASSPHRASE_FILE}" \
    --output "${output}" --decrypt "${archive}"
}

validate_archive() {
  local archive=$1 sidecar=$2 expected_name=${3:-}
  validate_checksum "${archive}" "${sidecar}" "${expected_name}" || return 1
  make_temp_file "${BACKUP_DIR}/.kamilya-verify.XXXXXX.dump"
  decrypt_archive "${archive}" "${TEMP_FILE}" >/dev/null 2>&1 || return 1
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
RETENTION_DAYS="${RETENTION_DAYS:-30}"
MIN_VALID_BACKUPS="${MIN_VALID_BACKUPS:-1}"
LOG_DIR="${LOG_DIR:-${BACKUP_DIR}/logs}"

validate_secret_file
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS must be a non-negative integer"
[[ "${MIN_VALID_BACKUPS}" =~ ^[1-9][0-9]*$ ]] || die "MIN_VALID_BACKUPS must be a positive integer"
[[ "${DB_PORT}" =~ ^[0-9]+$ ]] || die "DB_PORT must be numeric"
[[ "${DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "DB_NAME must be a simple PostgreSQL identifier"
[[ "${DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || die "DB_USER contains unsupported characters"
if [[ -n "${MC_ALIAS:-}" ]]; then
  [[ "${MC_ALIAS}" =~ ^[A-Za-z0-9_-]+$ ]] || die "MC_ALIAS contains unsupported characters"
  [[ -n "${MC_TARGET:-}" ]] || die "MC_TARGET is required when MC_ALIAS is set"
  [[ "${MC_TARGET}" == "${MC_ALIAS}/"* && "${MC_TARGET}" != *'/../'* ]] || die "MC_TARGET must be a path below MC_ALIAS"
  [[ "${MC_IMMUTABLE_RETENTION:-}" =~ ^[1-9][0-9]*[dhmy]$ ]] || die "MC_IMMUTABLE_RETENTION is required and must look like 30d when MC_ALIAS is set"
fi

if (( DRY_RUN == 1 )); then
  printf 'DRY-RUN: configuration and passphrase-file validation passed; no database operation performed.\n'
  exit 0
fi

for command in basename chmod cmp date find gpg grep mkdir mktemp mv pg_dump pg_restore rm sha256sum stat tee; do require_command "${command}"; done
mkdir -p -- "${BACKUP_DIR}" "${LOG_DIR}"
[[ -d "${BACKUP_DIR}" && ! -L "${BACKUP_DIR}" ]] || die "BACKUP_DIR must be a non-symlink directory"
[[ -d "${LOG_DIR}" && ! -L "${LOG_DIR}" ]] || die "LOG_DIR must be a non-symlink directory"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_ID
readonly LOG_FILE="${LOG_DIR}/backup_${RUN_ID}.log"
readonly FINAL_FILE="${BACKUP_DIR}/${BACKUP_PREFIX}${RUN_ID}${BACKUP_SUFFIX}"
readonly CHECKSUM_FILE="${FINAL_FILE}.sha256"
readonly DUMP_PART="${FINAL_FILE}.dump.part"
readonly ENCRYPTED_PART="${FINAL_FILE}.part"
readonly CHECKSUM_PART="${CHECKSUM_FILE}.part"
TEMP_FILES+=("${DUMP_PART}" "${ENCRYPTED_PART}" "${CHECKSUM_PART}")
[[ ! -e "${FINAL_FILE}" && ! -e "${CHECKSUM_FILE}" ]] || die "backup destination already exists"
exec > >(tee -a "${LOG_FILE}") 2>&1

printf 'Starting authenticated encrypted backup for database %s on %s:%s\n' "${DB_NAME}" "${DB_HOST}" "${DB_PORT}"
pg_dump --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
  --dbname="${DB_NAME}" --format=custom --compress=9 --file="${DUMP_PART}"
[[ -s "${DUMP_PART}" ]] || die "pg_dump produced an empty archive"
pg_restore --list "${DUMP_PART}" >/dev/null || die "pg_restore could not read the custom dump"

gpg --batch --yes --quiet --pinentry-mode loopback --symmetric --cipher-algo AES256 \
  --s2k-mode 3 --s2k-digest-algo SHA512 --s2k-count 65011712 \
  --passphrase-file "${BACKUP_PASSPHRASE_FILE}" --output "${ENCRYPTED_PART}" "${DUMP_PART}"
archive_digest="$(sha256sum -- "${ENCRYPTED_PART}")"
printf '%s  %s\n' "${archive_digest%% *}" "$(basename "${FINAL_FILE}")" >"${CHECKSUM_PART}"
validate_archive "${ENCRYPTED_PART}" "${CHECKSUM_PART}" "$(basename "${FINAL_FILE}")" || die "backup failed checksum/decrypt/pg_restore validation"
mv -- "${CHECKSUM_PART}" "${CHECKSUM_FILE}"
mv -- "${ENCRYPTED_PART}" "${FINAL_FILE}"
rm -f -- "${DUMP_PART}"
printf 'Published authenticated encrypted and verified backup: %s\n' "${FINAL_FILE}"

if [[ -n "${MC_ALIAS:-}" ]]; then
  require_command mc
  make_temp_file "${BACKUP_DIR}/.kamilya-offsite-verify.XXXXXX.gpg"
  OFFSITE_COPY="${TEMP_FILE}"
  make_temp_file "${BACKUP_DIR}/.kamilya-offsite-verify.XXXXXX.sha256"
  OFFSITE_CHECKSUM_COPY="${TEMP_FILE}"
  printf 'Uploading archive and checksum to immutable offsite destination %s\n' "${MC_TARGET}"
  mc cp -- "${FINAL_FILE}" "${CHECKSUM_FILE}" "${MC_TARGET}/"
  mc cp -- "${MC_TARGET}/$(basename "${FINAL_FILE}")" "${OFFSITE_COPY}"
  mc cp -- "${MC_TARGET}/$(basename "${CHECKSUM_FILE}")" "${OFFSITE_CHECKSUM_COPY}"
  cmp --silent -- "${FINAL_FILE}" "${OFFSITE_COPY}" || die "offsite round-trip verification failed"
  cmp --silent -- "${CHECKSUM_FILE}" "${OFFSITE_CHECKSUM_COPY}" || die "offsite checksum round-trip verification failed"
  mc retention set --recursive governance "${MC_IMMUTABLE_RETENTION}" "${MC_TARGET}/"
  mc retention info "${MC_TARGET}/" >/dev/null || die "offsite retention policy could not be verified"
fi

valid_count=0
while IFS= read -r -d '' archive; do
  if validate_archive "${archive}" "${archive}.sha256"; then valid_count=$((valid_count + 1)); fi
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*${BACKUP_SUFFIX}" -print0)
printf 'Valid authenticated encrypted local backups before retention: %s\n' "${valid_count}"

while IFS= read -r -d '' archive; do
  if (( valid_count <= MIN_VALID_BACKUPS )); then break; fi
  [[ "${archive}" != "${FINAL_FILE}" ]] || continue
  if validate_archive "${archive}" "${archive}.sha256"; then
    rm -f -- "${archive}" "${archive}.sha256"
    valid_count=$((valid_count - 1))
  fi
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}*${BACKUP_SUFFIX}" -mtime "+${RETENTION_DAYS}" -print0)

printf 'Backup completed successfully. Valid local backups retained: %s\n' "${valid_count}"
