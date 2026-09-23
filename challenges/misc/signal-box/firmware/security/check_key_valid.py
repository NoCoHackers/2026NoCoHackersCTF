#!/usr/bin/env python3
"""Check public KEY_VALID constants and explicit-file simulations; no device access."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import key_valid_policy as stage
import write_signing_hash as transport


SDK_CONSTANTS = {
    "OTP_DATA_BOOT_FLAGS1_ROW": 0x4b,
    "OTP_DATA_BOOT_FLAGS1_R1_ROW": 0x4c,
    "OTP_DATA_BOOT_FLAGS1_R2_ROW": 0x4d,
    "OTP_DATA_BOOT_FLAGS1_KEY_VALID_BITS": 0xf,
    "OTP_DATA_BOOT_FLAGS1_KEY_VALID_LSB": 0,
    "OTP_DATA_BOOT_FLAGS1_KEY_INVALID_BITS": 0xf00,
    "OTP_DATA_BOOT_FLAGS1_KEY_INVALID_LSB": 8,
    "OTP_DATA_CRIT1_SECURE_BOOT_ENABLE_BITS": 1,
}


def check_sdk(sdk):
    header = sdk / "src/rp2350/hardware_regs/include/hardware/regs/otp_data.h"
    text = header.read_text()
    for name, expected in SDK_CONSTANTS.items():
        values = re.findall(r"(?m)^#define " + re.escape(name) + r"\s+(?:_u\()?([0-9a-fx]+)\)?\s*$", text)
        if len(values) != 1 or int(values[0], 0) != expected:
            raise ValueError("SDK KEY_VALID constants differ; stop and re-review")


def check(tool, sdk):
    stage.changed_rows()
    check_sdk(sdk)
    # Snapshot this local tool for file-only simulation. The future artifact must
    # ALSO bind it to the restored private bundle; this checker does not do that.
    tool = tool.resolve(strict=True)
    tool_hash = transport.recovery_images.digest(tool)
    with transport.sealed_file(tool, tool_hash, executable=True) as handle:
        options = {"executable": f"/proc/self/fd/{handle}", "pass_fds": (handle,),
                   "capture_output": True, "timeout": 120}
        result = subprocess.run([str(tool), "version"], **options)
        if result.returncode or result.stderr.strip() or not result.stdout.startswith(b"picotool v2.3.1 "):
            raise ValueError("Use picotool 2.3.1 for the reviewed file-only model")
        with tempfile.TemporaryDirectory(prefix="key-valid-file-only-") as temporary:
            root = Path(temporary)
            # Both cases are ephemeral simulation inputs, NEVER published write
            # recipes. Explicit input selects device_support::none in otp dump.
            for index, contents in enumerate(({"BOOT_FLAGS1": 1}, {"BOOT_FLAGS1": {"KEY_VALID": 1}})):
                source, output = root / f"{index}.json", root / f"{index}.bin"
                source.write_text(json.dumps(contents) + "\n")
                result = subprocess.run([str(tool), "otp", "dump", "-r", "--output", str(output), str(source)],
                                        **options)
                if (result.returncode or result.stderr.strip() or
                        transport.BAD_DIAGNOSTIC.search(result.stdout.decode("utf-8", errors="strict"))):
                    raise ValueError("Explicit-file KEY_VALID simulation failed")
                stage.check_oracle_dump(output.read_bytes())
    print("KEY_VALID OFFLINE CHECK PASS: 8 SDK constants; two exact 4096-row file-only simulations.")
    print("No device/predecessor verification, writer, persistent loadable artifact or activation authorization.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    parser.add_argument("--sdk", type=Path, default=Path("/tmp/signal-box-pico-sdk-2.2.0"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        check(args.picotool, args.sdk)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("FATAL: Offline KEY_VALID check failed; stop and review. No device command was issued.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
