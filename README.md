# IAM Lab — Production-Grade Identity & Access Management

A fully operational enterprise IAM platform running 12 containers with SSO federation, LDAP directory services, RBAC lifecycle automation, SIEM integration, and infrastructure-as-code. Built to mirror the identity architecture at a Tier 1 financial institution.

> **Stack:** Keycloak 26.2 · OpenLDAP · PostgreSQL 16 · Nginx (TLS 1.3) · Grafana · Loki · Nextcloud · Gitea · SIEM Pipeline · Terraform · Docker Compose

> **[Visual Walkthrough with Screenshots](docs/WALKTHROUGH.md)** — Full step-by-step tour of the live stack

---

## Live Stack Screenshots

> 25 screenshots captured from the live environment — click to expand each section. See the **[Full Visual Walkthrough](docs/WALKTHROUGH.md)** for the complete tour.

<details>
<summary><strong>Keycloak Admin Console — Enterprise IAM Realm</strong></summary>

![Enterprise IAM Realm](docs/screenshots/01-enterprise-realm.png)
</details>

<details>
<summary><strong>RBAC Realm Roles — 5 custom roles mapped from LDAP groups</strong></summary>

![Realm Roles](docs/screenshots/02-realm-roles.png)
</details>

<details>
<summary><strong>SSO Clients — Grafana (OIDC), Gitea (OIDC), Nextcloud (SAML)</strong></summary>

![Clients](docs/screenshots/04-clients.png)
</details>

<details>
<summary><strong>Grafana OIDC Client — Redirect URIs & PKCE S256 Configuration</strong></summary>

![Grafana Client Settings](docs/screenshots/22-grafana-client-settings.png)
</details>

<details>
<summary><strong>LDAP User Federation — OpenLDAP directory integration</strong></summary>

![LDAP Settings](docs/screenshots/07-ldap-settings.png)
</details>

<details>
<summary><strong>Federated Users — LDAP-synced user directory</strong></summary>

![Users](docs/screenshots/05-users.png)
</details>

<details>
<summary><strong>Brute Force Detection — Progressive lockout after 5 failures</strong></summary>

![Brute Force](docs/screenshots/09-brute-force.png)
</details>

<details>
<summary><strong>Grafana — OIDC SSO with "Sign in with Keycloak SSO"</strong></summary>

![Grafana SSO](docs/screenshots/12-grafana-sso.png)
</details>

<details>
<summary><strong>IAM Operations Dashboard — Live authentication event monitoring</strong></summary>

![IAM Dashboard](docs/screenshots/19-grafana-iam-dashboard.png)
![IAM Dashboard Events](docs/screenshots/20-grafana-iam-dashboard-scroll.png)
</details>

<details>
<summary><strong>Loki Log Aggregation — Centralized log pipeline from all 12 containers</strong></summary>

![Grafana Data Sources](docs/screenshots/21-grafana-datasources.png)
</details>

<details>
<summary><strong>Gitea — Self-hosted Git service with OIDC SSO</strong></summary>

![Gitea](docs/screenshots/13-gitea.png)
</details>

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [What This Demonstrates](#what-this-demonstrates)
3. [Quick Start](#quick-start)
4. [Implementation Walkthrough](#implementation-walkthrough)
   - [Step 1: Network Architecture & TLS Termination](#step-1-network-architecture--tls-termination)
   - [Step 2: Directory Services (OpenLDAP)](#step-2-directory-services-openldap)
   - [Step 3: Identity Provider (Keycloak 26.2)](#step-3-identity-provider-keycloak-262)
   - [Step 4: SSO Federation (OIDC + SAML)](#step-4-sso-federation-oidc--saml)
   - [Step 5: RBAC — LDAP-to-Token Role Chain](#step-5-rbac--ldap-to-token-role-chain)
   - [Step 6: Security Hardening](#step-6-security-hardening)
   - [Step 7: Observability & SIEM](#step-7-observability--siem)
   - [Step 8: IGA Lifecycle Automation](#step-8-iga-lifecycle-automation)
   - [Step 9: Infrastructure-as-Code (Terraform)](#step-9-infrastructure-as-code-terraform)
   - [Step 10: CI/CD & Testing](#step-10-cicd--testing)
5. [Incident Playbooks](#incident-playbooks)
6. [Key Design Decisions](#key-design-decisions)
7. [Repository Structure](#repository-structure)

---

## Architecture Overview

```
                       ┌──────────────────────────────────────────────┐
                       │              BROWSER / CLIENT                │
                       └───────────────────┬──────────────────────────┘
                                           │ HTTPS (TLS 1.3 only)
                       ┌───────────────────▼──────────────────────────┐
                       │           Nginx Reverse Proxy                │
                       │  HSTS preload │ CSP │ Rate-limit │ OCSP     │
                       └──┬────────┬─────────┬──────────┬────────────┘
                          │        │         │          │
               ┌──────────▼──┐ ┌──▼────┐ ┌──▼──────┐ ┌▼───────┐
               │ Keycloak 26 │ │Grafana│ │Nextcloud│ │  Gitea │
               │  :8443 IdP  │ │ :3443 │ │  :8444  │ │  :3444 │
               │ OIDC │ SAML │ │ OIDC  │ │  SAML   │ │  OIDC  │
               └──────┬──────┘ └───────┘ └─────────┘ └────────┘
                      │
         ┌────────────┴──────────────────────────────┐
         │        iam-backend (internal network)      │
         │   ┌──────────────┐    ┌──────────────┐    │
         │   │ PostgreSQL   │    │   OpenLDAP   │    │
         │   │    :5432     │    │     :389     │    │
         │   │  (KC store)  │    │  (user dir)  │    │
         │   └──────────────┘    └──────────────┘    │
         └───────────────────────────────────────────┘

         ┌───────────────────────────────────────────┐
         │         Observability Pipeline             │
         │   Loki :3100 ◄── Promtail (all 12 svcs)  │
         │   Grafana IAM Dashboard (13 panels)       │
         └───────────────────────────────────────────┘

         ┌───────────────────────────────────────────┐
         │           SIEM Integration                 │
         │   KC Events ──► Forwarder ──► Receiver    │
         │                 (30s poll)   (gunicorn)   │
         └───────────────────────────────────────────┘
```

**Network segmentation:** `iam-backend` is an internal-only Docker network — PostgreSQL and OpenLDAP have zero port exposure to the host. All external traffic enters through the Nginx TLS termination point.

---

## What This Demonstrates

| Domain | Implementation |
|---|---|
| **Enterprise SSO** | Keycloak IdP with OIDC (Grafana, Gitea) and SAML 2.0 (Nextcloud) — three service providers, two protocols |
| **Directory Services** | OpenLDAP federation with Keycloak via `group-ldap-mapper`; OU hierarchy mirrors org chart |
| **MFA & Step-Up Auth** | TOTP enforced via Required Actions; ACR levels `silver`/`gold`; Grafana requires LoA 2 re-challenge |
| **Passwordless FIDO2** | WebAuthn browser flow; passkey enrollment via `webauthn-register-passwordless`; ES256/RS256 |
| **RBAC + ABAC** | 5 realm roles federated from LDAP groups; Grafana role mapping via JMESPath on token claims |
| **IGA Automation** | Joiner/Mover/Leaver + Access Certification + JIT Privileged Access against Keycloak Admin API |
| **Infrastructure-as-Code** | Terraform (`mrparkers/keycloak` provider) manages realm, clients, roles, LDAP declaratively |
| **Security Hardening** | TLS 1.3 only, HSTS preload, CSP, PKCE S256, brute force protection, password policy, OCSP stapling |
| **Observability** | Loki + Promtail log aggregation across all services; Grafana IAM ops dashboard (13 panels) |
| **SIEM Integration** | Keycloak event store → polling forwarder → gunicorn WSGI receiver; normalised JSON audit trail |
| **CI/CD** | GitHub Actions: config validation, Trivy CVE scan, stack smoke test, integration tests |
| **Incident Response** | 5 ITIL-aligned playbooks (P1-P3) covering credential stuffing, MFA degradation, SSO outage |

---

## Quick Start

### Prerequisites

- Docker Desktop (WSL2 backend recommended)
- `make` (available via Git Bash or WSL)
- Add to `C:\Windows\System32\drivers\etc\hosts`:

```
127.0.0.1  keycloak.iam-lab.local
127.0.0.1  grafana.iam-lab.local
127.0.0.1  nextcloud.iam-lab.local
127.0.0.1  gitea.iam-lab.local
```

### Boot the Stack

```bash
make setup          # Generate TLS certs + create .env from template
# Edit .env with your secrets (admin passwords, DB creds)
make up             # Start all 12 containers
make health         # Verify: expect 7 passed, 0 failed
```

Everything auto-bootstraps on first start — the Keycloak realm imports with all clients, roles, and LDAP federation preconfigured. OpenLDAP loads 4 user personas, 5 groups, and 2 service accounts from LDIF. Grafana provisions the IAM operations dashboard and Loki datasource. The SIEM forwarder begins polling Keycloak events immediately.

### Service URLs

| Service | URL | Authentication |
|---|---|---|
| Keycloak Admin | `https://keycloak.iam-lab.local:8443` | `admin` / see `.env` |
| Grafana | `https://grafana.iam-lab.local:3443` | SSO via Keycloak (OIDC) |
| Nextcloud | `https://nextcloud.iam-lab.local:8444` | SSO via Keycloak (SAML) |
| Gitea | `https://gitea.iam-lab.local:3444` | SSO via Keycloak (OIDC) |

### Makefile Operations

```bash
make help           # Show all 18 available targets
make up             # Start the full stack
make down           # Stop stack (preserves data volumes)
make clean          # Full teardown including volumes
make health         # 7-assertion production readiness check
make logs           # Tail all container logs
make backup         # Backup PostgreSQL + LDAP data
make restore        # Restore from backup with validation
make test           # Run 20+ integration tests against live stack
make lint           # Flake8 lint all Python scripts
make validate       # Validate all config files (compose, nginx, realm JSON)
make certify        # Run access certification report
make tf-plan        # Plan Terraform changes
make tf-apply       # Apply Terraform changes
```

---

## Implementation Walkthrough

This section walks through exactly how each component was designed, configured, and integrated. Every decision here maps to a real-world enterprise IAM deployment pattern.

### Step 1: Network Architecture & TLS Termination

The foundation is a segmented Docker network with TLS 1.3 termination at the edge.

**Network design:**

```yaml
# docker-compose.yml
networks:
  iam-frontend:
    driver: bridge
  iam-backend:
    driver: bridge
    internal: true    # No host access — DB and LDAP are isolated
```

PostgreSQL and OpenLDAP only attach to `iam-backend`. They have no port bindings to the host and cannot be reached from outside the Docker network. This mirrors how a production environment isolates directory services and databases behind a firewall.

**TLS configuration (Nginx):**

```nginx
# nginx/nginx.conf — TLS 1.3 only, no fallback to 1.2
ssl_protocols TLSv1.3;
ssl_prefer_server_ciphers off;       # TLS 1.3 cipher negotiation is client-driven
ssl_stapling on;                     # OCSP stapling for cert validation
ssl_stapling_verify on;
```

Every service gets its own SNI-based `server` block with the full security header stack:

| Header | Value | Purpose |
|---|---|---|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | HSTS preload list eligible |
| `Content-Security-Policy` | `default-src 'self'; frame-ancestors 'self'` | XSS and clickjacking prevention |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Disable unnecessary browser APIs |
| `X-Content-Type-Options` | `nosniff` | MIME type sniffing prevention |
| `Cross-Origin-Opener-Policy` | `same-origin` | Cross-origin isolation |

**Rate limiting** protects the login endpoint and API separately:

```nginx
limit_req_zone $binary_remote_addr zone=login:10m rate=10r/s;    # Login: 10 req/s
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;      # API: 30 req/s
```

---

### Step 2: Directory Services (OpenLDAP)

The LDAP directory provides the authoritative source of identity data. Keycloak federates from it rather than managing users directly — this is how enterprise IAM works in practice.

**Directory structure:**

```
dc=rbclab,dc=local
├── ou=users
│   ├── uid=jsmith     (John Smith — Trading)
│   ├── uid=alee       (Alice Lee — Risk)
│   ├── uid=mchen      (Michael Chen — Compliance)
│   └── uid=bpatel     (Bina Patel — IT Support)
├── ou=groups
│   ├── cn=traders
│   ├── cn=risk-analysts
│   ├── cn=compliance-admins
│   ├── cn=helpdesk
│   └── cn=iam-admins
└── ou=service-accounts
    ├── cn=readonly     (Keycloak bind account — read-only)
    └── cn=siem-svc     (SIEM forwarder service account)
```

Each user is a full `inetOrgPerson` with department, title, email, and group memberships via `memberOf`. The read-only service account is what Keycloak uses to bind to LDAP — it cannot modify directory data, enforcing least-privilege.

**LDIF auto-loading:**

```yaml
# docker-compose.yml
openldap:
  image: osixia/openldap:1.5.0
  command: --copy-service                    # Required for 1.5.0 template bug
  volumes:
    - ./ldap/init-ldap.ldif:/container/service/slapd/assets/config/bootstrap/ldif/custom/init.ldif
  environment:
    LDAP_ORGANISATION: "RBC Lab"
    LDAP_DOMAIN: "rbclab.local"
    LDAP_TLS: "false"                        # TLS handled at Nginx layer
```

The `--copy-service` flag works around a known osixia/openldap 1.5.0 startup bug where template files (`replication-disable.ldif`, `root-password-change.ldif`) are missing from the expected paths. TLS is disabled on the LDAP container because it sits on the internal network behind the Nginx TLS termination point — encrypting internal-only traffic adds latency without security benefit.

---

### Step 3: Identity Provider (Keycloak 26.2)

Keycloak runs in production mode with the realm auto-imported on first boot.

**Production configuration:**

```yaml
# docker-compose.yml
keycloak:
  image: quay.io/keycloak/keycloak:26.2
  command: >
    start
    --hostname=keycloak.iam-lab.local
    --hostname-port=8443
    --hostname-strict=false
    --proxy-headers=xforwarded
    --http-enabled=true
    --import-realm
    --health-enabled=true
```

Key points:
- `--proxy-headers=xforwarded` tells Keycloak it sits behind a reverse proxy (Nginx handles TLS)
- `--import-realm` auto-imports `enterprise-realm-export.json` on first boot
- `--health-enabled=true` exposes the health endpoint on the management port (9000) — this is separate from the application port (8080) in KC 26.2
- The healthcheck targets port 9000, not 8080, because KC 26.2 moved health endpoints to a dedicated management interface

**Realm settings (`enterprise`):**

| Setting | Value | Why |
|---|---|---|
| Brute force protection | 5 failures → lockout, 60s increments, 900s max | Prevents credential stuffing |
| Password policy | 12+ chars, upper + lower + digit + special, history 5 | Meets NIST 800-63B guidance |
| PKCE enforcement | S256 on all OIDC clients | OAuth 2.1 best practice |
| Token lifetimes | Access: 5m, SSO idle: 30m, SSO max: 10h | Minimize token exposure window |
| Events | Auth + admin events, 30-day retention | Audit trail for SIEM |
| WebAuthn | ES256/RS256, rpId `keycloak.iam-lab.local` | FIDO2 passkey support |

---

### Step 4: SSO Federation (OIDC + SAML)

Three service providers demonstrate both major SSO protocols:

**Grafana — OIDC with PKCE S256:**

```yaml
# Keycloak client config
Client ID:     grafana
Protocol:      OpenID Connect (confidential)
PKCE:          S256 enforced
Redirect URI:  https://grafana.iam-lab.local:3443/*
```

Grafana authenticates users via Keycloak's OIDC Authorization Code flow. The `roles` claim in the ID token maps to Grafana org roles via JMESPath — a trader gets Viewer, a compliance-admin gets Editor, and an iam-admin gets Admin.

**Gitea — OIDC with PKCE S256:**

```yaml
Client ID:     gitea
Protocol:      OpenID Connect (confidential)
PKCE:          S256 enforced
Redirect URI:  https://gitea.iam-lab.local:3444/user/oauth2/keycloak/callback
```

**Nextcloud — SAML 2.0:**

```yaml
Client ID:     https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/metadata
Protocol:      SAML 2.0
ACS URL:       https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/acs
```

Nextcloud uses SAML because it demonstrates protocol versatility — a real enterprise IdP needs to support both OIDC and SAML since legacy applications often only support SAML.

**SSO login flow:**

```
User visits Grafana → Redirect to Keycloak login → Authenticate (password + TOTP)
→ Authorization code issued → Grafana exchanges code for tokens (with PKCE S256)
→ ID token contains roles[] claim → Grafana maps role to org permissions → Session established
```

---

### Step 5: RBAC — LDAP-to-Token Role Chain

This is the core of the RBAC implementation. Roles flow from LDAP through Keycloak into application tokens:

```
LDAP Group (ou=groups) ──► Keycloak Group ──► Realm Role ──► Token Claim (roles[])
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cn=traders             ──► traders         ──► trader       ──► "trader"
cn=risk-analysts       ──► risk-analysts   ──► risk-analyst ──► "risk-analyst"
cn=compliance-admins   ──► compliance-admins──► compliance-admin ──► "compliance-admin"
cn=helpdesk            ──► helpdesk        ──► helpdesk     ──► "helpdesk"
cn=iam-admins          ──► iam-admins      ──► iam-admin    ──► "iam-admin"
```

**How this works in Keycloak:**

1. **LDAP User Federation** connects Keycloak to OpenLDAP as a read-only source (`ldap://openldap:389`)
2. **`group-ldap-mapper`** syncs LDAP groups to Keycloak groups automatically on user login
3. **Group-to-role mappings** assign realm roles based on group membership
4. **Protocol mapper** injects the `roles` claim into OIDC tokens and SAML assertions
5. **Service providers** (Grafana, Gitea) read the `roles` claim to determine authorization

This means that when a user is added to `cn=traders` in LDAP, they automatically get the `trader` realm role and the correct permissions in Grafana and Gitea — no manual Keycloak configuration needed. When they leave the group in LDAP, access is revoked at next sync.

**User personas and their role assignments:**

| User | Department | LDAP Group | Realm Role | Grafana Access |
|---|---|---|---|---|
| `jsmith` | Trading | `cn=traders` | `trader` | Viewer |
| `alee` | Risk | `cn=risk-analysts` | `risk-analyst` | Viewer |
| `mchen` | Compliance | `cn=compliance-admins` | `compliance-admin` | Editor |
| `bpatel` | IT Support | `cn=helpdesk` | `helpdesk` | Viewer |

---

### Step 6: Security Hardening

Every layer of the stack has security controls applied:

**Authentication controls:**

| Control | Configuration | Rationale |
|---|---|---|
| Brute force protection | 5 failures → progressive lockout (60s → 900s max) | Prevents credential stuffing attacks |
| Password policy | 12+ chars, complexity rules, history of 5 | Aligns with NIST SP 800-63B |
| PKCE S256 | Enforced on all OIDC clients | Defense against authorization code interception (OAuth 2.1) |
| MFA enrollment | CONFIGURE_TOTP as Required Action | Forces TOTP setup on first login |
| WebAuthn | ES256/RS256 attestation, origin-bound | Phishing-resistant authentication |
| Session management | Access token: 5m, SSO idle: 30m, SSO max: 10h | Limits exposure window |

**Transport controls:**

| Control | Configuration |
|---|---|
| TLS 1.3 only | `ssl_protocols TLSv1.3` — no TLS 1.2 fallback |
| HSTS preload | `max-age=63072000; includeSubDomains; preload` |
| OCSP stapling | Enabled for real-time certificate validation |
| Server tokens off | `server_tokens off` — no Nginx version disclosure |

**Network controls:**

| Control | Configuration |
|---|---|
| Internal network | `iam-backend: internal: true` — DB and LDAP unreachable from host |
| Rate limiting | Login: 10r/s burst=20, API: 30r/s burst=50 |
| Resource limits | Memory and CPU caps on all containers via `deploy.resources.limits` |
| Secret hygiene | `.env`, `*.key`, `*.tfvars` excluded from git |

---

### Step 7: Observability & SIEM

**Log aggregation pipeline:**

```
All 12 containers ──► Promtail (Docker SD) ──► Loki ──► Grafana Dashboard
```

Promtail uses Docker socket service discovery to scrape every container, not just Keycloak. This is intentional — security events can originate from any service. The Grafana IAM Operations dashboard is auto-provisioned from code (no manual setup) with 13 panels:

| Panel | Type | What It Shows |
|---|---|---|
| Login Success/Failure/MFA | Stat | Current counts with color thresholds |
| Auth Events Over Time | Timeseries | 30-second refresh, breakdown by event type |
| Login Failure Rate | Gauge | Brute-force detection indicator |
| Live Event Stream | Table | Real-time Keycloak event log |
| SIEM Severity Breakdown | Pie chart | HIGH/MEDIUM/LOW/INFO distribution |

**SIEM integration (pull model):**

```
Keycloak Event Store ──► siem-forwarder (30s poll) ──► siem-receiver (gunicorn WSGI)
```

The SIEM forwarder polls Keycloak's Admin REST API every 30 seconds for new authentication and admin events. It maintains state in `/state/.siem_state.json` to avoid re-processing events across restarts. The receiver normalizes events into a structured JSON audit trail:

| Event Type | Severity | Alertable |
|---|---|---|
| `LOGIN_ERROR` | HIGH | Yes |
| `REMOVE_TOTP` | HIGH | Yes |
| `ADMIN_DELETE_*` | HIGH | Yes |
| `UPDATE_PASSWORD` | MEDIUM | No |
| `LOGIN` | INFO | No |
| `LOGOUT` | LOW | No |

The pull model was chosen over webhook push because Keycloak's event listener SPI requires a custom JAR deployment, while the REST API approach works with the stock Keycloak image and survives forwarder restarts without event loss.

---

### Step 8: IGA Lifecycle Automation

Two CLI tools automate identity governance against the Keycloak Admin API:

**Joiner / Mover / Leaver (`iam_lifecycle.py`):**

```bash
# Onboard a new trader
python3 scripts/iam_lifecycle.py joiner \
  --username tchen --email tchen@rbclab.local --role trader

# Transfer to risk team
python3 scripts/iam_lifecycle.py mover \
  --username tchen --old-role trader --new-role risk-analyst

# Offboard (disable + revoke all sessions + remove roles)
python3 scripts/iam_lifecycle.py leaver --username tchen

# Quarterly access certification — flag users with roles unchanged > 90 days
python3 scripts/iam_lifecycle.py certify --days 90
```

The leaver action doesn't just disable the account — it revokes all active sessions, removes all role assignments, and logs the action for audit. The certify command generates a report of stale role assignments for access review.

**Just-In-Time Privileged Access (`jit_access.py`):**

```bash
# Grant temporary iam-admin role (2 hours, with incident ticket)
python3 scripts/jit_access.py elevate \
  --username bpatel --role iam-admin --duration 120 --reason "P1 INC0001234"

# List active JIT grants
python3 scripts/jit_access.py list

# Auto-revoke expired grants (designed for cron: */5 * * * *)
python3 scripts/jit_access.py expire

# Manual revocation
python3 scripts/jit_access.py revoke --username bpatel --role iam-admin
```

JIT access implements the principle of least privilege for break-glass scenarios. A helpdesk user can be temporarily elevated to `iam-admin` with a mandatory incident ticket reference, automatic expiry, and full audit logging.

---

### Step 9: Infrastructure-as-Code (Terraform)

The `terraform/` directory manages the Keycloak realm declaratively using the [`mrparkers/keycloak`](https://registry.terraform.io/providers/mrparkers/keycloak/latest) provider:

```bash
cd terraform
cp secrets.tfvars.example secrets.tfvars   # Fill in KC admin credentials
terraform init
terraform plan -var-file="secrets.tfvars"
terraform apply -var-file="secrets.tfvars"
```

**What Terraform manages:**

| Resource | Count | Details |
|---|---|---|
| `keycloak_realm` | 1 | Enterprise realm with all security settings |
| `keycloak_role` | 5 | trader, risk-analyst, compliance-admin, helpdesk, iam-admin |
| `keycloak_group` | 5 | With role mappings attached |
| `keycloak_ldap_user_federation` | 1 | Full LDAP config with all mappers |
| `keycloak_openid_client` | 2 | Grafana and Gitea (OIDC + PKCE) |
| `keycloak_saml_client` | 1 | Nextcloud (SAML 2.0) |

**Why both Terraform and the JSON realm export?** The JSON export bootstraps the realm on first `docker compose up` — it's the "day 0" configuration. Terraform manages ongoing changes declaratively, enabling GitOps workflows for IdP management. This dual approach is exactly how production IAM teams handle Keycloak at scale: realm export for initial provisioning, Terraform for change management.

---

### Step 10: CI/CD & Testing

**GitHub Actions pipeline (4 jobs):**

| Job | What It Validates |
|---|---|
| **validate** | Docker Compose syntax, Nginx config, Grafana dashboard JSON, realm export schema, Promtail YAML, secrets leak check |
| **python-lint** | Flake8 + syntax check on all Python files, Bash syntax check on all shell scripts |
| **trivy-scan** | CVE scan across 8 container images with SARIF upload to GitHub Security tab |
| **stack-smoke** | Full stack boot, OIDC discovery endpoint verification, admin token acquisition, realm auto-import check |

**Integration tests (20+ assertions against live stack):**

```bash
export KC_ADMIN_PASS=<your-admin-password>
make test
```

Tests validate the entire identity chain end-to-end:

| Test | What It Proves |
|---|---|
| OIDC discovery | Keycloak publishes valid `.well-known/openid-configuration` |
| Admin token | Service account authentication works |
| Realm config | Enterprise realm exists with correct display name and settings |
| Brute force | `bruteForceProtected: true`, `maxLoginFailures: 5` |
| Password policy | 12-char minimum with complexity requirements |
| Realm roles | All 5 custom roles present (trader, risk-analyst, etc.) |
| OIDC clients | Grafana and Gitea clients exist with PKCE S256 enforced |
| LDAP sync | All 4 user personas synced from LDAP (jsmith, alee, mchen, bpatel) |
| Group mapping | LDAP groups mapped to Keycloak groups correctly |
| Role chain | Groups have correct realm role assignments |
| SIEM health | Receiver endpoint responds, events are being ingested |
| SP health | Grafana, Gitea, and Nextcloud are reachable |

---

## Incident Playbooks

Five ITIL-aligned incident response procedures covering the most common IAM failure scenarios:

| Playbook | Priority | Scenario | Key Actions |
|---|---|---|---|
| [P1: Mass Login Failures](docs/incident-playbooks/P1-mass-login-failures.md) | P1 — Critical | Credential stuffing / account lockout wave | Block source IPs, check brute force logs, mass unlock |
| [P1: Unauthorized Admin Action](docs/incident-playbooks/P1-unauthorized-admin-action.md) | P1 — Critical | Privilege escalation detected | Revoke sessions, audit admin events, check JIT grants |
| [P2: MFA Degradation](docs/incident-playbooks/P2-mfa-degradation.md) | P2 — High | TOTP failure spike / authenticator app outage | Check OTP clock sync, temporary bypass with approval |
| [P2: SSO Outage](docs/incident-playbooks/P2-sso-outage.md) | P2 — High | Keycloak IdP unreachable | Healthcheck, DB connectivity, failover procedure |
| [P3: Lockout Wave](docs/incident-playbooks/P3-lockout-wave.md) | P3 — Medium | Targeted lockout on subset of users | Identify pattern, selective unlock, adjust thresholds |

Each playbook includes detection criteria, escalation paths, remediation steps, and post-incident review checklists.

---

## Key Design Decisions

**Why Keycloak + OpenLDAP instead of a managed IdP?**
Demonstrates hands-on understanding of OIDC, SAML, and LDAP protocols rather than SaaS console configuration. Enterprise environments commonly run hybrid identity stacks where the IdP federates from an existing directory. This mirrors the architecture at Tier 1 financial institutions.

**Why Terraform alongside the JSON realm export?**
The JSON export bootstraps the realm on first `docker compose up`. Terraform manages ongoing configuration changes declaratively, enabling GitOps workflows for IdP management — a pattern used in production at scale. This dual approach is intentional and reflects real-world IAM operations.

**Why PKCE S256 on confidential clients?**
Best practice per the OAuth 2.1 draft specification. Even confidential clients benefit from PKCE as defense-in-depth against authorization code interception. This is now a requirement, not optional.

**Why a pull-model SIEM instead of webhooks?**
Keycloak's event listener SPI requires building and deploying a custom JAR. The REST API polling approach works with the stock Keycloak image, survives forwarder restarts without event loss (stateful checkpointing), and is operationally simpler to maintain.

**Why Required Actions for MFA instead of a custom authentication flow?**
Keycloak 26 changed how `ConditionalUserConfiguredAuthenticator` evaluates in copied browser flows — it runs before user identity is established, breaking conditional OTP in custom flows. Required Actions are the correct KC 26 pattern for mandatory MFA enrollment and work reliably across version upgrades.

**Why Promtail scrapes all containers, not just Keycloak?**
Security events can originate from any service in the stack. Limiting log collection to Keycloak, LDAP, and Nginx meant that Grafana auth failures, Gitea login events, and SIEM receiver alerts were dropped from the observability pipeline. Comprehensive scraping is a security baseline.

**Why gunicorn for the SIEM receiver instead of Flask's dev server?**
Flask's built-in server is single-threaded and not suitable for production workloads. Gunicorn provides proper worker management, graceful restarts, and concurrent request handling — even in a lab environment, running production-grade infrastructure demonstrates the right operational mindset.

---

## Projects

Detailed technical documentation for each implementation area:

| # | Project | Technologies | Documentation |
|---|---|---|---|
| P1 | SSO Federation | OIDC, SAML 2.0, LDAP, group-ldap-mapper | [P1-SSO-Federation.md](docs/projects/P1-SSO-Federation.md) |
| P2 | MFA & Step-Up Authentication | TOTP Required Actions, ACR/LoA levels, gold/silver tiers | [P2-MFA-StepUp.md](docs/projects/P2-MFA-StepUp.md) |
| P3 | Passwordless FIDO2 | WebAuthn, passkeys, custom browser flow, origin-binding | [P3-Passwordless-FIDO2.md](docs/projects/P3-Passwordless-FIDO2.md) |
| P4 | RBAC, ABAC & Lifecycle | Realm roles, JMESPath ABAC, Joiner/Mover/Leaver, JIT PAM | [P4-RBAC-Lifecycle.md](docs/projects/P4-RBAC-Lifecycle.md) |
| P5 | Monitoring & Incident Response | Loki, Grafana, SIEM, access certification, playbooks | [P5-Monitoring-Incident-Audit.md](docs/projects/P5-Monitoring-Incident-Audit.md) |

---

## Repository Structure

```
iam-lab/
├── docker-compose.yml                  # 12-container production stack (auto-bootstrap)
├── docker-compose.override.yml.example # Dev mode overrides (debug logging, hot reload)
├── .env.example                        # Documented environment variable template
├── Makefile                            # 18 ops targets: setup, up, down, health, test, tf-*
├── .github/workflows/ci.yml           # CI: validate + lint + Trivy CVE scan + smoke test
│
├── nginx/
│   └── nginx.conf                      # TLS 1.3, HSTS, CSP, rate-limiting, OCSP stapling
├── certs/                              # Generated TLS certs (keys gitignored)
│
├── keycloak/
│   └── enterprise-realm-export.json    # Full realm config (auto-imported on first boot)
│
├── ldap/
│   ├── init-ldap.ldif                  # 4 users + 5 groups + 2 service accounts
│   └── bootstrap.sh                    # LDAP password hashing helper
│
├── grafana/
│   ├── provisioning/                   # Loki datasource + dashboard provider configs
│   └── dashboards/iam-operations.json  # 13-panel IAM operations dashboard
│
├── monitoring/
│   └── promtail-config.yml             # Docker SD scraping all containers
│
├── siem-receiver/
│   ├── app.py                          # Flask SIEM event normalizer
│   └── Dockerfile                      # gunicorn WSGI production build
│
├── siem-forwarder/
│   ├── siem_forwarder.py               # Keycloak event store poller
│   └── Dockerfile                      # Multi-stage production build
│
├── scripts/
│   ├── iam_lifecycle.py                # Joiner/Mover/Leaver/Certify CLI
│   ├── jit_access.py                   # JIT privileged access management
│   ├── healthcheck.sh                  # 7-assertion production readiness check
│   ├── backup.sh                       # PostgreSQL + LDAP backup with verification
│   └── restore.sh                      # Restore with validation
│
├── terraform/
│   ├── main.tf                         # Realm, roles, clients, LDAP (mrparkers/keycloak)
│   ├── variables.tf                    # Parameterized configuration
│   ├── outputs.tf                      # Terraform outputs
│   └── providers.tf                    # Provider + version constraints
│
├── tests/
│   ├── test_integration.py             # 20+ assertions against live stack
│   ├── conftest.py                     # Pytest fixtures (KC token, OIDC discovery)
│   └── requirements.txt               # Test dependencies
│
└── docs/
    ├── projects/P1-P5*.md              # Detailed project specifications
    ├── incident-playbooks/             # 5 ITIL-aligned response procedures
    ├── runbooks/                       # Keycloak realm setup procedures
    └── security/trivy-scan-report.md   # CVE scan results and remediation plan
```
