#!/usr/bin/env python3
"""
Initialise a fresh CTFd instance and mint an admin API token.

This is a convenience for local development and first-time setup - it drives the
one-time `/setup` wizard over HTTP and then creates an access token you can feed
to `make sync`. It is a no-op guard, not a reset: if the instance is already set
up it will say so and exit without touching anything.

    tools/ctfd-bootstrap.py --dev
    tools/ctfd-bootstrap.py --url https://ctf.nocohackers.com

On success it prints one line to stdout: the access token (ctfd_...). Everything
else goes to stderr, so you can capture it:

    TOKEN=$(tools/ctfd-bootstrap.py --dev)
"""
from __future__ import annotations

import argparse
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("bootstrap: requires 'requests' -> pip install requests")

import yaml

NONCE_RE = re.compile(r"""['"]csrfNonce['"]\s*:\s*['"]([0-9a-f]{16,})['"]""")


def log(*a):
    print("bootstrap:", *a, file=sys.stderr)


def find_nonce(html: str) -> str | None:
    m = NONCE_RE.search(html)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="CTFd base URL")
    ap.add_argument("--dev", action="store_true",
                    help="target the local `make dev` stack (127.0.0.1, Host: ctf.localhost)")
    ap.add_argument("--admin", default="admin")
    ap.add_argument("--email", default="admin@nocohackers.com")
    ap.add_argument("--password", default=None,
                    help="admin password (dev default: 'devadmin')")
    ap.add_argument("--event", default="event.yml",
                    help="read the CTF name/description from this file")
    args = ap.parse_args()

    # Dev talks to Traefik on 127.0.0.1 with a Host header; no DNS needed.
    session = requests.Session()
    if args.dev:
        base = args.url or "http://127.0.0.1"
        session.headers["Host"] = "ctf.localhost"
        password = args.password or "devadmin"
    else:
        if not args.url:
            sys.exit("bootstrap: --url is required (or use --dev)")
        base = args.url.rstrip("/")
        password = args.password
        if not password:
            sys.exit("bootstrap: --password is required for a non-dev target")

    try:
        ev = yaml.safe_load(open(args.event)) or {}
    except FileNotFoundError:
        ev = {}
    ctf_name = ev.get("name", "NoCo Hackers CTF 2026")
    ctf_desc = ev.get("description", "")
    user_mode = ev.get("mode", "users")
    if user_mode not in ("users", "teams"):
        sys.exit(f"bootstrap: event.yml mode must be 'users' or 'teams', got {user_mode!r}")

    # --- already set up? ------------------------------------------------
    r = session.get(f"{base}/setup", allow_redirects=False, timeout=15)
    if r.status_code in (301, 302) and "setup" not in r.headers.get("Location", ""):
        log("instance already set up - not touching it. Create a token in the admin UI,")
        log("or pass --password to an existing admin and use the API.")
        return 3
    if r.status_code != 200:
        log(f"unexpected status from /setup: {r.status_code}")
        return 1

    nonce = find_nonce(r.text)
    if not nonce:
        log("could not find the CSRF nonce on /setup - CTFd layout may have changed")
        return 1

    # --- run the setup wizard -------------------------------------------
    form = {
        "ctf_name": ctf_name,
        "ctf_description": ctf_desc,
        "user_mode": user_mode,
        "name": args.admin,
        "email": args.email,
        "password": password,
        "ctf_theme": "core-beta",
        "theme_color": ev.get("theme_color", ""),
        "challenge_visibility": "private",
        "account_visibility": "public",
        "score_visibility": "public",
        "registration_visibility": "public",
        "verify_emails": "false",
        "team_size": "",
        "nonce": nonce,
        "_submit": "Finish",
    }
    log(f"running setup wizard ('{ctf_name}', mode={user_mode}, admin '{args.admin}') ...")
    r = session.post(f"{base}/setup", data=form, allow_redirects=False, timeout=30)
    if r.status_code not in (200, 302):
        log(f"setup POST failed: {r.status_code}")
        return 1

    # --- mint an admin API token ----------------------------------------
    # We're logged in as admin now (session cookie). CTFd wants the nonce in a
    # CSRF header for API writes.
    page = session.get(f"{base}/settings", timeout=15)
    nonce = find_nonce(page.text) or nonce
    session.headers["CSRF-Token"] = nonce
    r = session.post(f"{base}/api/v1/tokens", json={"description": "ctfcli sync"}, timeout=15)
    if r.status_code != 200:
        log(f"token creation failed: {r.status_code} {r.text[:200]}")
        return 1
    token = r.json()["data"]["value"]
    log("done. Token printed to stdout.")
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
