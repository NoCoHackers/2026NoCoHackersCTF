#!/usr/bin/env python3
"""Print one challenge entry's deploy fields as shell assignments.

    eval "$(tools/chalmeta.py challenges/web/ghostdex)"
    eval "$(tools/chalmeta.py challenges/misc/device/challenge.uart.yml)"

A directory selects the primary entry; an explicit manifest selects that entry.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

from chalbundle import (
    BundleError,
    container_flag_var,
    host_flag_var,
    load_bundle,
    manifest_id,
)

if len(sys.argv) != 2:
    sys.exit("usage: chalmeta.py <bundle-directory|manifest.yml>")

path = Path(sys.argv[1]).resolve()
try:
    bundle = load_bundle(path.parent if path.is_file() else path)
except BundleError as exc:
    sys.exit(f"chalmeta: {exc}")

if path.is_file():
    entry_id = manifest_id(path)
    entry = next((item for item in bundle.entries if item.id == entry_id), None)
    if entry is None:
        sys.exit(f"chalmeta: {path} is not a manifest in {bundle.directory}")
else:
    entry = bundle.primary

x = bundle.x
fields = {
    "CHAL_KIND": x.get("kind", "web"),
    "CHAL_ID": entry.id,
    "CHAL_FLAG": entry.flag,
    "CHAL_FLAG_VAR": host_flag_var(bundle, entry),
    "CHAL_CONTAINER_FLAG_VAR": container_flag_var(entry),
    "CHAL_MANIFEST": entry.manifest.relative_to(bundle.directory).as_posix(),
    "CHAL_SOLVE": entry.autosolve,
    "CHAL_HPATH": x.get("healthcheck_path", "/"),
    "CHAL_TITLE": entry.data.get("name", ""),
    "CHAL_CAT": entry.data.get("category", "misc"),
    "CHAL_PORT": x.get("port") or "",
    "CHAL_SUB": x.get("subdomain") or "",
}
for key, value in fields.items():
    print(f"{key}={shlex.quote(str(value))}")
