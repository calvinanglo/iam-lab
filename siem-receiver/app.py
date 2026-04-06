#!/usr/bin/env python3
"""
siem_receiver.py — Mock SIEM event receiver for Keycloak HTTP event listener.

Receives Keycloak audit events via HTTP POST, normalises them to a
structured log format mirroring what a real SIEM (Splunk, Sentinel, QRadar)
would ingest. Demonstrates the Keycloak → SIEM integration pattern used in
production IAM deployments.

Keycloak Admin → Events → Event listeners → http event listener
  URL: http://siem-receiver:5000/events
  Content-Type: application/json

Event types handled:
  LOGIN, LOGIN_ERROR, LOGOUT
  REGISTER, UPDATE_PASSWORD
  CLIENT_LOGIN, CLIENT_LOGIN_ERROR
  ADMIN events (CREATE/UPDATE/DELETE on users, clients, roles)
"""

import json
import logging
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Logging: structured JSON to stdout (Loki-scrape-friendly) ─────────────────

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "source": "siem-receiver",
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            log_entry["event"] = record.event
        return json.dumps(log_entry)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
log = logging.getLogger("siem")
log.addHandler(handler)
log.setLevel(logging.INFO)

# Also write to an audit file for persistence
AUDIT_FILE = os.getenv("SIEM_AUDIT_FILE", "/var/log/siem/keycloak-events.jsonl")

def write_audit(event: dict):
    try:
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        log.warning("Failed to write audit file: %s", e)


# ── Event normalisation ───────────────────────────────────────────────────────

SEVERITY_MAP = {
    "LOGIN": "INFO",
    "LOGIN_ERROR": "HIGH",
    "LOGOUT": "LOW",
    "REGISTER": "MEDIUM",
    "UPDATE_PASSWORD": "MEDIUM",
    "RESET_PASSWORD": "MEDIUM",
    "UPDATE_PROFILE": "LOW",
    "SEND_VERIFY_EMAIL": "LOW",
    "VERIFY_EMAIL": "LOW",
    "REMOVE_TOTP": "HIGH",
    "UPDATE_TOTP": "MEDIUM",
    "GRANT_CONSENT": "LOW",
    "CLIENT_LOGIN": "INFO",
    "CLIENT_LOGIN_ERROR": "HIGH",
    "CODE_TO_TOKEN": "INFO",
    "CODE_TO_TOKEN_ERROR": "HIGH",
    "REFRESH_TOKEN": "INFO",
    "REFRESH_TOKEN_ERROR": "MEDIUM",
    "INTROSPECT_TOKEN": "LOW",
    "FEDERATED_IDENTITY_LINK": "MEDIUM",
}

ADMIN_SEVERITY_MAP = {
    "CREATE": "MEDIUM",
    "UPDATE": "MEDIUM",
    "DELETE": "HIGH",
    "ACTION": "MEDIUM",
}

ALERT_TYPES = {
    "LOGIN_ERROR",
    "CLIENT_LOGIN_ERROR",
    "CODE_TO_TOKEN_ERROR",
    "REMOVE_TOTP",
}


def normalise_user_event(raw: dict) -> dict:
    event_type = raw.get("type", "UNKNOWN")
    details = raw.get("details", {})

    normalised = {
        "siem_timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": raw.get("id", ""),
        "event_type": event_type,
        "severity": SEVERITY_MAP.get(event_type, "LOW"),
        "realm": raw.get("realmId", ""),
        "client_id": raw.get("clientId", ""),
        "user_id": raw.get("userId", ""),
        "username": details.get("username", raw.get("userId", "")),
        "ip_address": raw.get("ipAddress", ""),
        "session_id": raw.get("sessionId", ""),
        "error": details.get("error", ""),
        "redirect_uri": details.get("redirect_uri", ""),
        "alert": event_type in ALERT_TYPES,
        "source_system": "keycloak",
        "log_type": "authentication",
    }
    return normalised


def normalise_admin_event(raw: dict) -> dict:
    operation = raw.get("operationType", "UNKNOWN")
    resource_type = raw.get("resourceType", "UNKNOWN")

    normalised = {
        "siem_timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": raw.get("id", ""),
        "event_type": f"ADMIN_{operation}_{resource_type}",
        "severity": ADMIN_SEVERITY_MAP.get(operation, "MEDIUM"),
        "realm": raw.get("realmId", ""),
        "operation": operation,
        "resource_type": resource_type,
        "resource_path": raw.get("resourcePath", ""),
        "actor_id": raw.get("authDetails", {}).get("userId", ""),
        "actor_username": raw.get("authDetails", {}).get("username", ""),
        "actor_ip": raw.get("authDetails", {}).get("ipAddress", ""),
        "representation": raw.get("representation", "")[:500],  # cap size
        "alert": operation == "DELETE",
        "source_system": "keycloak",
        "log_type": "admin_audit",
    }
    return normalised


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "siem-receiver"}), 200


@app.route("/events", methods=["POST"])
def receive_event():
    """Receive Keycloak user auth events."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    raw = request.get_json(force=True, silent=True) or {}
    normalised = normalise_user_event(raw)

    severity_icon = {"HIGH": "!!!!", "MEDIUM": "!!", "INFO": "  ", "LOW": "  "}.get(
        normalised["severity"], ""
    )

    log_msg = (
        f"{severity_icon} [{normalised['severity']}] "
        f"{normalised['event_type']} "
        f"user={normalised['username'] or normalised['user_id']} "
        f"client={normalised['client_id']} "
        f"ip={normalised['ip_address']}"
        + (f" error={normalised['error']}" if normalised.get("error") else "")
    )

    extra = {"event": normalised}
    if normalised["alert"]:
        log.warning(log_msg, extra=extra)
    else:
        log.info(log_msg, extra=extra)

    write_audit(normalised)
    return jsonify({"received": True, "event_type": normalised["event_type"]}), 200


@app.route("/admin-events", methods=["POST"])
def receive_admin_event():
    """Receive Keycloak admin audit events."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    raw = request.get_json(force=True, silent=True) or {}
    normalised = normalise_admin_event(raw)

    log_msg = (
        f"{'!!!!' if normalised['alert'] else '  '} [ADMIN/{normalised['severity']}] "
        f"{normalised['operation']} {normalised['resource_type']} "
        f"path={normalised['resource_path']} "
        f"actor={normalised['actor_username']} "
        f"ip={normalised['actor_ip']}"
    )

    extra = {"event": normalised}
    if normalised["alert"]:
        log.warning(log_msg, extra=extra)
    else:
        log.info(log_msg, extra=extra)

    write_audit(normalised)
    return jsonify({"received": True, "event_type": normalised["event_type"]}), 200


@app.route("/events/recent", methods=["GET"])
def recent_events():
    """Return the last N events from the audit file (simple SIEM query endpoint)."""
    n = int(request.args.get("limit", 20))
    event_type = request.args.get("type", "")
    severity = request.args.get("severity", "")

    events = []
    try:
        with open(AUDIT_FILE) as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass

    # Filter
    if event_type:
        events = [e for e in events if e.get("event_type", "").startswith(event_type.upper())]
    if severity:
        events = [e for e in events if e.get("severity") == severity.upper()]

    return jsonify({
        "total": len(events),
        "events": events[-n:],
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("SIEM_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
