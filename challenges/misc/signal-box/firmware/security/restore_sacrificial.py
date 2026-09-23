#!/usr/bin/env python3
"""Interactive host-only recovery test; no flash or OTP operations."""

import argparse
import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import zlib

import package_probe
import recovery_images


SERIAL = "9423D016AADE5950"
MOUNT = Path("/run/media/bjames/NOCO_BACKUP")
UUID = "FFEB-102B"
BASE = Path.home() / ".local/share/noco-ctf-2026"
KEY_DIR = BASE / "keys" / f"sacrificial-{SERIAL}"
LIMITS = {
    "signing.pem": 4096,
    "public.pem": 4096,
    "aes-share.bin": 128,
    "iv-salt.bin": 16,
    "probe.elf": 1024 * 1024,
    "metadata.json": 16384,
    "README.txt": 16384,
    "SHA256SUMS": 16384,
}


def check_archive(path, max_bytes=2 * 1024 * 1024):
    path = path.resolve(strict=True)
    result = subprocess.run(
        ["findmnt", "-J", "--target", str(MOUNT), "-o", "TARGET,UUID,FSTYPE"],
        capture_output=True, check=True,
    )
    mounts = json.loads(result.stdout).get("filesystems", [])
    if len(mounts) != 1 or mounts[0] != {"target": str(MOUNT), "uuid": UUID, "fstype": "exfat"}:
        raise ValueError("Mount the prepared NOCO_BACKUP USB; its filesystem identity must match")
    if path.parent != MOUNT.resolve() or not path.name.startswith(f"noco2026-sacrificial-{SERIAL}-"):
        raise ValueError("Select this board's archive directly from the backup USB")
    if not path.is_file() or not path.name.endswith(".tar.gz.gpg") or not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("Expected a small encrypted sacrificial recovery archive")
    return path


def extract_bundle(archive, directory, limits=None, max_bytes=2 * 1024 * 1024):
    """Only call after GPG has fully authenticated the decrypted archive."""
    limits = LIMITS if limits is None else limits
    directory.mkdir(mode=0o700)
    seen = set()
    try:
        with gzip.open(archive, "rb") as compressed:
            raw = compressed.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Recovery archive expands beyond the allowed bundle size")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as source:
            for member in source:
                if member.name not in limits or member.name in seen:
                    raise ValueError("Unexpected or duplicate recovery archive member")
                if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.issparse():
                    raise ValueError("Recovery archive must contain only regular, nonsparse files")
                if not 0 < member.size <= limits[member.name]:
                    raise ValueError("Recovery archive member has an invalid size")
                stream = source.extractfile(member)
                data = stream.read(member.size + 1)
                if len(data) != member.size:
                    raise ValueError("Truncated recovery archive member")
                # Do not honor archive paths, permissions, ownership, or links.
                with (directory / member.name).open("xb") as output:
                    output.write(data)
                (directory / member.name).chmod(0o600)
                seen.add(member.name)
    except (tarfile.TarError, EOFError, zlib.error):
        raise ValueError("Invalid recovery tar archive") from None
    if seen != set(limits):
        raise ValueError("Recovery archive is missing required files")


def verify_bundle(restored, original, limits=None):
    limits = LIMITS if limits is None else limits
    lines = (restored / "SHA256SUMS").read_text().splitlines()
    checked = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match:
            raise ValueError("Invalid recovery integrity manifest")
        digest, name = match.groups()
        if name not in limits or name == "SHA256SUMS" or name in checked:
            raise ValueError("Unexpected or duplicate integrity manifest entry")
        if hashlib.sha256((restored / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Restored bundle failed its integrity manifest")
        checked.add(name)
    if checked != set(limits) - {"SHA256SUMS"}:
        raise ValueError("Integrity manifest does not cover the complete bundle")
    for name in limits:
        path = original / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("Working bundle is missing, symlinked, or not owner-only")
        if (restored / name).read_bytes() != path.read_bytes():
            raise ValueError("Backup differs from the working bundle; investigate before OTP")
    metadata = json.loads((restored / "metadata.json").read_text())
    if metadata.get("device_serial") != SERIAL or metadata.get("purpose") != "sacrificial-test-only; never production":
        raise ValueError("Recovered bundle has the wrong identity or purpose")
    package_probe.check_keys(restored)
    package_probe.check_ram_probe(restored / "probe.elf")


def decrypt(archive, destination, max_bytes=2 * 1024 * 1024):
    env = os.environ.copy()
    env["GPG_TTY"] = os.ttyname(sys.stdin.fileno())
    result = subprocess.run(
        ["gpg", "--no-options", "--no-symkey-cache", "--pinentry-mode", "loopback",
         "--max-output", str(max_bytes), "--yes", "--output", str(destination), "--decrypt", str(archive)],
        env=env, stdout=subprocess.DEVNULL,
    )
    if result.returncode:
        raise ValueError("GPG did not authenticate/decrypt the backup; nothing will be extracted")
    destination.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--prepared", action="store_true", help="Verify the expanded offline-preparation snapshot")
    parser.add_argument("--bundle-dir", type=Path, help="Working snapshot to compare (required with --prepared)")
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print("FATAL: Run in your own terminal; never supply a passphrase through chat or tool logs.", file=sys.stderr)
        return 1
    try:
        if args.prepared and args.bundle_dir is None:
            raise ValueError("Expanded restore requires its exact working snapshot directory")
        original = args.bundle_dir if args.bundle_dir is not None else KEY_DIR
        limits = {**LIMITS, **recovery_images.EXTRA_LIMITS} if args.prepared else LIMITS
        max_bytes = recovery_images.MAX_BUNDLE_BYTES if args.prepared else 2 * 1024 * 1024
        archive = check_archive(args.archive, max_bytes)
        tool = args.picotool.resolve(strict=True)
        base = package_probe.outside_repo(BASE)
        if (not base.is_dir() or base.stat().st_mode & 0o077 or
                base == MOUNT.resolve() or MOUNT.resolve() in base.parents):
            raise ValueError("Recovery staging requires the private local working directory, not USB")
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        print("Retrieve the backup passphrase from Bitwarden. No device will be accessed.")
        with tempfile.TemporaryDirectory(prefix="restore-check-", dir=base) as temp:
            stage = Path(temp)
            if stage.stat().st_mode & 0o077:
                raise ValueError("Recovery staging does not support owner-only permissions")
            plaintext = stage / "recovery.tar.gz"
            decrypt(archive, plaintext, max_bytes)
            restored = stage / "restored"
            extract_bundle(plaintext, restored, limits, max_bytes)
            verify_bundle(restored, original, limits)
            print(f"PASS: all {len(limits)} recovered files match the working bundle; integrity checks passed.")
            if args.prepared:
                recovery_images.check_binding(restored)
                binding = json.loads((restored / "binding.json").read_text())
                if recovery_images.digest(tool) != binding["picotool_binary_sha256"]:
                    raise ValueError("Restore requires the reviewed picotool executable")
                recovery_images.verify_stored_images(tool, restored)
                rebuilt = recovery_images.build_images(tool, restored, stage / "packaged")
                if rebuilt != binding:
                    raise ValueError("Restored image/source/key binding changed")
                print("PASS: recovered keys rebuilt six signed recovery/debug images and the encrypted closed probe.")
            else:
                package_probe.package_probe(tool, restored / "probe.elf", restored, stage / "packaged")
                print("PASS: recovered keys rebuilt a signature-verified encrypted probe; plaintext marker absent.")
            if hashlib.sha256(archive.read_bytes()).hexdigest() != archive_hash:
                raise ValueError("Backup archive changed during verification")
        # Write public evidence only, after both crypto checks and staging cleanup.
        report_dir = base / "recovery-verifications"
        report_dir.mkdir(mode=0o700, exist_ok=True)
        if report_dir.is_symlink() or report_dir.stat().st_mode & 0o077:
            raise ValueError("Recovery report directory must be private and not a symlink")
        now = datetime.datetime.now(datetime.timezone.utc)
        report = report_dir / (now.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + SERIAL + ".json")
        with report.open("x") as output:
            json.dump({
                "verified_utc": now.isoformat(), "device_serial": SERIAL,
                "archive": str(archive), "archive_sha256": archive_hash,
                "backup_uuid": UUID, "files_compared": len(limits),
                "bundle_profile": "prepared-v2" if args.prepared else "initial-v1",
                "gpg_decryption_and_integrity": "PASS", "bundle_match": "PASS",
                "recovered_key_packaging": "PASS", "picotool_version": package_probe.PICOTOOL_VERSION,
                "hardware_or_otp_validation": "NOT PERFORMED",
            }, output, indent=2)
            output.write("\n")
        print(f"RESTORE PASS. Private plaintext staging removed. Receipt: {report}")
        print("No flash/OTP writes. Policy approval does not replace artifact review or staged programming authorization.")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        # Never expose decrypted contents through exception messages or tracebacks.
        print("FATAL: Recovery verification failed. No successful receipt was recorded; do not program OTP.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
