#!/usr/bin/env python3
"""
Write challenges/names.lock: the path -> name mapping the sync relies on.

CTFd matches challenges BY NAME, so renaming a challenge that's already been
pushed creates a *second* challenge and splits its solves. The lock records the
name each challenge directory last published under; tools/validate.py warns if a
directory's current name drifts from the lock. Run this to bless an intended
rename (or a new challenge):

    tools/lock-names.py            # update the lock to match the tree
    tools/lock-names.py --check    # fail if the lock is stale (also run by validate)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "challenges" / "names.lock"


def current() -> dict[str, str]:
    out = {}
    for m in sorted((ROOT / "challenges").rglob("challenge.yml")):
        if m.parent.name == "TEMPLATE":
            continue
        rel = m.parent.relative_to(ROOT).as_posix()
        data = yaml.safe_load(m.read_text()) or {}
        if data.get("name"):
            out[rel] = data["name"]
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
