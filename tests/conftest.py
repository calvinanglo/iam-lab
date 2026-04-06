"""
Shared fixtures for IAM Lab integration tests.

These tests run against a live stack (docker compose up -d).
Set KC_ADMIN_PASS environment variable before running.
"""

import os
import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


KC_BASE = os.getenv("KC_BASE_URL", "https://keycloak.iam-lab.local:8443")
KC_REALM = os.getenv("KC_REALM", "enterprise")
KC_ADMIN_USER = os.getenv("KC_ADMIN_USER", "admin")
KC_ADMIN_PASS = os.getenv("KC_ADMIN_PASS", "")
SIEM_URL = os.getenv("SIEM_URL", "http://localhost:5000")


@pytest.fixture(scope="session")
def http_session():
    """Requests session with retry logic and TLS verification disabled (self-signed)."""
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.verify = False
    return s


@pytest.fixture(scope="session")
def admin_token(http_session):
    """Obtain Keycloak admin access token."""
    resp = http_session.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": KC_ADMIN_USER,
            "password": KC_ADMIN_PASS,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """Authorization headers for Keycloak Admin API."""
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin_api():
    """Keycloak Admin API base URL for the enterprise realm."""
    return f"{KC_BASE}/admin/realms/{KC_REALM}"
