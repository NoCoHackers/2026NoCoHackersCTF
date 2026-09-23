#!/usr/bin/env python3
"""Offline-only signed/encrypted RAM probe. Never accesses a connected device."""

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[5]
PICOTOOL_VERSION = "2.3.1"
PROBE_MARKER = b"0.2.0-rp2350-ram-prototype"
SRAM_START = 0x20000000
SRAM_END = 0x20082000


def outside_repo(path):
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError("Keep keys and security outputs outside the repository")
    return resolved


def check_ram_probe(path):
    data = path.read_bytes()
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Input must be a little-endian ELF32 RAM probe")
    if struct.unpack_from("<H", data, 18)[0] != 40:
        raise ValueError("Input must target ARM")
    entry, phoff = struct.unpack_from("<II", data, 24)
    phsize, phnum = struct.unpack_from("<HH", data, 42)
    if not SRAM_START <= (entry & ~1) < SRAM_END:
        raise ValueError("Input entry point is not in SRAM; rebuild with SIGNAL_BOX_RAM_PROTOTYPE=ON")
    if phsize < 32 or phoff + phsize * phnum > len(data):
        raise ValueError("Invalid ELF program header table")
    loaded = []
    for i in range(phnum):
        kind, offset, vaddr, paddr, size, memsize, _, _ = struct.unpack_from(
            "<8I", data, phoff + i * phsize
        )
        if kind != 1 or memsize == 0:
            continue
        if size > memsize or offset + size > len(data):
            raise ValueError("Invalid ELF load segment")
        if not all(SRAM_START <= addr < SRAM_END and addr + memsize <= SRAM_END
                   for addr in (vaddr, paddr)):
            raise ValueError("All load segments must reside in SRAM; XIP/copy_to_ram inputs are rejected")
        loaded.append(data[offset:offset + size])
    if not loaded or not any(PROBE_MARKER in segment for segment in loaded):
        raise ValueError("Input is not the diagnostic RAM probe; production payloads are not supported")


def check_flash_uf2(path):
    data = path.read_bytes()
    if not data or len(data) % 512:
        raise ValueError("Invalid UF2 size")
    blocks = set()
    chunks = {}
    count = len(data) // 512
    for offset in range(0, len(data), 512):
        magic0, magic1, flags, address, size, block, total, family = struct.unpack_from(
            "<8I", data, offset
        )
        end = struct.unpack_from("<I", data, offset + 508)[0]
        if (magic0, magic1, end) != (0x0a324655, 0x9e5d5157, 0x0ab16f30):
            raise ValueError("Invalid UF2 magic")
        if flags != 0x2000 or family != 0xe48bff59 or size != 256:
            raise ValueError("Expected RP2350 ARM Secure UF2 payload blocks")
        if total != count or block in blocks or block >= count:
            raise ValueError("Invalid UF2 block numbering")
        if not 0x10000000 <= address <= 0x101fff00 or address % 256 or address in chunks:
            raise ValueError("UF2 must target unique aligned blocks in XIAO's 2 MiB flash")
        blocks.add(block)
        chunks[address] = data[offset + 32:offset + 32 + size]
    # Reconstruct the address space so a marker split across UF2 blocks cannot
    # evade the check. This is a canary check, not a proof of confidentiality.
    first = min(chunks)
    flash = bytearray(max(chunks) + 256 - first)
    for address, chunk in chunks.items():
        start = address - first
        flash[start:start + 256] = chunk
    if PROBE_MARKER in flash:
        raise ValueError("Plaintext diagnostic marker leaked into flash payload")


def check_keys(directory):
    directory = outside_repo(directory)
    paths = [directory / name for name in ("signing.pem", "aes-share.bin", "iv-salt.bin")]
    for path in paths:
        outside_repo(path)
        if not path.is_file():
            raise ValueError(f"Missing key file: {path.name}")
        if path.stat().st_mode & 0o077:
            raise ValueError(f"Restrict {path.name} to its owner (chmod 600)")
    # Require a saved share, not a raw AES key that causes picotool to generate
    # new random shares. Future OTP review must use these exact backed-up bytes.
    if paths[1].stat().st_size != 128 or paths[2].stat().st_size != 16:
        raise ValueError("Expected 128-byte AES key share and 16-byte device IV salt")
    return paths


def run_tool(tool, *args):
    result = subprocess.run([str(tool), *map(str, args)], capture_output=True)
    # Some embedded-bootloader output is not UTF-8. Never echo tool output that
    # might contain secrets; all diagnostics here are our own bounded messages.
    if result.returncode:
        raise ValueError(f"picotool {args[0]} failed (exit {result.returncode}); no device was accessed")
    return result.stdout


def package_probe(tool, source, keys, output):
    tool = tool.resolve(strict=True)
    check_ram_probe(source)
    if b"SECURITY PROFILE=debug-reopen\n" in source.read_bytes():
        raise ValueError("Debug-reopen must be plaintext signed; the embedded decryptor locks its overrides")
    signing, aes_share, iv_salt = check_keys(keys)
    output = outside_repo(output)
    version = run_tool(tool, "version").decode("utf-8", errors="replace")
    if not version.startswith(f"picotool v{PICOTOOL_VERSION} "):
        raise ValueError(f"Use the reviewed picotool {PICOTOOL_VERSION}, not another version")
    # Refuse to overwrite any prior release or key directory, even if empty.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    encrypted = output / "encrypted.elf"
    pending = output / "DO-NOT-FLASH.partial.uf2"
    final = output / "offline-encrypted-probe.uf2"
    run_tool(tool, "encrypt", "--embed", "--sign", source, encrypted,
             aes_share, iv_salt, signing)
    # No OTP JSON argument: no key-share/permission recipe is emitted here.
    run_tool(tool, "uf2", "convert", encrypted, pending,
             "--offset", "0x10000000", "--family", "rp2350-arm-s")
    check_flash_uf2(pending)
    info = run_tool(tool, "info", "-a", pending)
    if b"signature:           verified" not in info:
        raise ValueError("Output signature did not verify; keep partial outputs off devices")
    for path in (encrypted, pending):
        if PROBE_MARKER in path.read_bytes():
            raise ValueError("Plaintext diagnostic marker leaked into output")
    (output / "inspection.txt").write_bytes(info)
    (output / "DO-NOT-FLASH.txt").write_text(
        "Offline artifact only. Requires matching OTP provisioning, which has NOT been performed.\n"
        "A verified embedded signature is not proof of a device's OTP trust or confidentiality.\n"
        "No device access, OTP recipe, or permanent lock is part of package_probe.py.\n"
    )
    pending.rename(final)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--key-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        result = package_probe(args.picotool, args.input, args.key_dir, args.output_dir)
    except (OSError, ValueError) as error:
        print(f"FATAL: {error}", file=sys.stderr)
        return 1
    print(f"Offline artifact: {result}")
    print("Signature verified; plaintext probe marker absent. NOT hardware-validated. Do not flash yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
