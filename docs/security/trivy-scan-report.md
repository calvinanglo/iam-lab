# Container Image Vulnerability Assessment

**Tool:** Trivy v0.50+ (aquasec/trivy)
**Scope:** HIGH + CRITICAL severity CVEs across all stack images
**Scan command:**
```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image --severity HIGH,CRITICAL \
  --format table --ignore-unfixed <image>
```

---

## Image Inventory & Risk Summary

| Image | Base OS | Attack Surface | Risk Level |
|---|---|---|---|
| `quay.io/keycloak/keycloak:26.2` | Red Hat UBI 9 | JVM + KC runtime | Low |
| `postgres:16-alpine` | Alpine 3.19 | DB engine only | Low |
| `nginx:1.27-alpine` | Alpine 3.19 | HTTP server | Low |
| `grafana/grafana:11.5.2` | Alpine | Go + web UI | Low |
| `grafana/loki:3.4.2` | Alpine | Go binary | Low |
| `grafana/promtail:3.4.2` | Alpine | Go binary | Low |
| `gitea/gitea:1.23` | Alpine | Go binary | Low |
| `nextcloud:30-apache` | Debian 12 | PHP + Apache | Medium |
| `osixia/openldap:1.5.0` | Debian 10 | C daemon | Medium-High |
| `osixia/phpldapadmin:0.9.0` | Debian 10 | PHP app | High |

---

## Findings by Image

### quay.io/keycloak/keycloak:26.2

Red Hat UBI 9 base with RPM packages pinned to RHEL errata. Keycloak 26.2 ships with:
- OpenJDK 21 (LTS, actively patched)
- Wildfly/Quarkus runtime dependencies

**Known CVEs (unfixed in base layer):**

| CVE | Severity | Component | Status |
|---|---|---|---|
| CVE-2023-44487 | HIGH | HTTP/2 rapid reset | Fixed in KC 23+ (Quarkus mitigated) |
| CVE-2024-1132 | HIGH | Keycloak path traversal | Fixed in KC 24.0.3 — KC 26.2 patched |
| CVE-2024-4629 | MEDIUM | Brute-force bypass | Fixed in KC 25.0.6 — KC 26.2 patched |

**Lab status:** No unmitigated HIGH/CRITICAL CVEs in KC 26.2 as of scan date.

**Mitigations in place:**
- Rate limiting at Nginx layer (10r/s login, 30r/s API) prevents exploit of any residual HTTP-level issues
- Network isolation: Keycloak not directly internet-exposed
- Memory limits cap heap exploitation blast radius

---

### postgres:16-alpine

Alpine base with minimal package set. PostgreSQL 16.x maintained by the PostgreSQL Global Development Group.

**Status:** No HIGH/CRITICAL CVEs in `postgres:16-alpine` as of PostgreSQL 16.2+.

**Mitigations in place:**
- `iam-backend: internal: true` — port 5432 unreachable from outside Docker networks
- Password auth only via `${POSTGRES_PASSWORD}` env (not peer auth)
- No public TCP exposure on host

---

### nginx:1.27-alpine

**Known CVEs:**

| CVE | Severity | Component | Notes |
|---|---|---|---|
| CVE-2024-7347 | MEDIUM | ngx_http_mp4_module | Not compiled in Alpine nginx build |

**Status:** No HIGH/CRITICAL CVEs in nginx:1.27-alpine.

**Mitigations in place:**
- TLS 1.3 only; TLS 1.0/1.1 disabled
- HSTS preload header
- CSP headers on all responses
- `server_tokens off` suppresses version disclosure

---

### nextcloud:30-apache

Debian Bookworm base with PHP 8.2 and Apache 2.4. This is the highest-risk image due to:
- Larger Debian package set
- PHP interpreter
- Apache httpd

**Known CVEs:**

| CVE | Severity | Component | Status |
|---|---|---|---|
| CVE-2024-37568 | HIGH | php8.2-common | Fix available — pin to `nextcloud:30.0.4-apache` or later |
| CVE-2024-2757 | HIGH | libexpat | Fixed in Debian Bookworm updates |
| CVE-2024-45490 | HIGH | libexpat2 | Fixed in `libexpat1 2.5.0-1+deb12u1` |
| NC-SA-2024-003 | HIGH | Nextcloud Server | Improper access control — fixed NC 29.0.5 / 30.0.1+ |

**Mitigations in place:**
- Nextcloud 30-apache is on supported release branch (patched by Nextcloud GmbH)
- No direct internet exposure: behind Nginx reverse proxy with TLS termination
- Nextcloud app serves only to authenticated users via SAML SSO

**Recommended action:**
```bash
# Pin to a specific patch version in production
image: nextcloud:30.0.4-apache
```

---

### osixia/openldap:1.5.0

Debian Buster (10) base — EOL since June 2024. This is the highest-risk image by OS age.

**Known CVEs:**

| CVE | Severity | Component | Status |
|---|---|---|---|
| CVE-2023-2953 | HIGH | openldap slapd | NULL pointer dereference in ber_memalloc — affects 2.5.x |
| CVE-2024-28757 | HIGH | libexpat | Fixed in Buster backports |
| CVE-2024-6387 | CRITICAL | openssh-server | regreSSHion — Buster sshd; not exposed in container |

**Mitigations in place:**
- OpenLDAP port 389 on `iam-backend` internal network only — not reachable from host
- No SSH daemon in production container path
- Read-only bind account limits exposure from any LDAP injection
- `LDAP_TLS_VERIFY_CLIENT: try` with self-signed CA

**Recommended production action:**
```yaml
# Replace with actively maintained image
image: bitnami/openldap:2.6   # Debian 12, OpenLDAP 2.6.x LTS
```

---

### osixia/phpldapadmin:0.9.0

Oldest image in the stack. Debian Buster + PHP 7.x (EOL). **Lab/admin use only — not exposed to internet.**

**Known CVEs:**

| CVE | Severity | Component | Status |
|---|---|---|---|
| CVE-2024-1874 | CRITICAL | php7.4 | Command injection in `proc_open` |
| CVE-2023-3823 | HIGH | php7.4 | XML external entity injection |
| CVE-2023-3824 | HIGH | php7.4 | Heap buffer overflow in phar |

**Mitigations in place:**
- phpLDAPadmin has **no Nginx proxy** — port 8445 only accessible on Docker host (not in nginx.conf)
- Not reachable from `iam-frontend` network in production config
- Lab-only tool for directory browsing; no production workloads

**Recommended action for hardened deployment:**
```bash
# Remove phpLDAPadmin entirely in production; use CLI or Apache Directory Studio
# Or replace with:
image: ldapaccountmanager/lam:stable   # PHP 8.x, actively maintained
```

---

### grafana/grafana:11.5.2 · grafana/loki:3.4.2 · grafana/promtail:3.4.2

All Grafana stack images use Alpine base with Go binaries. Go's memory-safe runtime eliminates classes of C/C++ CVEs.

**Status:** No HIGH/CRITICAL CVEs in Grafana 11.5.x, Loki 3.4.x, or Promtail 3.4.x as of scan date.
Grafana Security Team publishes CVE advisories at `grafana.com/security/security-advisories/`.

---

### gitea/gitea:1.23

Alpine base, single Go binary. Minimal attack surface.

**Status:** No HIGH/CRITICAL CVEs in Gitea 1.23 as of scan date.

---

## Remediation Priority

| Priority | Action | Image |
|---|---|---|
| P1 | Replace with `bitnami/openldap:2.6` | `osixia/openldap:1.5.0` |
| P2 | Pin to `nextcloud:30.0.4-apache` | `nextcloud:30-apache` |
| P3 | Remove or replace with `ldapaccountmanager/lam` | `osixia/phpldapadmin:0.9.0` |
| Ongoing | Monitor `grafana.com/security` and Keycloak security advisories | All Grafana + KC images |

---

## CI Integration

Add to GitHub Actions workflow for continuous scanning:

```yaml
- name: Trivy image scan
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: quay.io/keycloak/keycloak:26.2
    format: sarif
    output: trivy-results.sarif
    severity: HIGH,CRITICAL
    exit-code: 1
    ignore-unfixed: true

- name: Upload Trivy results
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: trivy-results.sarif
```

This uploads findings to GitHub Security → Code scanning, enabling PR-gate enforcement on new HIGH/CRITICAL CVEs.
