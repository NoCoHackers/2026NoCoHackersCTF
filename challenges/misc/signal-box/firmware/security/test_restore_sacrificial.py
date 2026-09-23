import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import restore_sacrificial as restore


def bundle():
    files = {name: b"test-only data" for name in restore.LIMITS if name != "SHA256SUMS"}
    files["metadata.json"] = json.dumps({
        "device_serial": restore.SERIAL,
        "purpose": "sacrificial-test-only; never production",
    }).encode()
    files["SHA256SUMS"] = b"".join(
        (hashlib.sha256(data).hexdigest() + "  " + name + "\n").encode()
        for name, data in sorted(files.items())
    )
    return files


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="signal-box-restore-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "recovery.tar.gz"
        self.original = self.root / "original"
        self.original.mkdir(mode=0o700)
        self.restored = self.root / "restored"
        self.files = bundle()
        for name, data in self.files.items():
            path = self.original / name
            path.write_bytes(data)
            path.chmod(0o600)

    def write_archive(self, entries=None):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data in entries if entries is not None else self.files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = 0o777  # Archive permissions must not be honored.
                archive.addfile(member, io.BytesIO(data))

    def extract(self):
        restore.extract_bundle(self.archive, self.restored)

    def verify(self):
        # The packaging module tests validate real ELF/key formats separately.
        with patch.object(restore.package_probe, "check_keys"), patch.object(restore.package_probe, "check_ram_probe"):
            restore.verify_bundle(self.restored, self.original)

    def test_valid_bundle_and_private_permissions(self):
        self.write_archive()
        self.extract()
        self.verify()
        self.assertEqual(len(list(self.restored.iterdir())), 8)
        self.assertEqual(os.stat(self.restored).st_mode & 0o777, 0o700)
        self.assertTrue(all(os.stat(p).st_mode & 0o777 == 0o600 for p in self.restored.iterdir()))

    def test_reject_path_traversal(self):
        self.write_archive([("../escape", b"not allowed")])
        with self.assertRaises(ValueError):
            self.extract()
        self.assertFalse((self.root / "escape").exists())

    def test_reject_symlink(self):
        with tarfile.open(self.archive, "w:gz") as archive:
            member = tarfile.TarInfo("signing.pem")
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            archive.addfile(member)
        with self.assertRaises(ValueError):
            self.extract()

    def test_reject_duplicate_and_missing_files(self):
        self.write_archive([("signing.pem", b"first"), ("signing.pem", b"second")])
        with self.assertRaises(ValueError):
            self.extract()
        other = self.root / "other"
        self.write_archive([("signing.pem", b"only file")])
        with self.assertRaises(ValueError):
            restore.extract_bundle(self.archive, other)

    def test_reject_oversized_member(self):
        self.write_archive([("iv-salt.bin", bytes(17))])
        with self.assertRaises(ValueError):
            self.extract()

    def test_reject_compression_bomb(self):
        self.archive.write_bytes(gzip.compress(bytes(2 * 1024 * 1024 + 1)))
        with self.assertRaisesRegex(ValueError, "expands"):
            self.extract()

    def test_reject_corrupt_manifest(self):
        self.write_archive()
        self.extract()
        (self.restored / "signing.pem").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.verify()

    def test_reject_incomplete_manifest(self):
        self.files["SHA256SUMS"] = self.files["SHA256SUMS"].splitlines(keepends=True)[0]
        self.write_archive()
        self.extract()
        with self.assertRaisesRegex(ValueError, "complete"):
            self.verify()

    def test_reject_stale_backup(self):
        self.write_archive()
        self.extract()
        (self.original / "signing.pem").write_bytes(b"new working key")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.verify()

    def test_decryption_failure_stops_before_extraction(self):
        encrypted = self.root / "test.gpg"
        encrypted.write_bytes(b"not real encryption")
        tool = self.root / "picotool"
        tool.touch()
        with patch.object(restore.sys, "argv", ["restore", str(encrypted), "--picotool", str(tool)]), \
             patch.object(restore.sys.stdin, "isatty", return_value=True), \
             patch.object(restore.sys.stderr, "isatty", return_value=True), \
             patch.object(restore, "BASE", self.root), \
             patch.object(restore, "check_archive", return_value=encrypted), \
             patch.object(restore, "decrypt", side_effect=ValueError("authentication failed")), \
             patch.object(restore, "extract_bundle") as extract, \
             patch.object(restore.package_probe, "package_probe") as package, \
             patch.object(restore.sys, "stdout", io.StringIO()), \
             patch.object(restore.sys, "stderr", io.StringIO()):
            # Reapply isatty on the substituted stderr stream.
            with patch.object(restore.sys.stderr, "isatty", return_value=True):
                self.assertEqual(restore.main(), 1)
        extract.assert_not_called()
        package.assert_not_called()
        self.assertFalse((self.root / "recovery-verifications").exists())
        self.assertFalse(list(self.root.glob("restore-check-*")))

    def test_gpg_invocation_never_includes_passphrase(self):
        destination = self.root / "plaintext.tar.gz"
        destination.touch()
        with patch.object(restore.os, "ttyname", return_value="/dev/pts/test"), \
             patch.object(restore.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            restore.decrypt(self.archive, destination)
        command = run.call_args.args[0]
        self.assertIn("--no-symkey-cache", command)
        self.assertIn("--max-output", command)
        self.assertNotIn("--passphrase", command)
        self.assertNotIn("--passphrase-file", command)
        self.assertEqual(command[-2:], ["--decrypt", str(self.archive)])


if __name__ == "__main__":
    unittest.main()
