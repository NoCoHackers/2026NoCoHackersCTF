#!/usr/bin/env python3
"""Host-only slot-0 artifact tests. No real keys or device access."""

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import prepare_signing_hash as stage


class EncodingTests(unittest.TestCase):
    def test_digest_byte_order_and_extent(self):
        payload = stage.hash_payload(bytes(range(32)).hex())
        rows = stage.row_plan(payload)
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]["row"], "0x0080")
        self.assertEqual(rows[0]["after_ecc16"], "0x0100")
        self.assertEqual(rows[-1]["row"], "0x008f")
        self.assertEqual(rows[-1]["after_ecc16"], "0x1f1e")
        self.assertTrue(all(r["before_raw24"] == "0x000000" for r in rows))

    def test_reject_noncanonical_or_wrong_size_hash(self):
        for value in (None, 32, "ab" * 31, "ab" * 33, "AB" * 32, "zz" * 32):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                stage.hash_payload(value)
        for value in (b"", b"x" * 31, b"x" * 33, bytearray(32)):
            with self.assertRaises(ValueError):
                stage.row_plan(value)

    def test_ecc_known_vectors_and_bounds(self):
        for value, expected in ((0, 0), (1, 0x230001), (0xffff, 0x1effff)):
            self.assertEqual(stage.ecc24(value), expected)
        for value in (-1, 65536, True, 1.0):
            with self.assertRaises(ValueError):
                stage.ecc24(value)
        for value in range(65536):
            self.assertEqual(stage.ecc24(value) & 0xffff, value)
            self.assertLess(stage.ecc24(value), 1 << 22)

    def test_oracle_requires_exact_physical_scope_and_padding(self):
        payload = bytes(range(32))
        raw = bytearray(16384)
        for row in stage.row_plan(payload):
            struct.pack_into("<I", raw, int(row["row"], 16) * 4, int(row["after_raw24"], 16))
        stage.check_oracle_dump(raw, payload)
        for offset in (0, 0x80 * 4, 0x80 * 4 + 3, 0x90 * 4, 0xfff * 4):
            broken = bytearray(raw)
            broken[offset] ^= 1
            with self.assertRaises(ValueError):
                stage.check_oracle_dump(broken, payload)
        with self.assertRaises(ValueError):
            stage.check_oracle_dump(raw[:-1], payload)

    def test_oracle_always_has_file_input_and_no_device_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            tool = parent / "tool"
            tool.write_bytes(b"fixture")
            payload = bytes(range(32))

            def run(selected, *args):
                self.assertEqual(selected, tool.resolve())
                self.assertEqual(args[:4], ("otp", "dump", "-r", "--output"))
                self.assertEqual(len(args), 6)
                data = json.loads(args[5].read_text())
                self.assertEqual(data, {"bootkey0": list(payload)})
                raw = bytearray(16384)
                for row in stage.row_plan(payload):
                    struct.pack_into("<I", raw, int(row["row"], 16) * 4, int(row["after_raw24"], 16))
                args[4].write_bytes(raw)
                return b""

            with mock.patch.object(stage.package_probe, "run_tool", side_effect=run):
                stage.offline_oracle(tool, payload, parent)
            self.assertEqual({p.name for p in parent.iterdir()}, {"tool"})


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mask = os.umask(0o077)
        self.addCleanup(os.umask, self.mask)
        self.bundle, self.original = self.root / "bundle", self.root / "original"
        for directory, limits in ((self.bundle, stage.prepare_recovery.PREPARED_LIMITS),
                                  (self.original, stage.restore.LIMITS)):
            directory.mkdir(mode=0o700)
            for name in limits:
                (directory / name).write_bytes(b"fixture")
        self.tool = self.root / "picotool"
        self.tool.write_bytes(b"pinned fixture tool")
        self.output = self.root / "sidecar"
        self.audit_dir = self.root / "audit"
        self.audit_dir.mkdir(mode=0o700)
        self.audit_path = self.audit_dir / "stage.json"
        self.key_hash = bytes(range(32)).hex()
        self.binding = {
            "original_manifest_sha256": stage.recovery_images.digest(self.original / "SHA256SUMS"),
            "signing_public_key_sha256_xy": self.key_hash,
            "picotool_binary_sha256": stage.recovery_images.digest(self.tool),
        }
        (self.bundle / "binding.json").write_text(json.dumps(self.binding))
        self.audit = {
            "status": "UNPROVISIONED_RECOVERY_ROUND_TRIP_PASS", "device_serial": stage.otp_policy.SERIAL,
            "source_bundle": str(self.bundle), "image_file": "debug-closed-ram.uf2",
            "image_sha256": stage.recovery_images.digest(self.bundle / "debug-closed-ram.uf2"),
            "flash_writes": False, "otp_writes": False, "ram_readback_verification": "PASS",
            "post_execution_flash_check": "PASS: full 2 MiB byte-for-byte match",
            "post_execution_otp_check": "PASS: 34 policy rows unchanged; 256 candidate key rows blank",
            "uart_execution_marker": "PASS: operator transcript SECURITY PROFILE=debug-closed",
            "normal_flash_return": "PASS: operator UART transcript SECURITY PROFILE=recovery after requested normal power cycle",
            "flash_before_sha256": "1" * 64, "flash_after_sha256": "1" * 64,
        }
        self.save_audit()
        # Existing key/image validators have their own real-tool integration.
        # These mocks isolate the additional bindings and output safety gates.
        for target, kwargs in (
            ((stage.prepare_recovery, "check_working"), {"side_effect": lambda p:
             stage.prepare_recovery.PREPARED_LIMITS if p == self.bundle else stage.restore.LIMITS}),
            ((stage.recovery_images, "public_key_hash"), {"return_value": self.key_hash}),
            ((stage.recovery_images, "verify_stored_images"), {}),
            ((stage.package_probe, "run_tool"), {"return_value": b"picotool v2.3.1 test\n"}),
            ((stage, "offline_oracle"), {}),
        ):
            patch = mock.patch.object(*target, **kwargs)
            patch.start()
            self.addCleanup(patch.stop)

    def save_audit(self):
        self.audit_path.write_text(json.dumps(self.audit))

    def prepare(self):
        return stage.prepare(self.tool, self.bundle, self.original, self.audit_path, self.output)

    def check(self):
        stage.check_artifact(self.tool, self.bundle, self.original, self.audit_path, self.output)

    def test_valid_artifact_and_no_source_changes(self):
        before = {p: p.read_bytes() for d in (self.bundle, self.original, self.audit_dir) for p in d.iterdir()}
        self.prepare()
        self.check()
        self.assertEqual({p.name for p in self.output.iterdir()}, set(stage.LIMITS))
        self.assertEqual((self.output / stage.PAYLOAD).read_bytes(), bytes(range(32)))
        record = json.loads((self.output / "review.json").read_text())
        self.assertIs(record["authorized_for_programming"], False)
        self.assertEqual(record["control_writes"], [])
        self.assertEqual(record["secret_writes"], [])
        self.assertEqual(record["proposed_argv_not_executed"], [
            "otp", "load", "--ecc", "--start_row", "0x0080", stage.PAYLOAD,
            "-t", "bin", "--ser", stage.otp_policy.SERIAL])
        for path in self.output.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_payload_tampering_even_with_new_manifest(self):
        self.prepare()
        (self.output / stage.PAYLOAD).write_bytes(bytes(reversed(range(32))))
        stage.prepare_recovery.manifest(self.output, stage.LIMITS)
        with self.assertRaises(ValueError):
            self.check()

    def test_review_tampering_even_with_new_manifest(self):
        self.prepare()
        path = self.output / "review.json"
        original = json.loads(path.read_text())
        for key, value in (("authorized_for_programming", True), ("device_serial", "another-board"),
                           ("control_writes", ["key_valid"]), ("secret_writes", ["AES"]),
                           ("proposed_argv_not_executed", ["otp", "load", "--raw"])):
            path.write_text(json.dumps({**original, key: value}))
            stage.prepare_recovery.manifest(self.output, stage.LIMITS)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check()

    def test_missing_or_extra_members(self):
        self.prepare()
        extra = self.output / "extra.bin"
        extra.write_bytes(b"x")
        with self.assertRaises(ValueError):
            self.check()
        extra.unlink()
        (self.output / "README.txt").unlink()
        with self.assertRaises(ValueError):
            self.check()

    def test_manifest_or_warning_tampering(self):
        self.prepare()
        (self.output / "SHA256SUMS").write_text("invalid\n")
        with self.assertRaises(ValueError):
            self.check()
        (self.output / "README.txt").write_text("approved\n")
        stage.prepare_recovery.manifest(self.output, stage.LIMITS)
        with self.assertRaises(ValueError):
            self.check()

    def test_source_tool_and_original_binding_fail_before_output(self):
        self.tool.write_bytes(b"wrong tool")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.tool.write_bytes(b"pinned fixture tool")
        (self.original / "SHA256SUMS").write_text("different manifest\n")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_incomplete_or_mismatched_hardware_evidence(self):
        for key, value in (("status", "PENDING"), ("device_serial", "another-board"),
                           ("source_bundle", "/tmp/disposable"), ("otp_writes", True),
                           ("flash_after_sha256", "2" * 64), ("normal_flash_return", "PENDING"),
                           ("uart_execution_marker", "recovery"),
                           ("post_execution_otp_check", "PENDING")):
            old = self.audit[key]
            self.audit[key] = value
            self.save_audit()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse(self.output.exists())
            self.audit[key] = old

    def test_no_overwrite_or_nested_output(self):
        self.prepare()
        before = (self.output / "SHA256SUMS").read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual((self.output / "SHA256SUMS").read_bytes(), before)
        for parent in (self.bundle, self.original, self.audit_dir):
            with self.assertRaises(ValueError):
                stage.prepare(self.tool, self.bundle, self.original, self.audit_path, parent / "nested")

    def test_symlink_and_world_readable_files_rejected(self):
        self.prepare()
        payload = self.output / stage.PAYLOAD
        payload.chmod(0o644)
        with self.assertRaises(ValueError):
            self.check()
        payload.unlink()
        payload.symlink_to(self.bundle / "binding.json")
        with self.assertRaises(ValueError):
            self.check()
        alias = self.root / "alias"
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            stage.check_artifact(self.tool, self.bundle, self.original, self.audit_path, alias)

    def test_repository_destination_rejected(self):
        with self.assertRaises(ValueError):
            stage.prepare(self.tool, self.bundle, self.original, self.audit_path,
                          stage.HERE / "must-not-create-artifact")


if __name__ == "__main__":
    unittest.main()
