#!/bin/bash
# scripts/healthcheck.sh

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

check() {
    if eval "$2" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $1"; ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $1"; ((FAIL++))
    fi
}

echo "═══════════════════════════════════════"
echo " IAM Lab Health Check — $(date)"
echo "═══════════════════════════════════════"

echo ""
echo "── Core Services ──"
check "Keycloak (IdP)" \
    "curl -sfk https://localhost:8443/ | grep -qiE 'keycloak|html'"
check "PostgreSQL" \
    "docker exec \$(docker ps -qf 'name=keycloak-db') pg_isready -U keycloak"
check "OpenLDAP" \
    "docker exec \$(docker ps -qf 'name=openldap') ldapsearch -x -H ldap://localhost:389 -b '' -s base '(objectclass=*)'"
check "Nginx (TLS)" \
    "curl -sfk https://localhost:8443"

echo ""
echo "── Service Providers ──"
check "Grafana" \
    "curl -sfk https://localhost:3443/api/health | grep -q ok"
check "Nextcloud" \
    "curl -sfk https://localhost:8444/status.php"
check "Gitea" \
    "curl -sfk https://localhost:3444/api/healthz"

echo ""
echo "── TLS Certificate ──"
EXPIRY=$(echo | openssl s_client -connect localhost:8443 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
echo -e "  Expires: ${EXPIRY:-unknown}"

echo ""
echo "═══════════════════════════════════════"
echo -e " ${GREEN}${PASS} passed${NC} | ${RED}${FAIL} failed${NC}"
echo "═══════════════════════════════════════"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
