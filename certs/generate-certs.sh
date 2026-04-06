#!/bin/bash
# certs/generate-certs.sh

set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="iam-lab.local"
DAYS_VALID=365

echo "[+] Generating CA..."
openssl genrsa -out "${CERT_DIR}/ca.key" 4096
openssl req -x509 -new -nodes \
    -key "${CERT_DIR}/ca.key" \
    -sha256 -days ${DAYS_VALID} \
    -out "${CERT_DIR}/ca.crt" \
    -subj "/C=CA/ST=Ontario/L=Toronto/O=IAM Lab CA/CN=IAM Lab Root CA"

echo "[+] Generating server certificate..."
openssl genrsa -out "${CERT_DIR}/server.key" 2048

cat > "${CERT_DIR}/san.cnf" << EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
C = CA
ST = Ontario
L = Toronto
O = IAM Lab
CN = ${DOMAIN}

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${DOMAIN}
DNS.2 = keycloak.${DOMAIN}
DNS.3 = ldap.${DOMAIN}
DNS.4 = grafana.${DOMAIN}
DNS.5 = gitea.${DOMAIN}
DNS.6 = nextcloud.${DOMAIN}
DNS.7 = localhost
IP.1 = 127.0.0.1
EOF

openssl req -new -key "${CERT_DIR}/server.key" \
    -out "${CERT_DIR}/server.csr" -config "${CERT_DIR}/san.cnf"

openssl x509 -req -in "${CERT_DIR}/server.csr" \
    -CA "${CERT_DIR}/ca.crt" -CAkey "${CERT_DIR}/ca.key" -CAcreateserial \
    -out "${CERT_DIR}/server.crt" -days ${DAYS_VALID} -sha256 \
    -extensions v3_req -extfile "${CERT_DIR}/san.cnf"

chmod 600 "${CERT_DIR}/ca.key" "${CERT_DIR}/server.key"
chmod 644 "${CERT_DIR}/ca.crt" "${CERT_DIR}/server.crt"
rm -f "${CERT_DIR}/server.csr" "${CERT_DIR}/san.cnf" "${CERT_DIR}/ca.srl"

echo "[+] Done. Add ca.crt to your browser trust store."
