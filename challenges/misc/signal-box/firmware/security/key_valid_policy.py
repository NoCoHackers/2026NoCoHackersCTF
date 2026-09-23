#!/usr/bin/env python3
"""Public KEY_VALID-only review model. No device, private file or writer access."""

import json
import struct

import otp_policy
import prepare_signing_hash as signing

# Public fingerprint supplied by the operator's completed hash-write transcript.
# This is not independent readback, a private-key binding check or authorization.
SIGNER_SHA256_XY = "b8fbbab76f60c7226c7172025f325b3bcb19986df08ff177c605e0217abd80ce"
HASH_RUN_NAME = "slot0-hash-v292yeja"
TARGETS = (0x004b, 0x004c, 0x004d)
CANDIDATES = tuple(range(0x80, 0xc0)) + tuple(range(0x740, 0x800))


def check_scope():
    stage = otp_policy.CONTROL_STAGES[0]
    if (stage != ("activate_verified_slot0", TARGETS, 0, 1) or
            otp_policy.BOOT_FLAGS1_ROWS != TARGETS or otp_policy.SLOT0_VALID != 1):
        raise ValueError("KEY_VALID-only policy changed; stop and re-review")


def raw_payload():
    """In-memory transport model only: three raw24 words, each padded to LE32."""
    check_scope()
    # RBIT-3 repeats whole physical rows, not bytes within one row, and not ECC.
    return struct.pack("<III", 1, 1, 1)


def validate_payload(payload):
    if type(payload) is not bytes or payload != raw_payload():
        raise ValueError("Expected exactly three raw24=1 words with zero transport padding")


def expected_rows(after=False):
    if type(after) is not bool:
        raise ValueError("Select the explicit before or after state")
    check_scope()
    rows = otp_policy.baseline_rows()
    rows.update({row: 0 for row in CANDIDATES})
    for item in signing.row_plan(signing.hash_payload(SIGNER_SHA256_XY)):
        rows[int(item["row"], 16)] = int(item["after_raw24"], 16)
    if after:
        for row in TARGETS:
            rows[row] = 1
    return rows


def validate_rows(observed, after=False):
    """Validate a caller's complete raw projection, not its transport provenance."""
    if (type(observed) is not dict or
            any(type(row) is not int or type(value) is not int or
                not 0 <= row < 4096 or not 0 <= value <= 0xffffff
                for row, value in observed.items())):
        raise ValueError("Expected an exact raw24 row map; values suppressed")
    if observed != expected_rows(after):
        raise ValueError("KEY_VALID stage state differs or is incomplete; stop, values suppressed")


def changed_rows():
    before, after = expected_rows(), expected_rows(True)
    changes = {row: (before[row], after[row]) for row in before if before[row] != after[row]}
    if changes != {row: (0, 1) for row in TARGETS}:
        raise ValueError("Transition leaves the three-row KEY_VALID-only scope")
    return changes


def check_oracle_dump(raw):
    """Check a full explicit-file picotool simulation, never a live device dump."""
    if type(raw) is not bytes or len(raw) != 4096 * 4:
        raise ValueError("Expected a full 4096-row raw simulation")
    expected = bytearray(len(raw))
    for row in TARGETS:
        struct.pack_into("<I", expected, row * 4, 1)
    if raw != expected:
        raise ValueError("Offline raw transport/row extent differs")


def proposal():
    before, after = expected_rows(), expected_rows(True)
    changed_rows()
    return {
        "kind": "NOCO_KEY_VALID_REVIEW_MODEL_NOT_A_PICOTOOL_RECIPE",
        "authorized_for_programming": False,
        "live_preflight_performed": False,
        "private_predecessor_binding_verified": False,
        "loadable_artifact_prepared": False,
        "stage": "slot0_key_valid_only_hold_before_signature_enforcement",
        "device_serial": otp_policy.SERIAL,
        "device_revision": "A4",
        "rom_gitrev": "0xa8bfe860",
        "predecessor_evidence": "operator transcript only; handoff13.22, not new readback",
        "predecessor_run_name": HASH_RUN_NAME,
        "signing_public_key_sha256_xy": SIGNER_SHA256_XY,
        "transport_model": {"encoding": "raw24 padded LE32; NOT ECC or byte-triplication",
                            "bytes": len(raw_payload()), "physical_rows": 3,
                            "padding_byte_each_word": 0},
        "control_transition": [
            {"row": f"0x{row:04x}", "before_raw24": "0x000000", "after_raw24": "0x000001"}
            for row in TARGETS],
        "unchanged_policy_rows": {f"0x{row:04x}": f"0x{value:06x}"
                                  for row, value in before.items()
                                  if row in otp_policy.baseline_rows() and row not in TARGETS},
        "unchanged_hash_rows": {f"0x{row:04x}": f"0x{before[row]:06x}" for row in range(0x80, 0x90)},
        "blank_other_candidate_rows": [f"0x{row:04x}" for row in CANDIDATES if row >= 0x90],
        "exact_readback_rows": len(after),
        "excluded": ["SECURE_BOOT_ENABLE", "DEBUG_DISABLE", "KEY_INVALID", "slots1-3 KEY_VALID",
                     "BOOT_FLAGS0", "page locks", "AES/salt", "rollback", "flash writes", "reboot"],
        "gates_still_required": [
            "Bind unchanged restored hash/key/recovery artifacts and actual successful hash journal/latch",
            "Prepare and independently back up/restore a new separately reviewed stage artifact",
            "Implement/review a separate guarded writer; never reuse or clear the hash attempt latch",
            "Separate explicit KEY_VALID-only approval and real local-terminal confirmation",
            "Fresh exact identity, all34 policy rows, exact16 hash raw encodings,240 blank other rows,2MiB flash",
            "Raw readback of EACH copy, not a majority-decoded named field; partial state means stop",
            "Positive raw binary-load verification plus independent complete postchecks; no retry",
            "Hold before signature enforcement, boot/debug tests, locks or secrets; each needs its own approval",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(proposal(), indent=2))
