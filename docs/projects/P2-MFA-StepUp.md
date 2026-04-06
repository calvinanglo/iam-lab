# Project 2 — MFA Enforcement, Recovery & Step-Up Authentication

## What This Demonstrates

Multi-factor authentication is enforced as a default Required Action rather than a custom flow — the correct pattern for Keycloak 26. Step-up authentication uses ACR (Authentication Context Class Reference) levels so that high-risk clients can demand re-verification of identity even within an existing session.

---

## Architecture

```
User authenticates to Grafana (gold ACR required)
    │
    ▼
Keycloak evaluates: does session have ACR ≥ 2?
    ├── No session  → Username/Password + TOTP prompt
    ├── Session ACR=1 (password only) → Re-challenge: TOTP prompt
    └── Session ACR=2 (password + TOTP) → Token issued
```

```
User authenticates to Gitea (silver ACR)
    │
    ▼
Keycloak evaluates: does session have ACR ≥ 1?
    ├── No session → Username/Password only
    └── Session exists → Token issued (no re-challenge)
```

---

## Configuration Applied

### MFA Enforcement — Required Actions

Rather than a custom browser flow (which has a Keycloak 26 NPE regression in `ConditionalUserConfiguredAuthenticator`), MFA is enforced via Required Actions:

| Required Action | State | Applies To |
|---|---|---|
| `CONFIGURE_TOTP` | Enabled, **Default** | All users (LDAP + local) |
| `webauthn-register` | Enabled, optional | All users |
| `webauthn-register-passwordless` | Enabled, optional | jsmith, alee (demo) |
| `UPDATE_PASSWORD` | Enabled | New local users |

When a user has `CONFIGURE_TOTP` in their `requiredActions` list, Keycloak prompts TOTP setup before granting any token — regardless of which client they are accessing.

Applied to all 5 LDAP users via API:
```bash
curl -X PUT .../admin/realms/enterprise/users/$USER_ID \
  -d '{"requiredActions":["CONFIGURE_TOTP"]}'
```

### Step-Up Authentication — ACR Levels

**Realm-level ACR-to-LoA mapping:**

| ACR label | Level of Assurance | Meaning |
|---|---|---|
| `silver` | 1 | Password authentication only |
| `gold` | 2 | Password + MFA (TOTP or WebAuthn) |

Configured via `attributes.acr.loa.map = {"silver":"1","gold":"2"}`.

**Client ACR requirements:**

| Client | Default ACR | Effect |
|---|---|---|
| `grafana` | `gold` (LoA 2) | MFA always required; existing sessions without MFA are re-challenged |
| `gitea` | `silver` (LoA 1) | Password sufficient; MFA not re-challenged within session |
| `nextcloud` (SAML) | — | SAML clients use `RequestedAuthnContext` instead |

**How step-up triggers:**
When Grafana initiates an OIDC auth request, Keycloak checks the current session's `acr` claim. If the session was established at LoA 1 (password only), Keycloak elevates authentication by prompting for TOTP before issuing the token. The issued access token contains `"acr": "gold"`.

### Browser Flow (Standard)

The built-in `browser` flow is used unchanged:

```
Cookie           [ALTERNATIVE]  — reuses existing session
Kerberos         [DISABLED]
IdP Redirector   [ALTERNATIVE]  — for future IdP chaining
forms            [ALTERNATIVE]
  ├── Username Password Form    [REQUIRED]
  └── Browser - Conditional OTP [CONDITIONAL]
        ├── Condition - user configured  [REQUIRED]
        └── OTP Form                     [REQUIRED]
```

The `Conditional OTP` subflow executes only when the user has configured TOTP — new users hit the `CONFIGURE_TOTP` Required Action before reaching this subflow.

---

## Verification Steps

```bash
# 1. Confirm CONFIGURE_TOTP is the default Required Action
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://keycloak.iam-lab.local:8443/admin/realms/enterprise/authentication/required-actions/CONFIGURE_TOTP | \
  grep '"defaultAction":true'

# 2. Confirm realm ACR map is set
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://keycloak.iam-lab.local:8443/admin/realms/enterprise | \
  grep 'acr.loa.map'

# 3. Confirm Grafana requires gold ACR
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/clients?clientId=grafana" | \
  grep '"default.acr.values":"gold"'

# 4. Confirm Gitea requires silver ACR
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/clients?clientId=gitea" | \
  grep '"default.acr.values":"silver"'

# 5. Manual SSO test
# Open https://grafana.iam-lab.local:3443 → click Keycloak SSO
# Enter jsmith credentials → TOTP prompt appears (gold ACR enforced)
# Open https://gitea.iam-lab.local:3444 → click Sign in with Keycloak
# If session exists at LoA ≥ 1 → no TOTP re-challenge (silver satisfied)
```

---

## Key Design Decisions

**Why Required Actions instead of a custom MFA flow?**
Keycloak 26 introduced a regression where `ConditionalUserConfiguredAuthenticator` throws a `NullPointerException` when evaluated before the user is authenticated (i.e., in copied browser flows). The correct KC26 pattern is Required Actions: the authenticator completes password authentication, then KC checks `requiredActions[]` and prompts TOTP setup if needed. This is also better UX — users aren't blocked from accessing non-sensitive apps while they set up MFA.

**Why ACR rather than per-client custom flows?**
Custom flows per client don't compose — you'd need a separate flow for each combination of requirements. ACR levels are reusable: adding a new high-risk client means setting `default.acr.values=gold`, not creating another flow.

**Why gold for Grafana but not Gitea?**
Grafana exposes the full IAM monitoring dashboard. A compromised Grafana session reveals auth patterns, active sessions, and user activity — high-value intelligence for an attacker. Gitea hosts code; valuable, but the blast radius of a single session compromise is lower. Tiered ACR reflects tiered risk.
