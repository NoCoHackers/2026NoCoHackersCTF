"""Offline lab image packaging and binding. No device or OTP commands."""

import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

import otp_policy
import package_probe

PROFILES = ("recovery", "debug-closed", "debug-reopen")
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
EXTRA_LIMITS = {
    "ORIGINAL-SHA256SUMS": 16384,
    "policy.json": 32768,
    "PROVISIONING-PLAN.md": 65536,
    "binding.json": 65536,
    "BUNDLE-README.txt": 16384,
    "encrypted-debug-closed.elf": 1024 * 1024,
    "encrypted-debug-closed.uf2": 2 * 1024 * 1024,
    "encrypted-debug-closed.inspection.txt": 65536,
}
for profile in PROFILES:
    EXTRA_LIMITS[profile + ".elf"] = 1024 * 1024
    for storage in ("flash", "ram"):
        for extension, limit in (("elf", 1024 * 1024), ("uf2", 2 * 1024 * 1024),
                                 ("inspection.txt", 65536)):
            EXTRA_LIMITS[f"{profile}-{storage}.{extension}"] = limit


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_key_hash(directory):
    # Validate a fixed SPKI encoding, then hash uncompressed X||Y, not DER.
    prefix = bytes.fromhex("3056301006072a8648ce3d020106052b8104000a03420004")
    encoded = []
    for filename, options in (("signing.pem", []), ("public.pem", ["-pubin"])):
        result = subprocess.run(
            ["openssl", "pkey", *options, "-in", str(directory / filename),
             "-pubout", "-outform", "DER"], capture_output=True,
        )
        if result.returncode or len(result.stdout) != len(prefix) + 64 or not result.stdout.startswith(prefix):
            raise ValueError("Expected a matching secp256k1 key pair")
        encoded.append(result.stdout)
    if encoded[0] != encoded[1]:
        raise ValueError("Public key does not match the signing key")
    return hashlib.sha256(encoded[0][len(prefix):]).hexdigest()


def check_profile(path, profile):
    package_probe.check_ram_probe(path)
    data = path.read_bytes()
    markers = [p for p in PROFILES if ("SECURITY PROFILE=" + p + "\n").encode() in data]
    if markers != [profile]:
        raise ValueError("ELF has the wrong/missing lab role; rebuild the selected profile")


def check_plain_uf2(path, storage, profile):
    if storage not in ("flash", "ram"):
        raise ValueError("Unknown storage mode")
    data = path.read_bytes()
    if not data or len(data) % 512:
        raise ValueError("Invalid signed UF2 length")
    start, end = ((0x10000000, 0x10200000) if storage == "flash" else
                  (package_probe.SRAM_START, package_probe.SRAM_END))
    chunks, blocks = {}, set()
    total = len(data) // 512
    for offset in range(0, len(data), 512):
        m0, m1, flags, addr, size, block, count, family = struct.unpack_from("<8I", data, offset)
        tail = struct.unpack_from("<I", data, offset + 508)[0]
        if (m0, m1, tail) != (0x0a324655, 0x9e5d5157, 0x0ab16f30):
            raise ValueError("Invalid signed UF2 magic")
        if flags != 0x2000 or family != 0xe48bff59 or size != 256:
            raise ValueError("Expected ARM Secure payload UF2 blocks")
        if count != total or block >= total or block in blocks:
            raise ValueError("Invalid signed UF2 numbering")
        if not start <= addr <= end - 256 or addr % 256 or addr in chunks:
            raise ValueError("Signed UF2 has out-of-range, duplicate or unaligned targets")
        blocks.add(block)
        chunks[addr] = data[offset + 32:offset + 288]
    image = bytearray(max(chunks) + 256 - min(chunks))
    for addr, chunk in chunks.items():
        image[addr - min(chunks):addr - min(chunks) + 256] = chunk
    if ("SECURITY PROFILE=" + profile + "\n").encode() not in image:
        raise ValueError("Signed plaintext UF2 lost its role marker")


def check_inspection(info, key_hash, storage=None):
    signatures = re.findall(rb"(?m)^\s*signature:\s*(\S+)\s*$", info)
    keys = re.findall(rb"(?m)^\s*public key:\s*([0-9A-Fa-f]{128})\s*$", info)
    if not signatures or set(signatures) != {b"verified"} or not keys:
        raise ValueError("Final lab image signature/key inspection failed")
    if any(hashlib.sha256(bytes.fromhex(k.decode())).hexdigest() != key_hash for k in keys):
        raise ValueError("Final image signer differs from the backed-up public key")
    if storage is None:
        return
    clears = re.findall(rb"Clear (0x[0-9a-f]+)->(0x[0-9a-f]+)", info)
    expected_clear = [(b"0x20000000", b"0x20082000")] if storage == "flash" else []
    if clears != expected_clear:
        raise ValueError("Unexpected SRAM-clear map for selected storage")
    copies = re.findall(rb"Copy (0x[0-9a-f]+)->(0x[0-9a-f]+) to (0x[0-9a-f]+)->(0x[0-9a-f]+)", info)
    loads = re.findall(rb"Load (0x[0-9a-f]+)->(0x[0-9a-f]+)", info)
    maps = re.findall(rb"load map entry [0-9]+:", info)
    if len(maps) != len(clears) + len(copies) + len(loads):
        raise ValueError("Unrecognized signed load-map entry")
    if loads and storage != "ram":
        raise ValueError("Flash probe must copy to SRAM, not execute in place")
    for first, last in loads:
        if not 0x20000000 <= int(first, 16) < int(last, 16) <= 0x20082000:
            raise ValueError("In-place SRAM load leaves approved memory")
    vectors = re.findall(rb"vector table:\s*(0x[0-9a-f]+)", info)
    entries = re.findall(rb"entry point:\s*EP (0x[0-9a-f]+), SP (0x[0-9a-f]+)", info)
    if not (copies or loads) or not vectors or not entries:
        raise ValueError("Missing signed load-map/vector/entry metadata")
    lo, hi = (0x10000000, 0x10200000) if storage == "flash" else (0x20000000, 0x20082000)
    for copy in copies:
        src, src_end, dst, dst_end = (int(v, 16) for v in copy)
        if not (lo <= src < src_end <= hi and 0x20000000 <= dst < dst_end <= 0x20082000 and
                src_end - src == dst_end - dst):
            raise ValueError("Signed copy map leaves approved storage/SRAM")
    for value in vectors:
        addr = int(value, 16)
        if not 0x20000000 <= addr < 0x20082000 or addr % 128:
            raise ValueError("Invalid SRAM vector table")
    for ep, sp in entries:
        ep, sp = int(ep, 16), int(sp, 16)
        if not (ep & 1 and 0x20000000 <= (ep & ~1) < 0x20082000 and 0x20000000 < sp <= 0x20082000):
            raise ValueError("Invalid SRAM entry/stack metadata")


def inspect(tool, uf2, output, key_hash, storage=None):
    info = package_probe.run_tool(tool, "info", "-a", uf2)
    check_inspection(info, key_hash, storage)
    output.write_bytes(info)


def build_images(tool, directory, output):
    """All source/key files are private; output must be a fresh private directory."""
    tool = tool.resolve(strict=True)
    directory = package_probe.outside_repo(directory)
    output = package_probe.outside_repo(output)
    version = package_probe.run_tool(tool, "version").decode("utf-8", errors="replace")
    if not version.startswith(f"picotool v{package_probe.PICOTOOL_VERSION} "):
        raise ValueError("Use pinned picotool 2.3.1")
    package_probe.check_keys(directory)
    key_hash = public_key_hash(directory)
    output.mkdir(mode=0o700)
    for profile in PROFILES:
        source = directory / (profile + ".elf")
        check_profile(source, profile)
        for storage in ("flash", "ram"):
            stem = output / f"{profile}-{storage}"
            elf, uf2 = Path(str(stem) + ".elf"), Path(str(stem) + ".uf2")
            # Direct SRAM rescue must not clear its own in-place source image.
            clear = ["--clear"] if storage == "flash" else []
            package_probe.run_tool(tool, "seal", "--sign", *clear, source, elf, directory / "signing.pem")
            relocate = ["--offset", "0x10000000"] if storage == "flash" else []
            package_probe.run_tool(tool, "uf2", "convert", elf, uf2, *relocate, "--family", "rp2350-arm-s")
            check_plain_uf2(uf2, storage, profile)
            inspect(tool, uf2, Path(str(stem) + ".inspection.txt"), key_hash, storage)
    # Never encrypt reopen: the embedded loader freezes DEBUGEN before app entry.
    encrypted_dir = output / "encrypted-staging"
    package_probe.package_probe(tool, directory / "debug-closed.elf", directory, encrypted_dir)
    for old, new in (("encrypted.elf", "encrypted-debug-closed.elf"),
                     ("offline-encrypted-probe.uf2", "encrypted-debug-closed.uf2"),
                     ("inspection.txt", "encrypted-debug-closed.inspection.txt")):
        (encrypted_dir / old).rename(output / new)
    check_inspection((output / "encrypted-debug-closed.inspection.txt").read_bytes(), key_hash)
    (encrypted_dir / "DO-NOT-FLASH.txt").unlink()
    encrypted_dir.rmdir()
    return {
        "device_serial": otp_policy.SERIAL,
        "purpose": "sacrificial-test-only; never production",
        "signing_public_key_sha256_xy": key_hash,
        "picotool_version": package_probe.PICOTOOL_VERSION,
        "picotool_binary_sha256": digest(tool),
        "policy_sha256": digest(directory / "policy.json"),
        "plan_sha256": digest(directory / "PROVISIONING-PLAN.md"),
        "original_manifest_sha256": digest(directory / "ORIGINAL-SHA256SUMS"),
        "source_sha256": {p: digest(directory / (p + ".elf")) for p in PROFILES},
        "hardware_validation": "NOT PERFORMED",
        "authorized_for_programming": False,
        "ram_rescue_clears_sram": False,
    }


def verify_stored_images(tool, directory):
    """Reinspect actual restored UF2 bytes, not just their saved inspection text."""
    binding = json.loads((directory / "binding.json").read_text())
    key_hash = binding["signing_public_key_sha256_xy"]
    for profile in PROFILES:
        for storage in ("flash", "ram"):
            info = package_probe.run_tool(tool, "info", "-a", directory / f"{profile}-{storage}.uf2")
            check_inspection(info, key_hash, storage)
    info = package_probe.run_tool(tool, "info", "-a", directory / "encrypted-debug-closed.uf2")
    check_inspection(info, key_hash)


def check_binding(directory):
    binding = json.loads((directory / "binding.json").read_text())
    if (binding.get("device_serial") != otp_policy.SERIAL or
            binding.get("purpose") != "sacrificial-test-only; never production" or
            binding.get("authorized_for_programming") is not False or
            binding.get("hardware_validation") != "NOT PERFORMED"):
        raise ValueError("Prepared bundle has the wrong identity or approval state")
    if binding.get("signing_public_key_sha256_xy") != public_key_hash(directory):
        raise ValueError("Prepared bundle signing fingerprint mismatch")
    for field, filename in (("policy_sha256", "policy.json"), ("plan_sha256", "PROVISIONING-PLAN.md"),
                            ("original_manifest_sha256", "ORIGINAL-SHA256SUMS")):
        if binding.get(field) != digest(directory / filename):
            raise ValueError("Prepared policy/plan binding mismatch")
    if json.loads((directory / "policy.json").read_text()) != otp_policy.proposal():
        raise ValueError("Prepared policy differs from the current approved policy")
    for profile in PROFILES:
        check_profile(directory / (profile + ".elf"), profile)
        if binding.get("source_sha256", {}).get(profile) != digest(directory / (profile + ".elf")):
            raise ValueError("Prepared source binding mismatch")
        for storage in ("flash", "ram"):
            check_plain_uf2(directory / f"{profile}-{storage}.uf2", storage, profile)
            check_inspection((directory / f"{profile}-{storage}.inspection.txt").read_bytes(),
                             binding["signing_public_key_sha256_xy"], storage)
    package_probe.check_flash_uf2(directory / "encrypted-debug-closed.uf2")
    check_inspection((directory / "encrypted-debug-closed.inspection.txt").read_bytes(),
                     binding["signing_public_key_sha256_xy"])

