#!/usr/bin/env python3
"""Offline row-model tests; no device, key, journal or receipt access."""

import itertools
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import check_key_valid as checker
from unittest.mock import patch

import key_valid_policy as stage


class KeyValidPolicyTests(unittest.TestCase):
    def test_fixed_scope_and_raw_transport(self):
        self.assertEqual(stage.TARGETS, (0x4b, 0x4c, 0x4d))
        self.assertEqual(stage.raw_payload(), bytes.fromhex("010000000100000001000000"))
        stage.validate_payload(stage.raw_payload())
        self.assertEqual(stage.changed_rows(), {row: (0, 1) for row in stage.TARGETS})

    def test_wrong_encoding_length_and_padding_are_rejected(self):
        good = stage.raw_payload()
        bad = [b"", good[:-1], good + bytes(4), struct.pack("<HHH", 1, 1, 1),
               bytes.fromhex("010000010000010000"), struct.pack(">III", 1, 1, 1),
               struct.pack("<III", 0x010101, 0x010101, 0x010101),
               struct.pack("<III", *([stage.signing.ecc24(1)] * 3)),
               bytearray(good), good.hex()]
        for index in (3, 7, 11):
            value = bytearray(good)
            value[index] = 1
            bad.append(bytes(value))
        for value in bad:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                stage.validate_payload(value)

    def test_exact_290_row_states_preserve_hash_and_other_controls(self):
        before, after = stage.expected_rows(), stage.expected_rows(True)
        self.assertEqual(len(before), 290)
        self.assertEqual(set(before), set(after))
        stage.validate_rows(before)
        stage.validate_rows(after, True)
        self.assertEqual(sum(before[r] != after[r] for r in before), 3)
        self.assertEqual(sum(after[r] for r in stage.TARGETS), 3)
        for r in set(before) - set(stage.TARGETS):
            self.assertEqual(before[r], after[r])
        self.assertTrue(all(before[r] == 0 for r in range(0x90, 0xc0)))
        self.assertTrue(all(before[r] == 0 for r in range(0x740, 0x800)))
        self.assertTrue(any(before[r] for r in range(0x80, 0x90)))

    def test_every_partial_copy_pattern_fails_both_complete_states(self):
        for copies in itertools.product((0, 1), repeat=3):
            rows = stage.expected_rows()
            rows.update(zip(stage.TARGETS, copies))
            vote = (copies[0] & copies[1]) | (copies[1] & copies[2]) | (copies[2] & copies[0])
            self.assertEqual(vote, int(sum(copies) >= 2))
            for after in (False, True):
                accepted = copies == ((1, 1, 1) if after else (0, 0, 0))
                if accepted:
                    stage.validate_rows(rows, after)
                else:
                    with self.subTest(copies=copies, after=after), self.assertRaises(ValueError):
                        stage.validate_rows(rows, after)

    def test_every_single_bit_change_in_monitored_rows_is_rejected(self):
        for after in (False, True):
            original = stage.expected_rows(after)
            for row in original:
                for bit in range(24):
                    rows = dict(original)
                    rows[row] ^= 1 << bit
                    with self.subTest(after=after, row=row, bit=bit), self.assertRaises(ValueError):
                        stage.validate_rows(rows, after)

    def test_missing_extra_and_non_raw_values_are_rejected(self):
        base = stage.expected_rows()
        missing = dict(base)
        del missing[0x4c]
        extra = {**base, 0x4e: 0}
        cases = [missing, extra, {**base, 0x4b: False}, {**base, 0x4b: 0.0},
                 {**base, 0x4b: -1}, {**base, 0x4b: 0x1000000},
                 {str(k): v for k, v in base.items()}, list(base.items())]
        for value in cases:
            with self.assertRaises(ValueError):
                stage.validate_rows(value)
        for after in (None, 0, 1, "before", "after"):
            with self.assertRaises(ValueError):
                stage.expected_rows(after)

    def test_all_blank_hash_is_no_longer_a_valid_predecessor(self):
        rows = stage.expected_rows()
        rows.update({r: 0 for r in range(0x80, 0x90)})
        with self.assertRaises(ValueError):
            stage.validate_rows(rows)

    def test_offline_dump_checks_extent_each_copy_and_padding(self):
        raw = bytearray(4096 * 4)
        for row in stage.TARGETS:
            struct.pack_into("<I", raw, row * 4, 1)
        stage.check_oracle_dump(bytes(raw))
        for index in (0x4a * 4, 0x4b * 4, 0x4c * 4, 0x4d * 4, 0x4e * 4, 0x4b * 4 + 3):
            bad = bytearray(raw)
            bad[index] ^= 1
            with self.assertRaises(ValueError):
                stage.check_oracle_dump(bytes(bad))
        with self.assertRaises(ValueError):
            stage.check_oracle_dump(bytes(raw[:-1]))

    def test_policy_drift_fails_closed(self):
        with patch.object(stage.otp_policy, "BOOT_FLAGS1_ROWS", (0x4b,)), self.assertRaises(ValueError):
            stage.raw_payload()
        with patch.object(stage.otp_policy, "SLOT0_VALID", 0xf), self.assertRaises(ValueError):
            stage.proposal()

    def test_proposal_is_only_unverified_public_review_data(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("No file inputs")), \
             patch.object(Path, "read_text", side_effect=AssertionError("No file inputs")):
            report = stage.proposal()
        for key in ("authorized_for_programming", "live_preflight_performed",
                    "private_predecessor_binding_verified", "loadable_artifact_prepared"):
            self.assertIs(report[key], False)
        self.assertEqual(report["transport_model"]["bytes"], 12)
        self.assertEqual(report["exact_readback_rows"], 290)
        self.assertEqual(len(report["unchanged_policy_rows"]), 31)
        self.assertEqual(len(report["unchanged_hash_rows"]), 16)
        self.assertEqual(len(report["blank_other_candidate_rows"]), 240)
        self.assertIn("operator transcript only", report["predecessor_evidence"])
        self.assertEqual(json.loads(json.dumps(report)), report)


class FileOnlyCheckerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="key-valid-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tool = self.root / "tool"
        self.tool.write_bytes(b"mock tool; never executed")
        self.header = self.root / "src/rp2350/hardware_regs/include/hardware/regs/otp_data.h"
        self.header.parent.mkdir(parents=True)
        self.header.write_text("\n".join(f"#define {k} _u({v:#x})" for k, v in checker.SDK_CONSTANTS.items()) + "\n")

    def test_only_explicit_file_commands_and_cleanup_on_success_or_mismatch(self):
        for mismatch in (False, True):
            inputs = []
            def run(command, **kwargs):
                if command == [str(self.tool), "version"]:
                    return subprocess.CompletedProcess(command, 0, b"picotool v2.3.1 test\n", b"")
                self.assertEqual(command[1:5], ["otp", "dump", "-r", "--output"])
                self.assertEqual(len(command), 7)
                self.assertNotIn("--ser", command)
                source, output = Path(command[6]), Path(command[5])
                self.assertIn(json.loads(source.read_text()), ({"BOOT_FLAGS1": 1}, {"BOOT_FLAGS1": {"KEY_VALID": 1}}))
                inputs.append(source)
                raw = bytearray(4096 * 4)
                for row in stage.TARGETS:
                    struct.pack_into("<I", raw, row * 4, 1)
                if mismatch:
                    raw[0x4d * 4] = 0
                output.write_bytes(raw)
                return subprocess.CompletedProcess(command, 0, b"", b"")
            with patch.object(checker.subprocess, "run", side_effect=run), \
                 patch.object(checker.transport, "NativeDevice", side_effect=AssertionError("No device")), \
                 patch.object(checker.transport, "load_plan", side_effect=AssertionError("No private inputs")), \
                 patch("builtins.print"):
                if mismatch:
                    with self.assertRaises(ValueError):
                        checker.check(self.tool, self.root)
                else:
                    checker.check(self.tool, self.root)
            self.assertEqual(len(inputs), 1 if mismatch else 2)
            self.assertTrue(all(not p.exists() for p in inputs))

    def test_sdk_drift_stops_before_tool_and_wrong_version_stops_before_dump(self):
        original = self.header.read_text()
        self.header.write_text(original.replace("_u(0x4b)", "_u(0x4a)"))
        with patch.object(checker.subprocess, "run") as run, self.assertRaises(ValueError):
            checker.check(self.tool, self.root)
        run.assert_not_called()
        self.header.write_text(original)
        wrong = subprocess.CompletedProcess([], 0, b"picotool v2.3.0 old\n", b"")
        with patch.object(checker.subprocess, "run", return_value=wrong) as run, self.assertRaises(ValueError):
            checker.check(self.tool, self.root)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], [str(self.tool), "version"])


if __name__ == "__main__":
    unittest.main()
