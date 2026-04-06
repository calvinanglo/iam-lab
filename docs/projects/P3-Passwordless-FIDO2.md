# Project 3 — FIDO2 / Passwordless Authentication

## What This Demonstrates

WebAuthn (FIDO2) as a complete replacement for passwords — not just a second factor. Users register a hardware key, platform authenticator (Touch ID, Windows Hello), or passkey, then authenticate to Gitea with biometrics or hardware touch alone. No password is transmitted or stored.

---

## Architecture

```
Gitea login flow (passwordless-browser flow override)
    │
    ├── Cookie check (existing session reuse)
    ├── IdP Redirector (ALTERNATIVE)
    └── WebAuthn Passwordless Authenticator [REQUIRED]
            │
            ├── First login: user registers FIDO2 credential
            │   (triggered by webauthn-register-passwordless Required Action)
            │
            └── Subsequent logins: browser sends WebAuthn assertion
                Keycloak verifies with stored public key
                Token issued — no password involved
```

---

## Configuration Applied

### WebAuthn Policy (Realm-Level)

| Parameter | Value | Rationale |
|---|---|---|
| RP Entity Name | `IAM Lab` | Displayed to user during registration |
| RP ID | `keycloak.iam-lab.local` | Must match the origin the browser authenticates to |
| Signature algorithms | `ES256`, `RS256` | ES256 preferred (ECDSA, smaller key, faster); RS256 for compatibility |
| Attestation | `indirect` | Validates authenticator model without requiring raw attestation cert |
| Resident key | `No` | Discoverable credentials optional (enabled separately via passkeys feature) |
| User verification | `preferred` | Requests biometric/PIN but doesn't hard-fail hardware keys without UV |
| Timeout | `300` seconds | |

### Passwordless Browser Flow

Custom flow `passwordless-browser` (copy of built-in `browser`), modified:

```
Cookie                          [ALTERNATIVE]  — reuse sessions
Kerberos                        [DISABLED]
Identity Provider Redirector    [ALTERNATIVE]
Organization subflow            [ALTERNATIVE]
forms subflow                   [ALTERNATIVE]
  ├── Username Password Form    [DISABLED]     ← removed
  └── Conditional OTP subflow  [DISABLED]     ← removed
WebAuthn Passwordless Auth      [REQUIRED]     ← added
```

This flow is bound exclusively to the **Gitea** client via `authenticationFlowBindingOverrides.browser`. All other clients continue to use the standard `browser` flow.

### Required Actions

| Action | State | Assigned to |
|---|---|---|
| `webauthn-register` | Enabled, not default | All users (optional second factor) |
| `webauthn-register-passwordless` | Enabled, not default | `jsmith`, `alee` (demo enrollment) |

Users with `webauthn-register-passwordless` in their `requiredActions[]` are prompted to register a passkey on next Gitea login before the WebAuthn authenticator runs.

### KC_FEATURES Flag

```yaml
# docker-compose.yml — Keycloak environment
KC_FEATURES: "preview,passkeys"
```

The `passkeys` feature enables:
- Resident credential (discoverable) support
- `passkeys-authenticator` provider
- Enhanced WebAuthn UI in the account console

---

## Verification Steps

```bash
# 1. Confirm passwordless-browser flow exists
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://keycloak.iam-lab.local:8443/admin/realms/enterprise/authentication/flows | \
  grep '"alias":"passwordless-browser"'

# 2. Confirm WebAuthn Passwordless Authenticator is REQUIRED in flow
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/authentication/flows/passwordless-browser/executions" | \
  grep -A1 "WebAuthn Passwordless" | grep '"requirement":"REQUIRED"'

# 3. Confirm Gitea has passwordless flow override
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/clients?clientId=gitea" | \
  grep '"authenticationFlowBindingOverrides"'
# Expected: {"browser":"84793fbb-..."}

# 4. Confirm webauthn-register-passwordless action is enabled
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/authentication/required-actions/webauthn-register-passwordless" | \
  grep '"enabled":true'

# 5. Confirm jsmith has passwordless enrollment pending
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users?username=jsmith&exact=true" | \
  grep "webauthn-register-passwordless"

# 6. Manual end-to-end test
# Navigate to: https://gitea.iam-lab.local:3444/user/oauth2/keycloak
# Keycloak shows WebAuthn prompt (no password field)
# On first login: browser prompts to create passkey (Touch ID / Windows Hello / YubiKey)
# On subsequent login: browser passkey assertion only — no credentials typed
```

---

## How a User Registers a Passkey

1. Navigate to `https://gitea.iam-lab.local:3444` → **Sign in with Keycloak**
2. Keycloak detects `webauthn-register-passwordless` in required actions
3. Browser shows "Register a passkey" UI — user touches YubiKey or uses biometric
4. Public key stored in Keycloak; private key never leaves the device
5. Next login: Keycloak sends WebAuthn challenge → device signs → assertion verified
6. Token issued with no password involved at any point

---

## Key Design Decisions

**Why a flow override on Gitea rather than the whole realm?**
Not all users have hardware keys or platform authenticators. Making passwordless the realm-wide default would lock out users without enrolled credentials. A client-level override lets Gitea be the passwordless demo surface while other clients (Grafana, Nextcloud) continue to work with TOTP.

**Why `webauthn-authenticator-passwordless` instead of `passkeys-authenticator`?**
`passkeys-authenticator` handles fully resident/discoverable credentials (no username required). `webauthn-authenticator-passwordless` handles the more common case: username entered, then WebAuthn replaces the password step. The latter has broader hardware compatibility and is the safer production choice in 2025.

**Why `attestation=indirect`?**
`direct` attestation requires the authenticator to send its full attestation certificate chain, which can reveal device model to the RP — a privacy concern for personal devices (phones). `indirect` lets an attestation CA vouch for the authenticator model without exposing individual device certs. `none` skips attestation entirely — acceptable for consumer apps, not for regulated environments.

**FIDO2 vs TOTP — when to use each?**
TOTP is phishable — an attacker who intercepts a TOTP code has ~30 seconds to use it. FIDO2/WebAuthn credentials are origin-bound: the private key only signs challenges from `keycloak.iam-lab.local`. A phishing site at `keycloak-iam-lab.evil.com` gets a credential bound to a different origin — the signing fails. FIDO2 is phishing-resistant; TOTP is not.
