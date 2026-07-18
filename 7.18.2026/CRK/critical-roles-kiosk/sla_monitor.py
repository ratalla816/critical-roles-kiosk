#!/usr/bin/env python3
"""
MCI5 Critical Roles Kiosk — SLA Monitor
Runs every hour via cron.
  - Flags New submissions >24h old (SLA breach)   → Slack alert
  - Warns on New submissions with <8h remaining   → Slack warning
"""

import json
import os
import subprocess
import logging
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
SUBMISSIONS_FILE = os.path.expanduser("~/shared/crk_submissions.json")
SLA_HOURS        = 24
WARN_HOURS       = 8    # warn when this many hours remain
LOG_FILE         = os.path.expanduser("~/critical-roles-kiosk/kiosk.log")
PYTHON           = "/home/robiatal/.local/share/mise/shims/python3"
NOTIFY           = "/home/robiatal/critical-roles-kiosk/slack_notify.py"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SLA] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────
def load():
    if not os.path.exists(SUBMISSIONS_FILE):
        return []
    with open(SUBMISSIONS_FILE, "r") as f:
        return json.load(f)

def save(data):
    with open(SUBMISSIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def notify(ntype, login, **kwargs):
    """Fire-and-forget Slack notification subprocess."""
    cmd = [PYTHON, NOTIFY, "--type", ntype, "--login", login]
    for k, v in kwargs.items():
        cmd += [f"--{k}", str(v)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info(f"Slack notify dispatched: type={ntype} login={login}")
    except Exception as e:
        log.error(f"Failed to dispatch Slack notify: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    submissions = load()
    if not submissions:
        log.info("No submissions — nothing to check.")
        return

    now_dt        = datetime.now()
    sla_deadline  = now_dt - timedelta(hours=SLA_HOURS)
    warn_deadline = now_dt - timedelta(hours=SLA_HOURS - WARN_HOURS)

    breaches  = 0
    warnings  = 0

    for s in submissions:
        if s.get("status") != "New":
            continue

        try:
            submitted_at = datetime.strptime(s["timestamp"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue

        hours_elapsed = (now_dt - submitted_at).total_seconds() / 3600
        hours_left    = SLA_HOURS - hours_elapsed

        # ── SLA BREACH ───────────────────────────────────────────────────────
        if submitted_at < sla_deadline:
            if not s.get("sla_breached"):
                hours_old = int(hours_elapsed)
                s["flag"]         = True
                s["sla_breached"] = True
                s["updated_at"]   = now()
                s["updated_by"]   = "sla_monitor"
                existing          = s.get("notes", "").strip()
                breach_note       = f"⚠️ SLA breach — {hours_old}h without action (auto-flagged {now()})"
                s["notes"]        = f"{existing}\n{breach_note}".strip() if existing else breach_note
                breaches         += 1
                log.info(f"SLA BREACH — {s.get('login')} submitted {s['timestamp']} ({hours_old}h ago)")
                notify("sla_breach",
                       login=s.get("login", "unknown"),
                       hours_old=hours_old,
                       submitted=s["timestamp"])

        # ── SLA WARNING (<8h remaining) ───────────────────────────────────────
        elif submitted_at < warn_deadline:
            if not s.get("sla_warned") and not s.get("sla_breached"):
                s["sla_warned"]  = True
                s["updated_at"]  = now()
                warnings        += 1
                hrs_left         = max(1, int(hours_left))
                log.info(f"SLA WARNING — {s.get('login')} submitted {s['timestamp']} ({hrs_left}h left)")
                notify("sla_warn",
                       login=s.get("login", "unknown"),
                       hours_left=hrs_left,
                       submitted=s["timestamp"])

    if breaches or warnings:
        save(submissions)

    log.info(f"SLA monitor complete — {breaches} breach(es), {warnings} warning(s).")

if __name__ == "__main__":
    run()
