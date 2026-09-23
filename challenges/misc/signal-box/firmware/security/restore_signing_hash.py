#!/usr/bin/env python3
"""Back up/restore a hash-artifact sidecar and its bound journal; host-only."""

import argparse
import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

import prepare_recovery
import prepare_signing_hash as signing
import recovery_images
import restore_sacrificial as restore

PROFILE = "slot0-hash-v1"
AUDIT_MEMBER = "recovery-round-trip.json"
LIMITS = {**signing.LIMITS, AUDIT_MEMBER: 65536}
MAX_BYTES = 256 * 1024
ARCHIVE_PREFIX = f"noco2026-sacrificial-{restore.SERIAL}-{PROFILE}-"


def local_base():
    base = signing.private_directory(restore.BASE)
    mount = restore.MOUNT.resolve()
    if base == mount or mount in base.parents:
        raise ValueError("Use private local staging, not the backup USB")
    return base


def artifact_directory(path):
    parent = signing.private_directory(signing.OUTPUT_PARENT)
    if path.is_symlink() or path.resolve().parent != parent:
        raise ValueError("Select an exact private provisioning-artifacts sidecar")
    return signing.private_directory(path)


def check_working(tool, artifact):
    artifact = artifact_directory(artifact)
    signing.check_artifact(tool, signing.BUNDLE, restore.KEY_DIR, signing.ROUND_TRIP, artifact)
    return artifact


def verify_snapshot(tool, snapshot, working, view):
    """Validate restored bytes using the restored journal, not the live journal."""
    signing.private_directory(snapshot)
    signing.private_directory(working)
    if {p.name for p in snapshot.iterdir()} != set(LIMITS):
        raise ValueError("Unexpected hash-backup members")
    if {p.name for p in working.iterdir()} != set(signing.LIMITS):
        raise ValueError("Unexpected working artifact members")
    for name, limit in LIMITS.items():
        signing.private_file(snapshot / name, limit)
    view.mkdir(mode=0o700)
    for name, limit in signing.LIMITS.items():
        signing.private_file(working / name, limit)
        prepare_recovery.copy_regular(snapshot / name, view / name, limit)
        if (view / name).read_bytes() != (working / name).read_bytes():
            raise ValueError("Recovered artifact differs from the working sidecar")
    # The existing validator derives the payload from the preserved key pair,
    # reinspects stored images, and checks the recovered journal's bound hash.
    signing.check_artifact(tool, signing.BUNDLE, restore.KEY_DIR,
                           snapshot / AUDIT_MEMBER, view)
    reviewed = json.loads((view / "review.json").read_text())
    return {
        "artifact_manifest_sha256": recovery_images.digest(view / "SHA256SUMS"),
        "recovery_journal_sha256": recovery_images.digest(snapshot / AUDIT_MEMBER),
        "required_key_bundle_manifest_sha256": reviewed["source_bundle_manifest_sha256"],
        "picotool_binary_sha256": reviewed["picotool_binary_sha256"],
    }


def stream_backup(tool, artifact, output):
    """Write only a validated, private snapshot to a caller-supplied tar stream."""
    tool = tool.resolve(strict=True)
    base = local_base()
    artifact = check_working(tool, artifact)
    with tempfile.TemporaryDirectory(prefix="hash-backup-", dir=base) as temporary:
        parent = Path(temporary)
        snapshot = parent / "snapshot"
        snapshot.mkdir(mode=0o700)
        for name, limit in signing.LIMITS.items():
            prepare_recovery.copy_regular(artifact / name, snapshot / name, limit)
        prepare_recovery.copy_regular(signing.ROUND_TRIP, snapshot / AUDIT_MEMBER, LIMITS[AUDIT_MEMBER])
        verify_snapshot(tool, snapshot, artifact, parent / "artifact-view")
        # Tar reads the validated private copy, never mutable working files.
        # No plaintext archive is written to USB or to a named local file here.
        with tarfile.open(fileobj=output, mode="w|gz") as archive:
            for name in sorted(LIMITS):
                data = (snapshot / name).read_bytes()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o600
                archive.addfile(member, io.BytesIO(data))


def check_archive(path):
    archive = restore.check_archive(path, MAX_BYTES)
    if not archive.name.startswith(ARCHIVE_PREFIX):
        raise ValueError("Select this board's slot0-hash-v1 archive, not a key archive")
    return archive


class ReceiptPublicationError(RuntimeError):
    """Validation passed and a receipt exists, but completion encountered I/O failure."""

    def __init__(self, report, operation="receipt directory synchronization"):
        super().__init__(str(report))
        self.operation = operation


def publish_receipt(report, record):
    # Final names appear only after a complete, fsynced file. link() refuses
    # collisions atomically; unlike rename(), it cannot replace an old receipt.
    fd, name = tempfile.mkstemp(prefix=".hash-receipt-", suffix=".partial", dir=report.parent)
    pending = Path(name)
    published = False
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(record, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(pending, report)
        published = True
        directory_fd = os.open(report.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        if published:
            raise ReceiptPublicationError(str(report)) from None
        raise
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            try:
                print("WARNING: Private pending-receipt cleanup failed; inspect the report directory locally.",
                      file=sys.stderr)
            except OSError:
                pass  # A failed warning must not misreport the publication state.


def restore_archive(tool, archive, working):
    """Authenticate, extract, validate, clean up, then publish a scoped receipt."""
    tool = tool.resolve(strict=True)
    base = local_base()
    working = artifact_directory(working)
    archive = check_archive(archive)
    archive_hash = recovery_images.digest(archive)
    print("Retrieve the backup passphrase from Bitwarden. No device will be accessed.")
    with tempfile.TemporaryDirectory(prefix="hash-restore-", dir=base) as temporary:
        parent = Path(temporary)
        plaintext = parent / "artifact.tar.gz"
        # GPG must return success before the archive is parsed at all.
        restore.decrypt(archive, plaintext, MAX_BYTES)
        snapshot = parent / "restored"
        restore.extract_bundle(plaintext, snapshot, LIMITS, MAX_BYTES)
        evidence = verify_snapshot(tool, snapshot, working, parent / "artifact-view")
        if recovery_images.digest(archive) != archive_hash:
            raise ValueError("Encrypted archive changed during verification")
        print("PASS: four recovered artifact files match; the fifth file is their verified bound journal.")
        print("PASS: restored hash data rederived from preserved keys; exact scope and offline ECC checks passed.")
    # A sidecar-only receipt must never be mistaken for recovered-key packaging
    # or approval to program. The separate key archives are still required.
    report_dir = base / "hash-artifact-verifications"
    report_dir.mkdir(mode=0o700, exist_ok=True)
    signing.private_directory(report_dir)
    now = datetime.datetime.now(datetime.timezone.utc)
    report = report_dir / (now.strftime("%Y%m%dT%H%M%S.%fZ") + "-" + restore.SERIAL + ".json")
    record = {
        "verified_utc": now.isoformat(), "device_serial": restore.SERIAL,
        "archive": str(archive), "archive_sha256": archive_hash,
        "backup_uuid": restore.UUID, "bundle_profile": PROFILE,
        "files_restored": 5, "artifact_files_compared": 4,
        **evidence,
        "gpg_decryption_and_integrity": "PASS", "artifact_match_and_rederivation": "PASS",
        "bound_recovery_journal": "PASS", "private_plaintext_staging_removed": True,
        "key_archive_restore": "NOT PERFORMED; this archive contains no private keys",
        "backup_restore_helper_sha256": recovery_images.digest(Path(__file__)),
        "hardware_or_otp_validation": "NOT PERFORMED", "authorized_for_programming": False,
    }
    publish_receipt(report, record)
    try:
        print(f"HASH ARTIFACT RESTORE PASS. Private plaintext staging removed. Receipt: {report}")
        print("Keep the separate key archives. No device/OTP operations or programming authorization.")
    except OSError:
        raise ReceiptPublicationError(report, "final status output") from None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-files", type=Path, help="Validate working inputs; list the five archive members")
    mode.add_argument("--stream-artifact", type=Path, help="Internal backup mode: gzip tar to stdout, local TTY required")
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.list_files or args.stream_artifact:
            if args.archive is not None or args.artifact_dir is not None:
                raise ValueError("Use exactly one backup/list or restore mode")
        elif args.archive is None or args.artifact_dir is None:
            raise ValueError("Restore requires the exact archive and --artifact-dir")
        tool = args.picotool.resolve(strict=True)
        if args.list_files:
            local_base()
            check_working(tool, args.list_files)
            print("\n".join(sorted(LIMITS)))
        else:
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise ValueError("Run in your own terminal; never put passphrases in chat or tool logs")
            if args.stream_artifact:
                stream_backup(tool, args.stream_artifact, sys.stdout.buffer)
            else:
                restore_archive(tool, args.archive, args.artifact_dir)
    except ReceiptPublicationError as error:
        print(f"FATAL: Restore validation passed, but {error.operation} failed. "
              f"A receipt was published at {error}; retain it for inspection and do not program OTP.",
              file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("FATAL: Hash-artifact backup/restore failed; check the mode, private inputs and USB locally. "
              "Use your own terminal for encryption/restore. No new successful restore receipt; do not program OTP.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
