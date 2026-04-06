#!/usr/bin/env python3
"""
jit_access.py — Just-In-Time Privileged Access Management

Grants a user a privileged role for a limited time window, then automatically
revokes it. Mirrors PAM patterns used in CyberArk/BeyondTrust for break-glass
and time-limited elevation requests.

Usage:
    # Grant iam-admin to bpatel for 2 hours (approval required in prod)
    python3 jit_access.py elevate \\
        --username bpatel \\
        --role iam-admin \\
        --duration 120 \\
        --reason "P1-incident: SSO outage - INC0001234"

    # Revoke immediately (before expiry)
    python3 jit_access.py revoke --username bpatel --role iam-admin

    # List active JIT grants
    python3 jit_access.py list

    # Expire all grants whose window has passed (run as cron)
    python3 jit_access.py expire

Audit log: iam_audit.log (same as iam_lifecycle.py)
State file: .jit_grants.json (tracks active grants with expiry timestamps)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Logging ───────────────────────────────────────────────────────���──────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
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
KC_USER      = os.getenv("KC_ADMIN_USER", "iam-superadmin")
KC_PASS      = os.getenv("KC_ADMIN_PASS", "")

ADMIN_API = f"{KC_BASE}/admin/realms/{KC_REALM}"

# Roles that require JIT elevation (cannot be held permanently by standard users)
PRIVILEGED_ROLES = {"iam-admin", "compliance-admin"}

# State file tracks active grants with expiry
GRANTS_FILE = Path(os.getenv("JIT_GRANTS_FILE", ".jit_grants.json"))

MAX_DURATION_MINUTES = 480  # 8 hours hard cap


# ── HTTP Session ──────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.verify = False
    return s


def get_token(session: requests.Session) -> str:
    url = f"{KC_BASE}/realms/master/protocol/openid-connect/token"
    resp = session.post(url, data={
        "grant_type": "password",
        "client_id": KC_CLIENT_ID,
        "username": KC_USER,
        "password": KC_PASS,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── User / Role Helpers ───────────────────────────────────────────────────────

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


def get_user_roles(session: requests.Session, token: str, user_id: str) -> list:
    resp = session.get(
        f"{ADMIN_API}/users/{user_id}/role-mappings/realm",
        headers=headers(token),
    )
    resp.raise_for_status()
    return [r["name"] for r in resp.json() if not r["name"].startswith("default-")]


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


# ── Grant State ───────────────────────────────────────────────────────────────

def load_grants() -> list:
    if not GRANTS_FILE.exists():
        return []
    try:
        return json.loads(GRANTS_FILE.read_text())
    except (json.JSONDecodeError, IOError):
        return []


def save_grants(grants: list):
    GRANTS_FILE.write_text(json.dumps(grants, indent=2))


def find_grant(grants: list, username: str, role: str) -> Optional[dict]:
    for g in grants:
        if g["username"] == username and g["role"] == role and g["active"]:
            return g
    return None


# ── JIT Actions ───────────────────────────────────────────────────────────────

def elevate(session: requests.Session, token: str, args: argparse.Namespace):
    """Grant a privileged role for a limited time window."""
    if args.duration > MAX_DURATION_MINUTES:
        log.error("Duration %d exceeds max allowed %d minutes.", args.duration, MAX_DURATION_MINUTES)
        sys.exit(1)

    user = find_user(session, token, args.username)
    if not user:
        log.error("User '%s' not found.", args.username)
        sys.exit(1)

    current_roles = get_user_roles(session, token, user["id"])
    if args.role in current_roles:
        log.error("User '%s' already has role '%s'. No JIT grant needed.", args.username, args.role)
        sys.exit(1)

    grants = load_grants()
    existing = find_grant(grants, args.username, args.role)
    if existing:
        log.error(
            "Active JIT grant already exists for %s → %s (expires %s).",
            args.username, args.role, existing["expires_at"],
        )
        sys.exit(1)

    # Grant role
    role_obj = get_realm_role(session, token, args.role)
    assign_role(session, token, user["id"], role_obj)

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=args.duration)

    grant = {
        "username": args.username,
        "user_id": user["id"],
        "role": args.role,
        "granted_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "duration_minutes": args.duration,
        "reason": args.reason,
        "granted_by": KC_USER,
        "active": True,
    }
    grants.append(grant)
    save_grants(grants)

    log.info(
        "JIT ELEVATE: %s granted role '%s' for %d min (expires %s). Reason: %s",
        args.username, args.role, args.duration,
        expires.strftime("%Y-%m-%d %H:%M UTC"), args.reason,
    )
    audit.info(
        "JIT_ELEVATE user=%s role=%s duration_min=%d expires=%s reason=%s actor=%s",
        args.username, args.role, args.duration,
        expires.isoformat(), args.reason, KC_USER,
    )

    print(f"\n  Elevation granted:")
    print(f"    User     : {args.username}")
    print(f"    Role     : {args.role}")
    print(f"    Expires  : {expires.strftime('%Y-%m-%d %H:%M UTC')} ({args.duration} min)")
    print(f"    Reason   : {args.reason}")
    print(f"\n  Run 'jit_access.py expire' or schedule it to auto-revoke at expiry.\n")


def revoke(session: requests.Session, token: str, args: argparse.Namespace):
    """Immediately revoke a JIT grant."""
    grants = load_grants()
    grant = find_grant(grants, args.username, args.role)

    if not grant:
        log.error("No active JIT grant found for %s → %s.", args.username, args.role)
        sys.exit(1)

    user = find_user(session, token, args.username)
    if not user:
        log.error("User '%s' not found in Keycloak.", args.username)
        sys.exit(1)

    role_obj = get_realm_role(session, token, args.role)
    remove_role(session, token, user["id"], role_obj)

    grant["active"] = False
    grant["revoked_at"] = datetime.now(timezone.utc).isoformat()
    grant["revoked_by"] = KC_USER
    save_grants(grants)

    log.info("JIT REVOKE: '%s' role '%s' revoked immediately by %s.", args.username, args.role, KC_USER)
    audit.info(
        "JIT_REVOKE user=%s role=%s reason=manual actor=%s",
        args.username, args.role, KC_USER,
    )
    print(f"\n  Role '{args.role}' revoked from '{args.username}'.\n")


def expire(session: requests.Session, token: str, args: argparse.Namespace):
    """Revoke all grants whose expiry time has passed. Run as cron job."""
    grants = load_grants()
    now = datetime.now(timezone.utc)
    expired_count = 0

    for grant in grants:
        if not grant["active"]:
            continue
        expires_at = datetime.fromisoformat(grant["expires_at"])
        if now >= expires_at:
            # Revoke
            user = find_user(session, token, grant["username"])
            if user:
                try:
                    role_obj = get_realm_role(session, token, grant["role"])
                    remove_role(session, token, user["id"], role_obj)
                    log.info(
                        "JIT EXPIRE: '%s' role '%s' auto-revoked (expired %s).",
                        grant["username"], grant["role"],
                        expires_at.strftime("%Y-%m-%d %H:%M UTC"),
                    )
                    audit.info(
                        "JIT_EXPIRE user=%s role=%s granted_at=%s expires_at=%s actor=system",
                        grant["username"], grant["role"],
                        grant["granted_at"], grant["expires_at"],
                    )
                    expired_count += 1
                except Exception as e:
                    log.warning("Failed to revoke %s → %s: %s", grant["username"], grant["role"], e)
            grant["active"] = False
            grant["revoked_at"] = now.isoformat()
            grant["revoked_by"] = "system (expiry)"

    save_grants(grants)

    if expired_count:
        log.info("JIT expire run: %d grant(s) revoked.", expired_count)
    else:
        log.info("JIT expire run: no grants expired.")


def list_grants(session: requests.Session, token: str, args: argparse.Namespace):
    """List all active JIT grants with time remaining."""
    grants = load_grants()
    now = datetime.now(timezone.utc)
    active = [g for g in grants if g["active"]]

    if not active:
        print("\n  No active JIT grants.\n")
        return

    print(f"\n{'='*80}")
    print(f"  Active JIT Grants — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*80}")
    print(f"{'USERNAME':<16} {'ROLE':<20} {'EXPIRES':<22} {'REMAINING':<12} REASON")
    print("-" * 80)

    for g in active:
        expires_at = datetime.fromisoformat(g["expires_at"])
        remaining = expires_at - now
        if remaining.total_seconds() < 0:
            remaining_str = "EXPIRED"
        else:
            h, m = divmod(int(remaining.total_seconds()) // 60, 60)
            remaining_str = f"{h}h {m}m"
        print(
            f"{g['username']:<16} {g['role']:<20} "
            f"{expires_at.strftime('%Y-%m-%d %H:%M UTC'):<22} "
            f"{remaining_str:<12} {g.get('reason','')[:40]}"
        )

    print(f"\n  Total active: {len(active)}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="JIT Privileged Access — time-limited role elevation with auto-revoke"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # elevate
    p_el = sub.add_parser("elevate", help="Grant a privileged role for a limited time window")
    p_el.add_argument("--username", required=True)
    p_el.add_argument("--role", required=True)
    p_el.add_argument("--duration", type=int, default=60, help="Minutes (default 60, max 480)")
    p_el.add_argument("--reason", required=True, help="Business justification / incident reference")

    # revoke
    p_rev = sub.add_parser("revoke", help="Immediately revoke a JIT grant")
    p_rev.add_argument("--username", required=True)
    p_rev.add_argument("--role", required=True)

    # expire
    sub.add_parser("expire", help="Auto-revoke all expired grants (run as cron)")

    # list
    sub.add_parser("list", help="Show all active JIT grants")

    args = parser.parse_args()

    if not KC_PASS:
        log.error("KC_ADMIN_PASS environment variable not set.")
        sys.exit(1)

    session = _session()
    token = get_token(session)

    dispatch = {
        "elevate": elevate,
        "revoke": revoke,
        "expire": expire,
        "list": list_grants,
    }
    dispatch[args.command](session, token, args)


if __name__ == "__main__":
    main()
