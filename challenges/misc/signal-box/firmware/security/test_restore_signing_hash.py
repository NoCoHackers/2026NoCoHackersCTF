"""Disposable-fixture tests for the separate five-member hash-backup profile."""

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

import restore_signing_hash as backup


class HashBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hash-backup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mask = os.umask(0o077)
        self.addCleanup(os.umask, self.mask)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(mode=0o700)
        self.working = self.artifacts / "sidecar"
        self.working.mkdir(mode=0o700)
        self.tool = self.root / "tool"
        self.tool.write_bytes(b"fixture tool")
        self.audit = self.root / "live-journal.json"
        self.audit.write_text('{"test_fixture": true}\n')
        self.archive = self.root / (backup.ARCHIVE_PREFIX + "test.tar.gz.gpg")
        self.archive.write_bytes(b"ciphertext fixture")
        self.files = {
            backup.signing.PAYLOAD: bytes(range(32)),
            "README.txt": b"fixture warning\n",
            "review.json": json.dumps({
                "recovery_test_audit_sha256": backup.recovery_images.digest(self.audit),
                "source_bundle_manifest_sha256": "a" * 64,
                "picotool_binary_sha256": backup.recovery_images.digest(self.tool),
            }).encode(),
        }
        self.files["SHA256SUMS"] = b"".join(
            (hashlib.sha256(data).hexdigest() + "  " + name + "\n").encode()
            for name, data in sorted(self.files.items()))
        for name, data in self.files.items():
            (self.working / name).write_bytes(data)
        for target, name, value in (
            (backup.restore, "BASE", self.root),
            (backup.signing, "OUTPUT_PARENT", self.artifacts),
            (backup.signing, "ROUND_TRIP", self.audit),
        ):
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        # The separately tested signing validator does real key/tool/image checks.
        # This fixture validator tests the added archive and journal data flow.
        p = patch.object(backup.signing, "check_artifact", side_effect=self.validate_fixture)
        self.validator = p.start()
        self.addCleanup(p.stop)

    def validate_fixture(self, tool, bundle, original, audit, artifact):
        self.assertEqual(tool, self.tool)
        self.assertEqual({p.name for p in artifact.iterdir()}, set(backup.signing.LIMITS))
        record = json.loads((artifact / "review.json").read_text())
        if record["recovery_test_audit_sha256"] != backup.recovery_images.digest(audit):
            raise ValueError("journal binding changed")
        if (artifact / backup.signing.PAYLOAD).read_bytes() != bytes(range(32)):
            raise ValueError("fixture payload changed")

    def compressed_backup(self):
        stream = io.BytesIO()
        backup.stream_backup(self.tool, self.working, stream)
        return stream.getvalue()

    def unpack(self, data, name="unpacked"):
        archive = self.root / (name + ".tar.gz")
        archive.write_bytes(data)
        directory = self.root / name
        backup.restore.extract_bundle(archive, directory, backup.LIMITS, backup.MAX_BYTES)
        return directory

    def raw_archive(self, entries):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, data in entries:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return stream.getvalue()

    def test_valid_snapshot_exact_members_private_and_inputs_unchanged(self):
        before = {p: p.read_bytes() for p in self.working.iterdir()}
        before[self.audit] = self.audit.read_bytes()
        snapshot = self.unpack(self.compressed_backup())
        self.assertEqual({p.name for p in snapshot.iterdir()}, set(backup.LIMITS))
        self.assertEqual(len(list(snapshot.iterdir())), 5)
        evidence = backup.verify_snapshot(self.tool, snapshot, self.working, self.root / "view")
        self.assertEqual(evidence["recovery_journal_sha256"], backup.recovery_images.digest(self.audit))
        self.assertEqual(evidence["required_key_bundle_manifest_sha256"], "a" * 64)
        for p in snapshot.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        for p, data in before.items():
            self.assertEqual(p.read_bytes(), data)
        self.assertFalse(list(self.root.glob("hash-backup-*")))

    def test_restore_uses_archived_journal_not_live_journal(self):
        snapshot = self.unpack(self.compressed_backup())
        self.audit.unlink()
        backup.verify_snapshot(self.tool, snapshot, self.working, self.root / "view")
        self.assertEqual(self.validator.call_args.args[3], snapshot / backup.AUDIT_MEMBER)

    def test_changed_archived_journal_rejected(self):
        snapshot = self.unpack(self.compressed_backup())
        (snapshot / backup.AUDIT_MEMBER).write_text('{"different": true}')
        with self.assertRaises(ValueError):
            backup.verify_snapshot(self.tool, snapshot, self.working, self.root / "view")

    def test_stale_artifact_rejected(self):
        snapshot = self.unpack(self.compressed_backup())
        (self.working / backup.signing.PAYLOAD).write_bytes(b"x" * 32)
        with self.assertRaisesRegex(ValueError, "differs"):
            backup.verify_snapshot(self.tool, snapshot, self.working, self.root / "view")

    def test_invalid_working_input_never_streams_tar(self):
        (self.working / backup.signing.PAYLOAD).write_bytes(b"x" * 32)
        stream = io.BytesIO()
        with self.assertRaises(ValueError):
            backup.stream_backup(self.tool, self.working, stream)
        self.assertEqual(stream.getvalue(), b"")
        self.assertFalse(list(self.root.glob("hash-backup-*")))

    def test_stream_reads_frozen_copy_not_working_files(self):
        real_open = tarfile.open

        def mutate(*args, **kwargs):
            (self.working / backup.signing.PAYLOAD).write_bytes(b"x" * 32)
            return real_open(*args, **kwargs)

        stream = io.BytesIO()
        with patch.object(backup.tarfile, "open", side_effect=mutate):
            backup.stream_backup(self.tool, self.working, stream)
        snapshot = self.unpack(stream.getvalue())
        self.assertEqual((snapshot / backup.signing.PAYLOAD).read_bytes(), bytes(range(32)))

    def test_reject_extra_missing_duplicate_and_traversal_members(self):
        entries = list(self.files.items()) + [(backup.AUDIT_MEMBER, self.audit.read_bytes())]
        cases = (entries + [("signing.pem", b"not allowed")], entries[:-1],
                 entries + [entries[0]], [("../escape", b"not allowed")])
        for i, values in enumerate(cases):
            with self.subTest(i=i), self.assertRaises(ValueError):
                self.unpack(self.raw_archive(values), f"case{i}")
        self.assertFalse((self.root / "escape").exists())

    def test_old_key_profile_does_not_accept_new_members(self):
        archive = self.root / "artifact.tar.gz"
        archive.write_bytes(self.compressed_backup())
        with self.assertRaises(ValueError):
            backup.restore.extract_bundle(archive, self.root / "old-profile")
        with self.assertRaises(ValueError):
            backup.restore.extract_bundle(archive, self.root / "old-prepared-profile",
                                          backup.prepare_recovery.PREPARED_LIMITS,
                                          backup.recovery_images.MAX_BUNDLE_BYTES)
        self.assertEqual(len(backup.restore.LIMITS), 8)
        self.assertEqual(len(backup.prepare_recovery.PREPARED_LIMITS), 37)

    def test_archive_size_and_wrong_profile(self):
        with patch.object(backup.restore, "check_archive", return_value=self.archive) as check:
            self.assertEqual(backup.check_archive(self.archive), self.archive)
            check.assert_called_once_with(self.archive, backup.MAX_BYTES)
        old = self.root / f"noco2026-sacrificial-{backup.restore.SERIAL}-old.tar.gz.gpg"
        with patch.object(backup.restore, "check_archive", return_value=old), self.assertRaises(ValueError):
            backup.check_archive(old)
        with self.assertRaises(ValueError):
            self.unpack(gzip.compress(bytes(backup.MAX_BYTES + 1)))

    def test_reject_archive_links_and_oversized_journal(self):
        for i, kind in enumerate((tarfile.SYMTYPE, tarfile.LNKTYPE)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                member = tarfile.TarInfo(backup.AUDIT_MEMBER)
                member.type, member.linkname = kind, "/etc/passwd"
                archive.addfile(member)
            with self.assertRaises(ValueError):
                self.unpack(stream.getvalue(), f"link{i}")
        entries = [(backup.AUDIT_MEMBER, b"x" * (backup.LIMITS[backup.AUDIT_MEMBER] + 1))]
        with self.assertRaises(ValueError):
            self.unpack(self.raw_archive(entries), "big")

    def test_nonprivate_and_symlinked_working_paths_rejected(self):
        self.working.chmod(0o755)
        with self.assertRaises(ValueError):
            backup.artifact_directory(self.working)
        self.working.chmod(0o700)
        alias = self.artifacts / "alias"
        alias.symlink_to(self.working, target_is_directory=True)
        with self.assertRaises(ValueError):
            backup.artifact_directory(alias)
        with self.assertRaises(ValueError):
            backup.artifact_directory(self.root)

    def test_auth_failure_prevents_extraction_and_receipt(self):
        def fail(archive, output, maximum):
            output.write_bytes(b"unauthenticated partial data")
            raise ValueError("authentication failed")

        with patch.object(backup, "check_archive", return_value=self.archive), \
             patch.object(backup.restore, "decrypt", side_effect=fail), \
             patch.object(backup.restore, "extract_bundle") as extract, \
             patch.object(backup, "verify_snapshot") as verify, \
             patch.object(backup.sys, "stdout", io.StringIO()):
            with self.assertRaises(ValueError):
                backup.restore_archive(self.tool, self.archive, self.working)
        extract.assert_not_called()
        verify.assert_not_called()
        self.assertFalse((self.root / "hash-artifact-verifications").exists())
        self.assertFalse(list(self.root.glob("hash-restore-*")))

    def test_authenticated_restore_cleanup_then_scoped_receipt(self):
        data = self.compressed_backup()
        self.audit.unlink()
        events = []
        real_extract = backup.restore.extract_bundle

        def decrypt(archive, output, maximum):
            self.assertEqual(maximum, backup.MAX_BYTES)
            output.write_bytes(data)
            events.append("authenticated")

        def extract(*args):
            self.assertEqual(events, ["authenticated"])
            events.append("extracted")
            return real_extract(*args)

        with patch.object(backup, "check_archive", return_value=self.archive), \
             patch.object(backup.restore, "decrypt", side_effect=decrypt), \
             patch.object(backup.restore, "extract_bundle", side_effect=extract), \
             patch.object(backup.sys, "stdout", io.StringIO()):
            report = backup.restore_archive(self.tool, self.archive, self.working)
        self.assertFalse(list(self.root.glob("hash-restore-*")))
        record = json.loads(report.read_text())
        self.assertEqual(record["files_restored"], 5)
        self.assertEqual(record["artifact_files_compared"], 4)
        self.assertEqual(record["bundle_profile"], "slot0-hash-v1")
        self.assertIs(record["authorized_for_programming"], False)
        self.assertTrue(record["key_archive_restore"].startswith("NOT PERFORMED"))
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)

    def test_changed_archive_never_gets_receipt(self):
        data = self.compressed_backup()
        real_verify = backup.verify_snapshot

        def verify(*args):
            evidence = real_verify(*args)
            self.archive.write_bytes(b"changed ciphertext")
            return evidence

        with patch.object(backup, "check_archive", return_value=self.archive), \
             patch.object(backup.restore, "decrypt", side_effect=lambda a, p, m: p.write_bytes(data)), \
             patch.object(backup, "verify_snapshot", side_effect=verify), \
             patch.object(backup.sys, "stdout", io.StringIO()):
            with self.assertRaisesRegex(ValueError, "changed"):
                backup.restore_archive(self.tool, self.archive, self.working)
        self.assertFalse(list(self.root.glob("hash-restore-*")))
        self.assertFalse((self.root / "hash-artifact-verifications").exists())

    def test_noninteractive_restore_and_stream_refused(self):
        for mode in ([str(self.archive), "--artifact-dir", str(self.working)],
                     ["--stream-artifact", str(self.working)]):
            with patch.object(backup.sys, "argv", ["restore", *mode, "--picotool", str(self.tool)]), \
                 patch.object(backup.sys.stdin, "isatty", return_value=False), \
                 patch.object(backup.sys, "stderr", io.StringIO()), \
                 patch.object(backup, "stream_backup") as stream, \
                 patch.object(backup, "restore_archive") as restore:
                self.assertEqual(backup.main(), 1)
                stream.assert_not_called()
                restore.assert_not_called()

    def test_list_mode_five_members_without_decryption(self):
        with patch.object(backup.sys, "argv", ["restore", "--list-files", str(self.working),
                                                "--picotool", str(self.tool)]), \
             patch.object(backup.sys, "stdout", io.StringIO()) as output, \
             patch.object(backup.restore, "decrypt") as decrypt:
            self.assertEqual(backup.main(), 0)
            self.assertEqual(set(output.getvalue().splitlines()), set(backup.LIMITS))
            decrypt.assert_not_called()

    def test_mixed_cli_modes_fail_before_any_work(self):
        for mode in ("--list-files", "--stream-artifact"):
            with patch.object(backup.sys, "argv", ["restore", str(self.archive), mode, str(self.working),
                                                   "--picotool", str(self.tool)]), \
                 patch.object(backup.sys, "stderr", io.StringIO()), \
                 patch.object(backup, "check_working") as check, \
                 patch.object(backup, "stream_backup") as stream, \
                 patch.object(backup, "restore_archive") as restore:
                self.assertEqual(backup.main(), 1)
                check.assert_not_called()
                stream.assert_not_called()
                restore.assert_not_called()

    def test_receipt_write_failure_leaves_no_final_receipt(self):
        report = self.root / "receipt.json"

        def fail(record, output, **kwargs):
            output.write('{"partial":')
            raise OSError("write failed")

        with patch.object(backup.json, "dump", side_effect=fail), self.assertRaises(OSError):
            backup.publish_receipt(report, {"authorized_for_programming": False})
        self.assertFalse(report.exists())
        self.assertFalse(list(self.root.glob(".hash-receipt-*")))

    def test_receipt_flush_failure_leaves_no_final_receipt(self):
        report = self.root / "receipt.json"
        real_fdopen = os.fdopen

        class FlushFailure:
            def __init__(self, file):
                self.file = file

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.file.close()

            def write(self, text):
                return self.file.write(text)

            def flush(self):
                raise OSError("flush failed")

        with patch.object(backup.os, "fdopen", side_effect=lambda *args: FlushFailure(real_fdopen(*args))), \
             self.assertRaises(OSError):
            backup.publish_receipt(report, {"authorized_for_programming": False})
        self.assertFalse(report.exists())
        self.assertFalse(list(self.root.glob(".hash-receipt-*")))

    def test_receipt_file_sync_failure_leaves_no_final_receipt(self):
        report = self.root / "receipt.json"
        with patch.object(backup.os, "fsync", side_effect=OSError("file sync failed")), \
             self.assertRaises(OSError):
            backup.publish_receipt(report, {"authorized_for_programming": False})
        self.assertFalse(report.exists())
        self.assertFalse(list(self.root.glob(".hash-receipt-*")))

    def test_receipt_directory_sync_failure_reports_published_state(self):
        report = self.root / "receipt.json"
        record = {"authorized_for_programming": False}
        with patch.object(backup.os, "fsync", side_effect=[None, OSError("directory sync failed")]), \
             self.assertRaises(backup.ReceiptPublicationError):
            backup.publish_receipt(report, record)
        self.assertEqual(json.loads(report.read_text()), record)
        self.assertFalse(list(self.root.glob(".hash-receipt-*")))
        with patch.object(backup.sys, "argv", ["restore", str(self.archive), "--artifact-dir", str(self.working),
                                               "--picotool", str(self.tool)]), \
             patch.object(backup.sys.stdin, "isatty", return_value=True), \
             patch.object(backup.sys, "stderr", io.StringIO()) as error, \
             patch.object(backup, "restore_archive", side_effect=backup.ReceiptPublicationError(str(report))):
            with patch.object(backup.sys.stderr, "isatty", return_value=True):
                self.assertEqual(backup.main(), 1)
            self.assertIn("receipt was published", error.getvalue())
            self.assertNotIn("No new successful restore receipt", error.getvalue())

    def test_final_print_failure_preserves_published_receipt_state(self):
        data = self.compressed_backup()
        real_print = print
        for prefix in ("HASH ARTIFACT RESTORE PASS", "Keep the separate key archives"):
            def fail_print(*args, **kwargs):
                if args and str(args[0]).startswith(prefix):
                    raise OSError("output failed")
                return real_print(*args, **kwargs)

            with patch.object(backup, "check_archive", return_value=self.archive), \
                 patch.object(backup.restore, "decrypt", side_effect=lambda a, p, m: p.write_bytes(data)), \
                 patch.object(backup.sys, "stdout", io.StringIO()), \
                 patch("builtins.print", side_effect=fail_print):
                with self.assertRaises(backup.ReceiptPublicationError) as error:
                    backup.restore_archive(self.tool, self.archive, self.working)
                self.assertEqual(error.exception.operation, "final status output")
                report = Path(str(error.exception))
                self.assertIs(json.loads(report.read_text())["authorized_for_programming"], False)
                self.assertFalse(list(self.root.glob("hash-restore-*")))

    def test_receipt_publication_never_replaces_an_existing_receipt(self):
        report = self.root / "receipt.json"
        report.write_bytes(b"existing receipt")
        with self.assertRaises(FileExistsError):
            backup.publish_receipt(report, {"authorized_for_programming": False})
        self.assertEqual(report.read_bytes(), b"existing receipt")
        self.assertFalse(list(self.root.glob(".hash-receipt-*")))

    def test_archive_publication_exact_destination_never_moves_inside_directory(self):
        script = Path(backup.__file__).with_name("backup_sacrificial.sh")
        self.assertIn('mv -nT -- "$TEMP" "$OUT"', script.read_text())
        source, target = self.root / "pending", self.root / "existing-directory"
        source.write_bytes(b"ciphertext fixture")
        target.mkdir()
        subprocess.run(["mv", "-nT", "--", str(source), str(target)], capture_output=True)
        self.assertTrue(source.exists())
        self.assertEqual(list(target.iterdir()), [])
        existing = self.root / "existing-file"
        existing.write_bytes(b"earlier archive")
        subprocess.run(["mv", "-nT", "--", str(source), str(existing)], capture_output=True)
        self.assertTrue(source.exists())
        self.assertEqual(existing.read_bytes(), b"earlier archive")

    def test_shell_syntax_and_explicit_profile_requires_path(self):
        script = Path(backup.__file__).with_name("backup_sacrificial.sh")
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        result = subprocess.run(["bash", str(script), "--hash-artifact"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"exact-sidecar-directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
