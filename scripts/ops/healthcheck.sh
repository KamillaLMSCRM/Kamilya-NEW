#!/usr/bin/env bash
# Kamilya production watchdog for the first-tenant operating baseline.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

API_HEALTH_URL="${API_HEALTH_URL:-https://api.kml.kz/api/v1/health}"
WEB_HEALTH_URL="${WEB_HEALTH_URL:-https://app.kml.kz/login}"
EXPECTED_DEPLOYMENT_ENVIRONMENT="${EXPECTED_DEPLOYMENT_ENVIRONMENT:-kz-production}"
EXPECTED_RELEASE_SHA="${EXPECTED_RELEASE_SHA:-}"
PRODUCTION_VERIFIER="${PRODUCTION_VERIFIER:-/opt/kamilya-worker/scripts/ops/verify_production_endpoint.py}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/kamilya-runtime/kamilya-app-worker.yml}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-/opt/kamilya-runtime/deploy.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kamilya-runtime}"
REQUIRED_COMPOSE_SERVICES="${REQUIRED_COMPOSE_SERVICES:-api,valkey,worker-ai,worker-documents,worker-ops}"
BACKUP_FRESHNESS_PATH="${BACKUP_FRESHNESS_PATH:-}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-30}"
DISK_MAX_PERCENT="${DISK_MAX_PERCENT:-85}"
ALERT_STATE_DIR="${ALERT_STATE_DIR:-/var/lib/kamilya-ops}"
ALERT_COOLDOWN_SECONDS="${ALERT_COOLDOWN_SECONDS:-21600}"
EXPECTED_CELERY_NODES="${EXPECTED_CELERY_NODES:-3}"

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
compose() {
  docker compose \
    --project-name "${COMPOSE_PROJECT_NAME}" \
    --env-file "${COMPOSE_ENV_FILE}" \
    --file "${COMPOSE_FILE}" "$@"
}

check_runtime_services() {
  local output service
  if [[ ! -f "${COMPOSE_FILE}" || ! -f "${COMPOSE_ENV_FILE}" ]]; then
    failures+=("KZ runtime compose inventory is missing")
    return
  fi
  output="$(compose ps --services --status running 2>/dev/null)" || {
    failures+=("KZ runtime compose status could not be read")
    return
  }
  IFS=',' read -r -a required_services <<<"${REQUIRED_COMPOSE_SERVICES}"
  for service in "${required_services[@]}"; do
    grep -Fxq "${service}" <<<"${output}" ||
      failures+=("compose service ${service} is not running")
  done
}

check_public_identity() {
  if [[ ! "${EXPECTED_RELEASE_SHA}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    failures+=("EXPECTED_RELEASE_SHA must be an exact 40-character Git SHA")
    return
  fi
  if [[ ! -f "${PRODUCTION_VERIFIER}" ]]; then
    failures+=("production endpoint verifier is missing")
    return
  fi
  python3 "${PRODUCTION_VERIFIER}" \
    --api-url "${API_HEALTH_URL}" \
    --web-url "${WEB_HEALTH_URL}" \
    --expected-deployment "${EXPECTED_DEPLOYMENT_ENVIRONMENT}" \
    --expected-release "${EXPECTED_RELEASE_SHA}" >/dev/null ||
    failures+=("KZ production endpoint identity check failed")
}

check_backup_age() {
  local newest now age_seconds max_age_seconds
  if [[ -z "${BACKUP_FRESHNESS_PATH}" || ! -e "${BACKUP_FRESHNESS_PATH}" ]]; then
    failures+=("KZ backup freshness source is not configured")
    return
  fi
  if [[ -d "${BACKUP_FRESHNESS_PATH}" ]]; then
    newest="$(find "${BACKUP_FRESHNESS_PATH}" -maxdepth 1 -type f \
      \( -name '*.dump.gpg' -o -name '*.tar.gpg' \) \
      -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 || true)"
  else
    newest="$(stat -c '%Y %n' "${BACKUP_FRESHNESS_PATH}" 2>/dev/null || true)"
  fi
  if [[ -z "${newest}" ]]; then
    failures+=("no current encrypted KZ backup evidence found")
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
  output="$(
    timeout 20 docker compose \
      --project-name "${COMPOSE_PROJECT_NAME}" \
      --env-file "${COMPOSE_ENV_FILE}" \
      --file "${COMPOSE_FILE}" \
      exec -T api poetry run celery \
      -A app.core.celery_app:celery_app inspect ping --timeout 8 --json
  )" 2>/dev/null || {
    failures+=("Celery workers did not answer ping")
    return
  }
  node_count="$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' <<<"${output}" 2>/dev/null || printf '0')"
  (( node_count >= EXPECTED_CELERY_NODES )) ||
    failures+=("only ${node_count}/${EXPECTED_CELERY_NODES} Celery workers answered ping")
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

check_runtime_services
check_public_identity
check_backup_age
check_disk
check_worker_ping
notify_state_change

if ((${#failures[@]} > 0)); then
  printf 'Production checks failed:\n' >&2
  printf ' - %s\n' "${failures[@]}" >&2
  exit 1
fi

printf 'All production checks passed.\n'
