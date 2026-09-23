#!/usr/bin/env python3
"""Opt-in real-tool offline integration using disposable keys, never hardware."""

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile

import prepare_recovery as prepare
import recovery_images as images
import restore_sacrificial as restore


def check_startup(source):
    result = subprocess.run(["arm-none-eabi-nm", "-n", str(source)], capture_output=True, check=True, text=True)
    symbols = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = int(parts[0], 16)
    start = symbols["__preinit_array_start"]
    if symbols["__pre_init_signal_box_security_init"] != start:
        raise ValueError("Security guard is not the first runtime initializer")
    data = source.read_bytes()
    phoff = struct.unpack_from("<I", data, 28)[0]
    phsize, phnum = struct.unpack_from("<HH", data, 42)
    for i in range(phnum):
        kind, offset, vaddr, _, size, _, _, _ = struct.unpack_from("<8I", data, phoff + i * phsize)
        if kind == 1 and vaddr <= start and start + 4 <= vaddr + size:
            pointer = struct.unpack_from("<I", data, offset + start - vaddr)[0]
            if pointer != symbols["signal_box_security_init"] | 1:
                raise ValueError("Runtime initializer does not point to the security guard")
            return
    raise ValueError("Missing loadable preinit pointer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--picotool", type=Path,
                        default=Path("/tmp/signal-box-picotool-2.3.1/picotool/picotool"))
    args = parser.parse_args()
    os.umask(0o077)
    sources = {p: prepare.HERE.parent / "debug" / ("build-rp2350-" + p) / "signal-box-debug-rp2350.elf"
               for p in images.PROFILES}
    for profile, source in sources.items():
        images.check_profile(source, profile)
        check_startup(source)
        print(f"PASS: {profile} ARM SRAM input; first runtime initializer points to retained guard")
    with tempfile.TemporaryDirectory(prefix="signal-box-recovery-test-", dir="/tmp") as temp:
        base = Path(temp)
        original = base / "original"
        original.mkdir(mode=0o700)
        commands = [
            ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:secp256k1",
             "-out", str(original / "signing.pem")],
            ["openssl", "pkey", "-in", str(original / "signing.pem"), "-pubout", "-out", str(original / "public.pem")],
        ]
        for command in commands:
            subprocess.run(command, capture_output=True, check=True)
        (original / "aes-share.bin").write_bytes(os.urandom(128))
        (original / "iv-salt.bin").write_bytes(os.urandom(16))
        shutil.copyfile(sources["debug-closed"], original / "probe.elf")
        (original / "metadata.json").write_text(json.dumps({
            "device_serial": restore.SERIAL, "purpose": "sacrificial-test-only; never production",
        }))
        (original / "README.txt").write_text("DISPOSABLE HOST TEST ONLY. Never provision these keys.")
        prepare.manifest(original, restore.LIMITS)
        before = {name: images.digest(original / name) for name in restore.LIMITS}
        snapshot = prepare.prepare(args.picotool, original, sources, base / "snapshot")
        print(f"PASS: {len(prepare.PREPARED_LIMITS)}-file snapshot; six signed UF2s plus encrypted closed UF2")
        archive = base / "test.tar.gz"
        with tarfile.open(archive, "w:gz") as target:
            for name in prepare.PREPARED_LIMITS:
                target.add(snapshot / name, arcname=name, recursive=False)
        restored = base / "restored"
        restore.extract_bundle(archive, restored, prepare.PREPARED_LIMITS, images.MAX_BUNDLE_BYTES)
        restore.verify_bundle(restored, snapshot, prepare.PREPARED_LIMITS)
        images.check_binding(restored)
        images.verify_stored_images(args.picotool, restored)
        rebuilt = images.build_images(args.picotool, restored, base / "rebuilt")
        if rebuilt != json.loads((restored / "binding.json").read_text()):
            raise ValueError("Rebuilt bindings differ from restored bindings")
        if before != {name: images.digest(original / name) for name in restore.LIMITS}:
            raise ValueError("Preparation changed the original key bundle")
        print("PASS: bounded archive extraction, exact restored files, all-image repackaging, unchanged originals")
    print("PASS: disposable staging removed. No persistent keys, USB, GPG passphrase or hardware accessed.")


if __name__ == "__main__":
    main()
