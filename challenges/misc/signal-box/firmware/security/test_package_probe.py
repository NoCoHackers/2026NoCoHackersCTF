import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import package_probe as probe


def ram_elf(address=probe.SRAM_START, marker=probe.PROBE_MARKER):
    data = bytearray(84 + len(marker))
    data[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", data, 18, 40)
    struct.pack_into("<II", data, 24, address | 1, 52)
    struct.pack_into("<HH", data, 42, 32, 1)
    struct.pack_into("<8I", data, 52, 1, 84, address, address, len(marker), len(marker), 5, 4)
    data[84:] = marker
    return data


def flash_uf2(payload=b"ciphertext", address=0x10000000):
    payload += bytes((-len(payload)) % 256)
    data = bytearray()
    for n in range(len(payload) // 256):
        block = bytearray(512)
        struct.pack_into("<8I", block, 0, 0x0a324655, 0x9e5d5157, 0x2000,
                         address + n * 256, 256, n, len(payload) // 256, 0xe48bff59)
        block[32:288] = payload[n * 256:(n + 1) * 256]
        struct.pack_into("<I", block, 508, 0x0ab16f30)
        data.extend(block)
    return data


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="signal-box-package-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "probe.elf"
        self.source.write_bytes(ram_elf())
        self.keys = self.root / "keys"
        self.keys.mkdir(mode=0o700)
        for name, data in [("signing.pem", b"test-only placeholder"),
                           ("aes-share.bin", bytes(128)), ("iv-salt.bin", bytes(16))]:
            path = self.keys / name
            path.write_bytes(data)
            path.chmod(0o600)
        self.tool = self.root / "picotool"
        self.tool.touch()
        self.output = self.root / "output"
        self.commands = []

    def tool_call(self, tool, *args):
        self.commands.append(args)
        if args[0] == "version":
            return b"picotool v2.3.1 (test)\n"
        if args[0] == "encrypt":
            Path(args[4]).write_bytes(b"encrypted ELF")
        elif args[:2] == ("uf2", "convert"):
            Path(args[3]).write_bytes(flash_uf2())
        elif args[0] == "info":
            return b"signature:           verified\n"
        return b""

    def test_ram_probe(self):
        probe.check_ram_probe(self.source)

    def test_reject_encrypted_reopen_before_tool_or_output(self):
        self.source.write_bytes(ram_elf(marker=probe.PROBE_MARKER + b"\0SECURITY PROFILE=debug-reopen\n"))
        with patch.object(probe, "run_tool") as run:
            with self.assertRaisesRegex(ValueError, "plaintext signed"):
                probe.package_probe(self.tool, self.source, self.keys, self.output)
        run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_reject_xip(self):
        self.source.write_bytes(ram_elf(address=0x10000000))
        with self.assertRaisesRegex(ValueError, "entry point"):
            probe.check_ram_probe(self.source)

    def test_reject_flash_load_segment(self):
        data = ram_elf()
        struct.pack_into("<I", data, 64, 0x10000000)
        self.source.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "load segments"):
            probe.check_ram_probe(self.source)

    def test_reject_truncated_elf(self):
        self.source.write_bytes(ram_elf()[:60])
        with self.assertRaises(ValueError):
            probe.check_ram_probe(self.source)

    def test_reject_nonprobe(self):
        self.source.write_bytes(ram_elf(marker=b"other application"))
        with self.assertRaisesRegex(ValueError, "diagnostic RAM probe"):
            probe.check_ram_probe(self.source)

    def test_reject_repo_paths_and_symlinks(self):
        with self.assertRaises(ValueError):
            probe.outside_repo(probe.REPO_ROOT / "ignored-key-directory")
        alias = self.root / "repo-alias"
        alias.symlink_to(probe.REPO_ROOT, target_is_directory=True)
        with self.assertRaises(ValueError):
            probe.outside_repo(alias / "keys")

    def test_reject_raw_aes_and_public_permissions(self):
        path = self.keys / "aes-share.bin"
        path.write_bytes(bytes(32))
        with self.assertRaisesRegex(ValueError, "128-byte"):
            probe.check_keys(self.keys)
        path.write_bytes(bytes(128))
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "owner"):
            probe.check_keys(self.keys)

    def test_reject_marker_split_across_uf2_blocks(self):
        path = self.root / "leak.uf2"
        path.write_bytes(flash_uf2(bytes(250) + probe.PROBE_MARKER))
        with self.assertRaisesRegex(ValueError, "leaked"):
            probe.check_flash_uf2(path)

    def test_reject_ram_uf2(self):
        path = self.root / "ram.uf2"
        path.write_bytes(flash_uf2(address=probe.SRAM_START))
        with self.assertRaisesRegex(ValueError, "flash"):
            probe.check_flash_uf2(path)

    def test_two_mib_flash_boundary(self):
        path = self.root / "boundary.uf2"
        path.write_bytes(flash_uf2(address=0x101fff00))
        probe.check_flash_uf2(path)
        path.write_bytes(flash_uf2(address=0x10200000))
        with self.assertRaisesRegex(ValueError, "2 MiB"):
            probe.check_flash_uf2(path)

    def test_offline_command_allowlist(self):
        with patch.object(probe, "run_tool", side_effect=self.tool_call):
            result = probe.package_probe(self.tool, self.source, self.keys, self.output)
        self.assertTrue(result.is_file())
        self.assertEqual([a[0] for a in self.commands], ["version", "encrypt", "uf2", "info"])
        self.assertEqual(len(self.commands[1]), 8)  # No OTP JSON positional argument.
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o700)

    def test_warning_failure_leaves_only_partial_uf2(self):
        with patch.object(probe, "run_tool", side_effect=self.tool_call):
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    probe.package_probe(self.tool, self.source, self.keys, self.output)
        self.assertFalse((self.output / "offline-encrypted-probe.uf2").exists())
        self.assertTrue((self.output / "DO-NOT-FLASH.partial.uf2").exists())

    def test_refuse_overwrite(self):
        self.output.mkdir()
        with patch.object(probe, "run_tool", side_effect=self.tool_call):
            with self.assertRaises(FileExistsError):
                probe.package_probe(self.tool, self.source, self.keys, self.output)
        self.assertEqual([a[0] for a in self.commands], ["version"])

    def test_refuse_old_tool(self):
        with patch.object(probe, "run_tool", return_value=b"picotool v2.1.1 (test)\n"):
            with self.assertRaisesRegex(ValueError, "2.3.1"):
                probe.package_probe(self.tool, self.source, self.keys, self.output)
        self.assertFalse(self.output.exists())

    def test_refuse_unverified_signature(self):
        def broken_signature(tool, *args):
            if args[0] == "info":
                return b"signature:           invalid\n"
            return self.tool_call(tool, *args)
        with patch.object(probe, "run_tool", side_effect=broken_signature):
            with self.assertRaisesRegex(ValueError, "signature"):
                probe.package_probe(self.tool, self.source, self.keys, self.output)
        self.assertFalse((self.output / "offline-encrypted-probe.uf2").exists())


if __name__ == "__main__":
    unittest.main()
