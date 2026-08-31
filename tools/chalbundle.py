#!/usr/bin/env python3
"""Discover challenge bundles and their independently scored manifests.

A bundle always has a primary ``challenge.yml`` and may add root-level
``challenge.<id>.yml`` manifests. The primary owns deployment; every manifest
remains a complete ctfcli challenge whose relative paths start at the bundle.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHALLENGES = ROOT / "challenges"
MANIFEST_RE = re.compile(r"^challenge(?:\.([a-z0-9]+(?:-[a-z0-9]+)*))?\.yml$")


class BundleError(ValueError):
    """A challenge bundle cannot be loaded safely."""


@dataclass(frozen=True)
class Entry:
    id: str
    manifest: Path
    data: dict
    primary: bool = False

    @property
    def x(self) -> dict:
        value = self.data.get("x-noco")
        return value if isinstance(value, dict) else {}

    @property
    def flag(self) -> str:
        flags = self.data.get("flags")
        if isinstance(flags, str):
            return flags
        if isinstance(flags, list) and flags and isinstance(flags[0], str):
            return flags[0]
        return ""

    @property
    def autosolve(self) -> str:
        default = "solution/solve.sh" if self.primary else f"solution/solve-{self.id}.sh"
        value = self.x.get("autosolve", default)
        return value if isinstance(value, str) and value else default


@dataclass(frozen=True)
class Bundle:
    directory: Path
    entries: tuple[Entry, ...]

    @property
    def primary(self) -> Entry:
        return self.entries[0]

    @property
    def x(self) -> dict:
        return self.primary.x


def manifest_id(path: Path) -> str | None:
    """Return ``main`` or a supplemental id; None means invalid filename."""
    match = MANIFEST_RE.fullmatch(path.name)
    if not match:
        return None
    return match.group(1) or "main"


def candidate_manifests(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("challenge*.yml") if p.is_file())


def manifest_paths(directory: Path) -> list[Path]:
    paths = [p for p in candidate_manifests(directory) if manifest_id(p) is not None]
    return sorted(paths, key=lambda p: (manifest_id(p) != "main", manifest_id(p) or ""))


def load_manifest(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise BundleError(f"cannot load {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BundleError(f"{path} must be a YAML mapping")
    return data


def load_bundle(directory: Path | str) -> Bundle:
    directory = Path(directory).resolve()
    primary = directory / "challenge.yml"
    if not primary.is_file():
        raise BundleError(f"{directory} has supplemental manifests but no challenge.yml")

    invalid = [p.name for p in candidate_manifests(directory) if manifest_id(p) is None]
    if invalid:
        names = ", ".join(invalid)
        raise BundleError(f"{directory} has invalid manifest filename(s): {names}")

    entries = []
    for path in manifest_paths(directory):
        entry_id = manifest_id(path)
        assert entry_id is not None
        if entry_id == "main" and path.name != "challenge.yml":
            raise BundleError("supplemental challenge id 'main' is reserved")
        entries.append(Entry(entry_id, path, load_manifest(path), entry_id == "main"))
    return Bundle(directory, tuple(entries))


def discover_bundle_dirs(root: Path = CHALLENGES) -> list[Path]:
    """Find only challenges/<category>/<slug> bundles plus TEMPLATE.

    Source and handout trees may legitimately contain files whose names begin
    with ``challenge``; recursive discovery must not reinterpret those as
    independently deployable bundles.
    """
    candidates = list(root.glob("*/*/challenge*.yml"))
    candidates += list((root / "TEMPLATE").glob("challenge*.yml"))
    return sorted({p.parent.resolve() for p in candidates if p.is_file()})


def discover_bundles(root: Path = CHALLENGES) -> list[Bundle]:
    return [load_bundle(path) for path in discover_bundle_dirs(root)]


def service_name(bundle: Bundle | Path) -> str:
    directory = bundle.directory if isinstance(bundle, Bundle) else Path(bundle)
    return f"{directory.parent.name}-{directory.name}"


def env_suffix(value: str) -> str:
    return value.upper().replace("-", "_")


def host_flag_var(bundle: Bundle, entry: Entry) -> str:
    base = f"FLAG_{env_suffix(service_name(bundle))}"
    # The explicit delimiter prevents device#uart from colliding with the
    # legacy primary variable for a separate device-uart bundle.
    return base if entry.primary else f"{base}__ENTRY_{env_suffix(entry.id)}"


def container_flag_var(entry: Entry) -> str:
    return f"NOCO_FLAG_{env_suffix(entry.id)}"


def lock_key(bundle: Bundle, entry: Entry, root: Path = ROOT) -> str:
    base = bundle.directory.relative_to(root).as_posix()
    return base if entry.primary else f"{base}#{entry.id}"


def selected_manifests(selection: str | None = None) -> list[Path]:
    if selection is None:
        return [entry.manifest for bundle in discover_bundles() for entry in bundle.entries
                if bundle.directory.name != "TEMPLATE"]
    path = Path(selection).resolve()
    if path.is_file():
        if manifest_id(path) is None:
            raise BundleError(f"{path} is not a recognized challenge manifest")
        load_bundle(path.parent)
        return [path]
    return [entry.manifest for entry in load_bundle(path).entries]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    manifests = sub.add_parser("manifests", help="print manifests for sync or tooling")
    manifests.add_argument("selection", nargs="?")
    sub.add_parser("env", help="print development flag environment")
    args = parser.parse_args()

    try:
        if args.command == "manifests":
            for path in selected_manifests(args.selection):
                print(path.relative_to(ROOT).as_posix())
        else:
            for bundle in discover_bundles():
                if bundle.directory.name == "TEMPLATE" or bundle.x.get("kind") == "static":
                    continue
                for entry in bundle.entries:
                    if entry.flag:
                        print(f"{host_flag_var(bundle, entry)}={entry.flag}")
    except BundleError as exc:
        print(f"chalbundle: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
