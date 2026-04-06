#!/usr/bin/env bash
# nextcloud-saml-setup.sh
# Configures Nextcloud SAML SSO via occ (Nextcloud CLI) inside the container.
#
# Run with: bash scripts/nextcloud-saml-setup.sh
# Prereqs:  docker compose up -d nextcloud && Nextcloud first-run completed
#           Keycloak enterprise realm with Nextcloud SAML client registered

set -euo pipefail

NC_CONTAINER="iam-nextcloud-1"
KC_HOST="keycloak.iam-lab.local"
KC_PORT="8443"
NC_HOST="nextcloud.iam-lab.local"
NC_PORT="8444"

log() { echo "[nextcloud-saml] $*"; }

# ── 1. Install SAML app ───────────────────────────────────────────────────────
log "Installing user_saml app..."
docker exec --user www-data "$NC_CONTAINER" \
  php occ app:install user_saml || \
docker exec --user www-data "$NC_CONTAINER" \
  php occ app:enable user_saml

log "user_saml app: OK"

# ── 2. Fetch Keycloak IdP metadata ───────────────────────────────────────────
log "Fetching Keycloak SAML IdP metadata..."
IDP_META_URL="https://${KC_HOST}:${KC_PORT}/realms/enterprise/protocol/saml/descriptor"

# Extract signing certificate from IdP metadata (strip header/footer/whitespace)
IDP_CERT=$(curl -sk "$IDP_META_URL" \
  | grep -oE '<ds:X509Certificate>[^<]*</ds:X509Certificate>' \
  | head -1 \
  | sed 's/<[^>]*>//g' \
  | tr -d ' \n\r')

if [ -z "$IDP_CERT" ]; then
  log "ERROR: Could not retrieve IdP signing certificate from $IDP_META_URL"
  exit 1
fi
log "IdP signing cert: ${IDP_CERT:0:40}..."

# ── 3. Configure SAML provider ────────────────────────────────────────────────
log "Configuring SAML IdP settings..."

OCC="docker exec --user www-data $NC_CONTAINER php occ"

# General
$OCC saml:config:set \
  --general-uid_mapping=uid \
  --general-idp0_display_name="Keycloak SSO"

# IdP settings
$OCC saml:config:set \
  --idp-entityId="https://${KC_HOST}:${KC_PORT}/realms/enterprise" \
  --idp-singleSignOnService.url="https://${KC_HOST}:${KC_PORT}/realms/enterprise/protocol/saml" \
  --idp-singleLogoutService.url="https://${KC_HOST}:${KC_PORT}/realms/enterprise/protocol/saml" \
  --idp-x509cert="$IDP_CERT"

# SP settings
$OCC saml:config:set \
  --sp-entityId="https://${NC_HOST}:${NC_PORT}/apps/user_saml/saml/metadata" \
  --sp-assertionConsumerService.url="https://${NC_HOST}:${NC_PORT}/apps/user_saml/saml/acs" \
  --sp-singleLogoutService.url="https://${NC_HOST}:${NC_PORT}/apps/user_saml/saml/sls"

# Security settings — require signed assertions (matches Keycloak saml.server.signature=true)
$OCC saml:config:set \
  --security-wantAssertionsSigned=1 \
  --security-authnRequestsSigned=0

# Attribute mappings (must match Keycloak mapper attribute names)
$OCC saml:config:set \
  --idp-attribute-mapping-email=email \
  --idp-attribute-mapping-displayName=displayName

log "SAML configuration applied."

# ── 4. Verify config ──────────────────────────────────────────────────────────
log "Verifying config..."
$OCC saml:config:get

# ── 5. Smoke test: SP-initiated SAML redirect ─────────────────────────────────
log ""
log "SAML Smoke Test:"
log "  SP metadata: https://${NC_HOST}:${NC_PORT}/apps/user_saml/saml/metadata"
log "  Expected:    XML with EntityDescriptor and SPSSODescriptor"
log ""

HTTP_CODE=$(curl -sk -o /tmp/nc_sp_meta.xml -w "%{http_code}" \
  "https://${NC_HOST}:${NC_PORT}/apps/user_saml/saml/metadata")

if [ "$HTTP_CODE" = "200" ]; then
  if grep -q "EntityDescriptor" /tmp/nc_sp_meta.xml; then
    log "  SP metadata: PASS (EntityDescriptor present)"
    grep -o 'entityID="[^"]*"' /tmp/nc_sp_meta.xml | head -1
  else
    log "  SP metadata: FAIL (no EntityDescriptor)"
  fi
else
  log "  SP metadata: FAIL (HTTP $HTTP_CODE)"
fi

log ""
log "  IdP metadata: $IDP_META_URL"
HTTP_CODE=$(curl -sk -o /tmp/idp_meta.xml -w "%{http_code}" "$IDP_META_URL")
if [ "$HTTP_CODE" = "200" ] && grep -q "IDPSSODescriptor" /tmp/idp_meta.xml; then
  log "  IdP metadata: PASS (IDPSSODescriptor present)"
  grep -o 'Location="https://keycloak[^"]*"' /tmp/idp_meta.xml | grep -v resolve | head -1
else
  log "  IdP metadata: FAIL (HTTP $HTTP_CODE)"
fi

log ""
log "SAML setup complete."
log ""
log "To test end-to-end SSO flow:"
log "  1. Open: https://${NC_HOST}:${NC_PORT}/"
log "  2. Click 'Login with Keycloak SSO'"
log "  3. You will be redirected to Keycloak login page"
log "  4. Authenticate as jsmith / alee / mchen / bpatel"
log "  5. TOTP enrollment screen shown (first login)"
log "  6. After TOTP setup, Keycloak sends SAML assertion to Nextcloud ACS"
log "  7. Nextcloud creates user account from uid/email/displayName attributes"
log "  8. User lands in Nextcloud dashboard"
