#!/usr/bin/env python3
"""Write challenges/names.lock: stable entry identity -> published CTFd name.

Primary entries retain their historic directory key. Supplemental entries use
``<directory>#<id>`` so adding bundle support does not churn existing locks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from chalbundle import discover_bundles, lock_key

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "challenges" / "names.lock"


def current() -> dict[str, str]:
    out = {}
    for bundle in discover_bundles(ROOT / "challenges"):
        if bundle.directory.name == "TEMPLATE":
            continue
        for entry in bundle.entries:
            if entry.data.get("name"):
                out[lock_key(bundle, entry)] = entry.data["name"]
    return out


def load_lock() -> dict[str, str]:
    if not LOCK.is_file():
        return {}
    return json.loads(LOCK.read_text())


def main() -> int:
    cur = current()
    if "--check" in sys.argv:
        if load_lock() == cur:
            print("lock-names: up to date")
            return 0
        print("lock-names: names.lock is stale - run tools/lock-names.py")
        return 1
    LOCK.write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n")
    print(f"lock-names: wrote {LOCK.relative_to(ROOT)} ({len(cur)} challenges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
