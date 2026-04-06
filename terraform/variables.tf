# ══════════════════════════════════════════════════════════════════════════════
# Terraform Variables — Keycloak IAM Configuration
# ══════════════════════════════════════════════════════════════════════════════
# Override via terraform.tfvars, environment variables (TF_VAR_*), or CLI flags.

variable "keycloak_url" {
  description = "Keycloak base URL"
  type        = string
  default     = "https://keycloak.iam-lab.local:8443"
}

variable "keycloak_admin_user" {
  description = "Keycloak admin username"
  type        = string
  default     = "admin"
}

variable "keycloak_admin_password" {
  description = "Keycloak admin password"
  type        = string
  sensitive   = true
}

variable "realm_name" {
  description = "Keycloak realm name"
  type        = string
  default     = "enterprise"
}

variable "ldap_connection_url" {
  description = "LDAP server URL"
  type        = string
  default     = "ldap://openldap:389"
}

variable "ldap_bind_dn" {
  description = "LDAP bind DN for Keycloak federation"
  type        = string
  default     = "cn=readonly,dc=rbclab,dc=local"
}

variable "ldap_bind_credential" {
  description = "LDAP bind password"
  type        = string
  sensitive   = true
}

variable "ldap_users_dn" {
  description = "LDAP base DN for user search"
  type        = string
  default     = "ou=users,dc=rbclab,dc=local"
}

variable "ldap_groups_dn" {
  description = "LDAP base DN for group search"
  type        = string
  default     = "ou=groups,dc=rbclab,dc=local"
}

variable "grafana_client_secret" {
  description = "Grafana OIDC client secret"
  type        = string
  sensitive   = true
}

variable "gitea_client_secret" {
  description = "Gitea OIDC client secret"
  type        = string
  sensitive   = true
}
