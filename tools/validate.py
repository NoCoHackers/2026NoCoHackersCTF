#!/usr/bin/env python3
"""
Validate NoCo Hackers CTF challenge directories.

    tools/validate.py                     # every challenge
    tools/validate.py challenges/web/foo  # just these

Checks each challenge in isolation, then checks the whole set for the things
that only break when challenges collide: duplicate subdomains, duplicate TCP
ports, reused flags.

Exit 0 = clean. Exit 1 = at least one error. Warnings never fail the build.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("validate: PyYAML is required -> pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
CHALLENGES = ROOT / "challenges"

CATEGORIES = {"web", "pwn", "rev", "crypto", "forensics", "osint", "misc"}
KINDS = {"web", "tcp", "static"}
FLAG_RE = re.compile(r"^noco\{[\x20-\x7e]{3,120}\}$")
FLAG_ANY_RE = re.compile(r"noco\{[^}\s]{3,120}\}")
SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$")
PORT_RANGE = range(30000, 30100)

# Placeholder values that are fine in TEMPLATE/ and nowhere else.
PLACEHOLDERS = {"noco{template_replace_me}", "your-github-handle", "Template Challenge"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def load(path: Path, rep: Report):
    """Parse challenge.yml, or return None if it is unusable."""
    where = path.relative_to(ROOT).as_posix()
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        rep.error(where, f"invalid YAML: {exc}")
        return None
    if not isinstance(data, dict):
        rep.error(where, "must be a YAML mapping")
        return None
    return data


def check_one(chal_dir: Path, rep: Report) -> dict | None:
    where = chal_dir.relative_to(ROOT).as_posix()
    is_template = chal_dir.name == "TEMPLATE"

    manifest = chal_dir / "challenge.yml"
    if not manifest.is_file():
        rep.error(where, "no challenge.yml")
        return None

    data = load(manifest, rep)
    if data is None:
        return None

    # --- required top-level fields -------------------------------------
    for key in ("name", "author", "category", "description", "value", "flags"):
        if not data.get(key):
            rep.error(where, f"missing required field '{key}'")

    category = data.get("category")
    if category and category not in CATEGORIES:
        rep.error(where, f"category '{category}' not in {sorted(CATEGORIES)}")

    # Directory must live under its declared category, so the tree stays
    # navigable and generate.py can trust the path.
    parent = chal_dir.parent.name
    if not is_template and category and parent != category:
        rep.error(where, f"lives under challenges/{parent}/ but declares category '{category}'")

    if data.get("state") not in (None, "hidden", "visible"):
        rep.error(where, "state must be 'hidden' or 'visible'")
    if not is_template and data.get("state") == "visible":
        rep.warn(where, "state is 'visible' - organizers flip this at kickoff, not authors")

    # --- flags ----------------------------------------------------------
    flags = data.get("flags") or []
    if isinstance(flags, str):
        flags = [flags]
    for flag in flags:
        if not isinstance(flag, str) or not FLAG_RE.match(flag):
            rep.error(where, f"flag {flag!r} must match noco{{...}}")
        elif not is_template and flag in PLACEHOLDERS:
            rep.error(where, "flag is still the template placeholder")
        elif not is_template and len(flag) < 12:
            rep.warn(where, f"flag {flag!r} is very short - easy to brute or guess")

    if not is_template and data.get("author") in PLACEHOLDERS:
        rep.error(where, "author is still the template placeholder")

    # --- x-noco deploy block --------------------------------------------
    x = data.get("x-noco")
    if not isinstance(x, dict):
        rep.error(where, "missing 'x-noco' deploy block")
        return {"dir": chal_dir, "data": data, "flags": flags, "x": {}}

    kind = x.get("kind")
    if kind not in KINDS:
        rep.error(where, f"x-noco.kind must be one of {sorted(KINDS)}")

    if kind == "web":
        sub = x.get("subdomain")
        if not sub or not isinstance(sub, str) or not SUBDOMAIN_RE.match(sub):
            rep.error(where, f"x-noco.subdomain {sub!r} must be a short lowercase DNS label")
        if x.get("port"):
            rep.warn(where, "x-noco.port is ignored for kind 'web'")
    elif kind == "tcp":
        port = x.get("port")
        if not isinstance(port, int) or port not in PORT_RANGE:
            rep.error(where, f"x-noco.port {port!r} must be an int in 30000-30099")

    # --- files on disk ---------------------------------------------------
    if kind in ("web", "tcp"):
        if not (chal_dir / "Dockerfile").is_file() and not (chal_dir / "compose.yml").is_file():
            rep.error(where, f"kind '{kind}' needs a Dockerfile or compose.yml")

    solve_rel = x.get("autosolve", "solution/solve.sh")
    solve = chal_dir / solve_rel
    if not solve.is_file():
        rep.error(where, f"no autosolve script at {solve_rel} - CI cannot verify this challenge")
    elif not (solve.stat().st_mode & 0o111):
        rep.error(where, f"{solve_rel} is not executable (chmod +x)")

    if not (chal_dir / "solution" / "writeup.md").is_file():
        rep.error(where, "no solution/writeup.md")

    # --- declared handout files must exist --------------------------------
    for f in data.get("files") or []:
        if not (chal_dir / f).is_file():
            rep.error(where, f"files: lists '{f}' which does not exist")

    # --- flag must not be baked into the source ---------------------------
    # The flag belongs in challenge.yml and in the runtime environment. If it
    # appears in the build context it ends up in an image layer, and image
    # layers are readable by anyone who can pull.
    for path in chal_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(chal_dir).as_posix()
        if rel == "challenge.yml" or rel.startswith("solution/"):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for hit in FLAG_ANY_RE.findall(text):
            if hit in flags:
                rep.error(where, f"flag literal found in {rel} - use the __FLAG__ token instead")

    return {"dir": chal_dir, "data": data, "flags": flags, "x": x}


def check_domain_consistency(rep: Report) -> None:
    """Warn when a hostname in player-facing content drifts from event.yml.

    Config domains are generated (see tools/domains.py), but challenge
    descriptions and theme links carry hostnames as prose.
    After a rebrand those go stale silently; this flags any that don't sit under
    the configured apex. Warning only - content isn't machine-critical.
    """
    import re as _re
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from domains import derive as _derive
        apex = _derive()["NOCO_APEX"]
    except Exception:
        return

    # Only hostnames in a real connect context: a URL, or `nc host port`.
    # This avoids matching filenames like favicon.svg or theme.bundle.css.
    host_re = _re.compile(
        r"(?:https?://|\bnc\s+)((?:[a-z0-9-]+\.)+[a-z]{2,})", _re.I)
    ignore = ("localhost", "example.com", "example.dev", "example.org")
    targets = list((ROOT / "challenges").rglob("challenge.yml"))
    targets += [ROOT / "theme" / "partials" / "header.html",
                ROOT / "theme" / "partials" / "footer.html"]
    for f in targets:
        if not f.is_file():
            continue
        where = f.relative_to(ROOT).as_posix()
        text = f.read_text(errors="ignore")
        seen = set()
        for host in host_re.findall(text):
            host = host.lower()
            if host in seen or any(host == i or host.endswith("." + i) for i in ignore):
                continue
            if host.endswith("." + apex) or host == apex:
                continue
            seen.add(host)
            rep.warn(where, f"hostname '{host}' is not under the configured domain "
                            f"'{apex}' - stale after a rebrand? (edit content or event.yml)")


def check_name_lock(loaded: list[dict], rep: Report) -> None:
    """Warn when a challenge's name drifts from challenges/names.lock.

    CTFd matches challenges by name on sync, so a directory that changes its
    `name:` after being published becomes a *new* challenge in CTFd and splits
    its solves. The lock records the last-blessed name per directory; an intended
    rename is blessed by re-running tools/lock-names.py.
    """
    import json as _json

    lock_path = CHALLENGES / "names.lock"
    if not lock_path.is_file():
        rep.warn("challenges/names.lock", "missing - run tools/lock-names.py to create it")
        return
    try:
        lock = _json.loads(lock_path.read_text())
    except _json.JSONDecodeError as exc:
        rep.error("challenges/names.lock", f"invalid JSON: {exc}")
        return

    for entry in loaded:
        if entry["dir"].name == "TEMPLATE":
            continue
        rel = entry["dir"].relative_to(ROOT).as_posix()
        name = entry["data"].get("name")
        if rel in lock and name and lock[rel] != name:
            rep.error(rel, f"name changed '{lock[rel]}' -> '{name}' since last sync. "
                           f"CTFd matches by name: this creates a NEW challenge and splits "
                           f"solves. If intended, re-run tools/lock-names.py to bless it.")
        elif rel not in lock:
            rep.warn(rel, "not in names.lock (new challenge) - run tools/lock-names.py")


def check_collisions(loaded: list[dict], rep: Report) -> None:
    subs: dict[str, str] = {}
    ports: dict[int, str] = {}
    flags: dict[str, str] = {}
    names: dict[str, str] = {}

    for entry in loaded:
        where = entry["dir"].relative_to(ROOT).as_posix()
        if entry["dir"].name == "TEMPLATE":
            continue
        x, data = entry["x"], entry["data"]

        sub = x.get("subdomain")
        if sub:
            if sub in subs:
                rep.error(where, f"subdomain '{sub}' already used by {subs[sub]}")
            subs[sub] = where

        port = x.get("port")
        if isinstance(port, int):
            if port in ports:
                rep.error(where, f"port {port} already used by {ports[port]}")
            ports[port] = where

        for flag in entry["flags"]:
            if flag in flags:
                rep.error(where, f"flag reused from {flags[flag]}")
            flags[flag] = where

        name = data.get("name")
        if name:
            key = name.strip().lower()
            if key in names:
                rep.error(where, f"challenge name '{name}' already used by {names[key]}")
            names[key] = where


def discover(args: list[str]) -> list[Path]:
    if args:
        return [Path(a).resolve() for a in args]
    return sorted(p.parent for p in CHALLENGES.rglob("challenge.yml"))


def main() -> int:
    rep = Report()
    dirs = discover(sys.argv[1:])
    if not dirs:
        print("validate: no challenges found")
        return 0

    loaded = [e for e in (check_one(d, rep) for d in dirs) if e]
    check_collisions(loaded, rep)
    check_name_lock(loaded, rep)
    check_domain_consistency(rep)

    for w in rep.warnings:
        print(f"  warn  {w}")
    for e in rep.errors:
        print(f"  ERROR {e}")

    print(f"\nvalidate: {len(dirs)} challenge(s), "
          f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
