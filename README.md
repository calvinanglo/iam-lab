# IAM Lab — Production-Grade Identity & Access Management

> **Stack:** Keycloak 26 · OpenLDAP · PostgreSQL 16 · Nginx TLS 1.3 · Grafana · Loki · Nextcloud · Gitea · Docker Compose

---

## What This Demonstrates

| Competency | Evidence |
|---|---|
| **Enterprise SSO** | Keycloak IdP with OIDC (Grafana, Gitea) and SAML 2.0 (Nextcloud) |
| **Directory Services** | OpenLDAP federation with Keycloak; OU hierarchy; 4 personas + 2 service accounts |
| **MFA Enforcement** | TOTP required action enforced on all users via Keycloak Required Actions |
| **RBAC** | 5 realm roles (trader, risk-analyst, compliance-admin, helpdesk, iam-admin) mapped to app roles |
| **IGA Automation** | Python Joiner/Mover/Leaver lifecycle CLI against Keycloak Admin API with structured audit log |
| **Secrets Management** | TLS 1.3 only, HSTS preload, CSP headers; all secrets in `.env` outside git |
| **Network Segmentation** | `iam-backend` internal network isolates DB/LDAP; `iam-frontend` for SP traffic |
| **Observability** | Loki + Promtail log aggregation; Grafana dashboards; structured JSON event logging |
| **Incident Response** | 5 ITIL-aligned playbooks (P1–P3) covering mass login failures, MFA degradation, SSO outage |
| **Production Ops** | healthcheck.sh (7 assertions), backup/restore scripts, resource headroom alerting |

---

## Architecture

```
                          ┌─────────────────────────────────────────────────┐
                          │              BROWSER / CLIENT                    │
                          └──────────────────┬──────────────────────────────┘
                                             │ HTTPS (TLS 1.3 only)
                          ┌──────────────────▼──────────────────────────────┐
                          │           Nginx Reverse Proxy                    │
                          │  HSTS · CSP · Rate-limiting · Cert termination  │
                          └──┬───────┬──────────┬──────────┬────────────────┘
                             │       │          │          │
               ┌─────────────▼─┐ ┌───▼───┐ ┌───▼────┐ ┌──▼──────┐
               │  Keycloak 26  │ │Grafana│ │Nextcloud│ │  Gitea  │
               │  :8443 (IdP)  │ │ :3443 │ │  :8444 │ │  :3444  │
               │  OIDC · SAML  │ │ OIDC  │ │ SAML   │ │  OIDC   │
               └──────┬────────┘ └───────┘ └────────┘ └─────────┘
                      │
          ┌───────────┴──────────────────────────┐
          │         iam-backend (internal)        │
          │  ┌─────────────┐  ┌────────────────┐ │
          │  │ PostgreSQL  │  │   OpenLDAP     │ │
          │  │  :5432      │  │   :389         │ │
          │  │ (KC store)  │  │ (user dir)     │ │
          │  └─────────────┘  └────────────────┘ │
          └──────────────────────────────────────┘

          ┌──────────────────────────────────────┐
          │         Observability Stack           │
          │  Loki :3100  ←  Promtail (all svc)   │
          │  Grafana Loki datasource              │
          └──────────────────────────────────────┘
```

---

## Identity Configuration

### Realm: `enterprise`

| Setting | Value |
|---|---|
| Realm | `enterprise` |
| Browser flow | `browser` (built-in, Conditional OTP) |
| MFA enforcement | CONFIGURE_TOTP required action on all users |
| Admin account | `iam-superadmin` (permanent, bootstrap admin deleted) |

### LDAP Federation

| Setting | Value |
|---|---|
| Connection | `ldap://openldap:389` |
| Bind DN | `cn=readonly,dc=rbclab,dc=local` |
| Edit mode | `READ_ONLY` |
| Users DN | `ou=users,dc=rbclab,dc=local` |
| Username attr | `uid` |
| Sync result | 4 users synced |

### User Personas

| Username | Name | Role | Department |
|---|---|---|---|
| `jsmith` | John Smith | `trader` | Trading |
| `alee` | Alice Lee | `risk-analyst` | Risk |
| `mchen` | Michael Chen | `compliance-admin` | Compliance |
| `bpatel` | Bina Patel | `helpdesk` | IT Support |

### Realm Roles → App Roles

| Realm Role | Grafana Org Role | Description |
|---|---|---|
| `iam-admin` | Admin | Full IAM access |
| `compliance-admin` | Editor | Compliance tools + audit logs |
| `trader` | Viewer | Trading systems + market data |
| `risk-analyst` | Viewer | Risk reporting + analytics |
| `helpdesk` | Viewer | User support operations |

### SSO Clients

| Client | Protocol | Redirect URI | Mappers |
|---|---|---|---|
| `grafana` | OIDC (confidential) | `https://grafana.iam-lab.local:3443/*` | realm-roles, email |
| `gitea` | OIDC (confidential) | `https://gitea.iam-lab.local:3444/user/oauth2/keycloak/callback` | realm-roles, email |
| Nextcloud | SAML 2.0 | `https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/acs` | uid, email, displayName |

---

## Running the Stack

### Prerequisites

- Docker Desktop (WSL2 backend)
- Add to `C:\Windows\System32\drivers\etc\hosts`:

```
127.0.0.1  keycloak.iam-lab.local
127.0.0.1  grafana.iam-lab.local
127.0.0.1  nextcloud.iam-lab.local
127.0.0.1  gitea.iam-lab.local
```

### Start

```bash
cp .env.example .env          # fill in secrets (or use the provided .env)
docker compose up -d
bash scripts/healthcheck.sh   # expect: 7 passed, 0 failed
```

### Service URLs

| Service | URL | Credentials |
|---|---|---|
| Keycloak Admin | https://keycloak.iam-lab.local:8443 | `iam-superadmin` / see `.env` |
| Grafana | https://grafana.iam-lab.local:3443 | SSO via Keycloak |
| Nextcloud | https://nextcloud.iam-lab.local:8444 | SSO via Keycloak |
| Gitea | https://gitea.iam-lab.local:3444 | SSO via Keycloak |

---

## IGA Lifecycle Automation

Python CLI that drives the Keycloak Admin API for joiner/mover/leaver workflows:

```bash
# Onboard a new joiner
python3 scripts/iam_lifecycle.py joiner \
  --username tchen --email tchen@rbclab.local \
  --first-name Tony --last-name Chen --role trader

# Move user to a new role
python3 scripts/iam_lifecycle.py mover \
  --username tchen --new-role risk-analyst

# Offboard a leaver (disables account, removes roles)
python3 scripts/iam_lifecycle.py leaver --username tchen

# Compliance report
python3 scripts/iam_lifecycle.py report
```

All actions are written to `iam_audit.log`:

```
2026-04-06 02:14:28 [INFO] JOINER: created user 'tchen' (id=d6ce3539) with role 'trader'
2026-04-06 02:14:28 [INFO] JOINER user=tchen role=trader email=tchen@rbclab.local actor=iam-superadmin
```

---

## Security Controls

| Control | Implementation |
|---|---|
| TLS 1.3 only | Nginx `ssl_protocols TLSv1.2 TLSv1.3` |
| HSTS preload | `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` |
| Content-Security-Policy | Nginx header on all responses |
| Rate limiting | Login: 10r/s burst=20 · API: 30r/s burst=50 |
| Network isolation | `iam-backend: internal: true` (DB/LDAP not routable externally) |
| Secret hygiene | `.env`, `ca.key`, `server.key` excluded from git |
| Least-privilege LDAP | Read-only bind account for Keycloak federation |
| Admin account hygiene | Bootstrap admin deleted; permanent `iam-superadmin` with audit trail |
| MFA | TOTP enforced via Required Action on all users |
| Backup | `scripts/backup.sh` → encrypted tar with timestamp; `restore.sh` for DR |

---

## Observability

- **Loki** collects structured logs from all containers via Promtail
- **Grafana** has Loki as a datasource — query `{container="iam-keycloak-1"}` for auth events
- Keycloak emits `LOGIN`, `LOGIN_ERROR`, `LOGOUT` events queryable in Admin → Events

---

## Incident Playbooks

ITIL-aligned response procedures in `docs/incident-playbooks/`:

| Playbook | Priority | Scenario |
|---|---|---|
| `P1-mass-login-failures.md` | P1 | Credential stuffing / account lockout wave |
| `P1-unauthorized-admin-action.md` | P1 | Privilege escalation detected |
| `P2-mfa-degradation.md` | P2 | TOTP failures spike / authenticator app outage |
| `P2-sso-outage.md` | P2 | Keycloak IdP unreachable |
| `P3-lockout-wave.md` | P3 | Targeted lockout on subset of users |

---

## Repository Structure

```
iam-lab/
├── docker-compose.yml          # 10-container production stack
├── .env                        # Secrets (not committed)
├── nginx/nginx.conf            # TLS termination, rate-limiting, security headers
├── certs/                      # TLS certs (ca.crt, server.crt committed; keys excluded)
├── ldap/init-ldap.ldif         # OU structure + 4 user personas + 2 service accounts
├── scripts/
│   ├── iam_lifecycle.py        # Joiner/Mover/Leaver CLI (Keycloak Admin API)
│   ├── healthcheck.sh          # 7-assertion production readiness check
│   ├── backup.sh               # Volume backup with retention
│   └── restore.sh              # Point-in-time restore
└── docs/
    ├── runbooks/               # Keycloak realm setup, LDAP federation procedures
    └── incident-playbooks/     # P1–P3 ITIL response procedures
```

---

## Key Design Decisions

**Why Keycloak + OpenLDAP instead of a managed IdP?**
Demonstrates hands-on understanding of the underlying protocols (OIDC, SAML, LDAP) rather than just clicking through a SaaS console. Enterprise environments commonly run hybrid on-premise/cloud identity stacks that require this depth.

**Why SAML for Nextcloud and OIDC for Grafana/Gitea?**
Real enterprise environments have both legacy SAML SPs and modern OIDC clients. This lab covers both code paths including assertion signing (RSA_SHA256), redirect binding, and token mappers.

**Why Required Actions for MFA instead of a custom flow?**
Keycloak 26 introduced a regression where `ConditionalUserConfiguredAuthenticator` evaluates before user identity is established in copied flows, causing NPE. Required Actions are the correct KC26 pattern for mandatory MFA enrollment — enforced on first login, not at flow evaluation time.

**Why Python for IGA automation instead of shell scripts?**
The Keycloak Admin REST API requires structured JSON, retry logic, and audit logging. Python with `requests` provides a maintainable, testable foundation that mirrors real IGA tool integrations (SailPoint, Saviynt).
