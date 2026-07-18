#!/usr/bin/env python3
"""
MCI5 Critical Roles Kiosk — Slack Notifier
Sends alerts via slack_send.js which spawns the AIM-managed Slack MCP server.
No token storage needed — inherits SSB auth from the MCP process.

Usage:
  python3 slack_notify.py --type new        --login jdoe --upt 28 --roles "Smalls,Waterspider"
  python3 slack_notify.py --type sla_warn   --login jdoe --hours_left 6 --submitted "2026-07-17 10:00:00"
  python3 slack_notify.py --type sla_breach --login jdoe --hours_old 25 --submitted "2026-07-17 09:00:00"
"""

import argparse
import os
import sys
import subprocess
import logging

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CHANNEL = "C0A2SGK7PJL"
NODE          = "/home/robiatal/.local/share/mise/installs/node/22.22.3/bin/node"
SLACK_SEND    = os.path.expanduser("~/critical-roles-kiosk/slack_send.js")
LOG_FILE      = os.path.expanduser("~/critical-roles-kiosk/kiosk.log")
DASHBOARD_URL = "https://ds-critical-roles-kiosk-sdh560os--5001.us-east-2.prod.proxy.devspaces.amazon.dev/submissions"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SLACK] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Message builders ──────────────────────────────────────────────────────────

def build_new_submission(login, upt, roles_str):
    roles_list = [r.strip() for r in roles_str.split(",")] if roles_str else []
    roles_fmt  = "\n".join(f"  - {r}" for r in roles_list)
    return (
        f":ox: *New Critical Role Interest — MCI5*\n"
        f"{'━' * 28}\n"
        f"*Associate:* `{login}`\n"
        f"*UPT Balance:* {upt}\n"
        f"*Roles Requested:*\n{roles_fmt}\n\n"
        f":timer_clock: SLA: Contact within 24 hours\n"
        f":link: <{DASHBOARD_URL}|Open CRM Dashboard>"
    )

def build_sla_warning(login, hours_left, submitted):
    return (
        f":warning: *SLA Warning — Action Required Soon*\n"
        f"{'━' * 28}\n"
        f"*Associate:* `{login}`\n"
        f"*Submitted:* {submitted}\n"
        f"*Time Remaining:* :alarm_clock: *{hours_left} hour(s)* before SLA expires\n\n"
        f"Contact this associate now to stay within the 24-hour SLA.\n"
        f":link: <{DASHBOARD_URL}|Open CRM Dashboard>"
    )

def build_sla_breach(login, hours_old, submitted):
    return (
        f":rotating_light: *SLA Breach — Immediate Attention Required*\n"
        f"{'━' * 28}\n"
        f"*Associate:* `{login}`\n"
        f"*Submitted:* {submitted}\n"
        f"*Elapsed:* {hours_old} hours without action\n\n"
        f"This submission has exceeded the 24-hour contact SLA.\n"
        f":link: <{DASHBOARD_URL}|Open CRM Dashboard>"
    )

# ── Send via MCP ──────────────────────────────────────────────────────────────

def post_to_slack(text):
    """Post via slack_send.js which spawns the Slack MCP with full SSB auth."""
    try:
        result = subprocess.run(
            [NODE, SLACK_SEND, SLACK_CHANNEL, text],
            capture_output=True,
            text=True,
            timeout=35
        )
        if result.returncode == 0:
            log.info(f"Slack notification sent OK")
            return True
        else:
            log.error(f"slack_send.js failed (rc={result.returncode}): {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        log.error("slack_send.js timed out after 35s")
        return False
    except Exception as e:
        log.error(f"slack_send dispatch error: {e}")
        return False

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MCI5 Kiosk Slack Notifier")
    parser.add_argument("--type",       required=True, choices=["new", "sla_warn", "sla_breach"])
    parser.add_argument("--login",      required=True)
    parser.add_argument("--upt",        default="N/A")
    parser.add_argument("--roles",      default="")
    parser.add_argument("--hours_left", type=int, default=0)
    parser.add_argument("--hours_old",  type=int, default=0)
    parser.add_argument("--submitted",  default="")
    args = parser.parse_args()

    if   args.type == "new":
        text = build_new_submission(args.login, args.upt, args.roles)
    elif args.type == "sla_warn":
        text = build_sla_warning(args.login, args.hours_left, args.submitted)
    elif args.type == "sla_breach":
        text = build_sla_breach(args.login, args.hours_old, args.submitted)

    success = post_to_slack(text)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
