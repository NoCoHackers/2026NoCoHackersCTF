#!/usr/bin/env python3
"""Print a challenge's deploy fields as shell assignments.

    eval "$(tools/chalmeta.py challenges/web/haunted-brewery)"

Keeps shell scripts out of the business of parsing YAML.
"""
import shlex
import sys

import yaml

path = sys.argv[1].rstrip("/")
d = yaml.safe_load(open(f"{path}/challenge.yml")) or {}
x = d.get("x-noco") or {}

fields = {
    "CHAL_KIND": x.get("kind", "web"),
    "CHAL_FLAG": (d.get("flags") or [""])[0],
    "CHAL_SOLVE": x.get("autosolve", "solution/solve.sh"),
    "CHAL_HPATH": x.get("healthcheck_path", "/"),
    "CHAL_TITLE": d.get("name", ""),
    "CHAL_CAT": d.get("category", "misc"),
    "CHAL_PORT": x.get("port") or "",
    "CHAL_SUB": x.get("subdomain") or "",
}
for key, value in fields.items():
    print(f"{key}={shlex.quote(str(value))}")
