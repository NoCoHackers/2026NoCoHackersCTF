#!/usr/bin/env python3
"""Shared helpers for externally hosted challenge bundles."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from chalbundle import Bundle, Entry, load_bundle

RECEIPT_NAME = "verification.json"
RECEIPT_TMP_NAME = f"{RECEIPT_NAME}.tmp"
RECEIPT_KIND = "noco-external-verification/v1"
LOCAL_FIELDS = {"subdomain", "port", "memory", "cpus", "pids", "healthcheck_path"}


class ExternalError(ValueError):
    """External bundle metadata or verification is invalid."""


def is_external_bundle(bundle: Bundle) -> bool:
    return bundle.x.get("kind") == "external"


def receipt_path(bundle_dir: Path) -> Path:
    return bundle_dir / RECEIPT_NAME


def normalize_origin(url: Any) -> str:
    if not isinstance(url, str) or not url:
        raise ExternalError("x-noco.url must be a non-empty HTTPS root origin")
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        raise ExternalError("x-noco.url must not contain whitespace or control characters")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ExternalError("x-noco.url is malformed") from exc
    if parsed.scheme != "https":
        raise ExternalError("x-noco.url must use https")
    if "@" in parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ExternalError("x-noco.url must not include credentials")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ExternalError("x-noco.url has an invalid hostname or port") from exc
    if port is not None:
        raise ExternalError("x-noco.url must not include an explicit port")
    if not host:
        raise ExternalError("x-noco.url must include a hostname")
    if parsed.path not in ("", "/"):
        raise ExternalError("x-noco.url must be the root origin")
    if parsed.query:
        raise ExternalError("x-noco.url must not include a query string")
    if parsed.fragment:
        raise ExternalError("x-noco.url must not include a fragment")
    if "%" in host:
        raise ExternalError("x-noco.url must not include a scoped IPv6 host")
    if ":" in host:
        try:
            host = ipaddress.IPv6Address(host).compressed.lower()
        except ValueError as exc:
            raise ExternalError("x-noco.url has an invalid IPv6 host") from exc
        return f"https://[{host}]"
    return f"https://{host.lower()}"


def external_bundle_errors(bundle: Bundle) -> list[str]:
    errors = []
    try:
        normalize_origin(bundle.x.get("url"))
    except ExternalError as exc:
        errors.append(str(exc))

    forbidden = sorted(key for key in LOCAL_FIELDS if key in bundle.x)
    if forbidden:
        errors.append("external bundles must not declare local container fields: "
                      + ", ".join(forbidden))
    return errors


def flag_sha256(entry: Entry) -> str:
    return hashlib.sha256(entry.flag.encode("utf-8")).hexdigest()


def entry_metadata(bundle: Bundle, entry: Entry, origin: str) -> dict[str, str]:
    name = entry.data.get("name")
    version = entry.data.get("version")
    data = {
        "id": entry.id,
        "name": name if isinstance(name, str) else "",
        "version": str(version) if version is not None else "",
        "origin": origin,
        "flagSha256": flag_sha256(entry),
    }
    data["fingerprint"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return data


def expected_entries(bundle: Bundle) -> list[dict[str, str]]:
    origin = normalize_origin(bundle.x.get("url"))
    return [entry_metadata(bundle, entry, origin) for entry in bundle.entries]


def live_snapshot(bundle: Bundle) -> dict[str, Any]:
    return {
        "kind": RECEIPT_KIND,
        "origin": normalize_origin(bundle.x.get("url")),
        "entries": expected_entries(bundle),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_verified_at(value: Any) -> str:
    if not isinstance(value, str):
        raise ExternalError("verification.json verifiedAt must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExternalError("verification.json verifiedAt must be a valid UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ExternalError("verification.json verifiedAt must use UTC")
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_receipt(bundle: Bundle, *, verified_at: str | None = None) -> dict[str, Any]:
    return build_receipt_from_snapshot(live_snapshot(bundle), verified_at=verified_at)


def build_receipt_from_snapshot(snapshot: dict[str, Any], *,
                                verified_at: str | None = None) -> dict[str, Any]:
    return {
        "kind": snapshot.get("kind", RECEIPT_KIND),
        "verifiedAt": _validate_verified_at(verified_at or _utc_now()),
        "origin": snapshot["origin"],
        "entries": snapshot["entries"],
    }


def _dump_receipt(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_receipt(bundle: Bundle, *, verified_at: str | None = None) -> Path:
    return write_receipt_snapshot(bundle.directory, live_snapshot(bundle), verified_at=verified_at)


def write_receipt_snapshot(bundle_dir: Path, snapshot: dict[str, Any], *,
                           verified_at: str | None = None) -> Path:
    path = receipt_path(bundle_dir)
    temp = bundle_dir / RECEIPT_TMP_NAME
    payload = _dump_receipt(build_receipt_from_snapshot(snapshot, verified_at=verified_at))
    temp.write_text(payload)
    temp.replace(path)
    return path


def load_receipt(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ExternalError("verification.json is not valid UTF-8") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExternalError("verification.json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ExternalError("verification.json must contain a JSON object")
    return data


def validate_receipt(bundle: Bundle) -> list[str]:
    path = receipt_path(bundle.directory)
    if not path.is_file():
        return ["verification.json is required before visible external entries can sync"]

    try:
        receipt = load_receipt(path)
    except FileNotFoundError:
        return ["verification.json is required before visible external entries can sync"]
    except (ExternalError, OSError) as exc:
        return [f"verification.json is invalid: {exc}"]

    try:
        if receipt.get("kind") != RECEIPT_KIND:
            raise ExternalError(f"verification.json kind must be {RECEIPT_KIND!r}")
        _validate_verified_at(receipt.get("verifiedAt"))
        origin = normalize_origin(bundle.x.get("url"))
        if receipt.get("origin") != origin:
            raise ExternalError("verification.json origin does not match the current bundle")

        actual = receipt.get("entries")
        if not isinstance(actual, list):
            raise ExternalError("verification.json entries must be a list")
        expected = expected_entries(bundle)
        if len(actual) != len(expected):
            raise ExternalError("verification.json must list every current entry exactly once")

        seen = set()
        actual_by_id = {}
        for item in actual:
            if not isinstance(item, dict):
                raise ExternalError("verification.json entries must be objects")
            entry_id = item.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                raise ExternalError("verification.json entries must include non-empty ids")
            if entry_id in seen:
                raise ExternalError("verification.json entries must have unique ids")
            seen.add(entry_id)
            actual_by_id[entry_id] = item

        for item in expected:
            current = actual_by_id.get(item["id"])
            if current is None:
                raise ExternalError("verification.json must list every current entry exactly once")
            for key in ("id", "name", "version", "origin", "flagSha256", "fingerprint"):
                if current.get(key) != item[key]:
                    raise ExternalError(
                        f"verification.json metadata fingerprint mismatch for entry {item['id']}")
    except ExternalError as exc:
        return [str(exc)]
    return []


def requires_receipt(bundle: Bundle) -> bool:
    return any(entry.data.get("state") != "hidden" for entry in bundle.entries)


def validate_live_snapshot(bundle: Bundle, snapshot: dict[str, Any]) -> list[str]:
    try:
        current = live_snapshot(bundle)
    except ExternalError as exc:
        return [f"external bundle metadata changed during live verification: {exc}"]
    if current.get("origin") != snapshot.get("origin") or current.get("entries") != snapshot.get("entries"):
        return ["external bundle metadata changed during live verification"]
    return []


def preflight_sync_paths(paths: list[str | Path]) -> list[str]:
    errors: list[str] = []
    seen: set[Path] = set()
    for item in paths:
        path = Path(item).resolve()
        bundle_dir = path.parent if path.is_file() else path
        if bundle_dir in seen:
            continue
        seen.add(bundle_dir)
        try:
            bundle = load_bundle(bundle_dir)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue
        if not is_external_bundle(bundle) or not requires_receipt(bundle):
            continue
        for error in validate_receipt(bundle):
            errors.append(f"{bundle_dir}: {error}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("validate-receipt", help="validate verification.json for a bundle")
    check.add_argument("bundle")
    preflight = sub.add_parser(
        "preflight-sync", help="fail closed if any to-be-synced external entry lacks proof")
    preflight.add_argument("paths", nargs="+")

    args = parser.parse_args()
    if args.command == "preflight-sync":
        errors = preflight_sync_paths(args.paths)
        if errors:
            for error in errors:
                print(f"external: {error}")
            return 1
        print("external: sync preflight passed")
        return 0

    bundle = load_bundle(Path(args.bundle).resolve())
    if not is_external_bundle(bundle):
        raise SystemExit("external: bundle is not marked x-noco.kind: external")

    errors = validate_receipt(bundle)
    if errors:
        for error in errors:
            print(f"external: {error}")
        return 1
    print("external: verification.json is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
