#!/usr/bin/env python3
"""
iam_lifecycle.py — Joiner/Mover/Leaver automation via Keycloak Admin API.

Usage:
    python iam_lifecycle.py joiner  --username jdoe --email jdoe@rbclab.local --role trader
    python iam_lifecycle.py mover   --username jdoe --old-role trader --new-role risk-analyst
    python iam_lifecycle.py leaver  --username jdoe
    python iam_lifecycle.py report  --days 30
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("iam_lifecycle.log"),
    ],
)
log = logging.getLogger(__name__)

AUDIT_LOG = "iam_audit.log"
audit_handler = logging.FileHandler(AUDIT_LOG)
audit_handler.setFormatter(logging.Formatter("%(asctime)s AUDIT %(message)s"))
audit = logging.getLogger("audit")
audit.addHandler(audit_handler)
audit.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────

KC_BASE      = os.getenv("KC_BASE_URL", "https://keycloak.iam-lab.local:8443")
KC_REALM     = os.getenv("KC_REALM", "enterprise")
KC_CLIENT_ID = os.getenv("KC_CLIENT_ID", "admin-cli")
KC_USER      = os.getenv("KC_ADMIN_USER", "admin")
KC_PASS      = os.getenv("KC_ADMIN_PASS", "")

ADMIN_API = f"{KC_BASE}/admin/realms/{KC_REALM}"

VALID_ROLES = {"trader", "risk-analyst", "compliance-admin", "helpdesk", "iam-admin"}


# ── HTTP Session ──────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.verify = False  # Self-signed cert in lab — remove in prod
    return s


def get_token(session: requests.Session) -> str:
    """Obtain an admin access token from Keycloak."""
    url = f"{KC_BASE}/realms/master/protocol/openid-connect/token"
    resp = session.post(url, data={
        "grant_type": "password",
        "client_id": KC_CLIENT_ID,
        "username": KC_USER,
        "password": KC_PASS,
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    log.debug("Token obtained.")
    return token


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── User Operations ───────────────────────────────────────────────────────────

def find_user(session: requests.Session, token: str, username: str) -> Optional[dict]:
    resp = session.get(
        f"{ADMIN_API}/users",
        params={"username": username, "exact": "true"},
        headers=headers(token),
    )
    resp.raise_for_status()
    users = resp.json()
    return users[0] if users else None


def get_realm_role(session: requests.Session, token: str, role_name: str) -> dict:
    resp = session.get(f"{ADMIN_API}/roles/{role_name}", headers=headers(token))
    if resp.status_code == 404:
        raise ValueError(f"Role '{role_name}' not found in realm '{KC_REALM}'")
    resp.raise_for_status()
    return resp.json()


def assign_role(session: requests.Session, token: str, user_id: str, role: dict):
    resp = session.post(
        f"{ADMIN_API}/users/{user_id}/role-mappings/realm",
        json=[role],
        headers=headers(token),
    )
    resp.raise_for_status()


def remove_role(session: requests.Session, token: str, user_id: str, role: dict):
    resp = session.delete(
        f"{ADMIN_API}/users/{user_id}/role-mappings/realm",
        json=[role],
        headers=headers(token),
    )
    resp.raise_for_status()


def disable_user(session: requests.Session, token: str, user_id: str):
    resp = session.put(
        f"{ADMIN_API}/users/{user_id}",
        json={"enabled": False},
        headers=headers(token),
    )
    resp.raise_for_status()


def logout_sessions(session: requests.Session, token: str, user_id: str):
    resp = session.post(
        f"{ADMIN_API}/users/{user_id}/logout",
        headers=headers(token),
    )
    resp.raise_for_status()


# ── Lifecycle Actions ─────────────────────────────────────────────────────────

def joiner(session: requests.Session, token: str, args: argparse.Namespace):
    """Create account and assign initial role."""
    if args.role not in VALID_ROLES:
        log.error("Invalid role '%s'. Valid: %s", args.role, VALID_ROLES)
        sys.exit(1)

    # Check for duplicate
    existing = find_user(session, token, args.username)
    if existing:
        log.error("User '%s' already exists (id=%s).", args.username, existing["id"])
        sys.exit(1)

    payload = {
        "username": args.username,
        "email": args.email,
        "firstName": args.first_name or "",
        "lastName": args.last_name or "",
        "enabled": True,
        "emailVerified": False,
        "requiredActions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
        "attributes": {
            "department": [args.department or ""],
            "created_by": ["iam_lifecycle.py"],
            "created_at": [datetime.now(timezone.utc).isoformat()],
        },
    }

    resp = session.post(f"{ADMIN_API}/users", json=payload, headers=headers(token))
    resp.raise_for_status()

    user = find_user(session, token, args.username)
    role = get_realm_role(session, token, args.role)
    assign_role(session, token, user["id"], role)

    log.info("JOINER: created user '%s' (id=%s) with role '%s'", args.username, user["id"], args.role)
    audit.info("JOINER user=%s role=%s email=%s actor=%s", args.username, args.role, args.email, KC_USER)


def mover(session: requests.Session, token: str, args: argparse.Namespace):
    """Reassign user from one role to another."""
    for role_name in (args.old_role, args.new_role):
        if role_name not in VALID_ROLES:
            log.error("Invalid role '%s'. Valid: %s", role_name, VALID_ROLES)
            sys.exit(1)

    user = find_user(session, token, args.username)
    if not user:
        log.error("User '%s' not found.", args.username)
        sys.exit(1)

    old_role = get_realm_role(session, token, args.old_role)
    new_role = get_realm_role(session, token, args.new_role)
    remove_role(session, token, user["id"], old_role)
    assign_role(session, token, user["id"], new_role)

    log.info("MOVER: user '%s' moved from '%s' to '%s'", args.username, args.old_role, args.new_role)
    audit.info("MOVER user=%s old_role=%s new_role=%s actor=%s", args.username, args.old_role, args.new_role, KC_USER)


def leaver(session: requests.Session, token: str, args: argparse.Namespace):
    """Disable account and terminate all sessions."""
    user = find_user(session, token, args.username)
    if not user:
        log.error("User '%s' not found.", args.username)
        sys.exit(1)

    logout_sessions(session, token, user["id"])
    disable_user(session, token, user["id"])

    log.info("LEAVER: user '%s' (id=%s) disabled and sessions terminated.", args.username, user["id"])
    audit.info("LEAVER user=%s user_id=%s actor=%s", args.username, user["id"], KC_USER)


def report(session: requests.Session, token: str, args: argparse.Namespace):
    """Print a summary of users and their realm roles."""
    resp = session.get(f"{ADMIN_API}/users", params={"max": 500}, headers=headers(token))
    resp.raise_for_status()
    users = resp.json()

    print(f"\n{'USERNAME':<20} {'EMAIL':<35} {'ENABLED':<8} ROLES")
    print("-" * 90)
    for u in users:
        roles_resp = session.get(
            f"{ADMIN_API}/users/{u['id']}/role-mappings/realm",
            headers=headers(token),
        )
        roles_resp.raise_for_status()
        role_names = [r["name"] for r in roles_resp.json() if not r["name"].startswith("default-")]
        print(f"{u.get('username',''):<20} {u.get('email',''):<35} {str(u.get('enabled','')):<8} {', '.join(role_names)}")
    print(f"\nTotal: {len(users)} users\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IAM Joiner/Mover/Leaver automation")
    sub = parser.add_subparsers(dest="command", required=True)

    # joiner
    p_join = sub.add_parser("joiner", help="Onboard a new user")
    p_join.add_argument("--username", required=True)
    p_join.add_argument("--email", required=True)
    p_join.add_argument("--role", required=True, choices=VALID_ROLES)
    p_join.add_argument("--first-name", dest="first_name")
    p_join.add_argument("--last-name", dest="last_name")
    p_join.add_argument("--department")

    # mover
    p_move = sub.add_parser("mover", help="Reassign user role (internal transfer)")
    p_move.add_argument("--username", required=True)
    p_move.add_argument("--old-role", required=True, dest="old_role", choices=VALID_ROLES)
    p_move.add_argument("--new-role", required=True, dest="new_role", choices=VALID_ROLES)

    # leaver
    p_leave = sub.add_parser("leaver", help="Offboard a user")
    p_leave.add_argument("--username", required=True)

    # report
    p_report = sub.add_parser("report", help="List all users and roles")
    p_report.add_argument("--days", type=int, default=30, help="Lookback window (informational)")

    args = parser.parse_args()

    if not KC_PASS:
        log.error("KC_ADMIN_PASS environment variable is not set.")
        sys.exit(1)

    session = _session()
    token = get_token(session)

    dispatch = {"joiner": joiner, "mover": mover, "leaver": leaver, "report": report}
    dispatch[args.command](session, token, args)


if __name__ == "__main__":
    main()
