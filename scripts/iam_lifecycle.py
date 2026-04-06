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

KC_BASE = os.getenv("KC_BASE_URL", "https://keycloak.iam-lab.local:8443")
KC_REALM = os.getenv("KC_REALM", "enterprise")
KC_CLIENT_ID = os.getenv("KC_CLIENT_ID", "admin-cli")
KC_USER = os.getenv("KC_ADMIN_USER", "admin")
KC_PASS = os.getenv("KC_ADMIN_PASS", "")

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


def certify(session: requests.Session, token: str, args: argparse.Namespace):
    """
    Access certification report — ISO 27001 / SOX access review.

    Outputs a structured table of all users with their roles, account status,
    and last login timestamp. Flags:
      INACTIVE  — enabled account with no login in >N days
      ORPHANED  — enabled account with no realm roles assigned
      DISABLED  — account disabled (offboarded)
    """
    lookback_days = args.days
    cutoff = datetime.now(timezone.utc).timestamp() - (lookback_days * 86400)

    resp = session.get(f"{ADMIN_API}/users", params={"max": 500}, headers=headers(token))
    resp.raise_for_status()
    users = resp.json()

    # Fetch sessions for last-login data
    active_sessions: dict = {}
    try:
        sessions_resp = session.get(
            f"{ADMIN_API}/sessions/stats",
            headers=headers(token),
        )
        if sessions_resp.ok:
            for entry in sessions_resp.json():
                active_sessions[entry.get("realm", "")] = entry
    except Exception:
        pass

    rows = []
    flags_summary: dict = {"INACTIVE": 0, "ORPHANED": 0, "DISABLED": 0, "CLEAN": 0}

    for u in users:
        user_id = u["id"]
        username = u.get("username", "")
        email = u.get("email", "")
        enabled = u.get("enabled", False)
        created_ts = u.get("createdTimestamp", 0) / 1000  # ms → s

        # Roles
        roles_resp = session.get(
            f"{ADMIN_API}/users/{user_id}/role-mappings/realm",
            headers=headers(token),
        )
        roles_resp.raise_for_status()
        role_names = [r["name"] for r in roles_resp.json() if not r["name"].startswith("default-")]

        # Last login via user sessions
        last_login_ts = None
        try:
            user_sessions_resp = session.get(
                f"{ADMIN_API}/users/{user_id}/sessions",
                headers=headers(token),
            )
            if user_sessions_resp.ok:
                user_sessions = user_sessions_resp.json()
                if user_sessions:
                    last_login_ts = max(s.get("lastAccess", 0) / 1000 for s in user_sessions)
        except Exception:
            pass

        if last_login_ts is None:
            # Fall back to offline sessions
            try:
                offline_resp = session.get(
                    f"{ADMIN_API}/users/{user_id}/offline-sessions",
                    headers=headers(token),
                )
                if offline_resp.ok and offline_resp.json():
                    last_login_ts = max(
                        s.get("lastAccess", 0) / 1000 for s in offline_resp.json()
                    )
            except Exception:
                pass

        # Determine flags
        flag = "CLEAN"
        if not enabled:
            flag = "DISABLED"
        elif not role_names:
            flag = "ORPHANED"
        elif last_login_ts is not None and last_login_ts < cutoff:
            flag = "INACTIVE"
        elif last_login_ts is None:
            flag = "INACTIVE"  # Never logged in — treat as inactive

        flags_summary[flag] += 1

        last_login_str = (
            datetime.fromtimestamp(last_login_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if last_login_ts else "never"
        )
        created_str = datetime.fromtimestamp(created_ts, tz=timezone.utc).strftime("%Y-%m-%d")

        rows.append({
            "username": username,
            "email": email,
            "enabled": enabled,
            "roles": ", ".join(role_names) if role_names else "(none)",
            "last_login": last_login_str,
            "created": created_str,
            "flag": flag,
        })

    # Sort: flagged first, then by username
    flag_order = {"ORPHANED": 0, "INACTIVE": 1, "DISABLED": 2, "CLEAN": 3}
    rows.sort(key=lambda r: (flag_order[r["flag"]], r["username"]))

    # Print report
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*100}")
    print(f"  ACCESS CERTIFICATION REPORT — Realm: {KC_REALM}")
    print(f"  Generated: {now_str}   Lookback window: {lookback_days} days   Certifier: {KC_USER}")
    print(f"{'='*100}")
    print(
        f"\n{'USERNAME':<20} {'EMAIL':<32} {'EN':<4} {'ROLES':<30} "
        f"{'LAST LOGIN':<12} {'CREATED':<12} {'FLAG'}"
    )
    print("-" * 120)

    for r in rows:
        flag_marker = "" if r["flag"] == "CLEAN" else f"  *** {r['flag']} ***"
        print(
            f"{r['username']:<20} {r['email']:<32} {str(r['enabled'])[:1]:<4} "
            f"{r['roles']:<30} {r['last_login']:<12} {r['created']:<12} {r['flag']}{flag_marker}"
        )

    print(f"\n{'─'*120}")
    print(f"  Summary: {len(rows)} total accounts")
    print(f"    CLEAN    : {flags_summary['CLEAN']}")
    print(f"    INACTIVE : {flags_summary['INACTIVE']}  (no login in >{lookback_days}d — review for removal)")
    print(f"    ORPHANED : {flags_summary['ORPHANED']}  (enabled with no roles — access gap or onboarding error)")
    print(f"    DISABLED : {flags_summary['DISABLED']}  (offboarded — confirm no active sessions or shared creds)")
    print(f"\n  Certification action required for: {flags_summary['INACTIVE'] + flags_summary['ORPHANED']} account(s)")
    print(f"{'='*100}\n")

    audit.info(
        "CERTIFY realm=%s total=%d inactive=%d orphaned=%d disabled=%d actor=%s lookback_days=%d",
        KC_REALM, len(rows), flags_summary["INACTIVE"], flags_summary["ORPHANED"],
        flags_summary["DISABLED"], KC_USER, lookback_days,
    )


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

    # certify
    p_certify = sub.add_parser("certify", help="Access certification report (ISO 27001 / SOX)")
    p_certify.add_argument(
        "--days", type=int, default=90,
        help="Flag accounts with no login in this many days as INACTIVE (default: 90)",
    )

    args = parser.parse_args()

    if not KC_PASS:
        log.error("KC_ADMIN_PASS environment variable is not set.")
        sys.exit(1)

    session = _session()
    token = get_token(session)

    dispatch = {"joiner": joiner, "mover": mover, "leaver": leaver, "report": report, "certify": certify}
    dispatch[args.command](session, token, args)


if __name__ == "__main__":
    main()
