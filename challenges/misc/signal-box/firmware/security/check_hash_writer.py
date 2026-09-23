#!/usr/bin/env python3
"""File-only checks of the writer binding and Linux sealed-executable transport."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import write_signing_hash as writer


def check(tool):
    tool = tool.resolve(strict=True)
    plan = writer.load_plan(tool)
    with writer.sealed_file(tool, plan["tool_sha256"], executable=True) as handle:
        options = {"executable": f"/proc/self/fd/{handle}", "pass_fds": (handle,),
                   "capture_output": True, "timeout": 120}
        result = subprocess.run([str(tool), "version"], **options)
        if result.returncode or result.stderr.strip() or not result.stdout.startswith(b"picotool v2.3.1 "):
            raise ValueError("Sealed executable version check failed")
        with tempfile.TemporaryDirectory(prefix="hash-writer-file-check-") as temporary:
            directory = Path(temporary)
            source, output = directory / "input.json", directory / "simulation.bin"
            source.write_text(json.dumps({"bootkey0": list(plan["payload"])}) + "\n")
            # The explicit JSON input selects device_support::none in picotool.
            result = subprocess.run([str(tool), "otp", "dump", "-r", "--output", str(output), str(source)],
                                    **options)
            if result.returncode or result.stderr.strip():
                raise ValueError("Sealed executable file-only OTP simulation failed")
            writer.signing.check_oracle_dump(output.read_bytes(), plan["payload"])
    print("OFFLINE SEALED-TRANSPORT CHECK PASS: restored artifact and pinned executable; exact file-only OTP simulation.")
    print("No device, live preflight, receipt access, attempt latch or OTP write. This is not physical validation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        check(args.picotool)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("FATAL: Offline sealed-transport check failed; do not use live writer modes on this host.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
