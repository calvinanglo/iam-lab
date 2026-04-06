# Incident Playbook: Account Lockout Wave (P3)

**Severity:** P3 — Medium
**SLA:** Acknowledge in 2 hours, resolve in next business day
**Owner:** IAM On-Call (or next available shift)

---

## Symptoms

- Help desk surge: multiple users locked out simultaneously
- Keycloak: Brute Force Detection showing mass lockouts
- Typically triggered by: password policy rollout, AD/LDAP sync issue, shared device with stale credentials

---

## Triage

```bash
# Count locked users in Keycloak
KC_TOKEN=$(curl -s -X POST \
  "https://keycloak.iam-lab.local:8443/realms/master/protocol/openid-connect/token" \
  -d "client_id=admin-cli&username=${KEYCLOAK_ADMIN}&password=${KEYCLOAK_ADMIN_PASSWORD}&grant_type=password" \
  | jq -r .access_token)

# List users with enabled=false (potential lockouts)
curl -sk \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users?enabled=false&max=200" \
  -H "Authorization: Bearer ${KC_TOKEN}" | jq '.[].username'
```

---

## Bulk Unlock (for verified non-attack scenario)

```bash
#!/bin/bash
# Unlock all users locked by brute force — ONLY after confirming this is not an attack
# Run from iam-lab root with KC_TOKEN set

USERS=$(curl -sk \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/attack-detection/brute-force/users" \
  -H "Authorization: Bearer ${KC_TOKEN}")

echo "$USERS" | jq -r '.[].userId' | while read USER_ID; do
  curl -sk -X DELETE \
    "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/attack-detection/brute-force/users/${USER_ID}" \
    -H "Authorization: Bearer ${KC_TOKEN}"
  echo "Unlocked: ${USER_ID}"
done
```

Single user unlock:
```bash
# Keycloak Admin UI → Users → [username] → Action → Clear lockout
# Or via API:
curl -sk -X DELETE \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/attack-detection/brute-force/users/USER_ID" \
  -H "Authorization: Bearer ${KC_TOKEN}"
```

---

## Root Cause Patterns

| Pattern | Indicator | Fix |
|---------|-----------|-----|
| Password policy change | Lockouts start right after policy update | Extend grace period, communicate to users |
| Stale cached credentials | Lockouts from specific IPs (shared devices) | Clear credential cache on offending device |
| LDAP sync conflict | Lockouts correlated with LDAP sync time | Pause sync, investigate LDAP password state |
| Credential stuffing (low/slow) | Distributed IPs, spread over hours | Enable CAPTCHA, tighten brute force thresholds |

---

## Prevention

Keycloak Admin → Realm Settings → Security Defenses → Brute Force Detection:
- Enabled: Yes
- Max login failures: 5
- Wait increment: 30 seconds
- Max wait: 15 minutes
- Failure reset time: 12 hours

**Note:** For lockout waves caused by password policy, increase `Failure reset time` temporarily rather than disabling brute force protection entirely.

---

## Communication Template

```
Subject: [IAM] Account Lockout Issue — Help Desk Alert

We are aware of an elevated number of account lockouts.
The IAM team is investigating the root cause.

If you are locked out, please contact the Help Desk and
reference ticket [TICKET_NUMBER].

Your account can be unlocked in approximately [TIME].
```

---

## Post-Incident

- [ ] Root cause identified and documented
- [ ] Number of affected users recorded
- [ ] Brute force thresholds reviewed
- [ ] Password policy change process reviewed if applicable
- [ ] Help Desk volume recorded for monthly KPI report
