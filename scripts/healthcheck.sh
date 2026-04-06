#!/bin/bash
# scripts/healthcheck.sh

set -uo pipefail

# Ensure docker is on PATH (Windows Docker Desktop)
export PATH="$PATH:/c/Program Files/Docker/Docker/resources/bin:/usr/local/bin:/usr/bin"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

check() {
    if eval "$2" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $1"; ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $1"; ((FAIL++))
    fi
}

warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"; ((WARN++))
}

check_secret() {
    local label="$1" file="$2"
    if git -C "$(dirname "$0")/.." ls-files --error-unmatch "$file" 2>/dev/null | grep -q .; then
        echo -e "  ${RED}✗${NC} SECRET EXPOSED: $label ($file) is tracked in git!"; ((FAIL++))
    else
        echo -e "  ${GREEN}✓${NC} $label not in git"
    fi
}

echo "═══════════════════════════════════════"
echo " IAM Lab Health Check — $(date)"
echo "═══════════════════════════════════════"

echo ""
echo "── Core Services ──"
check "Keycloak (IdP)" \
    "curl -skw '%{http_code}' -o /dev/null https://localhost:8443/ | grep -qE '^[23]'"
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
# Warn if cert expires within 30 days
if [ -n "$EXPIRY" ]; then
    EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$EXPIRY" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    [ "$DAYS_LEFT" -lt 30 ] && warn "Cert expires in ${DAYS_LEFT} days — renew soon"
fi

echo ""
echo "── Secret Hygiene ──"
check_secret ".env file" ".env"
check_secret "CA private key" "certs/ca.key"
check_secret "Server private key" "certs/server.key"

echo ""
echo "── Resource Headroom ──"
docker stats --no-stream --format "{{.Name}} {{.MemPerc}}" 2>/dev/null | while read name pct; do
    val=${pct//%/}
    val_int=${val%%.*}
    if [ "${val_int:-0}" -ge 85 ]; then
        echo -e "  ${RED}✗${NC} $name memory at ${pct} — approaching limit"
        ((FAIL++))
    elif [ "${val_int:-0}" -ge 70 ]; then
        echo -e "  ${YELLOW}⚠${NC} $name memory at ${pct}"
    fi
done

echo ""
echo "═══════════════════════════════════════"
echo -e " ${GREEN}${PASS} passed${NC} | ${RED}${FAIL} failed${NC} | ${YELLOW}${WARN} warnings${NC}"
echo "═══════════════════════════════════════"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
