"""
Integration tests for IAM Lab — validates end-to-end flows against a live stack.

Prerequisites:
    docker compose up -d   # stack must be running and healthy
    export KC_ADMIN_PASS=<your-admin-password>

Run:
    pytest tests/ -v --tb=short
"""

import os
import pytest
import requests

KC_BASE = os.getenv("KC_BASE_URL", "https://keycloak.iam-lab.local:8443")
KC_REALM = os.getenv("KC_REALM", "enterprise")
SIEM_URL = os.getenv("SIEM_URL", "http://localhost:5000")

# Skip all tests if KC_ADMIN_PASS is not set (prevents CI false failures)
pytestmark = pytest.mark.skipif(
    not os.getenv("KC_ADMIN_PASS"),
    reason="KC_ADMIN_PASS not set — skipping integration tests",
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Keycloak Core Health
# ══════════════════════════════════════════════════════════════════════════════

class TestKeycloakHealth:
    """Verify Keycloak is running and the enterprise realm exists."""

    def test_oidc_discovery(self, http_session):
        """OIDC discovery endpoint returns valid metadata."""
        resp = http_session.get(
            f"{KC_BASE}/realms/{KC_REALM}/.well-known/openid-configuration"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "jwks_uri" in data
        assert KC_REALM in data["issuer"]

    def test_admin_token_obtainable(self, admin_token):
        """Admin can obtain an access token."""
        assert admin_token is not None
        assert len(admin_token) > 50

    def test_realm_exists(self, http_session, admin_headers):
        """Enterprise realm is present and enabled."""
        resp = http_session.get(
            f"{KC_BASE}/admin/realms/{KC_REALM}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        realm = resp.json()
        assert realm["realm"] == KC_REALM
        assert realm["enabled"] is True


# ══���═══════════════════════════════════════════════════════════════���═══════════
# 2. Security Configuration
# ════���═══════════════════════════════════════════════���═════════════════════════

class TestSecurityConfig:
    """Verify security hardening settings are applied."""

    def test_brute_force_enabled(self, http_session, admin_headers):
        """Brute force protection is enabled on the realm."""
        resp = http_session.get(
            f"{KC_BASE}/admin/realms/{KC_REALM}",
            headers=admin_headers,
        )
        realm = resp.json()
        assert realm.get("bruteForceProtected") is True
        assert realm.get("failureFactor", 999) <= 10

    def test_password_policy_set(self, http_session, admin_headers):
        """Password policy enforces complexity requirements."""
        resp = http_session.get(
            f"{KC_BASE}/admin/realms/{KC_REALM}",
            headers=admin_headers,
        )
        realm = resp.json()
        policy = realm.get("passwordPolicy", "")
        assert "length" in policy
        assert "upperCase" in policy
        assert "digits" in policy
        assert "specialChars" in policy

    def test_events_enabled(self, http_session, admin_headers):
        """Event logging is enabled for audit trail."""
        resp = http_session.get(
            f"{KC_BASE}/admin/realms/{KC_REALM}",
            headers=admin_headers,
        )
        realm = resp.json()
        assert realm.get("eventsEnabled") is True
        assert realm.get("adminEventsEnabled") is True
        assert realm.get("adminEventsDetailsEnabled") is True


# ��═════════════════════════════════════════════════════════════════════════════
# 3. Realm Roles
# ══════════════════════════���═══════════════════════════════════════════════════

class TestRealmRoles:
    """Verify all 5 realm roles exist."""

    EXPECTED_ROLES = {"trader", "risk-analyst", "compliance-admin", "helpdesk", "iam-admin"}

    def test_all_roles_exist(self, http_session, admin_headers, admin_api):
        """All 5 business roles are defined in the realm."""
        resp = http_session.get(f"{admin_api}/roles", headers=admin_headers)
        assert resp.status_code == 200
        role_names = {r["name"] for r in resp.json()}
        assert self.EXPECTED_ROLES.issubset(role_names), (
            f"Missing roles: {self.EXPECTED_ROLES - role_names}"
        )


# ════════════════════════════��══════════════════════════════════���══════════════
# 4. OIDC Clients
# ═══════════════���══════════════════════════════════════════════════════════════

class TestOIDCClients:
    """Verify OIDC client configuration."""

    def test_grafana_client_exists(self, http_session, admin_headers, admin_api):
        """Grafana OIDC client is registered."""
        resp = http_session.get(
            f"{admin_api}/clients",
            params={"clientId": "grafana"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        clients = resp.json()
        assert len(clients) == 1
        client = clients[0]
        assert client["clientId"] == "grafana"
        assert client["protocol"] == "openid-connect"
        assert client["publicClient"] is False

    def test_gitea_client_exists(self, http_session, admin_headers, admin_api):
        """Gitea OIDC client is registered."""
        resp = http_session.get(
            f"{admin_api}/clients",
            params={"clientId": "gitea"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        clients = resp.json()
        assert len(clients) == 1
        assert clients[0]["clientId"] == "gitea"

    def test_pkce_enforced_on_grafana(self, http_session, admin_headers, admin_api):
        """PKCE S256 is enforced on Grafana client."""
        resp = http_session.get(
            f"{admin_api}/clients",
            params={"clientId": "grafana"},
            headers=admin_headers,
        )
        client = resp.json()[0]
        pkce = client.get("attributes", {}).get("pkce.code.challenge.method", "")
        assert pkce == "S256", f"Grafana PKCE is '{pkce}', expected 'S256'"

    def test_pkce_enforced_on_gitea(self, http_session, admin_headers, admin_api):
        """PKCE S256 is enforced on Gitea client."""
        resp = http_session.get(
            f"{admin_api}/clients",
            params={"clientId": "gitea"},
            headers=admin_headers,
        )
        client = resp.json()[0]
        pkce = client.get("attributes", {}).get("pkce.code.challenge.method", "")
        assert pkce == "S256", f"Gitea PKCE is '{pkce}', expected 'S256'"


# ═══════��═══════════════════���══════════════════════════════��═══════════════════
# 5. LDAP Federation
# ═══════════════════════���═════════════════════════════════���════════════════════

class TestLDAPFederation:
    """Verify LDAP users and groups are synced into Keycloak."""

    EXPECTED_USERS = {"jsmith", "alee", "mchen", "bpatel"}

    def test_ldap_users_synced(self, http_session, admin_headers, admin_api):
        """All 4 LDAP users are present in Keycloak."""
        resp = http_session.get(
            f"{admin_api}/users",
            params={"max": 100},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        usernames = {u["username"] for u in resp.json()}
        missing = self.EXPECTED_USERS - usernames
        assert not missing, f"Missing LDAP users: {missing}"

    def test_user_has_email(self, http_session, admin_headers, admin_api):
        """LDAP-synced users have email attributes."""
        resp = http_session.get(
            f"{admin_api}/users",
            params={"username": "jsmith", "exact": "true"},
            headers=admin_headers,
        )
        users = resp.json()
        assert len(users) == 1
        assert users[0].get("email") == "jsmith@rbclab.local"

    def test_groups_synced(self, http_session, admin_headers, admin_api):
        """LDAP groups are synced into Keycloak."""
        resp = http_session.get(f"{admin_api}/groups", headers=admin_headers)
        assert resp.status_code == 200
        group_names = {g["name"] for g in resp.json()}
        expected = {"traders", "risk-analysts", "compliance-admins", "helpdesk", "iam-admins"}
        missing = expected - group_names
        assert not missing, f"Missing groups: {missing}"


# ═══════════════════════════════════════════════════════════════════════��══════
# 6. Role Mapping Chain (LDAP group -> KC group -> realm role -> token claim)
# ═══════════════════════════════════════════════════��══════════════════════════

class TestRoleMappingChain:
    """Verify end-to-end role mapping from LDAP to token claims."""

    def test_jsmith_has_trader_role(self, http_session, admin_headers, admin_api):
        """jsmith (traders LDAP group) has the trader realm role."""
        resp = http_session.get(
            f"{admin_api}/users",
            params={"username": "jsmith", "exact": "true"},
            headers=admin_headers,
        )
        users = resp.json()
        assert len(users) == 1
        user_id = users[0]["id"]

        roles_resp = http_session.get(
            f"{admin_api}/users/{user_id}/role-mappings/realm",
            headers=admin_headers,
        )
        role_names = [r["name"] for r in roles_resp.json()]
        assert "trader" in role_names, f"jsmith roles: {role_names}"


# ═���════════════════════════════════════════════════════════════���═══════════════
# 7. SIEM Receiver
# ��═════════════════════════════════════════════════════════════════════════════

class TestSIEMReceiver:
    """Verify SIEM receiver is operational."""

    def test_health_endpoint(self, http_session):
        """SIEM receiver health check returns OK."""
        try:
            resp = http_session.get(f"{SIEM_URL}/health", timeout=5)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"
        except requests.ConnectionError:
            pytest.skip("SIEM receiver not reachable")

    def test_event_ingestion(self, http_session):
        """SIEM receiver accepts and processes events."""
        try:
            test_event = {
                "type": "LOGIN",
                "realmId": "enterprise",
                "clientId": "test-client",
                "userId": "test-user-id",
                "ipAddress": "127.0.0.1",
                "details": {"username": "test-user"},
            }
            resp = http_session.post(
                f"{SIEM_URL}/events",
                json=test_event,
                timeout=5,
            )
            assert resp.status_code == 200
            assert resp.json()["received"] is True
        except requests.ConnectionError:
            pytest.skip("SIEM receiver not reachable")

    def test_query_endpoint(self, http_session):
        """SIEM receiver query endpoint returns structured results."""
        try:
            resp = http_session.get(
                f"{SIEM_URL}/events/recent",
                params={"limit": 5},
                timeout=5,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data
            assert "events" in data
        except requests.ConnectionError:
            pytest.skip("SIEM receiver not reachable")


# ═════���═══════════════════════════════════════════════════════════════════��════
# 8. Service Provider Health
# ══════════════════════════════════════════════════════════════════════════════

class TestServiceProviders:
    """Verify downstream service providers are reachable."""

    def test_grafana_health(self, http_session):
        """Grafana API health check."""
        try:
            resp = http_session.get("https://grafana.iam-lab.local:3443/api/health", timeout=5)
            assert resp.status_code == 200
        except requests.ConnectionError:
            pytest.skip("Grafana not reachable")

    def test_gitea_health(self, http_session):
        """Gitea health endpoint."""
        try:
            resp = http_session.get("https://gitea.iam-lab.local:3444/api/healthz", timeout=5)
            assert resp.status_code == 200
        except requests.ConnectionError:
            pytest.skip("Gitea not reachable")

    def test_nextcloud_status(self, http_session):
        """Nextcloud status page."""
        try:
            resp = http_session.get("https://nextcloud.iam-lab.local:8444/status.php", timeout=10)
            assert resp.status_code == 200
        except requests.ConnectionError:
            pytest.skip("Nextcloud not reachable")
