# Incident Playbook: Unauthorized Admin Action (P1)

**Severity:** P1 — Critical
**SLA:** Acknowledge in 15 min, contain in 30 min
**Owner:** IAM On-Call + Security Operations

---

## Symptoms

- Alert: Admin action from unexpected IP, time, or user
- Keycloak admin event: `REALM_UPDATE`, `CLIENT_UPDATE`, `ADMIN_LOGIN` from unknown actor
- User reports: unexpected role changes, new accounts, disabled MFA
- SIEM alert on privileged access anomaly

---

## Immediate Containment (0–15 min)

```bash
# 1. Identify the suspicious admin session
# Keycloak Admin UI → Events → Admin Events → filter by time window

# 2. Revoke all active admin sessions for the compromised account
# Via API (replace USER_ID):
KC_TOKEN=$(curl -s -X POST \
  "https://keycloak.iam-lab.local:8443/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli&username=${KEYCLOAK_ADMIN}&password=${KEYCLOAK_ADMIN_PASSWORD}&grant_type=password" \
  | jq -r .access_token)

curl -sk -X POST \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users/USER_ID/logout" \
  -H "Authorization: Bearer ${KC_TOKEN}"

# 3. Disable the compromised account
curl -sk -X PUT \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users/USER_ID" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

---

## Evidence Collection

```bash
# Export all admin events from past 24h
curl -sk \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/admin-events?max=1000" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  | jq . > /tmp/admin-events-$(date +%Y%m%d_%H%M%S).json

# Check Grafana Loki for correlated logs
# Query: {container=~".*keycloak.*"} |= "ADMIN_LOGIN"

# Preserve nginx access logs
docker logs $(docker ps -qf "name=nginx") > /tmp/nginx-$(date +%Y%m%d).log
```

---

## Scope Assessment

| Question | Where to Check |
|----------|---------------|
| What was changed? | Keycloak Admin Events → filter by `operationType=UPDATE,CREATE,DELETE` |
| Which users affected? | Role mapping changes in admin events |
| Was data exfiltrated? | Nginx logs for unusual API call volume |
| Are new backdoor accounts present? | Keycloak Users list, sort by created date |
| Was MFA disabled? | Admin events: `AUTHENTICATION_EXECUTION_UPDATE` |

---

## Remediation

1. **Revert changes** — Identify each admin event and manually reverse (role removals, client config changes, new accounts)
2. **Rotate all admin credentials** — Keycloak admin password, service account passwords
3. **Re-enable MFA** on all admin accounts
4. **Review all active sessions** — Terminate any unrecognized sessions across all realms
5. **Audit LDAP** — Check for unauthorized changes to privileged group membership

```bash
# Rotate Keycloak admin password
curl -sk -X PUT \
  "https://keycloak.iam-lab.local:8443/admin/realms/master/users/ADMIN_USER_ID/reset-password" \
  -H "Authorization: Bearer ${KC_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"type":"password","temporary":false,"value":"NEW_STRONG_PASSWORD"}'
```

---

## Escalation

| T+ | Action |
|----|--------|
| 0 | Page IAM on-call + SOC |
| 15 min | Incident bridge — IAM lead, Security lead, CISO |
| 30 min | Legal/Compliance notification if PII/regulated data accessed |
| 1 hr | Executive notification |
| 24 hr | Regulatory notification assessment (OSFI, PIPEDA) |

---

## Post-Incident

- [ ] All unauthorized changes reverted and verified
- [ ] Compromised account credential evidence preserved
- [ ] Admin event log exported and sent to SIEM
- [ ] Privileged access review scheduled (all iam-admin accounts)
- [ ] MFA required for admin UI access — re-verified
- [ ] ITIL PIR within 2 business days (P1 requirement)
- [ ] Regulatory reporting assessment completed
