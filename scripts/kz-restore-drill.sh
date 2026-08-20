#!/usr/bin/env bash
# Restore a KZ production backup into an explicitly empty disposable database.
# This drill intentionally cannot target the production database.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly SCRIPT_NAME="$(basename "$0")"
BACKUP_FILE=''
TARGET_DB=''
DRY_RUN=0
ASSUME_YES=0
TEMP_FILES=()

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --backup-file <archive.dump.gpg> --target-db <empty_db> [--dry-run] [--yes]

Required environment:
  BACKUP_PASSPHRASE_FILE
  DB_HOST, DB_PORT, DB_USER, PRODUCTION_DB_NAME
  EXPECTED_ALEMBIC_HEAD
  DRILL_REPORT_DIR, DRILL_REPORT_SIGNING_KEY

Optional environment:
  MAX_RPO_SECONDS  Maximum archive age at drill start (86400)
  MAX_RTO_SECONDS  Maximum restore and validation duration (3600)

The target database must already exist and contain zero user tables. A target
whose name equals PRODUCTION_DB_NAME is always rejected; there is no override.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

on_error() {
  local exit_code=$?
  printf 'ERROR: KZ restore drill failed at line %s (exit %s)\n' "${BASH_LINENO[0]}" "${exit_code}" >&2
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
  local digest expected
  digest="$(sha256sum -- "${BACKUP_FILE}")"
  expected="${digest%% *}  $(basename "${BACKUP_FILE}")"
  grep -Fx -- "${expected}" "${BACKUP_FILE}.sha256" >/dev/null 2>&1
}

psql_scalar() {
  psql --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
    --dbname="${TARGET_DB}" --no-psqlrc --set=ON_ERROR_STOP=1 --tuples-only --no-align \
    --command "$1" | tr -d '[:space:]'
}

while (($# > 0)); do
  case "$1" in
    --backup-file) (($# >= 2)) || die "--backup-file requires a value"; BACKUP_FILE=$2; shift 2 ;;
    --target-db) (($# >= 2)) || die "--target-db requires a value"; TARGET_DB=$2; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

: "${BACKUP_FILE:?--backup-file is required}"
: "${TARGET_DB:?--target-db is required}"
: "${BACKUP_PASSPHRASE_FILE:?BACKUP_PASSPHRASE_FILE is required}"
: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${PRODUCTION_DB_NAME:?PRODUCTION_DB_NAME is required}"
: "${EXPECTED_ALEMBIC_HEAD:?EXPECTED_ALEMBIC_HEAD is required}"
: "${DRILL_REPORT_DIR:?DRILL_REPORT_DIR is required}"
: "${DRILL_REPORT_SIGNING_KEY:?DRILL_REPORT_SIGNING_KEY is required}"
MAX_RPO_SECONDS="${MAX_RPO_SECONDS:-86400}"
MAX_RTO_SECONDS="${MAX_RTO_SECONDS:-3600}"

[[ -f "${BACKUP_FILE}" && ! -L "${BACKUP_FILE}" ]] || die "backup archive must be a regular non-symlink file"
[[ "${BACKUP_FILE}" == *.dump.gpg ]] || die "KZ restore drill accepts only .dump.gpg archives"
archive_name="$(basename "${BACKUP_FILE}")"
[[ "${archive_name}" =~ ^kamilya_[0-9]{8}T[0-9]{6}Z\.dump\.gpg$ ]] || die "archive name does not match the canonical UTC backup format"
[[ -f "${BACKUP_FILE}.sha256" && ! -L "${BACKUP_FILE}.sha256" ]] || die "companion .sha256 file is required"
[[ "${TARGET_DB}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "target database must be a simple PostgreSQL identifier"
[[ "${PRODUCTION_DB_NAME}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "PRODUCTION_DB_NAME must be a simple PostgreSQL identifier"
[[ "${TARGET_DB,,}" != "${PRODUCTION_DB_NAME,,}" ]] || die "production target is always blocked for a restore drill"
[[ "${DB_PORT}" =~ ^[0-9]+$ ]] || die "DB_PORT must be numeric"
[[ "${DB_USER}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || die "DB_USER contains unsupported characters"
[[ "${EXPECTED_ALEMBIC_HEAD}" =~ ^[A-Za-z0-9_-]+$ ]] || die "EXPECTED_ALEMBIC_HEAD contains unsupported characters"
[[ "${DRILL_REPORT_SIGNING_KEY}" =~ ^[A-Za-z0-9@._+-]+$ ]] || die "DRILL_REPORT_SIGNING_KEY contains unsupported characters"
[[ "${MAX_RPO_SECONDS}" =~ ^[1-9][0-9]*$ ]] || die "MAX_RPO_SECONDS must be positive"
[[ "${MAX_RTO_SECONDS}" =~ ^[1-9][0-9]*$ ]] || die "MAX_RTO_SECONDS must be positive"
validate_secret_file

for command in basename date gpg grep mktemp pg_restore sha256sum; do require_command "${command}"; done
validate_checksum || die "archive checksum verification failed"
archive_digest="$(sha256sum -- "${BACKUP_FILE}")"
archive_sha256="${archive_digest%% *}"
make_temp_file "${TMPDIR:-/tmp}/kamilya-drill.XXXXXX.dump"
DECRYPTED_DUMP="${TEMP_FILE}"
gpg --batch --yes --quiet --pinentry-mode loopback \
  --passphrase-file "${BACKUP_PASSPHRASE_FILE}" \
  --output "${DECRYPTED_DUMP}" --decrypt "${BACKUP_FILE}"
pg_restore --list "${DECRYPTED_DUMP}" >/dev/null || die "decrypted archive is not a readable PostgreSQL custom dump"

now_epoch="$(date -u +%s)"
backup_stamp="${archive_name#kamilya_}"
backup_stamp="${backup_stamp%.dump.gpg}"
backup_epoch="$(date -u -d "${backup_stamp:0:4}-${backup_stamp:4:2}-${backup_stamp:6:2} ${backup_stamp:9:2}:${backup_stamp:11:2}:${backup_stamp:13:2}Z" +%s)" || die "cannot parse archive UTC timestamp"
rpo_seconds=$((now_epoch - backup_epoch))
(( rpo_seconds >= 0 && rpo_seconds <= MAX_RPO_SECONDS )) || die "archive age exceeds MAX_RPO_SECONDS"

if (( DRY_RUN == 1 )); then
  printf 'DRY-RUN: checksum, authenticated decryption, archive structure, target guard, and RPO passed; no database operation performed.\n'
  exit 0
fi

for command in cat chmod mkdir mv psql tr; do require_command "${command}"; done
mkdir -p -- "${DRILL_REPORT_DIR}"
[[ -d "${DRILL_REPORT_DIR}" && ! -L "${DRILL_REPORT_DIR}" ]] || die "DRILL_REPORT_DIR must be a non-symlink directory"
existing_tables="$(psql_scalar "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_toast' AND c.relkind IN ('r','p');")"
[[ "${existing_tables}" == "0" ]] || die "target database is not empty; restore drill refused"

if (( ASSUME_YES == 0 )); then
  printf 'Restore verified archive into empty disposable database %s on %s. Type DRILL %s to continue: ' "${TARGET_DB}" "${DB_HOST}" "${TARGET_DB}"
  read -r confirmation
  [[ "${confirmation}" == "DRILL ${TARGET_DB}" ]] || die "restore drill cancelled"
fi

started_epoch="$(date -u +%s)"
pg_restore --host="${DB_HOST}" --port="${DB_PORT}" --username="${DB_USER}" \
  --dbname="${TARGET_DB}" --no-owner --no-acl --exit-on-error --single-transaction \
  "${DECRYPTED_DUMP}"

table_count="$(psql_scalar "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
[[ "${table_count}" =~ ^[1-9][0-9]*$ ]] || die "restore verification found no public tables"
alembic_head="$(psql_scalar "SELECT version_num FROM alembic_version;")"
[[ "${alembic_head}" == "${EXPECTED_ALEMBIC_HEAD}" ]] || die "restored Alembic head does not match EXPECTED_ALEMBIC_HEAD"
vector_count="$(psql_scalar "SELECT count(*) FROM pg_extension WHERE extname='vector';")"
[[ "${vector_count}" == "1" ]] || die "pgvector extension is missing after restore"
force_rls_count="$(psql_scalar "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relrowsecurity AND c.relforcerowsecurity;")"
[[ "${force_rls_count}" =~ ^[1-9][0-9]*$ ]] || die "restore verification found no FORCE RLS tables"
tenant_count="$(psql_scalar "SELECT count(*) FROM tenants;")"
course_count="$(psql_scalar "SELECT count(*) FROM courses;")"
enrollment_count="$(psql_scalar "SELECT count(*) FROM enrollments;")"
certificate_count="$(psql_scalar "SELECT count(*) FROM certificates;")"
for value in "${tenant_count}" "${course_count}" "${enrollment_count}" "${certificate_count}"; do
  [[ "${value}" =~ ^[0-9]+$ ]] || die "aggregate verification returned a non-numeric result"
done

finished_epoch="$(date -u +%s)"
rto_seconds=$((finished_epoch - started_epoch))
(( rto_seconds <= MAX_RTO_SECONDS )) || die "restore duration exceeds MAX_RTO_SECONDS"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_FILE="${DRILL_REPORT_DIR}/kz_restore_drill_${RUN_ID}.json"
SIGNATURE_FILE="${REPORT_FILE}.asc"
[[ ! -e "${REPORT_FILE}" && ! -e "${SIGNATURE_FILE}" ]] || die "drill report destination already exists"
make_temp_file "${DRILL_REPORT_DIR}/.kz-restore-report.XXXXXX.json"
REPORT_PART="${TEMP_FILE}"
make_temp_file "${DRILL_REPORT_DIR}/.kz-restore-signature.XXXXXX.asc"
SIGNATURE_PART="${TEMP_FILE}"
cat >"${REPORT_PART}" <<EOF
{"schema_version":1,"result":"passed","archive":"${archive_name}","archive_sha256":"${archive_sha256}","target_database":"${TARGET_DB}","expected_alembic_head":"${EXPECTED_ALEMBIC_HEAD}","actual_alembic_head":"${alembic_head}","rpo_seconds":${rpo_seconds},"rto_seconds":${rto_seconds},"public_tables":${table_count},"force_rls_tables":${force_rls_count},"tenants":${tenant_count},"courses":${course_count},"enrollments":${enrollment_count},"certificates":${certificate_count},"completed_at_epoch":${finished_epoch}}
EOF
gpg --batch --yes --armor --local-user "${DRILL_REPORT_SIGNING_KEY}" \
  --output "${SIGNATURE_PART}" --detach-sign "${REPORT_PART}"
gpg --batch --verify "${SIGNATURE_PART}" "${REPORT_PART}" >/dev/null 2>&1 || die "drill report signature verification failed"
mv -- "${REPORT_PART}" "${REPORT_FILE}"
mv -- "${SIGNATURE_PART}" "${SIGNATURE_FILE}"
chmod 600 -- "${REPORT_FILE}" "${SIGNATURE_FILE}"
printf 'KZ restore drill passed. Signed report: %s\n' "${REPORT_FILE}"
