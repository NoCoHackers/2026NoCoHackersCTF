#!/usr/bin/env python3
"""Patch the RP2040 boot2 checksum and package a raw image as UF2."""

import argparse
import binascii
import pathlib
import struct

FLASH_BASE = 0x10000000
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID = 0x00002000
RP2040_FAMILY_ID = 0xE48BFF56
PAYLOAD_SIZE = 256


def bit_reverse(value: int, width: int) -> int:
    result = 0
    for _ in range(width):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def boot2_checksum(first_252_bytes: bytes) -> int:
    if len(first_252_bytes) != 252:
        raise ValueError("boot2 checksum input must be exactly 252 bytes")
    reflected = bytes(bit_reverse(value, 8) for value in first_252_bytes)
    checksum = binascii.crc32(reflected, 0) ^ 0xFFFFFFFF
    return bit_reverse(checksum, 32)


def make_uf2(image: bytes) -> bytes:
    padded_length = (len(image) + PAYLOAD_SIZE - 1) & ~(PAYLOAD_SIZE - 1)
    image = image.ljust(padded_length, b"\x00")
    block_count = len(image) // PAYLOAD_SIZE
    blocks = []

    for block_number in range(block_count):
        payload = image[
            block_number * PAYLOAD_SIZE : (block_number + 1) * PAYLOAD_SIZE
        ]
        header = struct.pack(
            "<8I",
            UF2_MAGIC_START0,
            UF2_MAGIC_START1,
            UF2_FLAG_FAMILY_ID,
            FLASH_BASE + block_number * PAYLOAD_SIZE,
            PAYLOAD_SIZE,
            block_number,
            block_count,
            RP2040_FAMILY_ID,
        )
        blocks.append(header + payload + bytes(220) + struct.pack("<I", UF2_MAGIC_END))

    return b"".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path, help="unpatched raw flash image")
    parser.add_argument("binary", type=pathlib.Path, help="patched raw image output")
    parser.add_argument("uf2", type=pathlib.Path, help="UF2 output")
    args = parser.parse_args()

    image = bytearray(args.input.read_bytes())
    if len(image) < 256:
        raise SystemExit("input is shorter than the 256-byte boot2 block")

    checksum = boot2_checksum(bytes(image[:252]))
    image[252:256] = struct.pack("<I", checksum)
    args.binary.write_bytes(image)
    args.uf2.write_bytes(make_uf2(bytes(image)))

    print(f"boot2 checksum: 0x{checksum:08x}")
    print(f"binary: {args.binary} ({len(image)} bytes)")
    print(f"uf2: {args.uf2}")


if __name__ == "__main__":
    main()
