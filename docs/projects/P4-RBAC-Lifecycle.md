# Project 4 — RBAC, ABAC & User Lifecycle Automation

## What This Demonstrates

Role-based access control with LDAP group federation as the authoritative source, automated IGA (Identity Governance & Administration) lifecycle operations, and just-in-time privileged access management. Together these implement the full identity lifecycle: provisioning, access review, and deprovisioning — without manual admin console work.

---

## Architecture

```
OpenLDAP (authoritative)
    │  group-ldap-mapper (sync)
    ▼
Keycloak Groups (/traders, /risk-analysts, ...)
    │  group-role mapping
    ▼
Realm Roles (trader, risk-analyst, ...)
    │  realm-roles protocol mapper
    ▼
OIDC token  →  Grafana role mapping (JMESPath)
               Gitea user (role in token)
               Nextcloud (SAML attribute)
```

```
iam_lifecycle.py                     jit_access.py
Joiner → create user + assign role   elevate → grant role for N min
Mover  → swap roles                  expire  → auto-revoke (cron)
Leaver → disable + terminate session revoke  → immediate revoke
Certify → access review report
```

---

## RBAC Configuration

### Realm Roles

| Role | Description | Mapped From |
|---|---|---|
| `trader` | Trading system access | `cn=traders` LDAP group |
| `risk-analyst` | Risk analytics access | `cn=risk-analysts` LDAP group |
| `compliance-admin` | Audit log and compliance tools | `cn=compliance-admins` LDAP group |
| `helpdesk` | User support operations | `cn=helpdesk` LDAP group |
| `iam-admin` | Full IAM administration | `cn=iam-admins` LDAP group |

### Grafana Role Mapping (ABAC via JMESPath)

Grafana receives the `roles` claim from Keycloak and maps to Grafana permission levels:

```
contains(roles[*], 'iam-admin')       && 'Admin'
contains(roles[*], 'compliance-admin') && 'Editor'
                                          'Viewer'   (default)
```

This is attribute-based: the same Grafana client serves different permission levels to different users based on identity attributes in the token — no per-user Grafana config required.

### Token Claim Configuration

The `realm-roles` protocol mapper adds all user realm roles to the `roles` claim in access and ID tokens:

```json
{
  "sub": "e52afafe-...",
  "preferred_username": "jsmith",
  "email": "jsmith@rbclab.local",
  "roles": ["trader", "default-roles-enterprise"]
}
```

---

## IGA Lifecycle Automation

### `iam_lifecycle.py`

All operations call the Keycloak Admin REST API with a service account token. Every action is written to `iam_audit.log`.

**Joiner** — onboard a new user:
```bash
python3 scripts/iam_lifecycle.py joiner \
  --username tchen --email tchen@rbclab.local \
  --first-name Tony --last-name Chen \
  --role trader --department Trading
```
Creates the Keycloak user, assigns the role, sets `UPDATE_PASSWORD` + `CONFIGURE_TOTP` Required Actions. User must set password and enroll TOTP on first login.

**Mover** — internal transfer:
```bash
python3 scripts/iam_lifecycle.py mover \
  --username tchen --old-role trader --new-role risk-analyst
```
Atomically removes old role and assigns new one. No privilege gap, no privilege accumulation.

**Leaver** — offboard:
```bash
python3 scripts/iam_lifecycle.py leaver --username tchen
```
Terminates all active sessions via `/users/{id}/logout`, then sets `enabled=false`. The account is retained for audit trail purposes but cannot authenticate.

**Certify** — access review (ISO 27001 / SOX):
```bash
python3 scripts/iam_lifecycle.py certify --days 90
```

Flags:
- `INACTIVE` — enabled account with no login in >N days
- `ORPHANED` — enabled account with no realm roles
- `DISABLED` — offboarded (verify no shared credentials)

Sample output:
```
USERNAME             EMAIL                            EN   ROLES                 LAST LOGIN   FLAG
tchen                tchen@rbclab.local               T    trader                never        INACTIVE  *** INACTIVE ***
jsmith               jsmith@rbclab.local              T    trader                2026-04-05   CLEAN
```

---

## JIT Privileged Access (`jit_access.py`)

Implements zero-standing-privilege for `iam-admin` and `compliance-admin` roles. No user holds these roles permanently — they must be explicitly elevated for a time-limited window.

```bash
# Elevate for P1 incident response
python3 scripts/jit_access.py elevate \
  --username bpatel \
  --role iam-admin \
  --duration 120 \
  --reason "P1-incident: SSO outage - INC0001234"

# Check active grants
python3 scripts/jit_access.py list

# Cron job (run every 5 minutes to auto-revoke expired grants)
*/5 * * * * python3 /scripts/jit_access.py expire

# Emergency revoke
python3 scripts/jit_access.py revoke --username bpatel --role iam-admin
```

Grant state is persisted in `.jit_grants.json`. All actions written to `iam_audit.log`:
```
AUDIT JIT_ELEVATE user=bpatel role=iam-admin duration_min=120 expires=2026-04-06T05:14:22 reason=P1-incident
AUDIT JIT_EXPIRE  user=bpatel role=iam-admin actor=system
```

Hard limits: maximum elevation window is 480 minutes (8 hours). Attempting to elevate a user who already has a standing grant fails with an error.

---

## Verification Steps

```bash
# 1. Confirm all 5 realm roles exist
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://keycloak.iam-lab.local:8443/admin/realms/enterprise/roles | \
  grep -o '"name":"[^"]*"' | grep -v default

# 2. Confirm LDAP group → role chain for jsmith
JSMITH_ID=$(curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users?username=jsmith&exact=true" | \
  grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users/$JSMITH_ID/groups" | \
  grep '"traders"'

curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users/$JSMITH_ID/role-mappings/realm" | \
  grep '"trader"'

# 3. Run joiner / certify
python3 scripts/iam_lifecycle.py joiner \
  --username verifytest --email vt@rbclab.local --role helpdesk
python3 scripts/iam_lifecycle.py certify --days 90
python3 scripts/iam_lifecycle.py leaver --username verifytest

# 4. JIT elevate/verify/revoke cycle
python3 scripts/jit_access.py elevate \
  --username bpatel --role iam-admin --duration 5 --reason "test"
python3 scripts/jit_access.py list   # should show bpatel, ~5min remaining
python3 scripts/jit_access.py revoke --username bpatel --role iam-admin
python3 scripts/jit_access.py list   # should show "No active JIT grants"
```

---

## Key Design Decisions

**Why LDAP as the authoritative group source (not Keycloak groups)?**
In enterprise environments, the directory (AD/LDAP) is the authoritative source of org structure. If Keycloak were authoritative, every org change would require a Keycloak admin operation. LDAP federation means org changes (new hire, team move) automatically propagate to Keycloak on next sync — no IAM admin involvement for routine changes.

**Why disable account on leaver rather than delete?**
Deletion removes the user's audit trail. Regulatory frameworks (SOX, GDPR retention obligations) require that access history be retained even after offboarding. Disabling preserves the record while preventing authentication.

**Why `.jit_grants.json` for JIT state rather than a database?**
This is a homelab. In production, JIT grant state would live in the IAM system's database with proper locking. The file-based approach here is intentionally simple — the design pattern (elevate/expire/revoke, audit log, hard time cap) is what matters for the portfolio.

**Why JMESPath for Grafana role mapping instead of Grafana's own role sync?**
Grafana's built-in role sync requires configuring role claims on the Grafana side. JMESPath in the docker-compose environment variable handles the mapping entirely at the Grafana OAuth layer — no Grafana database entries needed. Roles are derived from identity token claims at authentication time, which is the ABAC pattern.
