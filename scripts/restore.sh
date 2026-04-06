#!/bin/bash
# scripts/restore.sh
# Usage: ./restore.sh <backup_file.tar.gz>

set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <backup_file.tar.gz>"
    echo "Available backups:"
    ls -lh "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || echo "  None found"
    exit 1
fi

BACKUP_FILE="$1"
[ ! -f "${BACKUP_FILE}" ] && BACKUP_FILE="${BACKUP_DIR}/${BACKUP_FILE}"
[ ! -f "${BACKUP_FILE}" ] && echo "[ERROR] File not found: ${BACKUP_FILE}" && exit 1

EXTRACT_DIR="${BACKUP_DIR}/restore_$$"
mkdir -p "${EXTRACT_DIR}"
trap "rm -rf ${EXTRACT_DIR}" EXIT

echo "[$(date)] Extracting ${BACKUP_FILE}..."
tar -xzf "${BACKUP_FILE}" -C "${EXTRACT_DIR}" --strip-components=1

# PostgreSQL restore
if [ -f "${EXTRACT_DIR}/keycloak-db.dump" ]; then
    echo "[+] Restoring Keycloak database..."
    docker exec -i $(docker ps -qf "name=keycloak-db") \
        pg_restore -U keycloak -d keycloak -c < "${EXTRACT_DIR}/keycloak-db.dump"
    echo "  OK: database restored"
fi

# LDAP restore
if [ -f "${EXTRACT_DIR}/ldap-data.ldif" ]; then
    echo "[+] Restoring LDAP directory..."
    echo "  NOTE: Stop openldap container, restore manually with slapadd, then restart."
    echo "  Command: docker exec \$(docker ps -qf 'name=openldap') slapadd -n 1 -l /tmp/ldap-data.ldif"
    cp "${EXTRACT_DIR}/ldap-data.ldif" "${BACKUP_DIR}/ldap-data-restore.ldif"
    echo "  LDIF copied to: ${BACKUP_DIR}/ldap-data-restore.ldif"
fi

echo "[$(date)] Restore complete."
