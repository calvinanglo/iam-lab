# Project 5 — Monitoring, Incident Response & Audit

## What This Demonstrates

Production-grade IAM observability: log aggregation, a purpose-built IAM operations dashboard, SIEM integration, structured audit trails, and ITIL-aligned incident response playbooks. This covers the "what happened and when" story that security teams and auditors require.

---

## Architecture

```
Keycloak (auth events)
    │
    ├── stdout logs ──→ Promtail ──→ Loki ──→ Grafana Dashboard
    │                  (Docker SD)           (IAM Operations)
    │
    └── Admin API ──→ siem_forwarder.py ──→ siem-receiver ──→ /var/log/siem/
        (event store)  (poll 30s)            (normalise)       keycloak-events.jsonl
        /events
        /admin-events

iam_lifecycle.py / jit_access.py
    └── iam_audit.log  (structured local audit trail)
```

---

## Components

### Log Aggregation (Loki + Promtail)

Promtail uses Docker service discovery to scrape logs from all containers. Keycloak logs are parsed with a regex pipeline stage to extract `event_type` and `realm` as Loki labels:

```yaml
pipeline_stages:
  - match:
      selector: '{container=~".*keycloak.*"}'
      stages:
        - regex:
            expression: 'type=(?P<event_type>[A-Z_]+).*realmId=(?P<realm>[a-z-]+)'
        - labels:
            event_type:
            realm:
```

This enables LogQL queries like `{container=~".*keycloak.*", event_type="LOGIN_ERROR"}`.

### Grafana IAM Operations Dashboard

Auto-provisioned via `grafana/provisioning/` — no manual import required on stack start.

Dashboard: **IAM Operations** (`grafana/dashboards/iam-operations.json`)

| Panel | LogQL Query | Purpose |
|---|---|---|
| Successful Logins (stat) | `count_over_time({...} \|= "type=LOGIN " [$__range])` | Auth success count |
| Login Failures (stat) | `count_over_time({...} \|= "type=LOGIN_ERROR" [$__range])` | Failure count with threshold alert colour |
| MFA Enrollments (stat) | `count_over_time({...} \|= "CONFIGURE_TOTP" [$__range])` | MFA adoption rate |
| Logouts (stat) | `count_over_time({...} \|= "type=LOGOUT" [$__range])` | Session terminations |
| Admin Deletions (stat) | `count_over_time({...} \|= "ADMIN" \|= "DELETE" [$__range])` | Privileged operations |
| Password Resets (stat) | `count_over_time({...} \|= "UPDATE_PASSWORD" [$__range])` | Credential changes |
| Auth Events Over Time (timeseries) | All three event types on one graph | Trend detection |
| Auth Event Distribution (donut) | Login / Failure / Logout proportions | Visual risk ratio |
| Login Failure Rate (bar chart) | Failures per interval with threshold line | Brute-force detection |
| Top Login Error Reasons (table) | `logfmt` parse + aggregation | Error categorisation |
| Keycloak Event Stream (logs) | Raw event log, descending | Live audit tail |
| MFA & Credential Events (timeseries) | TOTP + WebAuthn + Password reset | Credential hygiene |
| Admin Operations (timeseries) | CREATE / UPDATE / DELETE separated | Privileged action audit |

Dashboard refreshes every 30 seconds. Default time window: last 6 hours.

### SIEM Integration

**Pull-model forwarder** (`siem_forwarder.py`):
- Polls `/admin/realms/enterprise/events` and `/admin/events` every 30 seconds
- Maintains watermark in `.siem_state.json` (last-seen event timestamp)
- Tolerates SIEM receiver downtime — events accumulate in the Keycloak store
- Filters by event types: `LOGIN,LOGIN_ERROR,LOGOUT,REGISTER,UPDATE_PASSWORD,REMOVE_TOTP,UPDATE_TOTP`

**SIEM receiver** (`siem-receiver/app.py`):
- Flask endpoint at `POST /events` and `POST /admin-events`
- Normalises raw Keycloak JSON to structured format with severity classification
- Appends to `/var/log/siem/keycloak-events.jsonl` (JSONL = one event per line, Loki-ingestable)
- `GET /events/recent` provides a simple query interface

**Severity classification:**

| Event | Severity | Alert flag |
|---|---|---|
| `LOGIN_ERROR` | HIGH | yes |
| `CLIENT_LOGIN_ERROR` | HIGH | yes |
| `REMOVE_TOTP` | HIGH | yes |
| `ADMIN_DELETE_*` | HIGH | yes |
| `UPDATE_PASSWORD` | MEDIUM | no |
| `REGISTER` | MEDIUM | no |
| `LOGIN` | INFO | no |
| `LOGOUT` | LOW | no |

### Keycloak Event Recording

Enabled on enterprise realm:
- `eventsEnabled: true` — auth events stored 30 days
- `adminEventsEnabled: true` — all admin operations recorded with full representation diff
- `adminEventsDetailsEnabled: true` — includes before/after state for mutations

Enabled event types: LOGIN, LOGIN_ERROR, LOGOUT, REGISTER, UPDATE_PASSWORD, RESET_PASSWORD, UPDATE_PROFILE, VERIFY_EMAIL, REMOVE_TOTP, UPDATE_TOTP, CLIENT_LOGIN, CLIENT_LOGIN_ERROR, CODE_TO_TOKEN, CODE_TO_TOKEN_ERROR, REFRESH_TOKEN, REFRESH_TOKEN_ERROR, GRANT_CONSENT, REVOKE_GRANT.

### IGA Audit Trail

All `iam_lifecycle.py` and `jit_access.py` operations write to `iam_audit.log`:

```
2026-04-06 03:14:22 AUDIT JOINER user=tchen role=trader email=tchen@rbclab.local actor=iam-superadmin
2026-04-06 03:14:28 AUDIT MOVER user=tchen old_role=trader new_role=risk-analyst actor=iam-superadmin
2026-04-06 03:14:35 AUDIT LEAVER user=tchen user_id=d6ce3539 actor=iam-superadmin
2026-04-06 03:14:40 AUDIT CERTIFY realm=enterprise total=5 inactive=1 orphaned=0 disabled=0 actor=iam-superadmin lookback_days=90
2026-04-06 03:20:00 AUDIT JIT_ELEVATE user=bpatel role=iam-admin duration_min=120 expires=2026-04-06T05:20:00 reason=P1-incident actor=iam-superadmin
2026-04-06 05:20:00 AUDIT JIT_EXPIRE user=bpatel role=iam-admin actor=system
```

---

## Incident Playbooks

Five ITIL-aligned playbooks in `docs/incident-playbooks/`:

| File | Incident | Priority |
|---|---|---|
| `P1-sso-outage.md` | SSO completely unavailable; users cannot authenticate | P1 |
| `P1-mass-account-lockout.md` | Brute-force or misconfiguration locking out large user population | P1 |
| `P2-mfa-degradation.md` | MFA service degraded; bypass risk | P2 |
| `P2-ldap-sync-failure.md` | LDAP federation sync broken; new users/group changes not propagating | P2 |
| `P3-token-anomaly.md` | Anomalous token issuance patterns detected in SIEM | P3 |

Each playbook follows: **Symptoms → Triage → Containment → Resolution → Post-Incident**.

---

## Healthcheck

`scripts/healthcheck.sh` — 7 assertions, exits non-zero if any fail:

| Check | What it verifies |
|---|---|
| Keycloak HTTPS | TLS endpoint responds |
| OIDC discovery | `.well-known/openid-configuration` valid JSON |
| Admin token | Service account can obtain token |
| Grafana API | `/api/health` returns ok |
| Gitea API | `/api/swagger` reachable |
| Nextcloud status | `status.php` returns `installed:true` |
| LDAP ping | LDAP port 389 accepting connections |

---

## Verification Steps

```bash
# 1. Healthcheck
bash scripts/healthcheck.sh

# 2. Confirm event recording is enabled
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://keycloak.iam-lab.local:8443/admin/realms/enterprise | \
  grep '"eventsEnabled":true'

# 3. Query recent auth events from Keycloak store
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/events?max=5" | \
  grep -o '"type":"[^"]*"'

# 4. SIEM receiver health
curl http://localhost:5000/health
# Expected: {"status":"ok","service":"siem-receiver"}

# 5. Query SIEM for recent events
curl "http://localhost:5000/events/recent?limit=10"

# 6. Grafana dashboard accessible
curl -sk -u admin:$GF_SECURITY_ADMIN_PASSWORD \
  https://grafana.iam-lab.local:3443/api/dashboards/uid/iam-operations-v1 | \
  grep '"title":"IAM Operations"'

# 7. Run access certification (produces audit output)
python3 scripts/iam_lifecycle.py certify --days 90

# 8. Trigger a login failure and observe in SIEM
curl -sk -X POST \
  https://keycloak.iam-lab.local:8443/realms/enterprise/protocol/openid-connect/token \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=admin-cli" \
  --data-urlencode "username=jsmith" \
  --data-urlencode "password=wrongpassword"

# Wait 30s for forwarder poll, then:
curl "http://localhost:5000/events/recent?type=LOGIN_ERROR"
```

---

## Key Design Decisions

**Why pull model for SIEM instead of Keycloak HTTP event listener SPI?**
The HTTP listener SPI requires a custom Keycloak extension (JAR) — adding a dependency not in the base image. The pull model (polling the Admin API event store) requires no KC modification, works with any Keycloak version, and is how most commercial SIEM connectors work (Splunk TA for Keycloak, Microsoft Sentinel). It also handles SIEM outages gracefully: events accumulate in KC's store and are forwarded when the receiver recovers.

**Why JSONL for the audit file?**
JSON Lines is the native format for Loki ingestion. Each event is a self-contained JSON object on one line — easy to `grep`, `jq`, and ship to any log aggregator without pre-processing.

**Why 30-day event retention in Keycloak?**
Balances storage cost against audit requirements. Most security standards (ISO 27001, SOX) require access logs to be retained for at least 1 year. The KC event store serves as the hot tier (30 days, queryable via API); the SIEM JSONL file serves as the warm tier; production would add a cold archive (S3/WORM).

**Why include IGA operations in the SIEM pipeline?**
Provisioning events (joiner, mover, leaver) are as security-relevant as authentication events. A leaver account that somehow re-authenticates after `leaver` was run is a critical incident. Keeping IGA audit output in the same pipeline as auth events makes correlation possible.
