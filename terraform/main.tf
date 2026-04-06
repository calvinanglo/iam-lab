# ══════════════════════════════════════════════════════════════════════════════
# Keycloak Realm Infrastructure-as-Code
# ══════════════════════════════════════════════════════════════════════════════
# Manages the enterprise realm, roles, clients, LDAP federation, and security
# policies via the mrparkers/keycloak Terraform provider. This is the IaC
# complement to the JSON realm export — use Terraform for ongoing management
# and the JSON export for initial bootstrap.
#
# Usage:
#   cd terraform
#   terraform init
#   terraform plan -var-file="secrets.tfvars"
#   terraform apply -var-file="secrets.tfvars"
# ══════════════════════════════════════════════════════════════════════════════

# ── Realm ─────────────────────────────────────────────────────────────────────

resource "keycloak_realm" "enterprise" {
  realm        = var.realm_name
  display_name = "Enterprise IAM"
  enabled      = true
  ssl_required = "external"

  # Token lifetimes
  access_token_lifespan    = "5m"
  sso_session_idle_timeout = "30m"
  sso_session_max_lifespan = "10h"

  # Login settings
  registration_allowed     = false
  login_with_email_allowed = true
  duplicate_emails_allowed = false
  reset_password_allowed   = false
  edit_username_allowed    = false

  # Brute force protection
  brute_force_detection {
    permanent_lockout                = false
    failure_reset_time_seconds       = 43200
    max_login_failures               = 5
    wait_increment_seconds           = 60
    max_failure_wait_seconds         = 900
    quick_login_check_milli_seconds  = 1000
    minimum_quick_login_wait_seconds = 60
  }

  # Password policy
  password_policy = "length(12) and upperCase(1) and lowerCase(1) and digits(1) and specialChars(1) and notUsername and passwordHistory(5)"

  # Events
  events_enabled    = true
  events_expiration = 2592000
  events_listeners  = ["jboss-logging"]
  admin_events_enabled         = true
  admin_events_details_enabled = true
}

# ── Realm Roles ───────────────────────────────────────────────────────────────

resource "keycloak_role" "trader" {
  realm_id    = keycloak_realm.enterprise.id
  name        = "trader"
  description = "Trading system access - market data and order entry"
}

resource "keycloak_role" "risk_analyst" {
  realm_id    = keycloak_realm.enterprise.id
  name        = "risk-analyst"
  description = "Risk reporting and analytics access"
}

resource "keycloak_role" "compliance_admin" {
  realm_id    = keycloak_realm.enterprise.id
  name        = "compliance-admin"
  description = "Compliance tooling and audit log access"
}

resource "keycloak_role" "helpdesk" {
  realm_id    = keycloak_realm.enterprise.id
  name        = "helpdesk"
  description = "User support operations"
}

resource "keycloak_role" "iam_admin" {
  realm_id    = keycloak_realm.enterprise.id
  name        = "iam-admin"
  description = "Full IAM administration - realm management"
}

# ── Groups (mapped to LDAP groups) ───────────────────────────────────────────

resource "keycloak_group" "traders" {
  realm_id = keycloak_realm.enterprise.id
  name     = "traders"
}

resource "keycloak_group_roles" "traders_roles" {
  realm_id = keycloak_realm.enterprise.id
  group_id = keycloak_group.traders.id
  role_ids = [keycloak_role.trader.id]
}

resource "keycloak_group" "risk_analysts" {
  realm_id = keycloak_realm.enterprise.id
  name     = "risk-analysts"
}

resource "keycloak_group_roles" "risk_analysts_roles" {
  realm_id = keycloak_realm.enterprise.id
  group_id = keycloak_group.risk_analysts.id
  role_ids = [keycloak_role.risk_analyst.id]
}

resource "keycloak_group" "compliance_admins" {
  realm_id = keycloak_realm.enterprise.id
  name     = "compliance-admins"
}

resource "keycloak_group_roles" "compliance_admins_roles" {
  realm_id = keycloak_realm.enterprise.id
  group_id = keycloak_group.compliance_admins.id
  role_ids = [keycloak_role.compliance_admin.id]
}

resource "keycloak_group" "helpdesk" {
  realm_id = keycloak_realm.enterprise.id
  name     = "helpdesk"
}

resource "keycloak_group_roles" "helpdesk_roles" {
  realm_id = keycloak_realm.enterprise.id
  group_id = keycloak_group.helpdesk.id
  role_ids = [keycloak_role.helpdesk.id]
}

resource "keycloak_group" "iam_admins" {
  realm_id = keycloak_realm.enterprise.id
  name     = "iam-admins"
}

resource "keycloak_group_roles" "iam_admins_roles" {
  realm_id = keycloak_realm.enterprise.id
  group_id = keycloak_group.iam_admins.id
  role_ids = [keycloak_role.iam_admin.id]
}

# ── LDAP User Federation ─────────────────────────────────────────────────────

resource "keycloak_ldap_user_federation" "openldap" {
  realm_id = keycloak_realm.enterprise.id
  name     = "ldap"
  enabled  = true
  priority = 0

  connection_url  = var.ldap_connection_url
  bind_dn         = var.ldap_bind_dn
  bind_credential = var.ldap_bind_credential

  users_dn                  = var.ldap_users_dn
  username_ldap_attribute   = "uid"
  rdn_ldap_attribute        = "uid"
  uuid_ldap_attribute       = "entryUUID"
  user_object_classes       = ["inetOrgPerson", "posixAccount"]
  edit_mode                 = "READ_ONLY"
  search_scope              = "ONE_LEVEL"
  connection_pooling        = true
  pagination                = true
  import_enabled            = true
  sync_registrations        = false
  full_sync_period          = 604800
  changed_sync_period       = 86400
  batch_size_for_sync       = 1000
  cache_policy              = "DEFAULT"
}

resource "keycloak_ldap_user_attribute_mapper" "username" {
  realm_id                = keycloak_realm.enterprise.id
  ldap_user_federation_id = keycloak_ldap_user_federation.openldap.id
  name                    = "username"
  ldap_attribute          = "uid"
  user_model_attribute    = "username"
  is_mandatory_in_ldap    = true
  read_only               = true
  always_read_value_from_ldap = true
}

resource "keycloak_ldap_user_attribute_mapper" "first_name" {
  realm_id                = keycloak_realm.enterprise.id
  ldap_user_federation_id = keycloak_ldap_user_federation.openldap.id
  name                    = "first name"
  ldap_attribute          = "givenName"
  user_model_attribute    = "firstName"
  read_only               = true
  always_read_value_from_ldap = true
}

resource "keycloak_ldap_user_attribute_mapper" "last_name" {
  realm_id                = keycloak_realm.enterprise.id
  ldap_user_federation_id = keycloak_ldap_user_federation.openldap.id
  name                    = "last name"
  ldap_attribute          = "sn"
  user_model_attribute    = "lastName"
  read_only               = true
  always_read_value_from_ldap = true
}

resource "keycloak_ldap_user_attribute_mapper" "email" {
  realm_id                = keycloak_realm.enterprise.id
  ldap_user_federation_id = keycloak_ldap_user_federation.openldap.id
  name                    = "email"
  ldap_attribute          = "mail"
  user_model_attribute    = "email"
  read_only               = true
  always_read_value_from_ldap = true
}

resource "keycloak_ldap_group_mapper" "groups" {
  realm_id                = keycloak_realm.enterprise.id
  ldap_user_federation_id = keycloak_ldap_user_federation.openldap.id
  name                    = "group-mapper"

  ldap_groups_dn                 = var.ldap_groups_dn
  group_name_ldap_attribute      = "cn"
  group_object_classes           = ["groupOfNames"]
  membership_attribute_type      = "DN"
  membership_ldap_attribute      = "member"
  membership_user_ldap_attribute = "uid"
  memberof_ldap_attribute        = "memberOf"
  mode                           = "READ_ONLY"
  groups_path                    = "/"
  drop_non_existing_groups_during_sync = false
  preserve_group_inheritance     = false
}

# ── OIDC Client: Grafana ─────────────────────────────────────────────────────

resource "keycloak_openid_client" "grafana" {
  realm_id  = keycloak_realm.enterprise.id
  client_id = "grafana"
  name      = "Grafana (OIDC SP)"

  access_type              = "CONFIDENTIAL"
  standard_flow_enabled    = true
  direct_access_grants_enabled = false
  service_accounts_enabled = false
  client_secret            = var.grafana_client_secret
  pkce_code_challenge_method = "S256"

  valid_redirect_uris = ["https://grafana.iam-lab.local:3443/*"]
  web_origins         = ["https://grafana.iam-lab.local:3443"]

  extra_config = {
    "post.logout.redirect.uris" = "https://grafana.iam-lab.local:3443/*"
  }
}

resource "keycloak_openid_user_realm_role_protocol_mapper" "grafana_roles" {
  realm_id  = keycloak_realm.enterprise.id
  client_id = keycloak_openid_client.grafana.id
  name      = "realm-roles"

  claim_name = "roles"
  multivalued = true
  add_to_access_token = true
  add_to_id_token     = true
  add_to_userinfo     = true
}

# ── OIDC Client: Gitea ───────────────────────────────────────────────────────

resource "keycloak_openid_client" "gitea" {
  realm_id  = keycloak_realm.enterprise.id
  client_id = "gitea"
  name      = "Gitea (OIDC SP)"

  access_type              = "CONFIDENTIAL"
  standard_flow_enabled    = true
  direct_access_grants_enabled = false
  client_secret            = var.gitea_client_secret
  pkce_code_challenge_method = "S256"

  valid_redirect_uris = ["https://gitea.iam-lab.local:3444/user/oauth2/keycloak/callback"]
  web_origins         = ["https://gitea.iam-lab.local:3444"]

  extra_config = {
    "post.logout.redirect.uris" = "https://gitea.iam-lab.local:3444/*"
  }
}

resource "keycloak_openid_user_realm_role_protocol_mapper" "gitea_roles" {
  realm_id  = keycloak_realm.enterprise.id
  client_id = keycloak_openid_client.gitea.id
  name      = "realm-roles"

  claim_name = "roles"
  multivalued = true
  add_to_access_token = true
}

# ── SAML Client: Nextcloud ────────────────────────────────────────────────────

resource "keycloak_saml_client" "nextcloud" {
  realm_id  = keycloak_realm.enterprise.id
  client_id = "https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/metadata"
  name      = "Nextcloud (SAML SP)"
  enabled   = true

  sign_documents          = true
  sign_assertions         = false
  signature_algorithm     = "RSA_SHA256"
  include_authn_statement = true
  force_post_binding      = true
  front_channel_logout    = true
  full_scope_allowed      = true

  valid_redirect_uris = ["https://nextcloud.iam-lab.local:8444/*"]

  assertion_consumer_post_url = "https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/acs"
  logout_service_post_binding_url = "https://nextcloud.iam-lab.local:8444/apps/user_saml/saml/sls"

  extra_config = {
    "saml.assertion.lifespan"           = "300"
    "saml_idp_initiated_sso_url_name"   = "nextcloud"
  }
}
