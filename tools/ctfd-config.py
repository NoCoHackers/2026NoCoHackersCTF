#!/usr/bin/env python3
"""
Push event-level CONFIG (name, description, ...) from event.yml to CTFd.

This changes settings on the running scoreboard. It does NOT touch challenges,
users, teams, submissions, or scores - it PATCHes config rows only, so it is
safe to re-run at any time, including mid-event.

    CTFCLI_ACCESS_TOKEN=... tools/ctfd-config.py --url https://ctf.nocohackers.com
    CTFCLI_ACCESS_TOKEN=... tools/ctfd-config.py --dev

Only the keys present in event.yml are sent; anything else on the instance is
left as-is. Use --dry-run to see what would change without sending it.
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("ctfd-config: requires 'requests' -> pip install requests")

import yaml

# event.yml key -> CTFd config key. Only these are managed.
KEYMAP = {
    "name": "ctf_name",
    "description": "ctf_description",
    "theme_color": "theme_color",
    "start": "start",
    "end": "end",
}


def _has_participants(base: str, headers: dict, live_mode: str | None) -> bool:
    """True if any non-admin user (or any team) exists on the instance."""
    r = requests.get(f"{base}/api/v1/users", headers=headers, timeout=15)
    if r.status_code == 200:
        if any(u.get("type") != "admin" for u in r.json().get("data", [])):
            return True
    if live_mode == "teams":
        r = requests.get(f"{base}/api/v1/teams", headers=headers, timeout=15)
        if r.status_code == 200 and r.json().get("data"):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("CTFCLI_URL"))
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--event", default="event.yml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.getenv("CTFCLI_ACCESS_TOKEN")
    if not token:
        sys.exit("ctfd-config: set CTFCLI_ACCESS_TOKEN")

    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    if args.dev:
        base = args.url or "http://127.0.0.1"
        headers["Host"] = "ctf.localhost"
    else:
        base = (args.url or "").rstrip("/")
        if not base:
            sys.exit("ctfd-config: set --url or CTFCLI_URL")

    ev = yaml.safe_load(open(args.event)) or {}
    desired = {KEYMAP[k]: v for k, v in ev.items() if k in KEYMAP and v not in (None, "")}

    # Read current values so we only report what changes.
    r = requests.get(f"{base}/api/v1/configs", headers=headers, timeout=15)
    r.raise_for_status()
    current = {c["key"]: c["value"] for c in r.json()["data"]}

    # --- user_mode: a launch-time decision, guarded --------------------------
    # It CAN be PATCHed, but flipping it after people have scored regroups or
    # orphans their scores. So we only change it on a still-empty instance and
    # refuse (loudly) once any real participant exists.
    want_mode = ev.get("mode")
    if want_mode:
        if want_mode not in ("users", "teams"):
            sys.exit(f"ctfd-config: event.yml mode must be 'users' or 'teams', got {want_mode!r}")
        live_mode = current.get("user_mode")
        if live_mode == want_mode:
            print(f"  = user_mode: {want_mode!r}  (unchanged)")
        elif _has_participants(base, headers, live_mode):
            print(f"  ! user_mode: live={live_mode!r} wanted={want_mode!r}", file=sys.stderr)
            sys.exit("ctfd-config: REFUSING to change user_mode - the instance already has "
                     "participants. Switching modes now would regroup or orphan their scores. "
                     "Set the mode before the event opens, or accept the current mode.")
        elif args.dry_run:
            print(f"  ~ user_mode: {want_mode!r}  (empty instance, would set)")
        else:
            rr = requests.patch(f"{base}/api/v1/configs", headers=headers,
                                json={"user_mode": want_mode}, timeout=15)
            if rr.status_code != 200:
                sys.exit(f"ctfd-config: user_mode PATCH failed {rr.status_code}: {rr.text[:200]}")
            print(f"  ~ user_mode: -> {want_mode!r}  (instance was empty; safe)")

    if not desired:
        print("ctfd-config: no other managed keys set in event.yml")
        return 0

    changes = {k: v for k, v in desired.items() if str(current.get(k)) != str(v)}
    for k, v in desired.items():
        mark = "~" if k in changes else "="
        print(f"  {mark} {k}: {v!r}" + ("" if k in changes else "  (unchanged)"))

    if not changes:
        print("ctfd-config: already up to date")
        return 0
    if args.dry_run:
        print(f"ctfd-config: --dry-run, would update {len(changes)} key(s)")
        return 0

    # PATCH /api/v1/configs accepts a flat {key: value} body.
    r = requests.patch(f"{base}/api/v1/configs", headers=headers, json=changes, timeout=15)
    if r.status_code != 200:
        sys.exit(f"ctfd-config: PATCH failed {r.status_code}: {r.text[:200]}")
    print(f"ctfd-config: updated {len(changes)} key(s) - users and scores untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
