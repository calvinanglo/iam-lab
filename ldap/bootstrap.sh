#!/bin/bash
# ldap/bootstrap.sh — Generate SSHA-hashed passwords and load LDAP data
# Called by osixia/openldap entrypoint via custom bootstrap mount.
#
# The osixia/openldap image automatically processes .ldif files in
# /container/service/slapd/assets/config/bootstrap/ldif/custom/
# on first start. This script pre-processes the template to replace
# password placeholders with proper SSHA hashes.

set -euo pipefail

LDIF_TEMPLATE="/ldap-seed/init-ldap.ldif"
LDIF_OUTPUT="/container/service/slapd/assets/config/bootstrap/ldif/custom/init-ldap.ldif"
DEFAULT_PASSWORD="${LDAP_USER_DEFAULT_PASSWORD:-ChangeMe123!}"

if [ ! -f "$LDIF_TEMPLATE" ]; then
    echo "[bootstrap] No LDIF template found at $LDIF_TEMPLATE — skipping"
    exit 0
fi

echo "[bootstrap] Generating SSHA password hashes..."
SSHA_HASH=$(slappasswd -s "$DEFAULT_PASSWORD")

echo "[bootstrap] Injecting hashed passwords into LDIF..."
mkdir -p "$(dirname "$LDIF_OUTPUT")"
sed "s|{SSHA}BOOTSTRAP_HASH|${SSHA_HASH}|g" "$LDIF_TEMPLATE" > "$LDIF_OUTPUT"

echo "[bootstrap] LDAP bootstrap data ready at $LDIF_OUTPUT"
