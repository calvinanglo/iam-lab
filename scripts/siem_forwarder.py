#!/usr/bin/env python3
"""
siem_forwarder.py — Keycloak → SIEM event forwarder (pull model).

Polls the Keycloak Admin API event store at a configurable interval and
forwards new events to the SIEM receiver. This mirrors the connector
architecture used by commercial SIEM integrations (Splunk TA for Keycloak,
Microsoft Sentinel Keycloak connector).

Why pull vs push:
  - No Keycloak extension required; works with any KC version
  - State (last seen event time) is maintained locally
  - Tolerates SIEM receiver downtime; events accumulate in KC store

Usage:
    python3 siem_forwarder.py          # runs continuously, polls every 30s
    python3 siem_forwarder.py --once   # single run, then exit (cron mode)

Environment:
    KC_BASE_URL       Keycloak base URL (default: https://keycloak.iam-lab.local:8443)
    KC_ADMIN_USER     Admin username
    KC_ADMIN_PASS     Admin password
    SIEM_URL          SIEM receiver URL (default: http://siem-receiver:5000)
    POLL_INTERVAL     Seconds between polls (default: 30)
    STATE_FILE        Last-seen timestamp state file (default: .siem_state.json)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Config ────────────────────────────────────────────────────────────────────

KC_BASE      = os.getenv("KC_BASE_URL", "https://keycloak.iam-lab.local:8443")
KC_REALM     = os.getenv("KC_REALM", "enterprise")
KC_USER      = os.getenv("KC_ADMIN_USER", "iam-superadmin")
KC_PASS      = os.getenv("KC_ADMIN_PASS", "")
SIEM_URL     = os.getenv("SIEM_URL", "http://siem-receiver:5000")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
STATE_FILE   = Path(os.getenv("STATE_FILE", ".siem_state.json"))

ADMIN_API = f"{KC_BASE}/admin/realms/{KC_REALM}"

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("siem-forwarder")

# ── HTTP Clients ──────────────────────────────────────────────────────────────

def _kc_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.verify = False
    return s


def _siem_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def get_token(session: requests.Session) -> str:
    url = f"{KC_BASE}/realms/master/protocol/openid-connect/token"
    resp = session.post(url, data={
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": KC_USER,
        "password": KC_PASS,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def kc_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── State management ──────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_event_time": 0, "last_admin_event_time": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Event fetching ────────────────────────────────────────────────────────────

def fetch_auth_events(session: requests.Session, token: str, since_ts: int) -> list:
    """Fetch auth events newer than since_ts (milliseconds)."""
    params = {
        "max": 100,
        "type": "LOGIN,LOGIN_ERROR,LOGOUT,REGISTER,UPDATE_PASSWORD,REMOVE_TOTP,UPDATE_TOTP",
    }
    if since_ts > 0:
        # KC dateFrom is in milliseconds
        params["dateFrom"] = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )

    resp = session.get(f"{ADMIN_API}/events", params=params, headers=kc_headers(token))
    resp.raise_for_status()
    events = resp.json()

    # Filter precisely by timestamp (dateFrom is day-level only)
    return [e for e in events if e.get("time", 0) > since_ts]


def fetch_admin_events(session: requests.Session, token: str, since_ts: int) -> list:
    """Fetch admin events newer than since_ts."""
    params = {"max": 100}
    if since_ts > 0:
        params["dateFrom"] = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )

    resp = session.get(f"{ADMIN_API}/admin-events", params=params, headers=kc_headers(token))
    resp.raise_for_status()
    events = resp.json()
    return [e for e in events if e.get("time", 0) > since_ts]


# ── Forwarding ────────────────────────────────────────────────────────────────

def forward_events(siem: requests.Session, events: list, endpoint: str) -> int:
    """Forward events to SIEM receiver. Returns count of successfully forwarded."""
    forwarded = 0
    for event in events:
        try:
            resp = siem.post(
                f"{SIEM_URL}{endpoint}",
                json=event,
                timeout=5,
            )
            if resp.ok:
                forwarded += 1
            else:
                log.warning("SIEM rejected event: HTTP %d", resp.status_code)
        except requests.RequestException as e:
            log.warning("Failed to forward event to SIEM: %s", e)
    return forwarded


# ── Poll loop ─────────────────────────────────────────────────────────────────

def poll_once(kc: requests.Session, siem: requests.Session, state: dict) -> dict:
    try:
        token = get_token(kc)
    except Exception as e:
        log.error("Failed to get Keycloak token: %s", e)
        return state

    # Auth events
    try:
        auth_events = fetch_auth_events(kc, token, state["last_event_time"])
        if auth_events:
            count = forward_events(siem, auth_events, "/events")
            new_max = max(e.get("time", 0) for e in auth_events)
            state["last_event_time"] = new_max
            log.info("Auth events: fetched=%d forwarded=%d", len(auth_events), count)
        else:
            log.debug("Auth events: none new")
    except Exception as e:
        log.error("Error fetching auth events: %s", e)

    # Admin events
    try:
        admin_events = fetch_admin_events(kc, token, state["last_admin_event_time"])
        if admin_events:
            count = forward_events(siem, admin_events, "/admin-events")
            new_max = max(e.get("time", 0) for e in admin_events)
            state["last_admin_event_time"] = new_max
            log.info("Admin events: fetched=%d forwarded=%d", len(admin_events), count)
        else:
            log.debug("Admin events: none new")
    except Exception as e:
        log.error("Error fetching admin events: %s", e)

    save_state(state)
    return state


def main():
    once = "--once" in sys.argv

    if not KC_PASS:
        log.error("KC_ADMIN_PASS not set.")
        sys.exit(1)

    log.info("SIEM forwarder starting. KC=%s SIEM=%s interval=%ds", KC_BASE, SIEM_URL, POLL_INTERVAL)

    kc = _kc_session()
    siem = _siem_session()
    state = load_state()

    if once:
        poll_once(kc, siem, state)
        return

    while True:
        state = poll_once(kc, siem, state)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
