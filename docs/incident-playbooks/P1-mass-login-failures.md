# Incident Playbook: Mass Login Failures (P1)

**Severity:** P1 — Critical
**SLA:** Acknowledge in 15 min, resolve or workaround in 1 hour
**Owner:** IAM On-Call

---

## Symptoms

- >50 login failures per minute across multiple users
- Keycloak event log showing `LOGIN_ERROR` storm
- Grafana alert: `auth_failure_rate > 50/min`
- User reports: "Can't log in" across teams

---

## Triage (0–5 min)

```bash
# 1. Check Keycloak is alive
curl -sfk https://keycloak.iam-lab.local:8443/health/ready

# 2. Tail auth events (filter login errors)
docker logs $(docker ps -qf "name=keycloak") --since=10m 2>&1 \
  | grep -i "LOGIN_ERROR\|type=LOGIN_ERROR"

# 3. Check PostgreSQL reachability
docker exec $(docker ps -qf "name=keycloak-db") pg_isready -U keycloak

# 4. Check LDAP
docker exec $(docker ps -qf "name=openldap") \
  ldapsearch -x -H ldap://localhost:389 -b "dc=rbclab,dc=local" -s base "(objectclass=*)"
```

---

## Decision Tree

```
Mass login failures
│
├─ Keycloak DOWN → Go to P2 SSO Outage playbook
│
├─ DB DOWN → Restart keycloak-db, then keycloak
│
├─ LDAP DOWN → Restart openldap, trigger re-sync in Keycloak
│
├─ Keycloak UP, failures concentrated on 1 user
│   └─ Likely credential stuffing or brute force — see "Attack Response" below
│
└─ Keycloak UP, failures across many users
    ├─ Recent password policy change? → Notify users, extend grace period
    ├─ Clock skew (TOTP failures)? → Check NTP on all containers
    └─ LDAP password sync issue? → Force LDAP re-sync
```

---

## Attack Response (Credential Stuffing / Brute Force)

```bash
# Identify source IPs in nginx logs
docker logs $(docker ps -qf "name=nginx") --since=15m 2>&1 \
  | awk '{print $1}' | sort | uniq -c | sort -rn | head -20

# Block top offending IP (replace X.X.X.X)
# In production: update WAF/ACL. In lab: nginx deny rule or iptables
iptables -I DOCKER-USER -s X.X.X.X -j DROP
```

In Keycloak admin:
- Realm Settings → Security Defenses → Brute Force Detection
- Enable: Max login failures = 5, Wait increment = 30s, Max wait = 15m

---

## LDAP Re-Sync

1. Keycloak Admin → Realm `enterprise` → User Federation → ldap
2. **Action → Sync changed users** (faster)
3. If full sync needed: **Action → Sync all users** (may take minutes for large directories)

---

## Escalation

| Time | Action |
|------|--------|
| T+0 | Page IAM on-call |
| T+15 | If unresolved, page IAM lead + Infra lead |
| T+30 | Incident bridge opened, comms to affected teams |
| T+60 | Escalate to CISO if auth fully unavailable |

---

## Post-Incident

- [ ] Root cause documented in incident ticket
- [ ] Timeline written (first alert → detection → resolution)
- [ ] Grafana alert thresholds reviewed
- [ ] LDAP/KC config change reviewed if applicable
- [ ] ITIL PIR scheduled within 5 business days (P1 requirement)
