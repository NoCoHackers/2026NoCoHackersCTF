#!/usr/bin/env python3
"""Validate NoCo Hackers CTF challenge bundles.

    tools/validate.py                     # every challenge bundle
    tools/validate.py challenges/web/foo  # just this bundle

A bundle has one deployment and one or more independently scored manifests.
Checks local metadata and files first, then global name, flag, endpoint, and
published-name collisions.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml  # noqa: F401 - gives a useful dependency error before imports below
except ImportError:
    sys.exit("validate: PyYAML is required -> pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
CHALLENGES = ROOT / "challenges"
sys.path.insert(0, str(ROOT / "tools"))
from chalbundle import (  # noqa: E402
    Bundle,
    BundleError,
    candidate_manifests,
    discover_bundle_dirs,
    host_flag_var,
    load_bundle,
    lock_key,
    manifest_id,
)

CATEGORIES = {"web", "pwn", "rev", "crypto", "forensics", "osint", "misc"}
KINDS = {"web", "tcp", "static"}
FLAG_RE = re.compile(r"^noco\{[\x20-\x7e]{3,120}\}$")
FLAG_ANY_RE = re.compile(r"noco\{[^}\s]{3,120}\}")
SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
PORT_RANGE = range(30000, 30100)
SUPPLEMENTAL_X_KEYS = {"autosolve"}
PLACEHOLDERS = {"noco{template_replace_me}", "your-github-handle", "Template Challenge"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def entry_where(entry) -> str:
    return entry.manifest.relative_to(ROOT).as_posix()


def normalized_flags(value, where: str, rep: Report) -> list:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        rep.error(where, "flags must be a list containing exactly one flag")
        return []
    return value


def check_entry(bundle: Bundle, entry, rep: Report, is_template: bool) -> dict:
    where = entry_where(entry)
    data = entry.data

    for key in ("name", "author", "category", "description", "value", "flags"):
        if not data.get(key):
            rep.error(where, f"missing required field '{key}'")

    category = data.get("category")
    if category and (not isinstance(category, str) or category not in CATEGORIES):
        rep.error(where, f"category {category!r} not in {sorted(CATEGORIES)}")
    parent = bundle.directory.parent.name
    if not is_template and isinstance(category, str) and category and parent != category:
        rep.error(where, f"lives under challenges/{parent}/ but declares category '{category}'")

    if data.get("state") not in (None, "hidden", "visible"):
        rep.error(where, "state must be 'hidden' or 'visible'")
    if not is_template and data.get("state") == "visible":
        rep.warn(where, "state is 'visible' - organizers flip this at kickoff, not authors")

    flags = normalized_flags(data.get("flags"), where, rep)
    if len(flags) != 1:
        rep.error(where, "each scoreboard manifest must declare exactly one flag")
    for flag in flags:
        if not isinstance(flag, str) or not FLAG_RE.match(flag):
            rep.error(where, f"flag {flag!r} must match noco{{...}}")
        elif not is_template and flag in PLACEHOLDERS:
            rep.error(where, "flag is still the template placeholder")
        elif not is_template and len(flag) < 12:
            rep.warn(where, f"flag {flag!r} is very short - easy to brute or guess")

    author = data.get("author")
    if not is_template and isinstance(author, str) and author in PLACEHOLDERS:
        rep.error(where, "author is still the template placeholder")

    raw_x = data.get("x-noco")
    if not isinstance(raw_x, dict):
        rep.error(where, "missing 'x-noco' block")
        x = {}
    else:
        x = raw_x
    if not entry.primary:
        forbidden = sorted(str(key) for key in x if key not in SUPPLEMENTAL_X_KEYS)
        if forbidden:
            rep.error(where, "supplemental x-noco may only contain autosolve; remove "
                      + ", ".join(forbidden))

    default_solve = "solution/solve.sh" if entry.primary else f"solution/solve-{entry.id}.sh"
    raw_solve = x.get("autosolve", default_solve)
    solve_valid = (isinstance(raw_solve, str) and bool(raw_solve.strip())
                   and not Path(raw_solve).is_absolute() and ".." not in Path(raw_solve).parts)
    if not solve_valid:
        rep.error(where, "x-noco.autosolve must be a non-empty relative path without '..'")
    else:
        solve = bundle.directory / raw_solve
        if not solve.is_file():
            rep.error(where, f"no autosolve script at {raw_solve} - CI cannot verify this entry")
        elif not (solve.stat().st_mode & 0o111):
            rep.error(where, f"{raw_solve} is not executable (chmod +x)")

    handouts = data.get("files") or []
    if not isinstance(handouts, list):
        rep.error(where, "files must be a list of bundle-relative paths")
        handouts = []
    for handout in handouts:
        if not isinstance(handout, str) or not (bundle.directory / handout).is_file():
            rep.error(where, f"files: lists {handout!r} which does not exist")

    return {"bundle": bundle, "entry": entry, "data": data, "flags": flags,
            "x": bundle.x, "primary": entry.primary}


def check_bundle(chal_dir: Path, rep: Report) -> list[dict]:
    where = chal_dir.relative_to(ROOT).as_posix()
    try:
        bundle = load_bundle(chal_dir)
    except BundleError as exc:
        rep.error(where, str(exc))
        return []

    is_template = bundle.directory.name == "TEMPLATE"
    loaded = [check_entry(bundle, entry, rep, is_template) for entry in bundle.entries]
    x = bundle.x
    kind = x.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        rep.error(entry_where(bundle.primary), f"x-noco.kind must be one of {sorted(KINDS)}")
    if kind == "web":
        sub = x.get("subdomain")
        if not sub or not isinstance(sub, str) or not SUBDOMAIN_RE.match(sub):
            rep.error(entry_where(bundle.primary),
                      f"x-noco.subdomain {sub!r} must be a short lowercase DNS label")
        if x.get("port"):
            rep.warn(entry_where(bundle.primary), "x-noco.port is ignored for kind 'web'")
    elif kind == "tcp":
        port = x.get("port")
        if not isinstance(port, int) or port not in PORT_RANGE:
            rep.error(entry_where(bundle.primary),
                      f"x-noco.port {port!r} must be an int in 30000-30099")

    if kind in ("web", "tcp"):
        if not (chal_dir / "Dockerfile").is_file() and not (chal_dir / "compose.yml").is_file():
            rep.error(where, f"kind '{kind}' needs a Dockerfile or compose.yml")
    if not (chal_dir / "solution" / "writeup.md").is_file():
        rep.error(where, "no solution/writeup.md")

    # Scan once against every entry flag. Recognized manifests are the sole
    # allowed locations for their literals, including under solution/.
    all_flags = {flag for item in loaded for flag in item["flags"] if isinstance(flag, str)}
    manifests = {p.resolve() for p in candidate_manifests(chal_dir)}
    for path in chal_dir.rglob("*"):
        if not path.is_file() or path.resolve() in manifests:
            continue
        rel = path.relative_to(chal_dir).as_posix()
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for hit in FLAG_ANY_RE.findall(text):
            if hit in all_flags:
                rep.error(where, f"flag literal found in {rel} - use a runtime flag token instead")

    return loaded


def check_domain_consistency(rep: Report, dirs: list[Path]) -> None:
    try:
        from domains import derive as _derive
        apex = _derive()["NOCO_APEX"]
    except Exception:
        return

    host_re = re.compile(r"(?:https?://|\bnc\s+)((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)
    ignore = ("localhost", "example.com", "example.dev", "example.org")
    targets = [p for directory in dirs for p in candidate_manifests(directory)
               if manifest_id(p) is not None]
    targets += [ROOT / "theme" / "partials" / "header.html",
                ROOT / "theme" / "partials" / "footer.html"]
    for path in targets:
        if not path.is_file():
            continue
        where = path.relative_to(ROOT).as_posix()
        text = path.read_text(errors="ignore")
        seen = set()
        for host in host_re.findall(text):
            host = host.lower()
            if host in seen or any(host == item or host.endswith("." + item) for item in ignore):
                continue
            if host.endswith("." + apex) or host == apex:
                continue
            seen.add(host)
            rep.warn(where, f"hostname '{host}' is not under the configured domain "
                            f"'{apex}' - stale after a rebrand? (edit content or event.yml)")


def check_name_lock(loaded: list[dict], rep: Report) -> None:
    import json

    lock_path = CHALLENGES / "names.lock"
    if not lock_path.is_file():
        rep.warn("challenges/names.lock", "missing - run tools/lock-names.py to create it")
        return
    try:
        lock = json.loads(lock_path.read_text())
    except json.JSONDecodeError as exc:
        rep.error("challenges/names.lock", f"invalid JSON: {exc}")
        return

    for item in loaded:
        bundle, entry = item["bundle"], item["entry"]
        if bundle.directory.name == "TEMPLATE":
            continue
        key = lock_key(bundle, entry)
        name = item["data"].get("name")
        if key in lock and name and lock[key] != name:
            rep.error(key, f"name changed '{lock[key]}' -> '{name}' since last sync. "
                      "CTFd matches by name: this creates a NEW challenge and splits solves. "
                      "If intended, re-run tools/lock-names.py to bless it.")
        elif key not in lock:
            rep.warn(key, "not in names.lock (new challenge) - run tools/lock-names.py")


def check_collisions(loaded: list[dict], rep: Report) -> None:
    subs: dict[str, str] = {}
    ports: dict[int, str] = {}
    flags: dict[str, str] = {}
    names: dict[str, str] = {}
    host_vars: dict[str, str] = {}

    for item in loaded:
        bundle, entry, data = item["bundle"], item["entry"], item["data"]
        if bundle.directory.name == "TEMPLATE":
            continue
        where = entry_where(entry)
        if bundle.x.get("kind") != "static":
            variable = host_flag_var(bundle, entry)
            if variable in host_vars:
                rep.error(where, f"runtime flag variable {variable} already used by "
                          f"{host_vars[variable]}")
            host_vars[variable] = where
        if item["primary"]:
            sub = item["x"].get("subdomain")
            if isinstance(sub, str) and sub:
                if sub in subs:
                    rep.error(where, f"subdomain '{sub}' already used by {subs[sub]}")
                subs[sub] = where
            port = item["x"].get("port")
            if isinstance(port, int):
                if port in ports:
                    rep.error(where, f"port {port} already used by {ports[port]}")
                ports[port] = where

        for flag in item["flags"]:
            if not isinstance(flag, str):
                continue
            if flag in flags:
                rep.error(where, f"flag reused from {flags[flag]}")
            flags[flag] = where

        name = data.get("name")
        if isinstance(name, str) and name:
            key = name.strip().lower()
            if key in names:
                rep.error(where, f"challenge name '{name}' already used by {names[key]}")
            names[key] = where


def discover(args: list[str]) -> list[Path]:
    if not args:
        return discover_bundle_dirs(CHALLENGES)
    dirs = []
    for arg in args:
        path = Path(arg).resolve()
        dirs.append(path.parent if path.is_file() else path)
    return sorted(set(dirs))


def main() -> int:
    rep = Report()
    dirs = discover(sys.argv[1:])
    if not dirs:
        print("validate: no challenges found")
        return 0

    loaded = [item for directory in dirs for item in check_bundle(directory, rep)]
    check_collisions(loaded, rep)
    check_name_lock(loaded, rep)
    check_domain_consistency(rep, dirs)

    for warning in rep.warnings:
        print(f"  warn  {warning}")
    for error in rep.errors:
        print(f"  ERROR {error}")

    print(f"\nvalidate: {len(dirs)} bundle(s), {len(loaded)} scoreboard entry(s), "
          f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
