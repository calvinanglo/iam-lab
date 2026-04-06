# Project 1 — SSO Federation (SAML + OIDC + LDAP)

## What This Demonstrates

Enterprise identity federation across three protocols: OIDC for modern SaaS-style apps, SAML 2.0 for legacy enterprise apps, and LDAP for directory services. This mirrors the multi-protocol environment found in every large organisation — no single protocol handles everything.

---

## Architecture

```
[Browser]
    │
    ▼
[Nginx TLS 1.3]  ──→  [Keycloak IdP :8443]
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
       [Grafana]       [Gitea]      [Nextcloud]
       OIDC SP         OIDC SP      SAML 2.0 SP
              │
              ▼
       [OpenLDAP :389]
       User/Group store
```

---

## Configuration Applied

### LDAP Federation

| Parameter | Value |
|---|---|
| Connection URL | `ldap://openldap:389` |
| Bind DN | `cn=readonly,dc=rbclab,dc=local` |
| Users DN | `ou=users,dc=rbclab,dc=local` |
| Edit Mode | `READ_ONLY` |
| User object classes | `inetOrgPerson, posixAccount` |
| UUID attribute | `entryUUID` |
| Sync | On-demand + import enabled |

LDAP user attributes mapped to Keycloak:

| LDAP attr | KC attribute | Notes |
|---|---|---|
| `uid` | `username` | Primary identifier |
| `givenName` | `firstName` | |
| `sn` | `lastName` | |
| `mail` | `email` | |

### LDAP Group Federation

Group mapper (`group-ldap-mapper`) syncs `ou=groups,dc=rbclab,dc=local` into Keycloak groups, which are then mapped to realm roles:

| LDAP Group | Keycloak Group | Realm Role |
|---|---|---|
| `cn=traders` | `/traders` | `trader` |
| `cn=risk-analysts` | `/risk-analysts` | `risk-analyst` |
| `cn=compliance-admins` | `/compliance-admins` | `compliance-admin` |
| `cn=helpdesk` | `/helpdesk` | `helpdesk` |
| `cn=iam-admins` | `/iam-admins` | `iam-admin` |

### OIDC Clients

**Grafana** (`grafana`):
- Protocol: `openid-connect`
- Flow: Authorization Code (confidential client, no PKCE)
- Redirect URI: `https://grafana.iam-lab.local:3443/*`
- Token claims: `roles` (realm role mapper), `email`, `preferred_username`
- Role mapping: `contains(roles[*], 'iam-admin') && 'Admin' || contains(roles[*], 'compliance-admin') && 'Editor' || 'Viewer'`

**Gitea** (`gitea`):
- Protocol: `openid-connect`
- Flow: Authorization Code (confidential client)
- Redirect URI: `https://gitea.iam-lab.local:3444/user/oauth2/keycloak/callback`
- Auth source: `gitea admin auth add-oauth --provider openidConnect`

### SAML 2.0 Client

**Nextcloud** (`https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/metadata`):
- Protocol: `saml`
- Binding: POST
- Signature algorithm: `RSA_SHA256`
- ACS URL: `https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/acs`
- SLS URL: `https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/sls`
- Server signature: enabled
- Client signature: disabled (SP does not sign AuthnRequests)

SAML attribute mappers:

| Keycloak attribute | SAML attribute | Nextcloud occ key |
|---|---|---|
| `username` | `uid` | `uid_mapping=uid` |
| `email` | `email` | |
| `firstName` | `displayName` | |

---

## Verification Steps

```bash
# 1. LDAP sync — confirm 4 users imported
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users | \
  grep -o '"username":"[^"]*"'
# Expected: jsmith, alee, mchen, bpatel

# 2. Group federation — confirm jsmith has trader role
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://keycloak.iam-lab.local:8443/admin/realms/enterprise/users/$JSMITH_ID/role-mappings/realm" | \
  grep '"name":"trader"'

# 3. OIDC discovery — Keycloak exposes well-known endpoint
curl -sk https://keycloak.iam-lab.local:8443/realms/enterprise/.well-known/openid-configuration | \
  grep '"authorization_endpoint"'

# 4. Grafana SSO redirect
curl -sk -o /dev/null -w "%{redirect_url}" \
  "https://grafana.iam-lab.local:3443/login/generic_oauth"
# Expected: redirect to keycloak.iam-lab.local

# 5. Gitea OAuth2 source
curl -sk -o /dev/null -w "%{redirect_url}" \
  "https://gitea.iam-lab.local:3444/user/oauth2/keycloak"
# Expected: redirect to keycloak.iam-lab.local

# 6. Nextcloud SAML SP metadata valid
curl -sk https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/metadata | \
  grep "EntityDescriptor"

# 7. Keycloak IdP SAML metadata valid
curl -sk https://keycloak.iam-lab.local:8443/realms/enterprise/protocol/saml/descriptor | \
  grep "IDPSSODescriptor"
```

---

## Key Design Decisions

**Why READ_ONLY LDAP mode?** Prevents Keycloak from writing back to the directory. In production, the authoritative user store is always the directory (Active Directory / LDAP); Keycloak should never mutate it directly — changes go through the IGA system.

**Why no PKCE on confidential OIDC clients?** PKCE is required for public clients (SPAs, mobile apps). Grafana and Gitea are server-side apps with a client secret — the secret already provides the channel binding that PKCE would otherwise supply.

**Why RSA_SHA256 for SAML?** SHA-1-based algorithms (RSA_SHA1) are deprecated. RSA_SHA256 is the minimum acceptable in modern PKI.
