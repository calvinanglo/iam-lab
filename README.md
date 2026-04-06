# IAM Lab — Production-Grade Identity & Access Management

> **Stack:** Keycloak 26 · OpenLDAP · PostgreSQL 16 · Nginx TLS 1.3 · Grafana · Loki · Nextcloud · Gitea · SIEM Receiver · Docker Compose (12 containers)

---

## What This Demonstrates

| Competency | Evidence |
|---|---|
| **Enterprise SSO** | Keycloak IdP with OIDC (Grafana, Gitea) and SAML 2.0 (Nextcloud) |
| **Directory Services** | OpenLDAP federation with Keycloak; OU hierarchy; group-ldap-mapper syncs 5 groups → realm roles |
| **MFA Enforcement** | TOTP (Required Action) + WebAuthn/FIDO2 as optional second factor; KC26 correct pattern |
| **RBAC** | 5 realm roles (trader, risk-analyst, compliance-admin, helpdesk, iam-admin) mapped to app roles |
| **LDAP Group Federation** | LDAP groups → Keycloak groups → realm roles → token claims; full chain verified end-to-end |
| **IGA Automation** | Joiner/Mover/Leaver + Access Certification + JIT Privileged Access CLI against Keycloak Admin API |
| **Secrets Management** | TLS 1.3 only, HSTS preload, CSP headers; all secrets in `.env` outside git |
| **Network Segmentation** | `iam-backend` internal network isolates DB/LDAP; `iam-frontend` for SP traffic |
| **Observability** | Loki + Promtail log aggregation; Grafana IAM ops dashboard (login rate, failure rate, MFA enrollment) |
| **SIEM Integration** | Keycloak event store → polling forwarder → structured SIEM receiver; normalised JSON audit trail |
| **Security Assessment** | Trivy CVE scan across all 12 images; P1/P2/P3 remediation roadmap in `docs/security/` |
| **CI/CD** | GitHub Actions: config validation, Trivy scan with SARIF upload, stack smoke test, IGA lint |
| **Incident Response** | 5 ITIL-aligned playbooks (P1–P3) covering mass login failures, MFA degradation, SSO outage |
| **Production Ops** | healthcheck.sh, backup/restore scripts; realm config exported as code (`keycloak/`) |

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
| MFA enforcement | CONFIGURE_TOTP required action on all users (enforced on first login) |
| WebAuthn/FIDO2 | `webauthn-register` action enabled; rpId `keycloak.iam-lab.local`; ES256/RS256 |
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

### LDAP Group Federation

Groups in `ou=groups,dc=rbclab,dc=local` are synced into Keycloak via `group-ldap-mapper` and mapped to realm roles:

| LDAP Group | Keycloak Group | Realm Role |
|---|---|---|
| `cn=traders` | `traders` | `trader` |
| `cn=risk-analysts` | `risk-analysts` | `risk-analyst` |
| `cn=compliance-admins` | `compliance-admins` | `compliance-admin` |
| `cn=helpdesk` | `helpdesk` | `helpdesk` |
| `cn=iam-admins` | `iam-admins` | `iam-admin` |

Role claim flows: LDAP membership → Keycloak group → group-to-role mapping → `roles` claim in OIDC token / `Role` attribute in SAML assertion.

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

Two Python CLIs drive the Keycloak Admin API:

### `iam_lifecycle.py` — Joiner / Mover / Leaver / Certify

```bash
# Onboard a new joiner
python3 scripts/iam_lifecycle.py joiner \
  --username tchen --email tchen@rbclab.local \
  --first-name Tony --last-name Chen --role trader

# Move user to a new role
python3 scripts/iam_lifecycle.py mover \
  --username tchen --old-role trader --new-role risk-analyst

# Offboard a leaver (disables account, terminates sessions)
python3 scripts/iam_lifecycle.py leaver --username tchen

# Access certification report (ISO 27001 / SOX access review)
python3 scripts/iam_lifecycle.py certify --days 90
```

Sample certification report output:

```
====================================================================================================
  ACCESS CERTIFICATION REPORT — Realm: enterprise
  Generated: 2026-04-06 03:12 UTC   Lookback window: 90 days   Certifier: iam-superadmin
====================================================================================================

USERNAME             EMAIL                            EN   ROLES                          LAST LOGIN   CREATED      FLAG
--------             -----                            --   -----                          ----------   -------      ----
tchen                tchen@rbclab.local               T    trader                         never        2026-04-05   INACTIVE  *** INACTIVE ***
jsmith               jsmith@rbclab.local              T    trader                         2026-04-05   2026-04-05   CLEAN
alee                 alee@rbclab.local                T    risk-analyst                   2026-04-05   2026-04-05   CLEAN
mchen                mchen@rbclab.local               T    compliance-admin               2026-04-05   2026-04-05   CLEAN
bpatel               bpatel@rbclab.local              T    helpdesk                       2026-04-05   2026-04-05   CLEAN

  INACTIVE : 1  (no login in >90d — review for removal)
  ORPHANED : 0
  DISABLED : 0
```

### `jit_access.py` — Just-In-Time Privileged Access

Time-limited role elevation with automatic revocation — zero-standing-privilege for iam-admin and compliance-admin roles:

```bash
# Elevate bpatel to iam-admin for 2 hours (P1 incident response)
python3 scripts/jit_access.py elevate \
  --username bpatel \
  --role iam-admin \
  --duration 120 \
  --reason "P1-incident: SSO outage - INC0001234"

# Check active JIT grants
python3 scripts/jit_access.py list

# Auto-revoke expired grants (run as cron: */5 * * * *)
python3 scripts/jit_access.py expire

# Emergency revoke before expiry
python3 scripts/jit_access.py revoke --username bpatel --role iam-admin
```

All actions written to `iam_audit.log`:

```
2026-04-06 03:14:22 AUDIT JIT_ELEVATE user=bpatel role=iam-admin duration_min=120 expires=2026-04-06T05:14:22 reason=P1-incident actor=iam-superadmin
2026-04-06 05:14:22 AUDIT JIT_EXPIRE user=bpatel role=iam-admin granted_at=2026-04-06T03:14:22 expires_at=2026-04-06T05:14:22 actor=system
```

---

## SIEM Integration

Keycloak auth and admin events are forwarded to a structured SIEM receiver using a pull-model forwarder — the same pattern used by commercial SIEM connectors (Splunk TA, Microsoft Sentinel).

```
Keycloak Admin API          siem-forwarder          siem-receiver
(event store)          →    (polls every 30s)   →   (normalises + stores)
/admin/realms/enterprise/   siem_forwarder.py        siem-receiver/app.py
  events
  admin-events
```

Events are normalised to structured JSON with severity classification:

| Event Type | Severity | Alert |
|---|---|---|
| `LOGIN` | INFO | no |
| `LOGIN_ERROR` | HIGH | yes |
| `REMOVE_TOTP` | HIGH | yes |
| `ADMIN_DELETE_*` | HIGH | yes |
| `UPDATE_PASSWORD` | MEDIUM | no |
| `LOGOUT` | LOW | no |

Query the SIEM receiver:
```bash
# Last 20 events
curl http://localhost:5000/events/recent

# Filter by type and severity
curl "http://localhost:5000/events/recent?type=LOGIN_ERROR&severity=HIGH&limit=50"
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

- **Loki** collects structured logs from all containers via Promtail (Docker socket SD)
- **Grafana IAM Operations dashboard** (`grafana/dashboards/iam-operations.json`) — provisioned automatically on startup:
  - Successful login / failure / MFA enrollment / logout stat panels
  - Auth events over time (timeseries, 30s refresh)
  - Login failure rate panel for brute-force spike detection
  - Live Keycloak event stream (log panel)
  - MFA & privileged admin operation trends
- Keycloak emits `LOGIN`, `LOGIN_ERROR`, `LOGOUT`, `ADMIN_*` events queryable via:
  - Grafana → IAM Operations dashboard
  - Keycloak Admin → Realm → Events

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
├── docker-compose.yml          # 12-container production stack
├── .env                        # Secrets (not committed)
├── .github/workflows/ci.yml    # CI: validate + Trivy scan + smoke test + IGA lint
├── nginx/nginx.conf            # TLS termination, rate-limiting, security headers
├── certs/                      # TLS certs (ca.crt, server.crt committed; keys excluded)
├── keycloak/
│   └── enterprise-realm-export.json  # Realm config-as-code (roles, clients, LDAP, WebAuthn)
├── ldap/init-ldap.ldif         # OU structure + 4 user personas + 2 service accounts
├── grafana/
│   ├── provisioning/datasources/loki.yml
│   ├── provisioning/dashboards/dashboards.yml
│   └── dashboards/iam-operations.json  # IAM ops dashboard (auto-provisioned)
├── monitoring/
│   └── promtail-config.yml     # Docker SD log scraping → Loki
├── siem-receiver/
│   ├── app.py                  # Flask SIEM event receiver + normaliser
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   ├── iam_lifecycle.py        # Joiner/Mover/Leaver/Certify CLI
│   ├── jit_access.py           # JIT privileged access (elevate/revoke/expire)
│   ├── siem_forwarder.py       # Keycloak → SIEM event forwarder (pull model)
│   ├── nextcloud-saml-setup.sh # Nextcloud user_saml app install + occ config
│   ├── healthcheck.sh          # 7-assertion production readiness check
│   ├── backup.sh               # Volume backup with retention
│   └── restore.sh              # Point-in-time restore
└── docs/
    ├── runbooks/               # Keycloak realm setup, LDAP federation procedures
    ├── incident-playbooks/     # P1–P3 ITIL response procedures
    └── security/
        └── trivy-scan-report.md  # CVE findings + P1/P2/P3 remediation roadmap
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

**Why WebAuthn as optional rather than mandatory alongside TOTP?**
TOTP is the default Required Action enforced on all users at first login. WebAuthn (`webauthn-register`) is opt-in because FIDO2 requires physical authenticator hardware that lab users may not have. In production, WebAuthn would be promoted to mandatory for privileged accounts (iam-admin, compliance-admin) once hardware token inventory is confirmed.

**Why provision Grafana dashboards as code rather than UI-built?**
Dashboard-as-code (`grafana/dashboards/*.json` + provisioning YAML) survives container rebuilds without volume state, and puts monitoring configuration in version control alongside the stack it monitors.
