import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import otp_policy
import package_probe
import prepare_recovery
import recovery_images as images
import restore_sacrificial as restore
from test_package_probe import flash_uf2, ram_elf


def marker(profile):
    return package_probe.PROBE_MARKER + b"\0SECURITY PROFILE=" + profile.encode() + b"\n"


class RecoveryImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="signal-box-images-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_profile_must_match(self):
        source = self.root / "probe.elf"
        source.write_bytes(ram_elf(marker=marker("debug-closed")))
        images.check_profile(source, "debug-closed")
        with self.assertRaises(ValueError):
            images.check_profile(source, "debug-reopen")
        source.write_bytes(ram_elf())
        with self.assertRaises(ValueError):
            images.check_profile(source, "recovery")

    def test_plaintext_storage_bounds_and_split_marker(self):
        path = self.root / "probe.uf2"
        for storage, address in (("flash", 0x10000000), ("ram", 0x20000000)):
            path.write_bytes(flash_uf2(bytes(250) + marker("recovery"), address))
            images.check_plain_uf2(path, storage, "recovery")
            with self.assertRaises(ValueError):
                images.check_plain_uf2(path, "ram" if storage == "flash" else "flash", "recovery")
        for storage, address in (("flash", 0x10200000), ("ram", 0x20082000)):
            path.write_bytes(flash_uf2(marker("recovery"), address))
            with self.assertRaises(ValueError):
                images.check_plain_uf2(path, storage, "recovery")

    def test_plaintext_uf2_rejects_wrong_role_and_duplicates(self):
        path = self.root / "probe.uf2"
        block = flash_uf2(marker("recovery"))
        path.write_bytes(block)
        with self.assertRaises(ValueError):
            images.check_plain_uf2(path, "flash", "debug-reopen")
        path.write_bytes(block + block)
        with self.assertRaises(ValueError):
            images.check_plain_uf2(path, "flash", "recovery")

    def test_public_key_hash_is_xy_not_der(self):
        prefix = bytes.fromhex("3056301006072a8648ce3d020106052b8104000a03420004")
        xy = bytes(range(64))
        result = subprocess.CompletedProcess([], 0, prefix + xy)
        with patch.object(images.subprocess, "run", return_value=result):
            self.assertEqual(images.public_key_hash(self.root), hashlib.sha256(xy).hexdigest())
        with patch.object(images.subprocess, "run", side_effect=[result, subprocess.CompletedProcess([], 0, prefix + bytes(64))]):
            with self.assertRaises(ValueError):
                images.public_key_hash(self.root)
        with patch.object(images.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"wrong curve")):
            with self.assertRaises(ValueError):
                images.public_key_hash(self.root)

    def test_all_packaging_is_offline_and_reopen_never_encrypted(self):
        source = self.root / "source"
        source.mkdir(mode=0o700)
        for name, data in (("signing.pem", b"test"), ("aes-share.bin", bytes(128)),
                           ("iv-salt.bin", bytes(16))):
            (source / name).write_bytes(data)
            (source / name).chmod(0o600)
        for profile in images.PROFILES:
            (source / (profile + ".elf")).write_bytes(ram_elf(marker=marker(profile)))
        for name in ("policy.json", "PROVISIONING-PLAN.md", "ORIGINAL-SHA256SUMS"):
            (source / name).write_text("test only")
        tool = self.root / "picotool"
        tool.touch()
        calls = []

        def run(tool, *args):
            calls.append(args)
            if args[0] == "version":
                return b"picotool v2.3.1 (test)"
            if args[0] == "seal":
                Path(args[-2]).write_bytes(b"sealed")
            elif args[0] == "encrypt":
                self.assertEqual(Path(args[3]).name, "debug-closed.elf")
                Path(args[4]).write_bytes(b"encrypted")
            elif args[:2] == ("uf2", "convert"):
                src, dst = Path(args[2]), Path(args[3])
                if src.name == "encrypted.elf":
                    dst.write_bytes(flash_uf2())
                else:
                    profile, storage = src.stem.rsplit("-", 1)
                    dst.write_bytes(flash_uf2(marker(profile), 0x10000000 if storage == "flash" else 0x20000000))
            elif args[0] == "info":
                info = b"signature:           verified\npublic key: " + b"00" * 64 + b"\n"
                if "-flash.uf2" in str(args[-1]):
                    info += b"load map entry 0: Clear 0x20000000->0x20082000\n"
                    info += b"load map entry 1: Copy 0x10000000->0x10000200 to 0x20000000->0x20000200\n"
                else:
                    info += b"load map entry 0: Copy 0x20000000->0x20000200 to 0x20000000->0x20000200\n"
                return info + b"vector table: 0x20000000\nentry point: EP 0x20000001, SP 0x20082000\n"
            return b""

        with patch.object(package_probe, "run_tool", side_effect=run), \
             patch.object(images, "public_key_hash", return_value=hashlib.sha256(bytes(64)).hexdigest()):
            binding = images.build_images(tool, source, self.root / "output")
        self.assertFalse(binding["authorized_for_programming"])
        self.assertEqual({c[0] for c in calls}, {"version", "seal", "uf2", "info", "encrypt"})
        seals = [c for c in calls if c[0] == "seal"]
        self.assertEqual(len(seals), 6)
        for call in seals:
            flash = "-flash.elf" in str(call[-2])
            self.assertEqual("--clear" in call, flash)
            self.assertEqual(len(call), 6 if flash else 5)  # No OTP JSON argument.
        for call in calls:
            if call[:2] == ("uf2", "convert") and "-ram.uf2" in str(call[3]):
                self.assertNotIn("--offset", call)

    def test_inspection_requires_expected_signer_and_safe_load_map(self):
        key_hash = hashlib.sha256(bytes(64)).hexdigest()
        info = (b"signature: verified\npublic key: " + b"00" * 64 +
                b"\nload map entry 0: Copy 0x20000000->0x20000200 to 0x20000000->0x20000200\n"
                b"vector table: 0x20000000\nentry point: EP 0x20000001, SP 0x20082000\n")
        images.check_inspection(info, key_hash, "ram")
        in_place = info.replace(b"Copy 0x20000000->0x20000200 to 0x20000000->0x20000200",
                                b"Load 0x20000000->0x20000200")
        images.check_inspection(in_place, key_hash, "ram")
        for bad in (info.replace(b"verified", b"incorrect"),
                    info.replace(b"to 0x20000000", b"to 0x10000000"),
                    info + b"load map entry 1: Clear 0x20000000->0x20082000\n"):
            with self.assertRaises(ValueError):
                images.check_inspection(bad, key_hash, "ram")
        with self.assertRaises(ValueError):
            images.check_inspection(info, "wrong key", "ram")

    def test_expanded_archive_exact_allowlist(self):
        archive = self.root / "test.tar.gz"
        limits = prepare_recovery.PREPARED_LIMITS
        with tarfile.open(archive, "w:gz") as target:
            for name in limits:
                member = tarfile.TarInfo(name)
                member.size = 1
                target.addfile(member, io.BytesIO(b"x"))
        restore.extract_bundle(archive, self.root / "restored", limits, images.MAX_BUNDLE_BYTES)
        self.assertEqual(len(list((self.root / "restored").iterdir())), len(limits))
        with self.assertRaises(ValueError):
            restore.extract_bundle(archive, self.root / "legacy")

    def test_expanded_bomb_bound(self):
        archive = self.root / "bomb.tar.gz"
        archive.write_bytes(gzip.compress(bytes(images.MAX_BUNDLE_BYTES + 1)))
        with self.assertRaisesRegex(ValueError, "expands"):
            restore.extract_bundle(archive, self.root / "restored", prepare_recovery.PREPARED_LIMITS,
                                   images.MAX_BUNDLE_BYTES)

    def test_restore_reinspects_actual_uf2_bytes(self):
        (self.root / "binding.json").write_text(json.dumps({
            "signing_public_key_sha256_xy": "test fingerprint",
        }))
        with patch.object(package_probe, "run_tool", return_value=b"signature: incorrect\n") as run:
            with self.assertRaises(ValueError):
                images.verify_stored_images(self.root / "tool", self.root)
        self.assertEqual(run.call_args.args[1:3], ("info", "-a"))
        self.assertEqual(run.call_args.args[3].name, "recovery-flash.uf2")

    def test_prepared_policy_binding_cannot_authorize_programming(self):
        (self.root / "binding.json").write_text(json.dumps({
            "device_serial": otp_policy.SERIAL,
            "purpose": "sacrificial-test-only; never production",
            "authorized_for_programming": True,
            "hardware_validation": "NOT PERFORMED",
        }))
        with self.assertRaises(ValueError):
            images.check_binding(self.root)

    def test_snapshot_cannot_be_inside_or_replace_originals(self):
        original = self.root / "original"
        original.mkdir(mode=0o700)
        with patch.object(prepare_recovery, "check_working", return_value=restore.LIMITS):
            for output in (original, original / "child", self.root):
                with self.assertRaises(ValueError):
                    prepare_recovery.prepare(self.root / "unused-tool", original, {}, output)
        self.assertEqual(list(original.iterdir()), [])

    def test_validation_errors_do_not_disclose_private_data(self):
        with patch.object(prepare_recovery.sys, "argv", ["prepare", "--list-files", str(self.root)]), \
             patch.object(prepare_recovery, "check_working", side_effect=ValueError("PRIVATE TEST BYTES")), \
             patch.object(prepare_recovery.sys, "stderr", io.StringIO()) as error:
            self.assertEqual(prepare_recovery.main(), 1)
            self.assertNotIn("PRIVATE TEST BYTES", error.getvalue())


if __name__ == "__main__":
    unittest.main()
