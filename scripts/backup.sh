#!/bin/bash
# Kamilya LMS — Database Backup Script
# Run daily via cron: 0 2 * * * /opt/lms/scripts/backup.sh

set -euo pipefail

# Configuration
BACKUP_DIR="/opt/lms/backups"
RETENTION_DAYS=30
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-kamilya}"
DB_USER="${DB_USER:-user}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/kamilya_${DATE}.sql.gz"

# Create backup directory
mkdir -p "${BACKUP_DIR}"

# Backup database
echo "Starting backup: ${DB_NAME}"
pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
  --format=custom \
  --compress=9 \
  --verbose \
  2>"${BACKUP_DIR}/backup_${DATE}.log" \
  | gzip > "${BACKUP_FILE}"

# Verify backup
if [ -f "${BACKUP_FILE}" ]; then
  SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
  echo "Backup created: ${BACKUP_FILE} (${SIZE})"
else
  echo "ERROR: Backup failed!"
  exit 1
fi

# Upload to S3/MinIO (optional)
if command -v mc &> /dev/null; then
  echo "Uploading to MinIO..."
  mc cp "${BACKUP_FILE}" minio/kamilya-backups/
  echo "Upload complete"
fi

# Clean old backups
echo "Cleaning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "Backup completed: ${BACKUP_FILE}"
