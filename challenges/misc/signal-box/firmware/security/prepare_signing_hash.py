#!/usr/bin/env python3
"""Prepare/check a private slot-0 hash artifact offline. Never program a device."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile

import otp_policy
import package_probe
import prepare_recovery
import recovery_images
import restore_sacrificial as restore

HERE = Path(__file__).resolve().parent
BUNDLE = restore.BASE / "recovery-bundles" / (
    "sacrificial-9423D016AADE5950-prepared-20260911T042403.044323Z")
ROUND_TRIP = restore.BASE / "device-backups" / (
    "sacrificial-9423D016AADE5950-ram-recovery-20260911T163115.320929Z") / "stage.json"
OUTPUT_PARENT = restore.BASE / "provisioning-artifacts"
PAYLOAD = "slot0-hash.ecc.bin"
LIMITS = {PAYLOAD: 32, "review.json": 65536, "README.txt": 8192, "SHA256SUMS": 4096}
SOURCES = ("prepare_signing_hash.py", "otp_policy.py", "package_probe.py",
           "prepare_recovery.py", "recovery_images.py", "restore_sacrificial.py")
WARNING = """REVIEW ONLY — NO OTP PROGRAMMING AUTHORIZED.
This is a sacrificial-board slot-0 signing-hash DATA stage, not key activation.
The 32-byte .bin is ECC input (16 little-endian 16-bit rows), NOT raw24 input,
firmware, a complete OTP image, an AES key or a signing private key.
Never drag it to BOOTSEL or use picotool load on it.
review.json is NOT a picotool OTP JSON file. Its proposed argv is review data,
not an executable writer and not a live-device preflight or authorization gate.
No KEY_VALID/KEY_INVALID, CRIT, boot flags, locks, counters or secret writes.

Before any separately approved write: verify this artifact against its original
key/recovery bundle, complete an independent encrypted backup/restore including
these new files, re-identify the exact A4/ROM/serial, and re-read every expected
raw policy and candidate-storage row. All 16 target rows must be physically
zero; corrected ECC zero is insufficient. Never auto-resume a partial write.
Hold after this data stage: separately read all 16 ECC and raw values, require
exact row coverage and the predicted fresh-row raw ECC encoding, verify the
other 48 page-2 rows remain blank, and recheck unchanged controls/secret pages.
Stop on any mismatch, interruption or unexpected bit; do not activate the key.

The future binary load MUST explicitly select ECC and start row 0x0080. BIN
otherwise defaults to raw mode. Pinned picotool's binary load prints a mismatch
without necessarily returning a failure exit code: exit 0 is NOT verification.
Require its positive verification message AND independent exact readbacks.
The JSON-load path has no automatic verification; no loadable JSON is emitted.
Current secure-boot/debug defaults stay unchanged in this stage. The earlier
unprovisioned recovery test is not authenticated-recovery acceptance under OTP.
Keep this sidecar separate from the unchanged restored 37-file recovery bundle.
"""


def private_file(path, limit):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077 or not 0 < info.st_size <= limit):
        raise ValueError("Expected a bounded owner-only regular file")


def private_directory(path):
    path = prepare_recovery.private_directory(path)
    if path.stat().st_uid != os.getuid():
        raise ValueError("Private directory must belong to the current operator")
    return path


def hash_payload(key_hash):
    if not isinstance(key_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", key_hash):
        raise ValueError("Expected canonical SHA256(X_BE32 || Y_BE32)")
    return bytes.fromhex(key_hash)


def ecc24(value):
    if type(value) is not int or not 0 <= value <= 0xffff:
        raise ValueError("ECC input must be one 16-bit word")
    # picotool 2.3.1 main.cpp otp_calculate_ecc, parity-map table 9.
    parity = [(value & mask).bit_count() & 1
              for mask in (0xad5b, 0x366d, 0xc78e, 0x07f0, 0xf800)]
    parity.append((value.bit_count() + sum(parity)) & 1)
    return value | sum(bit << (16 + i) for i, bit in enumerate(parity))


def row_plan(payload):
    if type(payload) is not bytes or len(payload) != 32:
        raise ValueError("Slot-0 hash must be exactly 32 digest bytes")
    return [{"row": f"0x{0x80 + i:04x}", "before_raw24": "0x000000",
             "after_ecc16": f"0x{value:04x}", "after_raw24": f"0x{ecc24(value):06x}"}
            for i, (value,) in enumerate(struct.iter_unpack("<H", payload))]


def check_inputs(tool, bundle, original, audit_path):
    bundle, original = private_directory(bundle), private_directory(original)
    for directory, limits in ((bundle, prepare_recovery.PREPARED_LIMITS),
                              (original, restore.LIMITS)):
        for name, limit in limits.items():
            private_file(directory / name, limit)
        if prepare_recovery.check_working(directory) != limits:
            raise ValueError("Unexpected source bundle format")
    binding = json.loads((bundle / "binding.json").read_text())
    if binding["original_manifest_sha256"] != recovery_images.digest(original / "SHA256SUMS"):
        raise ValueError("Snapshot is not bound to the preserved original bundle")
    if recovery_images.public_key_hash(original) != binding["signing_public_key_sha256_xy"]:
        raise ValueError("Original and recovery signers differ")
    tool = tool.resolve(strict=True)
    if recovery_images.digest(tool) != binding["picotool_binary_sha256"]:
        raise ValueError("Use the exact backed-up picotool executable")
    version = package_probe.run_tool(tool, "version")
    if not version.startswith(b"picotool v2.3.1 "):
        raise ValueError("Use pinned picotool 2.3.1")
    recovery_images.verify_stored_images(tool, bundle)
    private_directory(audit_path.parent)
    private_file(audit_path, 65536)
    audit = json.loads(audit_path.read_text())
    if (audit.get("status") != "UNPROVISIONED_RECOVERY_ROUND_TRIP_PASS" or
            audit.get("device_serial") != otp_policy.SERIAL or
            audit.get("source_bundle") != str(bundle) or
            audit.get("image_file") != "debug-closed-ram.uf2" or
            audit.get("image_sha256") != recovery_images.digest(bundle / "debug-closed-ram.uf2") or
            audit.get("flash_writes") is not False or audit.get("otp_writes") is not False or
            audit.get("ram_readback_verification") != "PASS" or
            audit.get("post_execution_flash_check") != "PASS: full 2 MiB byte-for-byte match" or
            audit.get("post_execution_otp_check") != "PASS: 34 policy rows unchanged; 256 candidate key rows blank" or
            audit.get("uart_execution_marker") != "PASS: operator transcript SECURITY PROFILE=debug-closed" or
            audit.get("normal_flash_return") != "PASS: operator UART transcript SECURITY PROFILE=recovery after requested normal power cycle" or
            not re.fullmatch(r"[0-9a-f]{64}", audit.get("flash_before_sha256", "")) or
            audit.get("flash_before_sha256") != audit.get("flash_after_sha256")):
        raise ValueError("Missing matching unprovisioned recovery evidence")
    return binding


def check_oracle_dump(raw, payload):
    if len(raw) != 4096 * 4:
        raise ValueError("Unexpected offline OTP dump size")
    expected = bytearray(len(raw))
    for row in row_plan(payload):
        struct.pack_into("<I", expected, int(row["row"], 16) * 4, int(row["after_raw24"], 16))
    if raw != expected:
        raise ValueError("Offline picotool row extent/ECC differs from the reviewed mapping")


def offline_oracle(tool, payload, parent):
    tool = tool.resolve(strict=True)
    # An explicit JSON input makes otp dump select device_support::none.
    # These temporary simulation files are never published as write artifacts.
    with tempfile.TemporaryDirectory(prefix="offline-otp-", dir=parent) as name:
        directory = Path(name)
        source, output = directory / "input.json", directory / "simulation.bin"
        source.write_text(json.dumps({"bootkey0": list(payload)}) + "\n")
        source.chmod(0o600)
        package_probe.run_tool(tool, "otp", "dump", "-r", "--output", output, source)
        if output.stat().st_size != 4096 * 4:
            raise ValueError("Unexpected offline OTP output size")
        check_oracle_dump(output.read_bytes(), payload)


def review_record(tool, bundle, original, audit_path, binding, payload):
    return {
        "kind": "NOCO_SLOT0_HASH_REVIEW_NOT_A_PICOTOOL_JSON",
        "authorized_for_programming": False,
        "device_serial": otp_policy.SERIAL,
        "device_revision": "A4",
        "rom_gitrev": "0xa8bfe860",
        "stage": "signing_hash_data_only_hold_before_key_valid",
        "source_bundle": str(bundle),
        "source_bundle_manifest_sha256": recovery_images.digest(bundle / "SHA256SUMS"),
        "source_binding_sha256": recovery_images.digest(bundle / "binding.json"),
        "original_manifest_sha256": recovery_images.digest(original / "SHA256SUMS"),
        "recovery_test_audit_sha256": recovery_images.digest(audit_path),
        "picotool_version": package_probe.PICOTOOL_VERSION,
        "picotool_binary_sha256": recovery_images.digest(tool),
        "producer_sha256": {name: recovery_images.digest(HERE / name) for name in SOURCES},
        "signing_public_key_sha256_xy": binding["signing_public_key_sha256_xy"],
        "payload_file": PAYLOAD,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_bytes": 32,
        "encoding": "ECC input: digest byte pairs little-endian; not raw24 or ASCII hex",
        "rows": row_plan(payload),
        "control_writes": [],
        "secret_writes": [],
        "unchanged_policy_rows": {f"0x{row:04x}": f"0x{value:06x}"
                                  for row, value in otp_policy.baseline_rows().items()},
        "blank_other_rows": [f"0x{row:04x}" for row in
                             (*range(0x90, 0xc0), *range(0x740, 0x800))],
        "proposed_argv_not_executed": ["otp", "load", "--ecc", "--start_row", "0x0080",
                                       PAYLOAD, "-t", "bin", "--ser", otp_policy.SERIAL],
        "gates_still_required": ["new artifacts independently backed up and restored",
                                 "exact writer/command review and separate hash-only write approval",
                                 "fresh identity, raw policy and physically blank storage preflight",
                                 "positive tool verification AND exact ECC/raw readbacks; no auto-retry",
                                 "hold before KEY_VALID or any other stage"],
    }


def check_artifact(tool, bundle, original, audit_path, directory):
    tool = tool.resolve(strict=True)
    directory = private_directory(directory)
    if {p.name for p in directory.iterdir()} != set(LIMITS):
        raise ValueError("Unexpected artifact members")
    for name, limit in LIMITS.items():
        private_file(directory / name, limit)
    binding = check_inputs(tool, bundle, original, audit_path)
    payload = hash_payload(binding["signing_public_key_sha256_xy"])
    expected = review_record(tool, bundle, original, audit_path, binding, payload)
    if ((directory / PAYLOAD).read_bytes() != payload or
            json.loads((directory / "review.json").read_text()) != expected or
            (directory / "README.txt").read_text() != WARNING):
        raise ValueError("Artifact scope, payload or binding changed")
    manifest = "".join(recovery_images.digest(directory / name) + "  " + name + "\n"
                       for name in sorted(set(LIMITS) - {"SHA256SUMS"}))
    if (directory / "SHA256SUMS").read_text() != manifest:
        raise ValueError("Artifact manifest mismatch")
    offline_oracle(tool, payload, directory.parent)


def prepare(tool, bundle, original, audit_path, output):
    tool = tool.resolve(strict=True)
    if output.is_symlink():
        raise ValueError("Artifact destination must not be a symlink")
    output = package_probe.outside_repo(output)
    private_directory(output.parent)
    for source in (bundle.resolve(), original.resolve(), audit_path.parent.resolve()):
        if output == source or source in output.parents or output in source.parents:
            raise ValueError("Keep the artifact separate from its input bundles and audit")
    binding = check_inputs(tool, bundle, original, audit_path)
    payload = hash_payload(binding["signing_public_key_sha256_xy"])
    output.mkdir(mode=0o700)
    with (output / "README.txt").open("x") as warning:
        warning.write(WARNING)
    offline_oracle(tool, payload, output)
    record = review_record(tool, bundle, original, audit_path, binding, payload)
    for name, data in ((PAYLOAD, payload), ("review.json", (json.dumps(record, indent=2) + "\n").encode())):
        with (output / name).open("xb") as target:
            target.write(data)
    prepare_recovery.manifest(output, LIMITS)
    check_artifact(tool, bundle, original, audit_path, output)
    for path in output.iterdir():
        with path.open("rb") as file:
            os.fsync(file.fileno())
    fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-dir", type=Path, help="New private sidecar under provisioning-artifacts")
    mode.add_argument("--check-dir", type=Path, help="Check an existing sidecar; no device access")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        private_directory(restore.BASE)
        if not OUTPUT_PARENT.exists():
            OUTPUT_PARENT.mkdir(mode=0o700)
        private_directory(OUTPUT_PARENT)
        directory = args.output_dir or args.check_dir
        if directory.is_symlink() or directory.resolve().parent != OUTPUT_PARENT.resolve():
            raise ValueError("Use a direct child of the private provisioning-artifacts directory")
        if args.check_dir:
            check_artifact(args.picotool, BUNDLE, restore.KEY_DIR, ROUND_TRIP, directory)
        else:
            prepare(args.picotool, BUNDLE, restore.KEY_DIR, ROUND_TRIP, directory)
        print(f"OFFLINE SLOT-0 HASH ARTIFACT PASS: {directory}")
        print("32 bytes, 16 ECC rows 0x0080–0x008f only. No activation, locks, secrets or device operations.")
        print("Not authorized for programming. New-artifact backup/restore and write review/approval remain required.")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("FATAL: Offline artifact validation failed; do not program partial outputs. Check inputs locally.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
