# IAM Lab — Production-Grade Identity & Access Management Portfolio

> **Targeted role:** RBC Senior IAM Systems Support Analyst (Global Security)
> **Stack:** Keycloak 26 · PostgreSQL 16 · OpenLDAP · Nginx TLS · Grafana/Loki · Nextcloud · Gitea · Docker Compose

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     iam-frontend network                     │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌───────────┐  ┌────────┐  │
│  │  Nginx   │   │ Keycloak │   │  Grafana  │  │ Gitea  │  │
│  │TLS Proxy │   │  IdP 26  │   │Dashboards │  │  SCM   │  │
│  └────┬─────┘   └────┬─────┘   └─────┬─────┘  └───┬────┘  │
│       │              │               │             │       │
└───────┼──────────────┼───────────────┼─────────────┼───────┘
        │              │               │             │
┌───────┼──────────────┼───────────────┼─────────────┼───────┐
│       │         iam-backend network (internal)     │       │
│       │              │               │             │       │
│  ┌────┴─────┐   ┌────┴─────┐   ┌────┴─────┐       │       │
│  │PostgreSQL│   │ OpenLDAP │   │   Loki   │       │       │
│  │  DB :5432│   │  :389    │   │  :3100   │       │       │
│  └──────────┘   └──────────┘   └──────────┘       │       │
└────────────────────────────────────────────────────────────┘
```

**Security posture:**
- `iam-backend` network is `internal: true` — zero external exposure for DB/LDAP
- TLS 1.2/1.3 only, strong ciphers, HSTS on all endpoints
- Rate limiting on Keycloak login (10 r/s) and admin API (30 r/s)
- All secrets in `.env`, excluded from git
- Non-root containers, resource limits on every service
- Automated backups with 30-day retention

---

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| **Keycloak** | https://keycloak.iam-lab.local:8443 | IdP — SSO, SAML, OIDC, MFA, FIDO2 |
| **Grafana** | https://grafana.iam-lab.local:3443 | Dashboards — Auth events, failed logins |
| **Nextcloud** | https://nextcloud.iam-lab.local:8444 | SAML SP — File storage demo |
| **Gitea** | https://gitea.iam-lab.local:3444 | OIDC SP — Git server demo |
| **phpLDAPadmin** | http://localhost (internal) | LDAP directory browser |
| **OpenLDAP** | ldap://openldap:389 (internal) | LDAP directory |
| **PostgreSQL** | postgres://keycloak-db:5432 (internal) | Keycloak persistence |
| **Loki + Promtail** | http://loki:3100 (internal) | Centralized log aggregation |

---

## Quick Start

### Prerequisites
- Docker Desktop 4.x
- OpenSSL
- Git Bash (Windows) or any Unix shell

### 1. Clone & configure

```bash
git clone https://github.com/calvinanglo/iam-lab.git
cd iam-lab
cp .env.example .env
# Edit .env — replace all CHANGE_ME values
# Generate passwords: openssl rand -hex 24
```

### 2. Add hosts entries

**Windows** — open Notepad as Administrator, edit `C:\Windows\System32\drivers\etc\hosts`:
```
127.0.0.1  iam-lab.local keycloak.iam-lab.local grafana.iam-lab.local
127.0.0.1  nextcloud.iam-lab.local gitea.iam-lab.local ldap.iam-lab.local
```

**Linux/Mac** — `sudo nano /etc/hosts` and add the same lines.

### 3. Generate TLS certificates

```bash
bash certs/generate-certs.sh
# Then import certs/ca.crt into your browser trust store
```

### 4. Launch

```bash
docker compose up -d
# Keycloak takes ~90 seconds to initialize on first run
docker compose ps   # verify all healthy
bash scripts/healthcheck.sh
```

---

## Projects

### Project 1 — SSO Federation (SAML + OIDC + LDAP)

Configure Keycloak `enterprise` realm with:
- **LDAP user federation** → OpenLDAP (read-only service account)
- **OIDC client** → Grafana (confidential, role mappers)
- **SAML client** → Nextcloud (signed assertions, SHA-256)
- **MFA browser flow** → TOTP + WebAuthn alternatives

📋 Runbook: [`docs/runbooks/keycloak-realm-setup.md`](docs/runbooks/keycloak-realm-setup.md)

---

### Project 2 — MFA Enrollment, Recovery & Step-Up Auth

- Custom Keycloak auth flows with OTP + FIDO2 alternatives
- Step-up authentication for admin operations
- Okta Developer parallel configuration (comparison)
- Recovery playbooks for lost devices, compromised accounts, lockout waves

📋 Playbook: [`docs/incident-playbooks/P2-mfa-degradation.md`](docs/incident-playbooks/P2-mfa-degradation.md)

---

### Project 3 — FIDO2 / Passwordless Authentication

- Keycloak WebAuthn passkeys (device-bound + synced)
- Microsoft Entra ID Free — FIDO2 security key policies
- Browser compatibility matrix
- Enterprise rollout plan (50,000-user scale)

---

### Project 4 — RBAC/ABAC & User Lifecycle Automation

Banking-relevant role model (trader, risk-analyst, compliance-admin, helpdesk) with Python automation:

```bash
# Onboard new employee
python scripts/iam_lifecycle.py joiner \
  --username jdoe --email jdoe@rbclab.local \
  --role trader --department Trading

# Internal transfer
python scripts/iam_lifecycle.py mover \
  --username jdoe --old-role trader --new-role risk-analyst

# Offboard — disables account + terminates all sessions
python scripts/iam_lifecycle.py leaver --username jdoe

# Access review report
python scripts/iam_lifecycle.py report
```

Produces a full audit log at `iam_audit.log`.

---

### Project 5 — Monitoring, Incident Response & Audit

- Grafana + Loki centralized log aggregation
- Keycloak auth event parsing (LOGIN, LOGIN_ERROR, LOGOUT events)
- 5 ITIL-aligned incident playbooks

| Playbook | Severity | Scenario |
|----------|----------|----------|
| [P1-mass-login-failures](docs/incident-playbooks/P1-mass-login-failures.md) | P1 | Credential stuffing / auth storm |
| [P1-unauthorized-admin-action](docs/incident-playbooks/P1-unauthorized-admin-action.md) | P1 | Compromised admin account |
| [P2-mfa-degradation](docs/incident-playbooks/P2-mfa-degradation.md) | P2 | TOTP / WebAuthn failures |
| [P2-sso-outage](docs/incident-playbooks/P2-sso-outage.md) | P2 | Keycloak down |
| [P3-lockout-wave](docs/incident-playbooks/P3-lockout-wave.md) | P3 | Mass account lockouts |

---

## Operations

```bash
# Health check all services
bash scripts/healthcheck.sh

# Backup (PostgreSQL + LDAP, 30-day retention)
bash scripts/backup.sh

# Restore from backup
bash scripts/restore.sh backups/20260405_020000.tar.gz

# View logs
docker compose logs -f keycloak
docker compose logs -f --tail=50 openldap
```

---

## Directory Structure

```
iam-lab/
├── .env.example              # Secrets template
├── .gitignore                # Excludes .env, keys, backups
├── docker-compose.yml        # 11-service production stack
├── certs/
│   └── generate-certs.sh     # SAN cert generation (CA + server)
├── nginx/
│   └── nginx.conf            # TLS termination, rate limiting, security headers
├── ldap/
│   └── init-ldap.ldif        # OU structure, users, groups, service accounts
├── scripts/
│   ├── backup.sh             # Automated PostgreSQL + LDAP backup
│   ├── restore.sh            # Guided restore
│   ├── healthcheck.sh        # Full-stack health check
│   └── iam_lifecycle.py      # Joiner/Mover/Leaver automation CLI
├── monitoring/
│   └── promtail-config.yml   # Docker log scraping + Keycloak event parsing
└── docs/
    ├── runbooks/
    │   └── keycloak-realm-setup.md
    └── incident-playbooks/
        ├── P1-mass-login-failures.md
        ├── P1-unauthorized-admin-action.md
        ├── P2-mfa-degradation.md
        ├── P2-sso-outage.md
        └── P3-lockout-wave.md
```

---

## Production-Ready Controls

| Control | Implementation |
|---------|---------------|
| **Secrets management** | `.env` excluded from git; template in `.env.example` |
| **TLS** | Nginx terminates TLS 1.2/1.3, SAN certs, HSTS, strong ciphers |
| **Network segmentation** | Backend network `internal: true` — DB/LDAP unreachable externally |
| **Health checks** | Every container has health check with start period, retries, timeout |
| **Resource limits** | CPU + memory limits/reservations on every container |
| **Log rotation** | json-file driver, 10MB max, 3-file rotation |
| **Rate limiting** | Nginx: 10 r/s login, 30 r/s admin API |
| **Backup & recovery** | Automated daily backup, 30-day retention, restore runbook |
| **Audit logging** | Keycloak event logging + `iam_audit.log` from lifecycle scripts |
| **Least privilege** | Keycloak uses read-only LDAP service account |

### What I'd add at RBC scale

| Gap | Enterprise Solution |
|-----|-------------------|
| High availability | Keycloak cluster (Infinispan), Postgres replication, LDAP multi-master |
| Real certificates | Enterprise CA (DigiCert / Entrust) or Let's Encrypt |
| Secrets vault | HashiCorp Vault / AWS Secrets Manager |
| SIEM integration | Forward Keycloak events to Splunk / Microsoft Sentinel |
| WAF | AWS WAF / Cloudflare / F5 |
| CI/CD | GitOps pipeline (ArgoCD / Flux) |
| Change management | ITIL CAB approval process |
| DR | Cross-region backup replication, documented RTO/RPO |

---

## Tech Stack

![Keycloak](https://img.shields.io/badge/Keycloak-26.2-blue)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql)
![OpenLDAP](https://img.shields.io/badge/OpenLDAP-1.5-lightgrey)
![Nginx](https://img.shields.io/badge/Nginx-1.27-009639?logo=nginx)
![Grafana](https://img.shields.io/badge/Grafana-11.5-F46800?logo=grafana)
![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python)
