#!/usr/bin/env python3
"""Prepare a new private lab recovery snapshot; never flash or program OTP."""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import otp_policy
import package_probe
import recovery_images
import restore_sacrificial as restore

HERE = Path(__file__).resolve().parent
PREPARED_LIMITS = {**restore.LIMITS, **recovery_images.EXTRA_LIMITS}


def private_directory(path):
    if path.is_symlink():
        raise ValueError("Private working directory must not be a symlink")
    path = package_probe.outside_repo(path)
    if not path.is_dir() or path.stat().st_mode & 0o077:
        raise ValueError("Private working directory must be owner-only")
    return path


def copy_regular(source, target, limit):
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= limit:
        raise ValueError("Missing, symlinked or oversized input")
    with target.open("xb") as output:
        output.write(source.read_bytes())
    target.chmod(0o600)


def manifest(directory, limits):
    lines = []
    for name in sorted(set(limits) - {"SHA256SUMS"}):
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limits[name]:
            raise ValueError("Incomplete prepared bundle")
        path.chmod(0o600)
        lines.append(recovery_images.digest(path) + "  " + name + "\n")
    (directory / "SHA256SUMS").write_text("".join(lines))
    (directory / "SHA256SUMS").chmod(0o600)


def check_working(directory):
    directory = private_directory(directory)
    names = {p.name for p in directory.iterdir()}
    if names == set(restore.LIMITS):
        limits = restore.LIMITS
    elif names == set(PREPARED_LIMITS):
        limits = PREPARED_LIMITS
    else:
        raise ValueError("Working bundle must match an exact supported file allowlist")
    for name, limit in limits.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError("Working bundle has an invalid file")
    restore.verify_bundle(directory, directory, limits)
    if limits is PREPARED_LIMITS:
        recovery_images.check_binding(directory)
    return limits


def prepare(tool, original, sources, output):
    original = private_directory(original)
    if check_working(original) != restore.LIMITS:
        raise ValueError("Preparation must start from the preserved initial eight-file bundle")
    # Snapshot, never upgrade the sole working key bundle in place.
    output = package_probe.outside_repo(output)
    if output == original or original in output.parents or output in original.parents:
        raise ValueError("Prepared snapshot must be separate from the original key directory")
    private_directory(output.parent)
    output.mkdir(mode=0o700)
    for name, limit in restore.LIMITS.items():
        copy_regular(original / name, output / name, limit)
    restore.verify_bundle(output, original)
    copy_regular(output / "SHA256SUMS", output / "ORIGINAL-SHA256SUMS", 16384)
    (output / "BUNDLE-README.txt").write_text(
        "PRIVATE SACRIFICIAL LAB SNAPSHOT. DO NOT FLASH OR LOAD OTP FROM THIS BUNDLE.\n"
        "No hardware tests or provisioning have been performed.\n"
        "The original eight-file key bundle and its prior USB backup remain unchanged.\n"
        "policy.json is review data, NOT picotool OTP JSON. No loadable OTP recipes exist here.\n"
        "*-flash.uf2: signed plaintext ARM SRAM application, flash storage, clear-on-load.\n"
        "*-ram.uf2: separately signed SRAM rescue, NO whole-SRAM clear; lab-only.\n"
        "encrypted-debug-closed.uf2: matching-key encrypted closed probe, NOT hardware validated.\n"
        "debug-reopen is plaintext signed only; NEVER publish an event-key-signed unlocker early.\n"
        "Restore and rebuild all images before staged hardware approval.\n"
        "This snapshot is not a completed post-provisioning recovery record.\n"
    )
    for profile in recovery_images.PROFILES:
        recovery_images.check_profile(sources[profile], profile)
        copy_regular(sources[profile], output / (profile + ".elf"), 1024 * 1024)
    (output / "policy.json").write_text(json.dumps(otp_policy.proposal(), indent=2) + "\n")
    copy_regular(HERE / "PROVISIONING-PLAN.md", output / "PROVISIONING-PLAN.md", 65536)
    images = output / "image-staging"
    binding = recovery_images.build_images(tool, output, images)
    for path in images.iterdir():
        if path.name not in recovery_images.EXTRA_LIMITS:
            raise ValueError("Unexpected packaging output")
        path.rename(output / path.name)
    images.rmdir()
    (output / "binding.json").write_text(json.dumps(binding, indent=2) + "\n")
    manifest(output, PREPARED_LIMITS)
    check_working(output)
    # No plaintext tar on USB: the interactive backup helper creates ciphertext.
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--list-files", type=Path, help="Validate a working bundle and print only its allowed member names")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.list_files is not None:
            for name in sorted(check_working(args.list_files)):
                print(name)
            return 0
        parent = package_probe.outside_repo(restore.BASE / "recovery-bundles")
        private_directory(restore.BASE)
        parent.mkdir(mode=0o700, exist_ok=True)
        private_directory(parent)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        output = args.output_dir or parent / f"sacrificial-{otp_policy.SERIAL}-prepared-{stamp}"
        if output.resolve().parent != parent.resolve():
            raise ValueError("Keep plaintext preparation under the private local recovery-bundles directory, not USB")
        sources = {p: HERE.parent / "debug" / ("build-rp2350-" + p) / "signal-box-debug-rp2350.elf"
                   for p in recovery_images.PROFILES}
        result = prepare(args.picotool, restore.KEY_DIR, sources, output)
        print(f"PREPARATION PASS: {result}")
        print(f"{len(PREPARED_LIMITS)} private files; six signed UF2s and one encrypted closed UF2 verified offline.")
        print("Original keys unchanged. No flash/OTP writes. Next: encrypted USB backup and expanded restore test.")
    except (OSError, ValueError, subprocess.SubprocessError):
        # Partial directories stay private for investigation; never leak key/tool output.
        print("FATAL: Preparation/validation failed; keep partial outputs off devices and inspect inputs locally.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
