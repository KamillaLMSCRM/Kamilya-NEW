#!/usr/bin/env bash
# Initialize pgvector extension and create the lms_app role on first
# Postgres container start. Wired in docker-compose.yml as
# /docker-entrypoint-initdb.d/01-init.sh — Postgres runs all .sh files
# in that directory alphabetically, exactly once, when the data
# directory is empty (i.e. on first 'docker compose up').

set -euo pipefail

# pgvector is bundled with the pgvector/pgvector:pg16 image but must be
# enabled per-database. Without this, alembic upgrade head fails when
# migration 0018 creates document_embeddings.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

# Pre-create the lms_app role that migration 0033 grants table
# privileges to. The role is NOLOGIN — the application connects with
# whatever role DATABASE_URL points at (we recommend 'lms' in dev).
# NOBYPASSRLS is critical: it ensures FORCE ROW LEVEL SECURITY applies
# to this role, so the tenant_id filter on every table is mandatory.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-EOSQL
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lms_app') THEN
            CREATE ROLE lms_app NOLOGIN NOBYPASSRLS;
        ELSE
            ALTER ROLE lms_app NOBYPASSRLS;
        END IF;
    END
    $$;
EOSQL

echo "init-pgvector: pgvector extension enabled, lms_app role created."