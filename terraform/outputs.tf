output "realm_id" {
  description = "Keycloak realm ID"
  value       = keycloak_realm.enterprise.id
}

output "grafana_client_id" {
  description = "Grafana OIDC client ID"
  value       = keycloak_openid_client.grafana.client_id
}

output "gitea_client_id" {
  description = "Gitea OIDC client ID"
  value       = keycloak_openid_client.gitea.client_id
}

output "nextcloud_client_id" {
  description = "Nextcloud SAML client ID"
  value       = keycloak_saml_client.nextcloud.client_id
}

output "ldap_federation_id" {
  description = "LDAP user federation ID"
  value       = keycloak_ldap_user_federation.openldap.id
}

output "realm_roles" {
  description = "Configured realm roles"
  value = [
    keycloak_role.trader.name,
    keycloak_role.risk_analyst.name,
    keycloak_role.compliance_admin.name,
    keycloak_role.helpdesk.name,
    keycloak_role.iam_admin.name,
  ]
}
