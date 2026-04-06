# Runbook: Keycloak Enterprise Realm Setup

**Applies to:** Keycloak 26.x
**Prereq:** Stack healthy (`./scripts/healthcheck.sh` all green)

---

## 1. Create the Enterprise Realm

1. Navigate to `https://keycloak.iam-lab.local:8443`
2. Log in with `KEYCLOAK_ADMIN` credentials from `.env`
3. Top-left dropdown → **Create realm**
4. Realm name: `enterprise` → **Create**

---

## 2. LDAP User Federation

**Clients → User Federation → Add provider → ldap**

| Field | Value |
|-------|-------|
| Vendor | Other |
| Connection URL | `ldap://openldap:389` |
| Bind DN | `uid=svc-keycloak,ou=service-accounts,dc=rbclab,dc=local` |
| Bind credentials | Value of `LDAP_READONLY_USER_PASSWORD` from `.env` |
| Users DN | `ou=users,dc=rbclab,dc=local` |
| Username LDAP attr | `uid` |
| RDN LDAP attr | `uid` |
| UUID LDAP attr | `entryUUID` |
| User object classes | `inetOrgPerson, posixAccount` |
| Sync registrations | Off |

Click **Test connection** → **Test authentication** → **Save**
Then: **Action → Sync all users**

**Mapper — add department attribute:**
Mappers tab → Add mapper
- Type: `user-attribute-ldap-mapper`
- Name: `department`
- LDAP Attribute: `department`
- User Model Attribute: `department`

---

## 3. OIDC Client for Grafana

**Clients → Create client**

| Field | Value |
|-------|-------|
| Client type | OpenID Connect |
| Client ID | `grafana` |
| Client authentication | On (confidential) |
| Valid redirect URIs | `https://grafana.iam-lab.local:3443/*` |
| Web origins | `https://grafana.iam-lab.local:3443` |

After save → **Credentials tab** → copy Client Secret → set as `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET` in `.env`

**Role mapper:**
Client scopes → `grafana-dedicated` → Add mapper → By configuration → User Realm Role
- Token claim name: `roles`
- Add to ID token: On
- Add to access token: On

---

## 4. SAML Client for Nextcloud

**Clients → Create client**

| Field | Value |
|-------|-------|
| Client type | SAML |
| Client ID | `https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/metadata` |
| Name ID format | `email` |
| Sign assertions | On |
| Signature algorithm | `RSA_SHA256` |
| Valid redirect URIs | `https://nextcloud.iam-lab.local:8444/*` |

**Attribute mappers:**
- `email` → `email` (user property)
- `firstName` → `firstName` (user property)
- `lastName` → `lastName` (user property)
- `uid` → `uid` (user attribute: username)

Export SAML metadata: `https://keycloak.iam-lab.local:8443/realms/enterprise/protocol/saml/descriptor`

---

## 5. MFA Browser Flow

**Authentication → Flows → Browser → Duplicate**
Name: `Enterprise MFA Browser`

In the duplicated flow:
1. Find **Browser Forms** sub-flow
2. **Add step** → `OTP Form` → set to **Required**
3. Bind: **Authentication → Bindings → Browser flow** → select `Enterprise MFA Browser`

**WebAuthn (FIDO2) alternative:**
1. Add step: `WebAuthn Authenticator`
2. Move above OTP Form
3. Set both to **Alternative** under a new sub-flow set to **Required**

---

## 6. Realm Roles

**Realm roles → Create role** for each:

| Role | Description |
|------|-------------|
| `trader` | Equity/FX trading desk access |
| `risk-analyst` | Risk dashboard read access |
| `compliance-admin` | Audit log and compliance tooling |
| `helpdesk` | Password reset, account unlock only |
| `iam-admin` | Full IAM platform administration |

---

## Verification Checklist

- [ ] LDAP sync shows users in realm
- [ ] Grafana login redirects to Keycloak SSO
- [ ] SAML metadata loads from Nextcloud URL
- [ ] MFA prompts on second authentication factor
- [ ] Role assignments visible on user accounts
