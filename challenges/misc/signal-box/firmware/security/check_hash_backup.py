#!/usr/bin/env python3
"""Test the five-file artifact archive locally, without GPG/USB/device operations."""

import argparse
import io
import os
from pathlib import Path
import sys
import tempfile

import restore_signing_hash as backup


def check(tool, artifact):
    tool = tool.resolve(strict=True)
    artifact = backup.check_working(tool, artifact)
    sources = [*(artifact / name for name in backup.signing.LIMITS), backup.signing.ROUND_TRIP,
               *backup.signing.BUNDLE.iterdir(), *backup.restore.KEY_DIR.iterdir()]
    before = {p: backup.recovery_images.digest(p) for p in sources}
    with tempfile.TemporaryDirectory(prefix="hash-integration-", dir=backup.local_base()) as temporary:
        parent = Path(temporary)
        stream = io.BytesIO()
        backup.stream_backup(tool, artifact, stream)
        archive = parent / "trusted-local-fixture.tar.gz"
        archive.write_bytes(stream.getvalue())
        if archive.stat().st_size > backup.MAX_BYTES:
            raise ValueError("Generated archive exceeds the profile bound")
        snapshot = parent / "restored"
        # Trusted locally generated fixture, not unauthenticated external data.
        # Production restore always authenticates through GPG before extracting.
        backup.restore.extract_bundle(archive, snapshot, backup.LIMITS, backup.MAX_BYTES)
        backup.verify_snapshot(tool, snapshot, artifact, parent / "artifact-view")
    if parent.exists() or any(backup.recovery_images.digest(p) != value for p, value in before.items()):
        raise ValueError("Staging cleanup or source preservation failed")
    print("OFFLINE HASH BACKUP INTEGRATION PASS: five-file archive/extract/compare, restored journal and hash checks.")
    print("Original artifact, eight-/37-file bundles and journal unchanged; private staging removed.")
    print("No encryption/USB restore performed. This is NOT the operator backup/restore gate; no device was accessed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        check(args.picotool, args.artifact_dir)
    except (OSError, ValueError, KeyError, TypeError):
        print("FATAL: Offline hash-backup integration failed; do not use the archive workflow yet.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
