#!/usr/bin/env python3
"""
Single source of truth for hostnames, derived from event.yml's `domain:` block.

    tools/domains.py            # print the derived env (NOCO_* = ...)
    tools/domains.py --env      # write deploy/domains.env
    tools/domains.py --check    # fail if deploy/domains.env is stale (CI)
    tools/domains.py --print    # human-readable summary

Importable:  from domains import derive  ->  dict of hostnames.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVENT = ROOT / "event.yml"
ENVFILE = ROOT / "deploy" / "domains.env"


def derive(event_path: Path = EVENT) -> dict[str, str]:
    ev = yaml.safe_load(event_path.read_text()) or {}
    d = ev.get("domain") or {}
    base = d.get("base")
    if not base:
        sys.exit("domains: event.yml is missing domain.base")
    sub_score = d.get("scoreboard", "ctf")
    sub_chal = d.get("challenges", "chal")
    challenge_base = f"{sub_chal}.{base}"
    return {
        "NOCO_APEX": base,
        "NOCO_SCOREBOARD_HOST": f"{sub_score}.{base}",
        "NOCO_CHALLENGE_BASE": challenge_base,          # web chals: <sub>.<this>
        "NOCO_WILDCARD": f"*.{challenge_base}",
        "NOCO_PIN_HOST": f"up.{challenge_base}",          # cert-pin / health router
        "NOCO_ACME_EMAIL": d.get("acme_email", ""),
        "NOCO_DNS_PROVIDER": d.get("dns_provider", "digitalocean"),
        "NOCO_SCOREBOARD_URL": f"https://{sub_score}.{base}",
    }


def render_env(values: dict[str, str]) -> str:
    lines = ["# GENERATED from event.yml by tools/domains.py - do not edit.",
             "# Consumed by the Traefik edge config, the Caddy scoreboard, and make sync."]
    lines += [f"{k}={v}" for k, v in values.items()]
    return "\n".join(lines) + "\n"


def main() -> int:
    values = derive()
    if "--print" in sys.argv:
        for k, v in values.items():
            print(f"  {k:22} {v}")
        return 0
    rendered = render_env(values)
    if "--check" in sys.argv:
        current = ENVFILE.read_text() if ENVFILE.is_file() else ""
        if current != rendered:
            print("domains: deploy/domains.env is stale - run: make domains")
            return 1
        print("domains: up to date")
        return 0
    if "--env" in sys.argv:
        ENVFILE.parent.mkdir(parents=True, exist_ok=True)
        ENVFILE.write_text(rendered)
        print(f"domains: wrote {ENVFILE.relative_to(ROOT)}")
        return 0
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
