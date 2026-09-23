#!/usr/bin/env python3
"""Print a public OTP proposal, not a picotool recipe. No device or key access."""

import json


SERIAL = "9423D016AADE5950"

# Named rows/fields: pico-sdk 2.2.0 hardware/regs/otp_data.h.
# RBIT-8/RBIT-3 repeat whole raw words across rows. LOCK1 repeats its low byte
# within one raw word. Do not substitute one form of redundancy for the other.
CRIT0_ROWS = tuple(range(0x38, 0x40))
CRIT1_ROWS = tuple(range(0x40, 0x48))
BOOT_FLAGS0_ROWS = tuple(range(0x48, 0x4b))
BOOT_FLAGS1_ROWS = tuple(range(0x4b, 0x4e))
SECURE_BOOT_ENABLE = 1 << 0
DEBUG_DISABLE = 1 << 2
DISABLE_OTP_BOOT = 1 << 13
DISABLE_BOOTSEL_UART_BOOT = 1 << 19
SLOT0_VALID = 1 << 0
READ_ONLY_ALL = 0x151515
SECURE_READ_ONLY_OTHER_DENIED = 0x3d3d3d

DATA_REGIONS = (
    ("bootkey0", 0x080, 0x08f, "ecc16", "SHA256(public X_BE32 || Y_BE32), 32 digest bytes"),
    ("29:0", 0x740, 0x75f, "ecc16", "aes-share.bin bytes 0..63"),
    ("29:32", 0x760, 0x77f, "raw24", "24-bit physical complements of rows 0x740..0x75f"),
    ("30:0", 0x780, 0x79f, "ecc16", "aes-share.bin bytes 64..127"),
    ("30:32", 0x7a0, 0x7bf, "raw24", "24-bit physical complements of rows 0x780..0x79f"),
    ("31:0", 0x7c0, 0x7c7, "ecc16", "iv-salt.bin bytes 0..15"),
    ("31:32", 0x7e0, 0x7e7, "raw24", "24-bit physical complements of rows 0x7c0..0x7c7"),
)

# This is ordering for review, not an executable write list. Required image,
# readback and cold-boot gates in PROVISIONING-PLAN.md must occur between stages.
CONTROL_STAGES = (
    ("activate_verified_slot0", BOOT_FLAGS1_ROWS, 0, SLOT0_VALID),
    ("enforce_signatures_no_aes_yet", CRIT1_ROWS, 0, SECURE_BOOT_ENABLE),
    ("close_unused_rom_routes", BOOT_FLAGS0_ROWS, 0,
     DISABLE_OTP_BOOT | DISABLE_BOOTSEL_UART_BOOT),
    ("disable_debug_by_default", CRIT1_ROWS, SECURE_BOOT_ENABLE,
     SECURE_BOOT_ENABLE | DEBUG_DISABLE),
    ("protect_signing_hash_page", (0xf85,), 0x040404, READ_ONLY_ALL),
    ("protect_policy_page", (0xf83,), 0x040404, READ_ONLY_ALL),
    ("protect_verified_aes_share_first_half", (0xfbb,), 0, SECURE_READ_ONLY_OTHER_DENIED),
    ("protect_verified_aes_share_second_half", (0xfbd,), 0, SECURE_READ_ONLY_OTHER_DENIED),
    ("protect_verified_device_salt", (0xfbf,), 0, SECURE_READ_ONLY_OTHER_DENIED),
)


def baseline_rows():
    rows = {row: 0 for row in range(0x38, 0x4e)}
    rows.update({0xf80: 0x3f3f3f, 0xf81: READ_ONLY_ALL,
                 0xf82: 0, 0xf83: 0x040404, 0xf84: 0, 0xf85: 0x040404})
    rows.update({row: 0 for row in range(0xfba, 0xfc0)})
    return rows


def validate_baseline(observed):
    if observed != baseline_rows():
        raise ValueError("Raw policy baseline changed or is incomplete; stop and replan")


def proposed_final_rows():
    rows = baseline_rows()
    for name, targets, before, after in CONTROL_STAGES:
        if not 0 <= after <= 0xffffff or before & ~after:
            raise ValueError(f"Non-monotonic/invalid raw value in {name}")
        for row in targets:
            if rows[row] != before:
                raise ValueError(f"Unexpected stage predecessor in {name}")
            rows[row] = after
    return rows


def proposal():
    proposed_final_rows()
    return {
        "kind": "NOCO_REVIEW_ONLY_NOT_A_PICOTOOL_RECIPE",
        "policy_approved": True,
        "authorized_for_programming": False,
        "device_serial": SERIAL,
        "scope": "sacrificial A4 only; not batch authorization",
        "secret_values_included": False,
        "critical_preconditions": [
            "Fresh exact raw baseline and physically blank candidate rows",
            "Verified restored keys; exact public-key fingerprint still to bind/review",
            "Signed plaintext recovery and debug-closed/reopen probes built and reviewed",
            "Separate approval before each irreversible gate",
            "Review plan and per-device artifacts added to a fresh verified backup",
        ],
        "data_regions": [
            {"selector": name, "first_row": f"0x{start:04x}", "last_row": f"0x{end:04x}",
             "encoding": mode, "source": source,
             "write_gate": ("verify before slot activation" if name == "bootkey0" else
                            "only after trusted recovery, debug policy and root-page protection pass")}
            for name, start, end, mode, source in DATA_REGIONS
        ],
        "control_stages": [
            {"stage": name, "physical_rows": [f"0x{row:04x}" for row in rows],
             "expected_before_each": f"0x{before:06x}", "proposed_after_each": f"0x{after:06x}"}
            for name, rows, before, after in CONTROL_STAGES
        ],
        "runtime_not_otp": {
            "event_debugen": "0x00000000",
            "event_debugen_lock": "0x0000010f",
            "private_post_event_debugen_override": "0x0000010f after a cold reset",
        },
        "preserved": [
            "Page 0 and every LOCK0 row remain unchanged",
            "Slots 1-3 remain blank/inactive; no KEY_INVALID bits are programmed",
            "Root-page write protection still prevents later signing-key enrollment",
            "USB BOOTSEL MSD, PICOBOOT, flash boot and authenticated SRAM recovery remain enabled",
            "No anti-rollback counters, debug authentication keys or glitch-detector fuse changes",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(proposal(), indent=2))
