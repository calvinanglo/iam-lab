#!/bin/bash
# scripts/backup.sh
# Schedule: 0 2 * * * /path/to/iam-lab/scripts/backup.sh

set -euo pipefail

export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin:/usr/local/bin:/usr/bin"

BACKUP_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
RETENTION_DAYS=30

mkdir -p "${BACKUP_PATH}"
echo "[$(date)] Starting backup..."

# PostgreSQL
echo "[+] Keycloak database..."
docker exec $(docker ps -qf "name=keycloak-db") \
    pg_dump -U keycloak -Fc keycloak > "${BACKUP_PATH}/keycloak-db.dump"

# LDAP
echo "[+] LDAP directory..."
docker exec $(docker ps -qf "name=openldap") \
    slapcat -n 1 > "${BACKUP_PATH}/ldap-data.ldif"

# Verify
echo "[+] Verifying..."
for file in "${BACKUP_PATH}"/*; do
    size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file")
    [ "$size" -eq 0 ] && echo "[ERROR] Empty: $file" && exit 1
    echo "  OK: $(basename $file) (${size} bytes)"
done

# Compress & prune
tar -czf "${BACKUP_DIR}/${TIMESTAMP}.tar.gz" -C "${BACKUP_DIR}" "${TIMESTAMP}"
rm -rf "${BACKUP_PATH}"
find "${BACKUP_DIR}" -name "*.tar.gz" -mtime +${RETENTION_DAYS} -delete

echo "[$(date)] Backup complete: ${BACKUP_DIR}/${TIMESTAMP}.tar.gz"
