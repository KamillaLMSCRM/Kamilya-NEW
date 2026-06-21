#!/bin/bash
# Kamilya LMS — Database Restore Script
# Usage: ./restore.sh /opt/lms/backups/kamilya_20260621_020000.sql.gz

set -euo pipefail

# Configuration
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-kamilya}"
DB_USER="${DB_USER:-user}"

# Check arguments
if [ $# -eq 0 ]; then
  echo "Usage: $0 <backup_file>"
  echo "Example: $0 /opt/lms/backups/kamilya_20260621_020000.sql.gz"
  exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "ERROR: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

# Confirm
read -p "This will OVERWRITE the database '${DB_NAME}'. Continue? (yes/no): " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
  echo "Restore cancelled."
  exit 0
fi

# Drop and recreate database
echo "Dropping existing database..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c \
  "DROP DATABASE IF EXISTS ${DB_NAME};"

echo "Creating new database..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c \
  "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# Restore from backup
echo "Restoring from: ${BACKUP_FILE}"
gunzip -c "${BACKUP_FILE}" | pg_restore \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --verbose \
  --no-owner \
  --no-acl \
  2>"${BACKUP_DIR}/restore_$(date +%Y%m%d_%H%M%S).log"

# Verify
echo "Verifying restore..."
TABLE_COUNT=$(psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -t -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")

echo "Restore complete. Tables: ${TABLE_COUNT}"
