# Incident Playbook: SSO Outage (P2)

**Severity:** P2 — High
**SLA:** Acknowledge in 30 min, resolve or workaround in 4 hours
**Owner:** IAM On-Call + Infra

---

## Symptoms

- Keycloak health endpoint returning non-200 or not reachable
- All SSO-connected apps (Grafana, Nextcloud, Gitea) showing login errors
- `https://keycloak.iam-lab.local:8443/health/ready` timing out

---

## Triage (0–5 min)

```bash
# Is the container running?
docker ps | grep keycloak

# Is it healthy?
docker inspect --format='{{.State.Health.Status}}' $(docker ps -qf "name=keycloak")

# Logs (last 50 lines)
docker logs $(docker ps -qf "name=keycloak") --tail=50

# Is the database up?
docker exec $(docker ps -qf "name=keycloak-db") pg_isready -U keycloak

# Is nginx passing traffic?
docker logs $(docker ps -qf "name=nginx") --since=5m | grep -i "error\|upstream"
```

---

## Recovery Steps

### Step 1: Restart Keycloak

```bash
docker restart $(docker ps -aqf "name=keycloak")
# Wait 120 seconds for startup
sleep 120
curl -sfk https://localhost:8443/health/ready
```

### Step 2: If DB connection failure

```bash
# Restart DB first, then Keycloak
docker restart $(docker ps -aqf "name=keycloak-db")
sleep 30
docker restart $(docker ps -aqf "name=keycloak")
```

### Step 3: Full stack restart (last resort)

```bash
cd /path/to/iam-lab
docker compose down
docker compose up -d
# Keycloak takes ~2 minutes to be healthy
watch docker compose ps
```

### Step 4: Verify

```bash
./scripts/healthcheck.sh
```

---

## Emergency Local Access

If SSO is down but direct DB access needed:

```bash
# Connect to Keycloak DB directly
docker exec -it $(docker ps -qf "name=keycloak-db") \
  psql -U keycloak -d keycloak

# Check active realm config
SELECT id, name, enabled FROM realm;
```

---

## Service-Specific Fallbacks

| Service | Fallback Access |
|---------|----------------|
| Grafana | Direct login via `/login` with local admin account (`GF_SECURITY_ADMIN_USER`) |
| Nextcloud | Local admin account (set `NEXTCLOUD_ADMIN_USER`) |
| Gitea | Local admin account created during install |

---

## Communication Template

```
Subject: [IAM] SSO Login Unavailable — Active Incident

SSO-based login is currently unavailable. Affected services:
- Grafana (use local admin fallback at https://grafana.iam-lab.local:3443/login)
- Nextcloud
- Gitea

We are working to restore service. ETA: [TIME]
```

---

## Post-Incident

- [ ] Keycloak startup logs reviewed for OOM / DB connection errors
- [ ] Memory limits reviewed (1536M — increase if OOM was the cause)
- [ ] DB connection pool settings reviewed
- [ ] Liveness probe vs readiness probe settings validated
- [ ] Monitoring alert confirmed firing within 5 min of outage
- [ ] PIR within 5 business days
