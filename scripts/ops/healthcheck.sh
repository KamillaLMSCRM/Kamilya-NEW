#!/usr/bin/env bash
# Kamilya production watchdog for the first-tenant operating baseline.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

API_HEALTH_URL="${API_HEALTH_URL:-https://kamilya-lms-api.onrender.com/api/v1/health}"
WEB_HEALTH_URL="${WEB_HEALTH_URL:-https://app.kml.kz/login}"
WORKER_SERVICES="${WORKER_SERVICES:-kamilya-worker.service,kamilya-worker-documents.service,kamilya-worker-ai.service}"
VALKEY_SERVICE="${VALKEY_SERVICE:-valkey-server.service}"
BACKUP_DIR="${BACKUP_DIR:-/opt/kamilya-backups}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-30}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-85}"
ALERT_STATE_DIR="${ALERT_STATE_DIR:-/var/lib/kamilya-ops}"
ALERT_COOLDOWN_SECONDS="${ALERT_COOLDOWN_SECONDS:-21600}"
CELERY_BIN="${CELERY_BIN:-/opt/kamilya-worker/apps/api/.venv/bin/celery}"
CELERY_APP="${CELERY_APP:-app.core.celery_app:celery_app}"
CELERY_WORKDIR="${CELERY_WORKDIR:-/opt/kamilya-worker/apps/api}"
EXPECTED_CELERY_NODES="${EXPECTED_CELERY_NODES:-3}"
CELERY_QUEUE_MAX_DEPTH="${CELERY_QUEUE_MAX_DEPTH:-50}"

failures=()

require_integer() {
  local name=$1
  local value=$2
  [[ "${value}" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: %s must be a non-negative integer\n' "${name}" >&2
    exit 2
  }
}

require_integer BACKUP_MAX_AGE_HOURS "${BACKUP_MAX_AGE_HOURS}"
require_integer DISK_MAX_PERCENT "${DISK_MAX_PERCENT}"
require_integer ALERT_COOLDOWN_SECONDS "${ALERT_COOLDOWN_SECONDS}"
require_integer EXPECTED_CELERY_NODES "${EXPECTED_CELERY_NODES}"
require_integer CELERY_QUEUE_MAX_DEPTH "${CELERY_QUEUE_MAX_DEPTH}"

check_service() {
  local service=$1
  systemctl is-active --quiet "${service}" ||
    failures+=("service ${service} is not active")
}

check_url() {
  local label=$1
  local url=$2
  curl --fail --silent --show-error --location \
    --connect-timeout 10 --max-time 20 --retry 2 --retry-delay 2 \
    --output /dev/null "${url}" ||
    failures+=("${label} is unavailable")
}

check_backup_age() {
  local newest now age_seconds max_age_seconds
  newest="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'kamilya_*.dump.enc' \
    -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 || true)"
  if [[ -z "${newest}" ]]; then
    failures+=("no encrypted database backup found")
    return
  fi
  newest="${newest%% *}"
  now="$(date +%s)"
  age_seconds=$((now - ${newest%.*}))
  max_age_seconds=$((BACKUP_MAX_AGE_HOURS * 3600))
  (( age_seconds <= max_age_seconds )) ||
    failures+=("latest database backup is older than ${BACKUP_MAX_AGE_HOURS} hours")
}

check_disk() {
  local used
  used="$(df -P / | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')"
  [[ "${used}" =~ ^[0-9]+$ ]] || {
    failures+=("disk usage could not be determined")
    return
  }
  (( used < DISK_MAX_PERCENT )) ||
    failures+=("root disk usage is ${used}% (limit ${DISK_MAX_PERCENT}%)")
}

check_worker_ping() {
  local output node_count
  if [[ ! -x "${CELERY_BIN}" ]]; then
    failures+=("Celery executable is missing")
    return
  fi
  output="$(
    cd "${CELERY_WORKDIR}"
    timeout 20 "${CELERY_BIN}" -A "${CELERY_APP}" inspect ping --timeout 8 --json
  )" 2>/dev/null || {
    failures+=("Celery workers did not answer ping")
    return
  }
  node_count="$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' <<<"${output}" 2>/dev/null || printf '0')"
  (( node_count >= EXPECTED_CELERY_NODES )) ||
    failures+=("only ${node_count}/${EXPECTED_CELERY_NODES} Celery workers answered ping")
}

check_queue_depth() {
  local output
  output="$(
    cd "${CELERY_WORKDIR}"
    PYTHONPATH="${CELERY_WORKDIR}" \
      .venv/bin/python /opt/kamilya-worker/scripts/ops/queue_depth.py \
      --max-depth "${CELERY_QUEUE_MAX_DEPTH}"
  )" 2>/dev/null || {
    failures+=("${output:-Celery queue depth could not be checked}")
    return
  }
  [[ -z "${output}" ]] || failures+=("${output}")
}

send_email() {
  local subject=$1
  local body=$2
  local payload

  [[ -n "${RESEND_API_KEY:-}" ]] || return 1
  [[ -n "${ALERT_EMAIL:-}" ]] || return 1
  [[ -n "${EMAIL_FROM:-}" ]] || return 1

  payload="$(python3 -c \
    'import json,sys; print(json.dumps({"from":sys.argv[1],"to":[sys.argv[2]],"subject":sys.argv[3],"text":sys.argv[4]}))' \
    "${EMAIL_FROM}" "${ALERT_EMAIL}" "${subject}" "${body}")"

  curl --fail --silent --show-error \
    --connect-timeout 10 --max-time 20 \
    --request POST 'https://api.resend.com/emails' \
    --header "Authorization: Bearer ${RESEND_API_KEY}" \
    --header 'Content-Type: application/json' \
    --data "${payload}" >/dev/null
}

notify_state_change() {
  local state_file="${ALERT_STATE_DIR}/last_failure"
  local sent_file="${ALERT_STATE_DIR}/last_sent_at"
  local current_state previous_state now last_sent body
  mkdir -p -- "${ALERT_STATE_DIR}"
  current_state="$(printf '%s\n' "${failures[@]:-}")"
  previous_state="$(cat "${state_file}" 2>/dev/null || true)"
  now="$(date +%s)"
  last_sent="$(cat "${sent_file}" 2>/dev/null || printf '0')"

  if ((${#failures[@]} == 0)); then
    if [[ -n "${previous_state}" ]]; then
      if send_email '[RECOVERED] Kamilya LMS production checks' \
        "All production checks are healthy on $(hostname)."; then
        : >"${state_file}"
        printf '%s' "${now}" >"${sent_file}"
      fi
      return
    fi
    : >"${state_file}"
    return
  fi

  printf '%s\n' "${current_state}" >"${state_file}"
  if [[ "${current_state}" != "${previous_state}" ]] ||
    (( now - last_sent >= ALERT_COOLDOWN_SECONDS )); then
    body="Host: $(hostname)
UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)

${current_state}"
    if send_email '[ALERT] Kamilya LMS production checks failed' "${body}"; then
      printf '%s' "${now}" >"${sent_file}"
    fi
  fi
}

IFS=',' read -r -a worker_services <<<"${WORKER_SERVICES}"
for worker_service in "${worker_services[@]}"; do
  check_service "${worker_service}"
done
check_service "${VALKEY_SERVICE}"
check_url API "${API_HEALTH_URL}"
check_url frontend "${WEB_HEALTH_URL}"
check_backup_age
check_disk
check_worker_ping
check_queue_depth
notify_state_change

if ((${#failures[@]} > 0)); then
  printf 'Production checks failed:\n' >&2
  printf ' - %s\n' "${failures[@]}" >&2
  exit 1
fi

printf 'All production checks passed.\n'
