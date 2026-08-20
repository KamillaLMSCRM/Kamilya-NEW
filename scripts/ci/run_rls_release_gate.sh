#!/usr/bin/env bash
# Focused PostgreSQL 17/pgvector tenant-isolation release gate.

set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
API_DIR="${ROOT_DIR}/apps/api"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

: "${DATABASE_URL:?DATABASE_URL is required}"
[[ "${APP_ENV:-}" == "test" ]] || die "RLS gate requires APP_ENV=test"
[[ "${RLS_GATE_CONFIRMATION:-}" == "EPHEMERAL_POSTGRES_ONLY" ]] || die "RLS gate requires explicit ephemeral-database confirmation"
[[ "${DATABASE_URL}" == *'@localhost:'* || "${DATABASE_URL}" == *'@127.0.0.1:'* ]] || die "RLS gate accepts only a localhost ephemeral database"

cd -- "${API_DIR}"
PYTHONPATH=. poetry run pytest -q \
  tests/integration/test_rls_release_environment.py \
  tests/test_tenant_isolation.py \
  tests/integration/test_adaptive_staff_import_rls.py \
  tests/integration/test_training_evidence_export_api.py \
  tests/integration/test_training_evidence_shares.py \
  tests/integration/test_ai_generation_execution_claim.py \
  tests/integration/test_superadmin_admin_rls.py
