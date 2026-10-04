#!/usr/bin/env python3
"""Shared helpers for externally hosted challenge bundles."""
from __future__ import annotations

import argparse
import hashlib
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
    if not isinstance(url, str) or not url.strip():
        raise ExternalError("x-noco.url must be a non-empty HTTPS root origin")
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https":
        raise ExternalError("x-noco.url must use https")
    if parsed.username or parsed.password:
        raise ExternalError("x-noco.url must not include credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExternalError("x-noco.url has an invalid port") from exc
    if port is not None:
        raise ExternalError("x-noco.url must not include an explicit port")
    if not parsed.hostname:
        raise ExternalError("x-noco.url must include a hostname")
    if parsed.path not in ("", "/"):
        raise ExternalError("x-noco.url must be the root origin")
    if parsed.query:
        raise ExternalError("x-noco.url must not include a query string")
    if parsed.fragment:
        raise ExternalError("x-noco.url must not include a fragment")
    return f"https://{parsed.hostname.lower()}"


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
    return {
        "kind": RECEIPT_KIND,
        "verifiedAt": _validate_verified_at(verified_at or _utc_now()),
        "origin": normalize_origin(bundle.x.get("url")),
        "entries": expected_entries(bundle),
    }


def _dump_receipt(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def write_receipt(bundle: Bundle, *, verified_at: str | None = None) -> Path:
    path = receipt_path(bundle.directory)
    temp = bundle.directory / RECEIPT_TMP_NAME
    payload = _dump_receipt(build_receipt(bundle, verified_at=verified_at))
    temp.write_text(payload)
    temp.replace(path)
    return path


def load_receipt(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
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
    except (ExternalError, OSError, json.JSONDecodeError) as exc:
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
    return any(entry.data.get("state") == "visible" for entry in bundle.entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write-receipt", help="write verification.json for a bundle")
    write.add_argument("bundle")
    write.add_argument("--verified-at")

    check = sub.add_parser("validate-receipt", help="validate verification.json for a bundle")
    check.add_argument("bundle")

    args = parser.parse_args()
    bundle = load_bundle(Path(args.bundle).resolve())
    if not is_external_bundle(bundle):
        raise SystemExit("external: bundle is not marked x-noco.kind: external")

    if args.command == "write-receipt":
        path = write_receipt(bundle, verified_at=args.verified_at)
        print(path.relative_to(bundle.directory).as_posix())
        return 0

    errors = validate_receipt(bundle)
    if errors:
        for error in errors:
            print(f"external: {error}")
        return 1
    print("external: verification.json is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
