#!/usr/bin/env python3
"""Inject runtime flags into fixed-width slots in a private RK05 copy."""
import os
from pathlib import Path
import sys

SLOT_SIZE = 128
SLOTS = (
    ("FLAG", "__FLAG__"),
    ("NOCO_FLAG_LEDGER_ESCAPE", "__FLAG_LEDGER_ESCAPE__"),
    ("NOCO_FLAG_PROPRIETOR", "__FLAG_PROPRIETOR__"),
)


def slot_bytes(token):
    encoded = token.encode("ascii")
    if len(encoded) > SLOT_SIZE:
        raise ValueError(f"flag token exceeds {SLOT_SIZE}-byte slot")
    return encoded.ljust(SLOT_SIZE, b" ")


def runtime_flags(environ=None):
    environ = os.environ if environ is None else environ
    values = {}
    for name, _ in SLOTS:
        value = environ.get(name)
        if value is None:
            raise RuntimeError(f"FATAL: {name} is required to provision guest flags")
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError as error:
            raise RuntimeError(f"FATAL: {name} must be ASCII") from error
        if not (value.startswith("noco{") and value.endswith("}")):
            raise RuntimeError(f"FATAL: {name} must use noco{{...}} format")
        if len(encoded) > SLOT_SIZE:
            raise RuntimeError(
                f"FATAL: {name} is {len(encoded)} bytes; maximum is {SLOT_SIZE}")
        values[name] = value
    return values


def inject(image, values=None):
    """Replace each unique padded token in image without changing its length."""
    path = Path(image)
    data = bytearray(path.read_bytes())
    if b"noco{" in data.lower():
        raise RuntimeError("FATAL: base RK05 already contains a flag literal")
    values = runtime_flags() if values is None else values
    for name, token in SLOTS:
        marker = slot_bytes(token)
        count = data.count(marker)
        if count != 1:
            raise RuntimeError(
                f"FATAL: expected one {token} slot in {path}, found {count}")
        replacement = values[name].encode("ascii").ljust(SLOT_SIZE, b" ")
        start = data.index(marker)
        data[start:start + SLOT_SIZE] = replacement
    temporary = path.with_name(path.name + ".flags.tmp")
    with temporary.open("wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} disk.rk")
    inject(sys.argv[1])
