#!/usr/bin/env bash
# Stable VM126 -> CT125 backup and revision gate. No credentials are accepted.
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

CONFIG_FILE="${KAMILYA_CT125_GATE_CONFIG:-/etc/kamilya-release-plane/ct125.env}"

usage() {
  printf 'Usage: %s --expected-revision NNNN --freshness-seconds NNN\n' "$(basename "$0")"
}

EXPECTED_REVISION=''
FRESHNESS_SECONDS=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-revision) EXPECTED_REVISION="${2:-}"; shift 2 ;;
    --freshness-seconds) FRESHNESS_SECONDS="${2:-}"; shift 2 ;;
    *) usage >&2; exit 2 ;;
  esac
done

[[ "${EXPECTED_REVISION}" =~ ^[0-9]{4}$ ]] || { printf 'BLOCKED: invalid expected revision\n' >&2; exit 2; }
[[ "${FRESHNESS_SECONDS}" =~ ^[0-9]+$ ]] || { printf 'BLOCKED: invalid freshness\n' >&2; exit 2; }
(( FRESHNESS_SECONDS >= 300 && FRESHNESS_SECONDS <= 3600 )) || { printf 'BLOCKED: freshness out of range\n' >&2; exit 2; }
[[ -f "${CONFIG_FILE}" && ! -L "${CONFIG_FILE}" ]] || { printf 'BLOCKED: config unavailable\n' >&2; exit 3; }
# shellcheck disable=SC1090 -- fixed root-owned configuration path
source "${CONFIG_FILE}"
: "${CT125_HOST:?}"
: "${CT125_IDENTITY_FILE:?}"
: "${CT125_KNOWN_HOSTS:?}"
: "${CT125_DB_NAME:?}"
: "${CT125_BACKUP_DIR:?}"

exec ssh -T \
  -i "${CT125_IDENTITY_FILE}" \
  -o BatchMode=yes \
  -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="${CT125_KNOWN_HOSTS}" \
  "root@${CT125_HOST}" bash -s -- \
  "${EXPECTED_REVISION}" "${FRESHNESS_SECONDS}" "${CT125_DB_NAME}" "${CT125_BACKUP_DIR}" <<'CT125_GATE'
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

expected_revision="$1"
freshness_seconds="$2"
db_name="$3"
backup_dir="$4"
[[ "$(hostname)" == 'KML-1-77' ]]
[[ "$(runuser -u postgres -- psql -d "${db_name}" -Atqc 'SELECT version_num FROM alembic_version')" == "${expected_revision}" ]]
systemctl is-active --quiet kamilya-pg-backup.timer

verify_latest() {
  local latest latest_epoch latest_path age now
  latest="$(find "${backup_dir}" -maxdepth 1 -type f -name "${db_name}_*.dump.gpg" -printf '%T@ %p\n' | sort -nr | head -n 1)"
  [[ -n "${latest}" ]] || return 1
  latest_epoch="${latest%% *}"
  latest_epoch="${latest_epoch%.*}"
  latest_path="${latest#* }"
  now="$(date +%s)"
  age=$((now - latest_epoch))
  (( age >= -60 && age <= freshness_seconds )) || return 1
  [[ -f "${latest_path}.sha256" && ! -L "${latest_path}" && ! -L "${latest_path}.sha256" ]] || return 1
  [[ "$(stat -c '%a' "${latest_path}")" == '600' ]]
  [[ "$(stat -c '%a' "${latest_path}.sha256")" == '600' ]]
  (cd "$(dirname "${latest_path}")" && sha256sum --check "$(basename "${latest_path}").sha256" >/dev/null)
  [[ -z "$(find "${backup_dir}" -maxdepth 1 -type f \( -name '*.dump' -o -name '*.part' -o -name '*.dump.part' \) -print -quit)" ]]
}

backup_state='reused'
if ! verify_latest; then
  systemctl start kamilya-pg-backup.service
  [[ "$(systemctl show kamilya-pg-backup.service -p Result --value)" == 'success' ]]
  [[ "$(systemctl show kamilya-pg-backup.service -p ExecMainStatus --value)" == '0' ]]
  verify_latest
  backup_state='created'
fi
[[ "$(runuser -u postgres -- psql -d "${db_name}" -Atqc 'SELECT version_num FROM alembic_version')" == "${expected_revision}" ]]
printf 'EVIDENCE|ct125_revision=%s|backup=encrypted_verified_fresh|backup_action=%s\n' "${expected_revision}" "${backup_state}"
CT125_GATE
