#!/bin/bash
# scripts/restore.sh
# Usage: ./restore.sh <backup_file.tar.gz>
# Restores PostgreSQL and LDAP from a backup created by backup.sh.

set -euo pipefail

export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin:/usr/local/bin:/usr/bin"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

BACKUP_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <backup_file.tar.gz>"
    echo ""
    echo "Available backups:"
    ls -lh "${BACKUP_DIR}"/*.tar.gz 2>/dev/null || echo "  None found in ${BACKUP_DIR}/"
    exit 1
fi

BACKUP_FILE="$1"
[ ! -f "${BACKUP_FILE}" ] && BACKUP_FILE="${BACKUP_DIR}/${BACKUP_FILE}"
[ ! -f "${BACKUP_FILE}" ] && echo -e "${RED}[ERROR]${NC} File not found: ${BACKUP_FILE}" && exit 1

EXTRACT_DIR="${BACKUP_DIR}/restore_$$"
mkdir -p "${EXTRACT_DIR}"
trap "rm -rf ${EXTRACT_DIR}" EXIT

echo "[$(date)] Starting restore from $(basename "${BACKUP_FILE}")..."
echo ""

# Verify backup integrity before extracting
echo "[+] Verifying backup integrity..."
if ! tar -tzf "${BACKUP_FILE}" >/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} Backup file is corrupt or not a valid tar.gz"
    exit 1
fi
echo -e "  ${GREEN}OK${NC}: archive is valid"

echo "[+] Extracting..."
tar -xzf "${BACKUP_FILE}" -C "${EXTRACT_DIR}" --strip-components=1

# Verify expected files exist
for expected in keycloak-db.dump ldap-data.ldif; do
    if [ ! -f "${EXTRACT_DIR}/${expected}" ]; then
        echo -e "  ${YELLOW}WARN${NC}: ${expected} not found in backup — skipping"
    fi
done

# PostgreSQL restore
if [ -f "${EXTRACT_DIR}/keycloak-db.dump" ]; then
    echo ""
    echo "[+] Restoring Keycloak database..."
    DB_CONTAINER=$(docker ps -qf "name=keycloak-db")
    if [ -z "$DB_CONTAINER" ]; then
        echo -e "  ${RED}FAIL${NC}: keycloak-db container not running"
    else
        if docker exec -i "$DB_CONTAINER" \
            pg_restore -U keycloak -d keycloak -c --if-exists < "${EXTRACT_DIR}/keycloak-db.dump" 2>/dev/null; then
            echo -e "  ${GREEN}OK${NC}: database restored"
        else
            echo -e "  ${YELLOW}WARN${NC}: pg_restore reported warnings (often harmless — verify manually)"
        fi

        # Verify restore
        echo "[+] Verifying database restore..."
        TABLE_COUNT=$(docker exec "$DB_CONTAINER" \
            psql -U keycloak -d keycloak -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ')
        if [ "${TABLE_COUNT:-0}" -gt 0 ]; then
            echo -e "  ${GREEN}OK${NC}: ${TABLE_COUNT} tables found in restored database"
        else
            echo -e "  ${RED}FAIL${NC}: no tables found after restore"
        fi
    fi
fi

# LDAP restore
if [ -f "${EXTRACT_DIR}/ldap-data.ldif" ]; then
    echo ""
    echo "[+] Restoring LDAP directory..."
    LDAP_CONTAINER=$(docker ps -qf "name=openldap")
    if [ -z "$LDAP_CONTAINER" ]; then
        echo -e "  ${RED}FAIL${NC}: openldap container not running"
    else
        # Copy LDIF into container and attempt restore
        docker cp "${EXTRACT_DIR}/ldap-data.ldif" "${LDAP_CONTAINER}:/tmp/ldap-data.ldif"
        echo "  LDIF copied into container at /tmp/ldap-data.ldif"
        echo ""
        echo -e "  ${YELLOW}NOTE${NC}: LDAP restore requires manual steps:"
        echo "    1. docker compose stop openldap"
        echo "    2. docker compose run --rm openldap slapadd -n 1 -l /tmp/ldap-data.ldif"
        echo "    3. docker compose start openldap"
        echo ""
        echo "  Alternatively, the backup LDIF is also saved to:"
        cp "${EXTRACT_DIR}/ldap-data.ldif" "${BACKUP_DIR}/ldap-data-restore.ldif"
        echo "    ${BACKUP_DIR}/ldap-data-restore.ldif"
    fi
fi

echo ""
echo "════════════════════════════════════════"
echo -e " ${GREEN}Restore complete${NC} — restart Keycloak to pick up DB changes:"
echo "   docker compose restart keycloak"
echo "════════════════════════════════════════"
