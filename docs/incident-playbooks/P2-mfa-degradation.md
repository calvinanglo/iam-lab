# Incident Playbook: MFA Degradation (P2)

**Severity:** P2 — High
**SLA:** Acknowledge in 30 min, resolve or workaround in 4 hours
**Owner:** IAM On-Call

---

## Symptoms

- Users unable to complete MFA step (TOTP or WebAuthn)
- Keycloak event log: `LOGIN_ERROR` with `error=invalid_totp` or `error=webauthn_error` at elevated rate
- Grafana alert: `mfa_failure_rate > 20/min`
- Help desk ticket surge: "authenticator app not working"

---

## Triage (0–10 min)

```bash
# Check MFA-specific errors
docker logs $(docker ps -qf "name=keycloak") --since=15m 2>&1 \
  | grep -iE "totp|webauthn|otp|mfa|authenticator"

# Check Keycloak time sync (TOTP is time-sensitive ±30s)
docker exec $(docker ps -qf "name=keycloak") date
date  # Compare host time
```

---

## Decision Tree

```
MFA failures
│
├─ TOTP failures only
│   ├─ Clock skew > 30s? → Fix NTP (see below)
│   └─ Users report "expired codes" → Widen TOTP window in Keycloak
│
├─ WebAuthn/FIDO2 failures only
│   ├─ Browser update? → Check browser compatibility matrix
│   └─ Keycloak WebAuthn config changed? → Review admin events
│
└─ All MFA types failing
    └─ Authentication flow broken → Roll back recent flow changes
```

---

## Fix: NTP / Clock Skew

```bash
# Restart NTP sync on Docker host (Windows WSL2 / Linux)
sudo hwclock --hctosys  # Sync hardware clock to system

# Check Keycloak container time
docker exec $(docker ps -qf "name=keycloak") date -u

# If skewed: restart container (picks up host time)
docker restart $(docker ps -qf "name=keycloak")
```

---

## Fix: Widen TOTP Window (Temporary)

Keycloak Admin → Realm `enterprise` → Authentication → Policies → OTP Policy
- **Look ahead window**: Change from 1 to 3 (allows codes ±90s)
- Save → communicate to users that retrying once resolves the issue

Revert to 1 after clock sync is confirmed.

---

## Fix: Authentication Flow Rollback

Keycloak Admin → Authentication → Flows
- If `Enterprise MFA Browser` was recently changed, re-bind `Browser flow` to the original built-in `browser` flow temporarily
- Restore changes once root cause identified

---

## Temporary Bypass (Break-Glass)

> **Only with manager approval. Log all bypass grants in the incident ticket.**

For critical users (trading desk, on-call ops) who are blocked:

Keycloak Admin → Users → [username] → Required Actions
- Remove `CONFIGURE_TOTP` if they haven't enrolled yet (grants temporary access)

For enrolled users:
- Credentials tab → Delete TOTP device → User will be prompted to re-enroll at next login

---

## Communication Template

```
Subject: [IAM] MFA Login Issues — In Progress

We are aware that some users are experiencing issues completing
multi-factor authentication. Our team is investigating.

Workaround: If your authenticator code is rejected, wait 60 seconds
and try with the next code. If still failing, contact the Help Desk.

ETA for resolution: [TIME]
Updates every 30 minutes.
```

---

## Post-Incident

- [ ] Root cause documented
- [ ] NTP monitoring added if clock skew was the cause
- [ ] TOTP window reverted to standard value
- [ ] Affected users confirmed able to log in
- [ ] Help Desk ticket queue cleared
- [ ] PIR within 5 business days
