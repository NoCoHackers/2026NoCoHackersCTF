#!/usr/bin/env python3
"""Compare slot-0 mapping and all ECC16 encodings with file-only picotool dumps."""

import argparse
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

import package_probe
import prepare_signing_hash as stage


def check(tool):
    tool = tool.resolve(strict=True)
    if not package_probe.run_tool(tool, "version").startswith(b"picotool v2.3.1 "):
        raise ValueError("Use picotool 2.3.1")
    with tempfile.TemporaryDirectory(prefix="noco-slot0-offline-check-") as name:
        directory = Path(name)
        stage.offline_oracle(tool, bytes(range(32)), directory)
        # Exercise every input word against upstream's real encoding and JSON
        # parser, entirely in memory/files. No connected-device dump is used.
        source, output = directory / "input.json", directory / "simulation.bin"
        # Address 0 is a named register: JSON objects there select fields,
        # not raw-address encoding. Use an unnamed region for synthetic words.
        first_row, count = 0x0100, 2048
        for base in range(0, 65536, count):
            words = list(range(base, base + count))
            data = struct.pack("<2048H", *words)
            source.write_text(json.dumps({"0x0100": {"ecc": True, "value": list(data)}}) + "\n")
            package_probe.run_tool(tool, "otp", "dump", "-r", "--output", output, source)
            if output.stat().st_size != 4096 * 4:
                raise ValueError("Unexpected simulated OTP size")
            raw = output.read_bytes()
            expected = bytearray(16384)
            struct.pack_into("<2048I", expected, first_row * 4, *(stage.ecc24(value) for value in words))
            if raw != expected:
                raise ValueError("ECC encoding differs from pinned picotool")
    print("OFFLINE INTEGRATION PASS: slot-0 extent/byte order and all 65,536 ECC16 encodings.")
    print("Explicit JSON inputs only; no device commands, persistent keys or retained simulations.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        check(args.picotool)
    except (OSError, ValueError):
        print("FATAL: Offline encoding check failed; do not use the artifact for provisioning.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
